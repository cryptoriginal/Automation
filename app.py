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

# ================================
# CONFIG
# ================================
BITGET_API_KEY = "bg_5773fe57167e2e9abb7d87f6510f54b5"
BITGET_API_SECRET = "cc3a0bc4771b871c989e68068206e9fc12a973350242ea136f34693ee64b69bb"
BITGET_PASSPHRASE = "automatioN"
BASE_URL = "https://api.bitget.com"

logging.basicConfig(level=logging.INFO)

# ================================
# AUTH HELPERS
# ================================
def get_timestamp():
    return str(int(time.time() * 1000))

def sign(message):
    mac = hmac.new(BITGET_API_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode("utf-8")

def headers(method, request_path, body=None):
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

# ================================
# BITGET FUNCTIONS
# ================================
def get_balance():
    """Fetch available USDT balance safely."""
    endpoint = "/api/mix/v1/account/accounts?productType=umcbl"
    try:
        resp = requests.get(BASE_URL + endpoint, headers=headers("GET", endpoint))
        data = resp.json()
        if not data or "data" not in data:
            logging.error(f"⚠️ Balance fetch failed: {data}")
            return 0.0
        for acc in data["data"]:
            if acc.get("marginCoin") == "USDT":
                return float(acc.get("available", 0))
        return 0.0
    except Exception as e:
        logging.error(f"⚠️ Error fetching balance: {str(e)}")
        return 0.0

def get_last_price(symbol):
    """Get latest price for given symbol."""
    try:
        endpoint = f"/api/mix/v1/market/ticker?symbol={symbol}"
        resp = requests.get(BASE_URL + endpoint)
        data = resp.json()
        return float(data["data"]["last"]) if data and "data" in data else 0.0
    except Exception as e:
        logging.error(f"⚠️ Error fetching price: {str(e)}")
        return 0.0

def place_order(symbol, side):
    balance = get_balance()
    if balance <= 0:
        logging.error("❌ No available balance or failed to fetch balance.")
        return {"error": "No available balance"}

    leverage = 3
    notional = balance * leverage
    price = get_last_price(symbol)

    if price <= 0:
        logging.error("❌ Failed to get price.")
        return {"error": "Failed to get price"}

    size = round(notional / price, 4)
    order_side = "open_long" if side == "buy" else "open_short"

    logging.info(f"🚀 Sending {side.upper()} order for {symbol} | Bal: {balance} | Lev: {leverage}x | Size: {size}")

    endpoint = "/api/mix/v1/order/placeOrder"
    body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "size": str(size),
        "side": order_side,
        "orderType": "market",
        "timeInForceValue": "normal"
    }

    try:
        resp = requests.post(BASE_URL + endpoint, headers=headers("POST", endpoint, body), json=body)
        logging.info(f"📡 Bitget Response: {resp.text}")
        return resp.json()
    except Exception as e:
        logging.error(f"⚠️ Order placement failed: {str(e)}")
        return {"error": str(e)}

# ================================
# FLASK ROUTES
# ================================
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json(force=True)
    logging.info(f"📩 Received TradingView alert: {data}")

    try:
        symbol = data.get("symbol")
        side = data.get("side")

        if not symbol or not side:
            return jsonify({"error": "Missing symbol or side"}), 400

        result = place_order(symbol, side)
        return jsonify(result)

    except Exception as e:
        logging.error(f"⚠️ Webhook processing error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/')
def home():
    return "🚀 Bitget Auto-Trader is running with 3x cross leverage!"

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
