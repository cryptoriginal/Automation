import os
import time
import hmac
import hashlib
import base64
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# === Load Environment Variables ===
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
PASSPHRASE = os.getenv("PASSPHRASE")
TRADE_BALANCE = float(os.getenv("TRADE_BALANCE_USDT", "0.0"))

print("🔑 API Key loaded:", bool(API_KEY))
print("🔒 API Secret loaded:", bool(API_SECRET))
print("🧩 Passphrase loaded:", bool(PASSPHRASE))
print("💰 Trade Balance (env):", TRADE_BALANCE)

BASE_URL = "https://api.bitget.com"


# === Signature Helper ===
def bitget_signature(timestamp, method, request_path, body):
    message = f"{timestamp}{method.upper()}{request_path}{body}"
    mac = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()


# === Auth Header Helper ===
def get_headers(method, endpoint, body):
    timestamp = str(int(time.time() * 1000))
    sign = bitget_signature(timestamp, method, endpoint, body)
    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json"
    }


# === Fetch Current Positions ===
def get_open_positions(symbol):
    try:
        endpoint = f"/api/mix/v1/position/singlePosition?symbol={symbol}&marginCoin=USDT"
        headers = get_headers("GET", endpoint, "")
        response = requests.get(BASE_URL + endpoint, headers=headers)
        data = response.json()
        if data.get("code") == "00000" and data.get("data"):
            pos = data["data"]
            long_pos = float(pos.get("long", {}).get("total", 0)) if "long" in pos else 0
            short_pos = float(pos.get("short", {}).get("total", 0)) if "short" in pos else 0
            return long_pos, short_pos
        else:
            print("⚠️ Position fetch returned:", data)
            return 0, 0
    except Exception as e:
        print("❌ Error fetching positions:", str(e))
        return 0, 0


# === Close Opposite Position ===
def close_opposite(symbol, side):
    try:
        long_pos, short_pos = get_open_positions(symbol)

        if side == "buy" and short_pos > 0:
            print("🔻 Closing short position before opening long")
            close_payload = {
                "symbol": symbol,
                "marginCoin": "USDT",
                "size": str(short_pos),
                "side": "close_short",
                "orderType": "market",
                "timeInForceValue": "normal"
            }
        elif side == "sell" and long_pos > 0:
            print("🔼 Closing long position before opening short")
            close_payload = {
                "symbol": symbol,
                "marginCoin": "USDT",
                "size": str(long_pos),
                "side": "close_long",
                "orderType": "market",
                "timeInForceValue": "normal"
            }
        else:
            return  # nothing to close

        body = json.dumps(close_payload)
        headers = get_headers("POST", "/api/mix/v1/order/placeOrder", body)
        response = requests.post(BASE_URL + "/api/mix/v1/order/placeOrder", headers=headers, data=body)
        print("🧾 Close position response:", response.status_code, response.text)

    except Exception as e:
        print("❌ Error closing opposite position:", str(e))


# === Place New Order ===
def place_order(symbol, side):
    try:
        print(f"📈 Executing trade for {symbol} ({side})")

        # First close opposite position
        close_opposite(symbol, side)

        endpoint = "/api/mix/v1/order/placeOrder"
        url = BASE_URL + endpoint

        trade_size = round(TRADE_BALANCE * 3, 2)  # 3× balance as size

        payload = {
            "symbol": symbol,
            "marginCoin": "USDT",
            "size": str(trade_size),
            "side": "open_long" if side.lower() == "buy" else "open_short",
            "orderType": "market",
            "timeInForceValue": "normal"
        }

        body = json.dumps(payload)
        headers = get_headers("POST", endpoint, body)
        print("🧾 Sending order payload:", payload)
        response = requests.post(url, headers=headers, data=body)
        print("🌍 Bitget Response:", response.status_code, response.text)

    except Exception as e:
        print("❌ Exception placing order:", str(e))


# === Webhook ===
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        print("🚀 Webhook triggered!")
        data = request.get_json()
        print("📩 Received payload:", data)

        symbol = data.get("symbol")
        side = data.get("side")

        if not symbol or not side:
            return jsonify({"error": "Missing symbol or side"}), 400

        place_order(symbol, side)
        return jsonify({"status": "success"}), 200

    except Exception as e:
        print("❌ Webhook Error:", str(e))
        return jsonify({"error": str(e)}), 500


@app.route('/')
def home():
    return "✅ Bitget Auto-Trader Webhook is Live"


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
