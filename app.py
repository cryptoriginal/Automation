import os
import hmac
import hashlib
import base64
import json
import time
import threading
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ==============================
# CONFIGURATION
# ==============================
BITGET_API_KEY = os.getenv("BITGET_API_KEY", "YOUR_BITGET_API_KEY")
BITGET_SECRET_KEY = os.getenv("BITGET_SECRET_KEY", "YOUR_BITGET_SECRET_KEY")
BITGET_PASSPHRASE = os.getenv("BITGET_PASSPHRASE", "YOUR_BITGET_PASSPHRASE")
BITGET_BASE_URL = "https://api.bitget.com"

# ==============================
# SIGNATURE FUNCTION
# ==============================
def generate_signature(timestamp, method, request_path, body=""):
    if not body:
        body = ""
    message = f"{timestamp}{method}{request_path}{body}"
    mac = hmac.new(BITGET_SECRET_KEY.encode(), message.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()

# ==============================
# API REQUEST WRAPPER
# ==============================
def send_signed_request(method, path, body=None):
    url = BITGET_BASE_URL + path
    timestamp = str(int(time.time() * 1000))
    body_json = json.dumps(body) if body else ""
    sign = generate_signature(timestamp, method, path, body_json)

    headers = {
        "ACCESS-KEY": BITGET_API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": BITGET_PASSPHRASE,
        "Content-Type": "application/json",
    }

    try:
        if method == "POST":
            r = requests.post(url, headers=headers, data=body_json)
        else:
            r = requests.get(url, headers=headers)
        return r.json()
    except Exception as e:
        app.logger.error(f"Request failed: {e}")
        return None

# ==============================
# TRADING FUNCTIONS
# ==============================
def close_positions(symbol, side):
    """Close opposite positions first"""
    try:
        close_side = "close_short" if side == "buy" else "close_long"
        payload = {"symbol": symbol, "marginCoin": "USDT", "side": close_side}
        result = send_signed_request("POST", "/api/mix/v1/order/close-positions", payload)
        app.logger.info(f"🧹 Close Result: {result}")
        return result
    except Exception as e:
        app.logger.error(f"Error closing positions: {e}")
        return None

def place_order(symbol, side):
    """Open new position"""
    try:
        order_side = "open_long" if side == "buy" else "open_short"
        payload = {
            "symbol": symbol,
            "marginCoin": "USDT",
            "side": order_side,
            "orderType": "market",
            "leverage": "3",
            "size": "1"
        }
        result = send_signed_request("POST", "/api/mix/v1/order/placeOrder", payload)
        app.logger.info(f"🚀 Order Result: {result}")
        return result
    except Exception as e:
        app.logger.error(f"Error placing order: {e}")
        return None

# ==============================
# WEBHOOK ENDPOINT
# ==============================
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        app.logger.info(f"📩 Alert received: {data}")

        symbol = data.get("symbol")
        side = data.get("side")

        if not symbol or side not in ["buy", "sell"]:
            return jsonify({"error": "Invalid alert format"}), 400

        # Step 1: Close opposite side
        app.logger.info(f"🔄 Closing opposite positions for {symbol}")
        close_positions(symbol, side)

        # Step 2: Place new order
        app.logger.info(f"💥 Placing {side.upper()} order on {symbol}")
        place_order(symbol, side)

        return jsonify({"status": "success"}), 200
    except Exception as e:
        app.logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

# ==============================
# TEST SIGNATURE (runs in background)
# ==============================
def test_signature_on_startup():
    try:
        time.sleep(2)
        app.logger.info("===================================")
        app.logger.info("🔍 Testing Bitget Signature...")
        timestamp = str(int(time.time() * 1000))
        sign = generate_signature(timestamp, "GET", "/api/mix/v1/market/contracts?productType=umcbl", "")
        app.logger.info("✅ Signature generated successfully!")
        app.logger.info(f"Timestamp: {timestamp}")
        app.logger.info(f"Example request: /api/mix/v1/market/contracts?productType=umcbl")
        app.logger.info(f"Signature (first 50 chars): {sign[:50]}...")
        app.logger.info(f"Passphrase: {BITGET_PASSPHRASE}")
        app.logger.info("===================================")
    except Exception as e:
        app.logger.error(f"Signature test failed: {e}")

# ==============================
# ROOT ENDPOINT
# ==============================
@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "running", "service": "Bitget Auto Trader"}), 200

# ==============================
# MAIN ENTRY
# ==============================
if __name__ == "__main__":
    threading.Thread(target=test_signature_on_startup).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

