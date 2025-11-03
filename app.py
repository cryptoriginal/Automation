import os
import json
import time
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ==================================================
# ✅ Load API keys from environment variables
# ==================================================
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
PASSPHRASE = os.getenv("PASSPHRASE")

# ==================================================
# ✅ Helper: Bitget Signature
# ==================================================
def sign_request(api_key, api_secret, passphrase, method, request_path, body=None):
    timestamp = str(int(time.time() * 1000))
    body_str = json.dumps(body) if body else ""
    pre_sign = timestamp + method.upper() + request_path + body_str
    signature = hmac.new(api_secret.encode("utf-8"), pre_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    headers = {
        "ACCESS-KEY": api_key,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": passphrase,
        "Content-Type": "application/json"
    }
    return headers

# ==================================================
# ✅ Home Route
# ==================================================
@app.route('/')
def home():
    return "🚀 Automation Service is Live — Bitget Trade Webhook Ready!"

# ==================================================
# ✅ TradingView Webhook Listener
# ==================================================
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json(force=True)
        print(f"\n📩 Received alert: {data}")

        symbol = data.get("symbol")
        side = data.get("side")

        if not symbol or not side:
            return jsonify({"error": "Missing symbol or side"}), 400

        marginCoin = "USDT"
        endpoint = "/api/mix/v1/order/placeOrder"
        url = f"https://api.bitget.com{endpoint}"

        # ✅ Map sides
        if side.lower() == "buy":
            orderSide = "open_long"
        elif side.lower() == "sell":
            orderSide = "open_short"
        else:
            return jsonify({"error": "Invalid side"}), 400

        # Example position size (adjust to your need)
        order = {
            "symbol": symbol,
            "marginCoin": marginCoin,
            "side": orderSide,
            "orderType": "market",
            "size": "1"  # 1 contract / coin — adjust as needed
        }

        headers = sign_request(API_KEY, API_SECRET, PASSPHRASE, "POST", endpoint, order)

        print(f"📤 Sending order: {order}")
        response = requests.post(url, headers=headers, data=json.dumps(order))
        print(f"🧾 Response: {response.text}")

        return jsonify(response.json()), response.status_code

    except Exception as e:
        print("❌ Webhook Error:", e)
        return jsonify({"error": str(e)}), 500

# ==================================================
# ✅ Keepalive Ping for Render
# ==================================================
@app.before_request
def keepalive():
    if request.path == "/":
        print("✅ Service alive ping received")

# ==================================================
# ✅ Run Flask App
# ==================================================
if __name__ == "__main__":
    print("🚀 Your service is live 🎉")
    print("==> Available at your primary URL")
    print("==>", os.getenv("RENDER_EXTERNAL_URL", "http://localhost:5000"))
    print("🔑 API Key loaded:", bool(API_KEY))
    print("🔐 API Secret loaded:", bool(API_SECRET))
    print("🧩 Passphrase loaded:", bool(PASSPHRASE))
    app.run(host="0.0.0.0", port=5000)

