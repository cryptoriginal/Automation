import os
import hmac
import time
import json
import base64
import hashlib
import logging
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

BITGET_API_KEY = "bg_5773fe57167e2e9abb7d87f6510f54b5"
BITGET_API_SECRET = "cc3a0bc4771b871c989e68068206e9fc12a973350242ea136f34693ee64b69bb"
BITGET_PASSPHRASE = "automatioN"
BASE_URL = "https://api.bitget.com"

logging.basicConfig(level=logging.INFO)

# ===========================================================
# Bitget helper functions
# ===========================================================
def get_timestamp():
    return str(int(time.time() * 1000))

def sign(message):
    mac = hmac.new(BITGET_API_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode("utf-8")

def headers(method, request_path, body=""):
    timestamp = get_timestamp()
    body_str = json.dumps(body) if body else ""
    message = f"{timestamp}{method}{request_path}{body_str}"
    signature = sign(message)
    return {
        "ACCESS-KEY": BITGET_API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": BITGET_PASSPHRASE,
        "Content-Type": "application/json"
    }

# ===========================================================
# Core logic
# ===========================================================
def get_balance():
    """Fetch available USDT balance."""
    endpoint = "/api/mix/v1/account/accounts?productType=umcbl"
    resp = requests.get(BASE_URL + endpoint, headers=headers("GET", endpoint))
    data = resp.json()
    for acc in data.get("data", []):
        if acc["marginCoin"] == "USDT":
            return float(acc["available"])
    return 0.0

def get_last_price(symbol):
    """Get the latest price for the given symbol."""
    endpoint = f"/api/mix/v1/market/ticker?symbol={symbol}"
    resp = requests.get(BASE_URL + endpoint)
    data = resp.json()
    return float(data["data"]["last"]) if "data" in data and "last" in data["data"] else 0.0

def place_order(symbol, side):
    balance = get_balance()
    if balance <= 0:
        logging.error("❌ No available balance to trade.")
        return

    # Cross leverage 3x fixed
    leverage = 3
    notional = balance * leverage

    # Get price to calculate size
    price = get_last_price(symbol)
    if price <= 0:
        logging.error("❌ Failed to fetch price.")
        return

    # Calculate contract size in terms of coin
    size = round(notional / price, 4)

    order_side = "open_long" if side == "buy" else "open_short"

    logging.info(f"🚀 Sending {side.upper()} order for {symbol} | Balance: {balance} USDT | Leverage: {leverage}x | Size: {size} | Cross")

    endpoint = "/api/mix/v1/order/placeOrder"
    body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "size": str(size),
        "side": order_side,
        "orderType": "market",
        "timeInForceValue": "normal"
    }

    resp = requests.post(BASE_URL + endpoint, headers=headers("POST", endpoint, body), json=body)
    logging.info(f"📡 Bitget Response: {resp.text}")
    return resp.json()

# ===========================================================
# Flask webhook
# ===========================================================
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json(force=True)
    logging.info(f"📩 Received TradingView alert: {data}")

    try:
        symbol = data.get("symbol")
        side = data.get("side")

        if symbol and side:
            result = place_order(symbol, side)
            return jsonify(result)
        else:
            return jsonify({"error": "Missing symbol or side"}), 400

    except Exception as e:
        logging.error(f"⚠️ Webhook processing error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/')
def home():
    return "🚀 Bitget Auto-Trader is running!"

# ===========================================================
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
