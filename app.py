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
    return base64.b64encode(mac.digest()).decode()

# === Helper: HTTP Headers ===
def make_headers(method, endpoint, body=""):
    timestamp = str(int(time.time() * 1000))
    sign = bitget_signature(timestamp, method, endpoint, body)
    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json"
    }

# === Fetch current position ===
def get_position(symbol):
    try:
        endpoint = f"/api/mix/v1/position/singlePosition?symbol={symbol}&marginCoin=USDT"
        url = BASE_URL + endpoint
        headers = make_headers("GET", "/api/mix/v1/position/singlePosition", f"?symbol={symbol}&marginCoin=USDT")
        res = requests.get(url, headers=headers)
        data = res.json()
        if "data" in data and data["data"]:
            pos = data["data"]
            return {
                "holdSide": pos.get("holdSide"),
                "total": float(pos.get("total", 0))
            }
    except Exception as e:
        print("⚠️ Error fetching position:", e)
    return {"holdSide": None, "total": 0}

# === Close opposite position ===
def close_opposite(symbol, side):
    pos = get_position(symbol)
    if pos["total"] > 0:
        if side.lower() == "buy" and pos["holdSide"] == "short":
            print("🔻 Closing short before opening long")
            close_order(symbol, "close_short", pos["total"])
        elif side.lower() == "sell" and pos["holdSide"] == "long":
            print("🔼 Closing long before opening short")
            close_order(symbol, "close_long", pos["total"])

# === Close order ===
def close_order(symbol, side_type, qty):
    try:
        endpoint = "/api/mix/v1/order/placeOrder"
        url = BASE_URL + endpoint
        payload = {
            "symbol": symbol,
            "marginCoin": "USDT",
            "size": str(qty),
            "side": side_type,
            "orderType": "market",
            "timeInForceValue": "normal"
        }
        body = json.dumps(payload)
        headers = make_headers("POST", endpoint, body)
        res = requests.post(url, headers=headers, data=body)
        print(f"💥 Closing order: {payload}")
        print("🌍 Bitget Response:", res.status_code, res.text)
    except Exception as e:
        print("❌ Error closing position:", e)

# === Place new order ===
def place_order(symbol, side):
    try:
        close_opposite(symbol, side)  # ✅ Step 1: close opposite before new one

        print(f"📈 Executing trade for {symbol} ({side})")
        endpoint = "/api/mix/v1/order/placeOrder"
        url = BASE_URL + endpoint

        margin_coin = "USDT"
        order_type = "market"
        trade_size = round(TRADE_BALANCE * 3, 2)  # ✅ full 3× multiplier

        payload = {
            "symbol": symbol,
            "marginCoin": margin_coin,
            "size": str(trade_size),
            "side": "open_long" if side.lower() == "buy" else "open_short",
            "orderType": order_type,
            "timeInForceValue": "normal"
        }

        body = json.dumps(payload)
        headers = make_headers("POST", endpoint, body)
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
