import os
import hmac
import hashlib
import time
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# === Environment Variables (set in Render) ===
API_KEY = os.getenv("BITGET_API_KEY")
API_SECRET = os.getenv("BITGET_SECRET_KEY")
PASSPHRASE = os.getenv("BITGET_PASSPHRASE")

# === Bitget API Base ===
BASE_URL = "https://api.bitget.com"

# === Helper: Signature ===
def bitget_signature(timestamp, method, request_path, body=""):
    message = f"{timestamp}{method}{request_path}{body}"
    signature = hmac.new(API_SECRET.encode('utf-8'),
                         message.encode('utf-8'),
                         hashlib.sha256).hexdigest()
    return signature

# === Bitget API Request Function ===
def bitget_request(method, path, body=None):
    timestamp = str(int(time.time() * 1000))
    body_str = json.dumps(body) if body else ""
    sign = bitget_signature(timestamp, method, path, body_str)
    
    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json"
    }

    url = BASE_URL + path

    try:
        if method == "POST":
            response = requests.post(url, headers=headers, data=body_str)
        else:
            response = requests.get(url, headers=headers, params=body)

        print("Bitget response:", response.text)  # DEBUG PRINT
        return response.json()
    except Exception as e:
        print(f"Error while sending Bitget request: {e}")
        return None

# === Place Order ===
def place_order(symbol, side):
    # Market order setup (3x cross leverage, 100% balance usage)
    body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "side": "open_long" if side == "buy" else "open_short",
        "orderType": "market",
        "size": "100%",  # use full available balance
        "leverage": "3",
        "marginMode": "cross"
    }

    print(f"📩 Placing {side.upper()} order on {symbol}")
    res = bitget_request("POST", "/api/mix/v1/order/placeOrder", body)
    print("✅ Order Result:", res)
    return res


# === Close All Positions ===
def close_positions(symbol, side):
    close_side = "close_long" if side == "sell" else "close_short"
    body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "side": close_side,
        "orderType": "market",
        "size": "100%",
        "marginMode": "cross"
    }
    print(f"🔻 Closing opposite positions for {symbol}")
    res = bitget_request("POST", "/api/mix/v1/order/placeOrder", body)
    print("🧾 Close Result:", res)
    return res


# === Webhook (TradingView Alert Endpoint) ===
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    print("Alert received:", data)

    try:
        symbol = data.get("symbol")
        side = data.get("side")

        if not symbol or not side:
            return jsonify({"error": "Invalid alert data"}), 400

        # If BUY — close short, then open long
        if side.lower() == "buy":
            close_positions(symbol, "buy")
            place_order(symbol, "buy")

        # If SELL — close long, then open short
        elif side.lower() == "sell":
            close_positions(symbol, "sell")
            place_order(symbol, "sell")

        return jsonify({"message": "Order executed"}), 200

    except Exception as e:
        print("Error in webhook:", str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/", methods=["GET"])
def home():
    return "Bitget Trading Bot is live 🚀"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

