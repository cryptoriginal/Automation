from flask import Flask, request, jsonify
import hmac
import hashlib
import time
import requests
import json
import base64

app = Flask(__name__)

# === CONFIGURATION ===
API_KEY = "bg_5773fe57167e2e9abb7d87f6510f54b5"
API_SECRET = "cc3a0bc4771b871c989e68068206e9fc12a973350242ea136f34693ee64b69bb"
API_PASSPHRASE = "automatioN"
BASE_URL = "https://api.bitget.com"

# === UTILITIES ===
def get_signature(timestamp, method, request_path, body=""):
    body_str = json.dumps(body) if body else ""
    message = f"{timestamp}{method}{request_path}{body_str}"
    signature = hmac.new(API_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(signature).decode()

def headers(method, path, body=""):
    timestamp = str(int(time.time() * 1000))
    sign = get_signature(timestamp, method, path, body)
    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json",
    }

# === ROUTES ===
@app.route("/", methods=["GET"])
def home():
    return "✅ Bitget Webhook Server is running."

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        print("🚀 Received TradingView alert:", data)

        symbol = data.get("symbol")
        side = data.get("side")

        if not symbol or not side:
            print("⚠️ Missing symbol or side in alert.")
            return jsonify({"error": "Missing symbol or side"}), 400

        # Convert basic buy/sell to Bitget futures sides
        if side.lower() == "buy":
            side_value = "open_long"
        elif side.lower() == "sell":
            side_value = "open_short"
        else:
            print(f"⚠️ Invalid side received: {side}")
            return jsonify({"error": "Invalid side"}), 400

        order = {
            "symbol": symbol,
            "marginCoin": "USDT",
            "size": "0.1",
            "side": side_value,
            "orderType": "market",
            "timeInForceValue": "normal"
        }

        path = "/api/mix/v1/order/placeOrder"
        url = BASE_URL + path
        print(f"📡 Sending order to Bitget: {order}")

        response = requests.post(url, headers=headers("POST", path, order), json=order)
        print("📩 Bitget Response:", response.status_code, response.text)

        return jsonify({"message": "Order sent", "bitget_response": response.json()}), response.status_code

    except Exception as e:
        print("❌ ERROR in webhook:", str(e))
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
