import os
import json
import hmac
import time
import hashlib
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

BITGET_API_KEY = os.getenv("BITGET_API_KEY")
BITGET_API_SECRET = os.getenv("BITGET_API_SECRET")
BITGET_PASSPHRASE = os.getenv("BITGET_PASSPHRASE")
TRADE_BALANCE = float(os.getenv("TRADE_BALANCE", 0))

BASE_URL = "https://api.bitget.com"

def log(msg):
    print(f"🪶 {msg}", flush=True)

def generate_signature(timestamp, method, request_path, body=""):
    pre_sign = f"{timestamp}{method}{request_path}{body}"
    return hmac.new(
        BITGET_API_SECRET.encode("utf-8"),
        pre_sign.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

def headers(method, endpoint, body=""):
    timestamp = str(int(time.time() * 1000))
    sign = generate_signature(timestamp, method, endpoint, body)
    return {
        "ACCESS-KEY": BITGET_API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": BITGET_PASSPHRASE,
        "Content-Type": "application/json",
    }

# === Fetch current position ===
def get_position(symbol):
    url = f"{BASE_URL}/api/mix/v1/position/singlePosition?symbol={symbol}&marginCoin=USDT"
    res = requests.get(url, headers=headers("GET", "/api/mix/v1/position/singlePosition", f"?symbol={symbol}&marginCoin=USDT"))
    try:
        data = res.json()
        if "data" in data and data["data"]:
            pos = data["data"]
            return {
                "holdSide": pos.get("holdSide"),
                "total": float(pos.get("total", 0))
            }
    except Exception as e:
        log(f"❌ Error parsing position: {e}")
    return {"holdSide": None, "total": 0}

# === Close opposite position ===
def close_opposite(symbol, side):
    pos = get_position(symbol)
    if pos["total"] > 0:
        if side == "buy" and pos["holdSide"] == "short":
            log("🔻 Closing short before opening long")
            place_order(symbol, "close_short", pos["total"])
        elif side == "sell" and pos["holdSide"] == "long":
            log("🔼 Closing long before opening short")
            place_order(symbol, "close_long", pos["total"])

# === Place new order ===
def place_order(symbol, side, qty=None):
    if qty is None:
        qty = TRADE_BALANCE * 3  # 3x of environment variable
    
    endpoint = "/api/mix/v1/order/placeOrder"
    url = f"{BASE_URL}{endpoint}"
    
    if side == "buy":
        side_type = "open_long"
    elif side == "sell":
        side_type = "open_short"
    elif side == "close_long":
        side_type = "close_long"
    elif side == "close_short":
        side_type = "close_short"
    else:
        return {"error": "Invalid side"}

    payload = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "size": str(qty),
        "side": side_type,
        "orderType": "market",
        "timeInForceValue": "normal"
    }

    body = json.dumps(payload)
    res = requests.post(url, headers=headers("POST", endpoint, body), data=body)
    log(f"📦 Sent order payload: {payload}")
    try:
        log(f"🧾 Response: {res.json()}")
    except:
        log(f"🧾 Raw Response: {res.text}")
    return res.json()

@app.route('/')
def home():
    return "✅ Bitget Automation Webhook Active"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    log(f"📨 Received payload: {data}")

    symbol = data.get('symbol')
    side = data.get('side')

    if not symbol or not side:
        return jsonify({'error': 'Missing symbol or side'}), 400

    close_opposite(symbol, side)
    place_order(symbol, side)

    return jsonify({'status': 'order_executed'})

if __name__ == '__main__':
    log("/////////////////////////////////////////////////////")
    log(f"🔑 API Key loaded: {bool(BITGET_API_KEY)}")
    log(f"🔒 API Secret loaded: {bool(BITGET_API_SECRET)}")
    log(f"🧩 Passphrase loaded: {bool(BITGET_PASSPHRASE)}")
    log(f"💰 Trade Balance (env): {TRADE_BALANCE}")
    log("/////////////////////////////////////////////////////")
    app.run(host='0.0.0.0', port=10000)
