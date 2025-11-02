import hmac
import hashlib
import base64
import time
import json
import logging
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ==================== CONFIG ====================
BITGET_API_KEY = "YOUR_BITGET_API_KEY"
BITGET_API_SECRET = "YOUR_BITGET_API_SECRET"
BITGET_PASSPHRASE = "YOUR_BITGET_PASSPHRASE"
BASE_URL = "https://api.bitget.com"
LEVERAGE = 3
MARGIN_MODE = "cross"
SYMBOL_SUFFIX = "_UMCBL"  # USDT-M perpetual

# =================================================

def get_server_time():
    url = f"{BASE_URL}/api/spot/v1/public/time"
    res = requests.get(url)
    return str(res.json()["data"])

def sign_request(timestamp, method, request_path, body=""):
    msg = f"{timestamp}{method}{request_path}{body}"
    mac = hmac.new(BITGET_API_SECRET.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()

def send_request(method, endpoint, body=None):
    url = f"{BASE_URL}{endpoint}"
    timestamp = str(int(time.time() * 1000))
    body_str = json.dumps(body) if body else ""
    signature = sign_request(timestamp, method, endpoint, body_str)
    
    headers = {
        "ACCESS-KEY": BITGET_API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": BITGET_PASSPHRASE,
        "Content-Type": "application/json",
    }
    response = requests.request(method, url, headers=headers, data=body_str)
    return response.json()

def get_balance():
    endpoint = "/api/mix/v1/account/accounts"
    res = send_request("GET", endpoint)
    if res.get("data"):
        for acc in res["data"]:
            if acc["marginCoin"] == "USDT":
                return float(acc["available"])
    return 0

def set_leverage(symbol, leverage):
    endpoint = "/api/mix/v1/account/setLeverage"
    body = {"symbol": symbol, "marginCoin": "USDT", "leverage": str(leverage), "holdSide": "long"}
    send_request("POST", endpoint, body)
    body["holdSide"] = "short"
    send_request("POST", endpoint, body)

def close_all_positions(symbol):
    endpoint = "/api/mix/v1/order/closeAllPositions"
    body = {"symbol": symbol, "marginCoin": "USDT"}
    send_request("POST", endpoint, body)

def place_order(symbol, side, size):
    endpoint = "/api/mix/v1/order/placeOrder"
    body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "size": str(size),
        "side": "open_long" if side == "buy" else "open_short",
        "orderType": "market",
        "timeInForceValue": "normal",
    }
    return send_request("POST", endpoint, body)

def get_market_price(symbol):
    endpoint = f"/api/mix/v1/market/ticker?symbol={symbol}"
    res = requests.get(BASE_URL + endpoint).json()
    return float(res["data"]["last"]) if res.get("data") else 0

def execute_trade(symbol, side):
    try:
        logging.info(f"🚀 Executing {side.upper()} order for {symbol} on Bitget...")
        set_leverage(symbol, LEVERAGE)
        close_all_positions(symbol)
        balance = get_balance()
        if balance <= 0:
            logging.warning("⚠️ No USDT balance available to trade.")
            return

        price = get_market_price(symbol)
        size = round((balance * LEVERAGE) / price, 3)
        res = place_order(symbol, side, size)
        logging.info(f"✅ Trade executed: {res}")
    except Exception as e:
        logging.error(f"Trade execution failed: {e}")

@app.route('/')
def home():
    return "✅ Bitget Trading Webhook is Running"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json(force=True)
        logging.info(f"📩 Webhook received: {data}")
        
        if "ticker" not in data or "strategy" not in data:
            return jsonify({"error": "Invalid alert format"}), 400

        symbol = data["ticker"]
        side = data["strategy"]["order_action"].lower()
        symbol_name = f"{symbol}{SYMBOL_SUFFIX}"
        
        execute_trade(symbol_name, side)
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=10000)

