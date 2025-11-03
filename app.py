import os
import json
import hmac
import time
import hashlib
import base64
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# === Load Environment Variables ===
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
PASSPHRASE = os.getenv("PASSPHRASE")
TRADE_BALANCE_USDT = float(os.getenv("TRADE_BALANCE_USDT", 20))

print("//////////////////////////////////////////////////////////////")
print("==> Your service is live 🎉")
print("==>")
print("==> Available at your primary URL https://automation-777x.onrender.com")
print("//////////////////////////////////////////////////////////////")
print(f"🔑 API Key loaded: {bool(API_KEY)}")
print(f"🔐 API Secret loaded: {bool(API_SECRET)}")
print(f"🧩 Passphrase loaded: {bool(PASSPHRASE)}")
print("//////////////////////////////////////////////////////////////")

# === Bitget Futures API Base URL ===
BASE_URL = "https://api.bitget.com"

# === Signature Helper Function ===
def generate_signature(secret_key, timestamp, method, request_path, body=""):
    if body is None:
        body = ""
    message = f"{timestamp}{method}{request_path}{body}"
    mac = hmac.new(secret_key.encode('utf-8'), message.encode('utf-8'), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode('utf-8')

# === Place Futures Order ===
def place_order(symbol, side):
    try:
        marginCoin = "USDT"
        timestamp = str(int(time.time() * 1000))

        if side.lower() == "buy":
            order_side = "open_long"
        elif side.lower() == "sell":
            order_side = "open_short"
        else:
            print(f"⚠️ Invalid side: {side}")
            return jsonify({"error": "Invalid side"}), 400

        size = round(TRADE_BALANCE_USDT / 18.8, 2)  # Example position sizing logic

        body = {
            "symbol": symbol,
            "marginCoin": marginCoin,
            "side": order_side,
            "orderType": "market",
            "size": str(size)
        }

        body_json = json.dumps(body)
        request_path = "/api/mix/v1/order/placeOrder"
        method = "POST"

        signature = generate_signature(API_SECRET, timestamp, method, request_path, body_json)

        headers = {
            "ACCESS-KEY": API_KEY,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": PASSPHRASE,
            "Content-Type": "application/json",
            "locale": "en-US"
        }

        url = BASE_URL + request_path
        response = requests.post(url, headers=headers, data=body_json)
        print(f"Response: {response.text}")

        return jsonify(response.json())

    except Exception as e:
        print(f"🔥 Error placing order: {e}")
        return jsonify({"error": str(e)}), 500

# === Webhook Endpoint ===
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        print(f"📩 Received alert: {data}")

        if not data or 'symbol' not in data or 'side' not in data:
            print("⚠️ Invalid alert payload")
            return jsonify({"error": "Invalid alert payload"}), 400

        symbol = data['symbol']
        side = data['side']

        print(f"🚀 Sending order: {symbol}, {side}")
        return place_order(symbol, side)

    except Exception as e:
        print(f"❌ Webhook Error: {e}")
        return jsonify({"error": str(e)}), 500

# === Keep Alive Route ===
@app.route('/')
def home():
    return "🚀 Bitget Auto Trader is live!"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
