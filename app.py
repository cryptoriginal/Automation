import os
import hmac
import time
import json
import hashlib
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ==========================
# ENVIRONMENT VARIABLES
# ==========================
API_KEY = os.getenv("BITGET_API_KEY")
API_SECRET = os.getenv("BITGET_API_SECRET")
PASSPHRASE = os.getenv("BITGET_PASSPHRASE")
TRADE_BALANCE = float(os.getenv("TRADE_BALANCE", "0"))

BITGET_BASE_URL = "https://api.bitget.com"
HEADERS = {
    "Content-Type": "application/json",
    "ACCESS-KEY": API_KEY,
    "ACCESS-PASSPHRASE": PASSPHRASE
}

print("////////////////////////////////////////////////////////////")
print("🚀 Available at your primary URL")
print("🔑 API Key loaded:", bool(API_KEY))
print("🔒 API Secret loaded:", bool(API_SECRET))
print("🔐 Passphrase loaded:", bool(PASSPHRASE))
print("💰 Trade Balance (env):", TRADE_BALANCE)
print("////////////////////////////////////////////////////////////")


# ==========================
# BITGET SIGNATURE FUNCTION
# ==========================
def bitget_signature(timestamp, method, request_path, body=""):
    if not API_SECRET:
        raise Exception("API secret not set")
    message = f"{timestamp}{method}{request_path}{body}"
    mac = hmac.new(API_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
    return mac.hexdigest()


# ==========================
# CLOSE ALL OPEN POSITIONS
# ==========================
def close_existing_positions(symbol, marginCoin):
    try:
        url = f"{BITGET_BASE_URL}/api/mix/v1/position/allPosition?productType=umcbl"
        timestamp = str(int(time.time() * 1000))
        sign = bitget_signature(timestamp, "GET", "/api/mix/v1/position/allPosition", "")
        headers = {
            **HEADERS,
            "ACCESS-SIGN": sign,
            "ACCESS-TIMESTAMP": timestamp
        }

        response = requests.get(url, headers=headers)
        data = response.json()

        if "data" in data:
            for pos in data["data"]:
                if pos["symbol"] == symbol and float(pos["total"] or 0) > 0:
                    side = "close_long" if pos["holdSide"] == "long" else "close_short"
                    print(f"⚠️ Closing existing {pos['holdSide']} position for {symbol}...")
                    close_order(symbol, marginCoin, side)
        else:
            print("✅ No open positions to close.")
    except Exception as e:
        print("❌ Error closing positions:", e)


# ==========================
# PLACE ORDER FUNCTION
# ==========================
def place_order(symbol, marginCoin, size, side):
    try:
        endpoint = "/api/mix/v1/order/placeOrder"
        url = BITGET_BASE_URL + endpoint
        timestamp = str(int(time.time() * 1000))
        body = json.dumps({
            "symbol": symbol,
            "marginCoin": marginCoin,
            "size": str(size),
            "side": side,
            "orderType": "market",
            "timeInForceValue": "normal"
        })

        sign = bitget_signature(timestamp, "POST", endpoint, body)
        headers = {
            **HEADERS,
            "ACCESS-SIGN": sign,
            "ACCESS-TIMESTAMP": timestamp
        }

        print("📤 Sending order payload:", body)
        response = requests.post(url, headers=headers, data=body)
        print("🌐 Bitget Response:", response.status_code, response.text)
        return response.json()
    except Exception as e:
        print("❌ Error placing order:", e)
        return {"error": str(e)}


# ==========================
# CLOSE ORDER FUNCTION
# ==========================
def close_order(symbol, marginCoin, side):
    endpoint = "/api/mix/v1/order/placeOrder"
    url = BITGET_BASE_URL + endpoint
    timestamp = str(int(time.time() * 1000))
    body = json.dumps({
        "symbol": symbol,
        "marginCoin": marginCoin,
        "size": "1",  # small size to close
        "side": side,
        "orderType": "market",
        "timeInForceValue": "normal"
    })
    sign = bitget_signature(timestamp, "POST", endpoint, body)
    headers = {
        **HEADERS,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp
    }
    response = requests.post(url, headers=headers, data=body)
    print(f"💣 Close order response ({side}):", response.status_code, response.text)


# ==========================
# FLASK WEBHOOK ENDPOINT
# ==========================
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        print("📩 Webhook triggered!")
        payload = request.get_json(force=True)
        print("📥 Received payload:", payload)

        symbol = payload.get("symbol", "").upper()
        side_raw = payload.get("side", "").lower()

        if not symbol or side_raw not in ["buy", "sell"]:
            return jsonify({"error": "Invalid payload"}), 400

        marginCoin = "USDT"
        side = "open_long" if side_raw == "buy" else "open_short"
        size = round(TRADE_BALANCE * 3 / 100, 2)  # Example: 3x trade balance, simplified

        # Step 1: Close opposite positions first
        close_existing_positions(symbol, marginCoin)

        # Step 2: Place new order
        print(f"🚀 Executing trade for {symbol} ({side_raw})")
        result = place_order(symbol, marginCoin, size, side)
        return jsonify(result)
    except Exception as e:
        print("❌ Webhook Error:", e)
        return jsonify({"error": str(e)}), 500


@app.route('/')
def home():
    return "✅ Bitget Auto-Trader is Live"


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)

