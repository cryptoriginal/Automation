import os
from flask import Flask, request, jsonify
import requests
import hmac
import hashlib
import time

app = Flask(__name__)

BITGET_API_KEY = os.getenv("BITGET_API_KEY")
BITGET_SECRET_KEY = os.getenv("BITGET_SECRET_KEY")
BITGET_PASSPHRASE = os.getenv("BITGET_PASSPHRASE")

BASE_URL = "https://api.bitget.com"

# --- Helper for Signature ---
def generate_signature(timestamp, method, request_path, body=""):
    message = f"{timestamp}{method.upper()}{request_path}{body}"
    signature = hmac.new(
        BITGET_SECRET_KEY.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return signature

# --- Bitget API Call ---
def bitget_request(method, path, body=None):
    timestamp = str(int(time.time() * 1000))
    body_str = "" if body is None else json.dumps(body)
    headers = {
        "ACCESS-KEY": BITGET_API_KEY,
        "ACCESS-SIGN": generate_signature(timestamp, method, path, body_str),
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": BITGET_PASSPHRASE,
        "Content-Type": "application/json"
    }
    url = BASE_URL + path
    response = requests.request(method, url, headers=headers, data=body_str)
    return response.json()

# --- Get Available Balance ---
def get_balance():
    data = bitget_request("GET", "/api/mix/v1/account/accounts?productType=umcbl")
    try:
        for acc in data["data"]:
            if acc["marginCoin"] == "USDT":
                return float(acc["available"])
    except:
        return 0.0
    return 0.0

# --- Set Leverage (Cross 3x) ---
def set_leverage(symbol):
    body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "leverage": "3",
        "holdSide": "long"  # just to set cross for both sides
    }
    bitget_request("POST", "/api/mix/v1/account/setLeverage", body)
    body["holdSide"] = "short"
    bitget_request("POST", "/api/mix/v1/account/setLeverage", body)

# --- Close All Positions ---
def close_positions(symbol):
    positions = bitget_request("GET", f"/api/mix/v1/position/singlePosition?symbol={symbol}&marginCoin=USDT")
    if "data" in positions and positions["data"]:
        pos = positions["data"]
        side = pos["holdSide"]
        size = abs(float(pos["total"]))
        if size > 0:
            opposite = "close_long" if side == "long" else "close_short"
            body = {
                "symbol": symbol,
                "marginCoin": "USDT",
                "size": str(size),
                "side": opposite,
                "orderType": "market"
            }
            bitget_request("POST", "/api/mix/v1/order/placeOrder", body)

# --- Place Market Order (Buy/Sell) ---
def place_order(symbol, side):
    balance = get_balance()
    if balance <= 0:
        print("⚠️ No available balance.")
        return {"error": "No balance"}
    
    # get current price
    ticker = bitget_request("GET", f"/api/mix/v1/market/ticker?symbol={symbol}")
    price = float(ticker["data"]["last"])
    qty = balance * 3 / price  # use 100% balance with 3x cross

    order_side = "open_long" if side.lower() == "buy" else "open_short"
    body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "size": str(round(qty, 4)),
        "side": order_side,
        "orderType": "market"
    }
    print(f"Placing {side.upper()} order on {symbol} for {qty} contracts")
    return bitget_request("POST", "/api/mix/v1/order/placeOrder", body)

# --- Webhook Endpoint ---
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    symbol = data.get("symbol")
    side = data.get("side")

    if not symbol or not side:
        return jsonify({"error": "Invalid alert format"}), 400

    print(f"📩 Received signal: {side.upper()} for {symbol}")

    # Apply cross 3x leverage
    set_leverage(symbol)

    # Close opposite positions before new trade
    close_positions(symbol)

    # Place new market order
    result = place_order(symbol, side)

    return jsonify(result)

@app.route("/", methods=["GET"])
def home():
    return "🚀 Bitget TradingView Futures Bot is Live!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
