import os
import time
import hmac
import hashlib
import base64
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- Load environment variables ---
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
PASSPHRASE = os.getenv("PASSPHRASE")
TRADE_BALANCE = float(os.getenv("TRADE_BALANCE_USDT", "0.0"))

# --- Verify keys loaded ---
print("🔑 API Key loaded:", bool(API_KEY))
print("🔒 API Secret loaded:", bool(API_SECRET))
print("🧩 Passphrase loaded:", bool(PASSPHRASE))
print("💰 Trade Balance (env):", TRADE_BALANCE)

BASE_URL = "https://api.bitget.com"

# === Proper Bitget Signature Function ===
def bitget_signature(timestamp, method, request_path, body):
    message = f"{timestamp}{method.upper()}{request_path}{body}"
    mac = hmac.new(API_SECRET.encode('utf-8'), message.encode('utf-8'), hashlib.sha256)
    d = mac.digest()
    return base64.b64encode(d).decode()

# === Place Order ===
def place_order(symbol, side):
    try:
        print(f"📈 Executing trade for {symbol} ({side})")

        endpoint = "/api/mix/v1/order/placeOrder"
        url = BASE_URL + endpoint

        margin_coin = "USDT"
        order_type = "market"
        trade_size = round((TRADE_BALANCE * 3) / 100, 2)  # 3x of balance %

        payload = {
            "symbol": symbol,
            "marginCoin": margin_coin,
            "size": str(trade_size),
            "side": "open_long" if side.lower() == "buy" else "open_short",
            "orderType": order_type,
            "timeInForceValue": "normal"
        }

        body = json.dumps(payload)
        timestamp = str(int(time.time() * 1000))
        sign = bitget_signature(timestamp, "POST", endpoint, body)

        headers = {
            "ACCESS-KEY": API_KEY,
            "ACCESS-SIGN": sign,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": PASSPHRASE,
            "Content-Type": "application/json"
        }

        print("🧾 Sending order payload:", payload)
        response = requests.post(url, headers=headers, data=body)
        print("🌍 Bitget Response:", response.status_code, response.text)

    except Exception as e:
        print("❌ Exception placing order:", str(e))

# === Webhook Endpoint ===
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        print("🚀 Webhook triggered!")
        data = request.get_json()
        print("📩 Received payload:", data)

        symbol = data.get('symbol')
        side = data.get('side')

        if not symbol or not side:
            return jsonify({"error": "Missing symbol or side"}), 400

        place_order(symbol, side)
        return jsonify({"status": "success"}), 200

    except Exception as e:
        print("❌ Webhook Error:", str(e))
        return jsonify({"error": str(e)}), 500

# === Root Endpoint ===
@app.route('/')
def home():
    return "✅ Bitget Trading Webhook is Live"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)

