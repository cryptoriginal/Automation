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

# Get Futures account balance (USDT)
def get_balance():
    url = f"{BASE_URL}/api/mix/v1/account/accounts?productType=umcbl"
    headers = get_headers("GET", "/api/mix/v1/account/accounts?productType=umcbl")
    res = requests.get(url, headers=headers).json()
    if "data" in res:
        for acc in res["data"]:
            if acc["marginCoin"] == "USDT":
                return float(acc["available"])
    return 0.0

# Place futures order (cross 3×, full balance)
def place_order(symbol="SUIUSDT", side="open_long"):
    balance = get_balance()
    if balance <= 0:
        return {"error": "Insufficient balance"}

    notional = balance * 3  # use 3× total balance
    price = get_latest_price(symbol)
    if not price:
        return {"error": "Unable to fetch price"}

    # calculate quantity based on notional
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

# Get latest price
def get_latest_price(symbol="SUIUSDT"):
    url = f"{BASE_URL}/api/mix/v1/market/ticker?symbol={symbol}"
    res = requests.get(url).json()
    if "data" in res:
        return float(res["data"]["last"])
    return None

@app.route("/")
def home():
    return "Bitget Auto Trader is live."

@app.route("/trade", methods=["POST"])
def trade():
    data = request.json
    side = data.get("side", "open_long")  # open_long / open_short
    result = place_order("SUIUSDT", side)
    return jsonify(result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

