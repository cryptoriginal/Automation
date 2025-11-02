# app.py
from flask import Flask, request, jsonify
import os, time, json, hmac, hashlib, base64, requests

app = Flask(__name__)

# === CONFIG ===
BITGET_API_KEY = os.getenv("BITGET_API_KEY")
BITGET_API_SECRET = os.getenv("BITGET_API_SECRET")
BITGET_API_PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE")
BITGET_BASE = "https://api.bitget.com"

if not all([BITGET_API_KEY, BITGET_API_SECRET, BITGET_API_PASSPHRASE]):
    print("⚠️ Missing Bitget API credentials. Add them in Render Environment.")

# === SIGNING ===
def sign(msg: str) -> str:
    mac = hmac.new(BITGET_API_SECRET.encode(), msg.encode(), hashlib.sha256).digest()
    return base64.b64encode(mac).decode()

def headers(method, endpoint, body=""):
    ts = str(int(time.time() * 1000))
    msg = f"{ts}{method}{endpoint}{body}"
    return {
        "ACCESS-KEY": BITGET_API_KEY,
        "ACCESS-SIGN": sign(msg),
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": BITGET_API_PASSPHRASE,
        "Content-Type": "application/json",
        "locale": "en-US",
    }

# === BITGET CALLS ===
def fetch_futures_balance(coin="USDT"):
    endpoint = "/api/v2/mix/account/account"
    url = BITGET_BASE + endpoint + f"?productType=umcbl"
    r = requests.get(url, headers=headers("GET", endpoint, ""), timeout=10)
    data = r.json()
    if data.get("code") != "00000":
        raise RuntimeError(f"Error fetching balance: {data}")
    for acc in data["data"]:
        if acc["marginCoin"] == coin:
            return float(acc["available"])
    raise RuntimeError(f"{coin} not found in balance: {data}")

def fetch_mark_price(symbol):
    endpoint = "/api/v2/mix/market/ticker"
    url = BITGET_BASE + endpoint + f"?symbol={symbol}&productType=umcbl"
    r = requests.get(url, headers=headers("GET", endpoint, ""), timeout=10)
    data = r.json()
    if data.get("code") != "00000" or "data" not in data:
        raise RuntimeError(f"Ticker error: {data}")
    return float(data["data"]["last"])

def place_market_order(symbol, side, size, lev=3):
    endpoint = "/api/v2/mix/order/place-order"
    url = BITGET_BASE + endpoint
    body = {
        "symbol": symbol,
        "productType": "umcbl",
        "marginCoin": "USDT",
        "side": "open_long" if side.lower() in ["buy", "long"] else "open_short",
        "orderType": "market",
        "size": str(size),
        "leverage": str(lev),
    }
    body_str = json.dumps(body)
    r = requests.post(url, headers=headers("POST", endpoint, body_str), data=body_str, timeout=10)
    return r.json()

def calc_size(balance, price, lev=3):
    notional = balance * lev
    return round(notional / price, 6)

# === WEBHOOK ===
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        symbol = data.get("symbol")
        side = data.get("side")
        if not symbol or not side:
            return jsonify({"error": "Missing symbol or side"}), 400

        bal = fetch_futures_balance("USDT")
        price = fetch_mark_price(symbol)
        size = calc_size(bal, price, 3)

        order = place_market_order(symbol, side, size, 3)
        return jsonify({
            "status": "ok",
            "balance": bal,
            "price": price,
            "size": size,
            "order_response": order
        })
    except Exception as e:
        app.logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))

