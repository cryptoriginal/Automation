import os
import hmac
import hashlib
import base64
import json
import time
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Environment variables
API_KEY = os.getenv("BITGET_API_KEY")
API_SECRET = os.getenv("BITGET_SECRET_KEY")
API_PASSPHRASE = os.getenv("BITGET_PASSPHRASE")
BASE_URL = os.getenv("BASE_URL", "https://api.bitget.com")

# Futures market type
PRODUCT_TYPE = "umcbl"  # USDT-M Futures

# ======== BITGET SIGNATURE FUNCTION ======== #
def bitget_signature(timestamp, method, request_path, body=""):
    if not body or body == "{}":
        body = ""
    message = f"{timestamp}{method.upper()}{request_path}{body}"
    mac = hmac.new(API_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
    sign = base64.b64encode(mac.digest()).decode()
    return sign


def bitget_headers(method, endpoint, body=""):
    timestamp = str(int(time.time() * 1000))
    sign = bitget_signature(timestamp, method, endpoint, body)
    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json",
        "locale": "en-US"
    }

# ======== BITGET API FUNCTIONS ======== #

def get_positions(symbol):
    """Get open positions for given symbol"""
    endpoint = f"/api/mix/v1/position/allPosition?productType={PRODUCT_TYPE}"
    headers = bitget_headers("GET", endpoint)
    resp = requests.get(BASE_URL + endpoint, headers=headers)
    try:
        data = resp.json()
        if "data" in data:
            positions = [p for p in data["data"] if p["symbol"] == symbol]
            return positions
    except Exception as e:
        print("Position fetch error:", e)
    return []


def close_all_positions(symbol):
    """Close both long & short positions for symbol at market"""
    positions = get_positions(symbol)
    for pos in positions:
        size = abs(float(pos["total"]))
        if size > 0:
            side = "close_long" if pos["holdSide"] == "long" else "close_short"
            print(f"🔁 Closing {side} position for {symbol} ({size} contracts)")
            endpoint = "/api/mix/v1/order/closePosition"
            body = json.dumps({
                "symbol": symbol,
                "marginCoin": "USDT",
                "productType": PRODUCT_TYPE,
                "holdSide": pos["holdSide"]
            })
            headers = bitget_headers("POST", endpoint, body)
            r = requests.post(BASE_URL + endpoint, headers=headers, data=body)
            print("Close response:", r.text)


def place_order(symbol, side, size=0.1, leverage=3):
    """Place futures market order"""
    endpoint = "/api/mix/v1/order/placeOrder"
    order_side = "open_long" if side == "buy" else "open_short"
    body_dict = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "size": str(size),
        "side": order_side,
        "orderType": "market",
        "productType": PRODUCT_TYPE,
        "leverage": str(leverage)
    }
    body = json.dumps(body_dict)
    headers = bitget_headers("POST", endpoint, body)
    response = requests.post(BASE_URL + endpoint, headers=headers, data=body)
    print("Order response:", response.text)
    return response.json()


# ======== FLASK WEBHOOK ROUTE ======== #
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print(f"📩 Received alert: {data}")

    try:
        symbol = data.get("symbol", "").upper()
        action = data.get("action", "").lower()  # 'buy' or 'sell'

        if not symbol or action not in ["buy", "sell"]:
            return jsonify({"error": "Invalid payload"}), 400

        print(f"🚀 Trading signal for {symbol} - {action.upper()}")

        # Step 1: Close any open opposite positions
        close_all_positions(symbol)
        print(f"✅ Closed opposite positions before opening new {action} for {symbol}")

        # Step 2: Open new position
        res = place_order(symbol, action)
        print("✅ New order placed:", res)

        return jsonify({"success": True, "data": res}), 200

    except Exception as e:
        print("❌ ERROR:", e)
        return jsonify({"error": str(e)}), 500


@app.route('/')
def home():
    return "✅ Bitget Futures Webhook Bot is live."


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

