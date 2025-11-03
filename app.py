import os
import time
import hmac
import json
import base64
import hashlib
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ==============================
# AUTH HEADER CREATOR
# ==============================
def get_auth_headers(method, endpoint, api_key, api_secret, api_passphrase, params=""):
    try:
        base_url = os.getenv("BITGET_BASE_URL", "https://api.bitget.com")
        timestamp = str(int(time.time() * 1000))
        message = timestamp + method + endpoint + (params if params else "")
        mac = hmac.new(api_secret.encode('utf-8'), message.encode('utf-8'), hashlib.sha256)
        sign = base64.b64encode(mac.digest()).decode()
        passphrase = base64.b64encode(
            hmac.new(api_secret.encode('utf-8'), api_passphrase.encode('utf-8'), hashlib.sha256).digest()
        ).decode()

        return {
            "ACCESS-KEY": api_key,
            "ACCESS-SIGN": sign,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": passphrase,
            "Content-Type": "application/json",
        }
    except Exception as e:
        print(f"❌ Error creating auth headers: {e}")
        return None

# ==============================
# PLACE ORDER FUNCTION
# ==============================
def place_order(symbol, side, api_key, api_secret, api_passphrase):
    try:
        base_url = os.getenv("BITGET_BASE_URL", "https://api.bitget.com")
        headers = get_auth_headers("POST", "/api/mix/v1/order/placeOrder", api_key, api_secret, api_passphrase)
        if not headers:
            print("❌ Failed to generate headers.")
            return

        # ✅ Get ticker price
        ticker_res = requests.get(f"{base_url}/api/mix/v1/market/ticker?symbol={symbol}")
        ticker_data = ticker_res.json()
        if not ticker_data or "data" not in ticker_data or not ticker_data["data"]:
            print(f"⚠️ Could not fetch price for {symbol}, skipping order.")
            return
        price = float(ticker_data["data"]["last"])
        print(f"📊 Current price for {symbol}: {price}")

        # ✅ Get user-defined trade balance
        balance_env = os.getenv("TRADE_BALANCE_USDT", "5")
        try:
            base_trade_value = float(balance_env)
        except ValueError:
            base_trade_value = 5

        # ✅ Take 3x of that
        trade_value = base_trade_value * 3

        # ✅ Ensure at least 5 USDT trade value
        if trade_value < 5:
            print(f"⚠️ TRADE_BALANCE_USDT too low ({trade_value}), using 5 USDT minimum.")
            trade_value = 5

        # ✅ Calculate position size
        size = trade_value / price

        payload = {
            "symbol": symbol,
            "marginCoin": "USDT",
            "size": round(size, 4),
            "side": side,
            "orderType": "market",
            "timeInForceValue": "normal"
        }

        print(f"🚀 Placing {side.upper()} order for {symbol} | size={payload['size']} | value={trade_value} USDT")

        response = requests.post(f"{base_url}/api/mix/v1/order/placeOrder", headers=headers, json=payload)
        print(f"📦 Order response: {response.text}")

        data = response.json()
        if data.get("code") != "00000":
            print(f"⚠️ Order error: {data.get('msg')}")
        else:
            print(f"✅ Order successful: {data.get('data')}")

    except Exception as e:
        print(f"❌ Error placing order for {symbol}: {e}")

# ==============================
# CLOSE OPPOSITE POSITIONS
# ==============================
def close_opposite_positions(symbol, side, api_key, api_secret, api_passphrase):
    try:
        base_url = os.getenv("BITGET_BASE_URL", "https://api.bitget.com")
        headers = get_auth_headers("GET", "/api/mix/v1/position/singlePosition", api_key, api_secret, api_passphrase,
                                   f"?symbol={symbol}&marginCoin=USDT")
        res = requests.get(f"{base_url}/api/mix/v1/position/singlePosition?symbol={symbol}&marginCoin=USDT", headers=headers)
        data = res.json()

        if not data or "data" not in data:
            print(f"⚠️ Position fetch error: {data}")
            return

        for pos in data["data"]:
            pos_side = pos.get("holdSide")
            size = float(pos.get("total", 0))
            if size > 0:
                opposite = "sell" if side == "buy" else "buy"
                print(f"🧹 Closing {pos_side} position of {size} before new {side} for {symbol}")
                payload = {
                    "symbol": symbol,
                    "marginCoin": "USDT",
                    "size": round(size, 4),
                    "side": opposite,
                    "orderType": "market",
                    "timeInForceValue": "normal"
                }
                requests.post(f"{base_url}/api/mix/v1/order/placeOrder", headers=headers, json=payload)
    except Exception as e:
        print(f"⚠️ Error closing opposite positions: {e}")

# ==============================
# WEBHOOK ENDPOINT
# ==============================
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json(force=True)
        print(f"📩 Received alert: {data}")

        symbol = data.get("symbol")
        action = data.get("action")

        if not symbol or not action:
            return jsonify({"error": "Missing symbol or action"}), 400

        api_key = os.getenv("BITGET_API_KEY")
        api_secret = os.getenv("BITGET_API_SECRET")
        api_passphrase = os.getenv("BITGET_API_PASSPHRASE")

        if not api_key or not api_secret or not api_passphrase:
            return jsonify({"error": "Missing API credentials"}), 500

        print(f"📈 Trading signal for {symbol} - {action.upper()}")

        # ✅ Close any opposite positions first
        close_opposite_positions(symbol, action, api_key, api_secret, api_passphrase)

        # ✅ Place new order
        place_order(symbol, action, api_key, api_secret, api_passphrase)

        return jsonify({"success": True}), 200
    except Exception as e:
        print(f"❌ Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

# ==============================
# ROOT CHECK
# ==============================
@app.route('/')
def home():
    return "🚀 Bitget Futures Trading Bot is Live!"

# ==============================
# MAIN ENTRY
# ==============================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)

