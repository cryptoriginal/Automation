import os
import hmac
import hashlib
import time
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

BITGET_API_KEY = os.getenv("BITGET_API_KEY")
BITGET_API_SECRET = os.getenv("BITGET_API_SECRET")
BITGET_API_PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE")
BASE_URL = "https://api.bitget.com"

# Generate Bitget signature
def sign(message):
    return hmac.new(
        BITGET_API_SECRET.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

def get_headers(method, request_path, body=""):
    timestamp = str(int(time.time() * 1000))
    if body and isinstance(body, dict):
        import json
        body = json.dumps(body)
    message = f"{timestamp}{method.upper()}{request_path}{body}"
    signature = sign(message)
    return {
        "ACCESS-KEY": BITGET_API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": BITGET_API_PASSPHRASE,
        "Content-Type": "application/json",
    }

def get_balance():
    url = f"{BASE_URL}/api/mix/v1/account/accounts?productType=umcbl"
    headers = get_headers("GET", "/api/mix/v1/account/accounts?productType=umcbl")
    res = requests.get(url, headers=headers).json()
    if "data" in res:
        for acc in res["data"]:
            if acc["marginCoin"] == "USDT":
                return float(acc["available"])
    return 0.0

def get_latest_price(symbol="SUIUSDT"):
    url = f"{BASE_URL}/api/mix/v1/market/ticker?symbol={symbol}"
    res = requests.get(url).json()
    if "data" in res:
        return float(res["data"]["last"])
    return None

def place_order(symbol="SUIUSDT", side="open_long"):
    balance = get_balance()
    if balance <= 0:
        return {"error": "Insufficient balance"}

    notional = balance * 3  # 3× leverage
    price = get_latest_price(symbol)
    if not price:
        return {"error": "Unable to fetch price"}

    quantity = round(notional / price, 2)

    url = f"{BASE_URL}/api/mix/v1/order/placeOrder"
    body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "side": side,
        "orderType": "market",
        "size": str(quantity),
        "price": str(price),
        "leverage": "3",
        "marginMode": "crossed",
        "productType": "umcbl"
    }
    headers = get_headers("POST", "/api/mix/v1/order/placeOrder", body)
    res = requests.post(url, headers=headers, json=body).json()
    return res

@app.route("/")
def home():
    return "Bitget Auto Trader is live."

# ✅ New webhook endpoint for TradingView
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if not data or "side" not in data:
        return jsonify({"error": "Invalid payload"}), 400

    side = data["side"].lower()
    if side == "long":
        result = place_order("SUIUSDT", "open_long")
    elif side == "short":
        result = place_order("SUIUSDT", "open_short")
    else:
        return jsonify({"error": "Invalid side"}), 400

    return jsonify(result)

# Optional endpoints for testing
@app.route("/balance")
def balance():
    return jsonify({"balance": get_balance()})

@app.route("/price")
def price():
    return jsonify({"price": get_latest_price("SUIUSDT")})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

