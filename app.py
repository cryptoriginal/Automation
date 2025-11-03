import os
import hmac
import hashlib
import base64
import json
import time
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

BITGET_API_KEY = os.getenv("BITGET_API_KEY")
BITGET_API_SECRET = os.getenv("BITGET_API_SECRET")
BITGET_API_PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE")
TRADE_VALUE = float(os.getenv("TRADE_VALUE", 10))  # in USDT
BASE_URL = os.getenv("BITGET_BASE_URL", "https://api.bitget.com")

def sign_request(timestamp, method, request_path, body):
    if body:
        body_str = json.dumps(body, separators=(',', ':'))
    else:
        body_str = ''
    message = f"{timestamp}{method.upper()}{request_path}{body_str}"
    signature = base64.b64encode(
        hmac.new(BITGET_API_SECRET.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).digest()
    )
    return signature.decode()

def place_order(symbol, side):
    url_path = "/api/mix/v1/order/placeOrder"
    timestamp = str(int(time.time() * 1000))
    notional = TRADE_VALUE * 3  # use 3x of your trade value

    order_data = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "side": "open_long" if side == "buy" else "open_short",
        "orderType": "market",
        "size": round(notional / 100, 3)  # approx size (adjust by symbol price)
    }

    headers = {
        "ACCESS-KEY": BITGET_API_KEY,
        "ACCESS-SIGN": sign_request(timestamp, "POST", url_path, order_data),
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": BITGET_API_PASSPHRASE,
        "Content-Type": "application/json"
    }

    response = requests.post(BASE_URL + url_path, headers=headers, json=order_data)
    print("➡️ Sending order:", order_data)
    print("📨 Response:", response.text)
    return response.json()

@app.route('/')
def home():
    return "✅ Bitget Trading Bot is running!"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        print("📩 Received alert:", data)

        if not data or 'symbol' not in data or 'side' not in data:
            return jsonify({"error": "Invalid alert format"}), 400

        symbol = data['symbol']
        side = data['side'].lower()
        if side not in ['buy', 'sell']:
            return jsonify({"error": "Invalid side"}), 400

        order_response = place_order(symbol, side)
        return jsonify(order_response)

    except Exception as e:
        print("❌ Error in webhook:", e)
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
