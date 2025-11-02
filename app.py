import os
import time
import json
import hmac
import base64
import hashlib
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ==== BITGET CREDENTIALS ====
API_KEY = os.getenv("BITGET_API_KEY")
API_SECRET = os.getenv("BITGET_API_SECRET")
PASSPHRASE = os.getenv("BITGET_PASSPHRASE")

# ==== BASE URL ====
BASE_URL = "https://api.bitget.com"

# ==== SIGNING FUNCTION ====
def sign_request(timestamp, method, request_path, body_str=""):
    message = f"{timestamp}{method.upper()}{request_path}{body_str}"
    signature = base64.b64encode(
        hmac.new(API_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    ).decode()
    return signature

# ==== FUTURES ORDER FUNCTION ====
def place_futures_order(symbol, side, size, price=None, order_type="market", marginMode="cross", leverage="5"):
    """
    Places a futures order on Bitget.
    """
    timestamp = str(int(time.time() * 1000))
    request_path = "/api/mix/v1/order/placeOrder"
    body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "side": side.lower(),  # buy or sell
        "orderType": order_type.lower(),  # limit or market
        "size": str(size),
        "marginMode": marginMode,
        "leverage": leverage,
    }

    if order_type.lower() == "limit" and price:
        body["price"] = str(price)

    body_str = json.dumps(body)
    sign = sign_request(timestamp, "POST", request_path, body_str)

    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json",
        "locale": "en-US"
    }

    url = BASE_URL + request_path
    response = requests.post(url, headers=headers, data=body_str, timeout=15)
    return response.json()

# ==== FLASK WEBHOOK ====
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    if not data:
        return jsonify({"error": "No JSON payload received"}), 400

    symbol = data.get("symbol")
    side = data.get("side", "").lower()
    size = data.get("size", "0.01")
    order_type = data.get("type", "market")
    price = data.get("price")

    result = place_futures_order(symbol, side, size, price, order_type)

    return jsonify({
        "status": "Order executed",
        "symbol": symbol,
        "side": side,
        "order_type": order_type,
        "response": result
    })

# ==== HOME PAGE ====
@app.route("/", methods=["GET"])
def home():
    return "✅ Bitget Futures TradingView Webhook Bot is Running!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))

