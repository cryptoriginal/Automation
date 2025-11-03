import os
import json
import time
import hmac
import hashlib
import requests
import logging
from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === ENVIRONMENT VARIABLES ===
API_KEY = os.getenv("BITGET_API_KEY")
API_SECRET = os.getenv("BITGET_API_SECRET")
API_PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE")
TRADE_BALANCE_USDT = float(os.getenv("TRADE_BALANCE_USDT", "100"))
BASE_URL = "https://api.bitget.com"

# === AUTH SIGNING FUNCTION ===
def sign_request(timestamp, method, request_path, body=""):
    if body and isinstance(body, dict):
        body = json.dumps(body, separators=(",", ":"))
    message = f"{timestamp}{method.upper()}{request_path}{body}"
    mac = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256)
    return mac.hexdigest()

def headers(method, path, body=None):
    timestamp = str(int(time.time() * 1000))
    sign = sign_request(timestamp, method, path, body)
    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json"
    }

# === BITGET API HELPERS ===
def bitget_post(path, payload):
    url = BASE_URL + path
    response = requests.post(url, headers=headers("POST", path, payload), json=payload)
    if response.status_code != 200:
        logger.error(f"HTTP {response.status_code}: {response.text}")
    return response.json()

@app.route('/')
def home():
    return "✅ Bitget Auto-Trader (SDK-Free) is live"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = json.loads(request.data)
        symbol = data.get('symbol')
        side = data.get('side', '').lower()

        if not symbol or side not in ['buy', 'sell']:
            return jsonify({'error': 'Invalid payload'}), 400

        logger.info(f"🚀 Received {side.upper()} alert for {symbol}")

        # 1️⃣ Set Cross Margin Mode + 3x Leverage
        bitget_post("/api/mix/v1/account/set-margin-mode", {
            "symbol": symbol,
            "marginMode": "crossed"
        })
        bitget_post("/api/mix/v1/account/set-leverage", {
            "symbol": symbol,
            "marginCoin": "USDT",
            "leverage": "3"
        })

        # 2️⃣ Force close opposite direction
        opposite = "short" if side == "buy" else "long"
        close_payload = {
            "symbol": symbol,
            "marginCoin": "USDT",
            "holdSide": opposite
        }
        bitget_post("/api/mix/v1/order/close-position", close_payload)
        logger.info(f"🧹 Closed {opposite} position before entering new {side}")

        # 3️⃣ Open new position
        order_value = TRADE_BALANCE_USDT * 3  # leverage 3x
        payload = {
            "symbol": symbol,
            "marginCoin": "USDT",
            "side": side,
            "orderType": "market",
            "size": str(order_value / 10)  # simple qty logic, Bitget adjusts automatically
        }
        order = bitget_post("/api/mix/v1/order/place-order", payload)

        logger.info(f"✅ New order placed: {order}")
        return jsonify({"status": "ok", "response": order}), 200

    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    logger.info("🚀 Starting Bitget Auto-Trader")
    app.run(host='0.0.0.0', port=port)

