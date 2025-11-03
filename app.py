# app.py
from flask import Flask, request, jsonify
import os, time, json, hmac, hashlib, base64
import requests

app = Flask(__name__)

# ========== CONFIG ==========
BITGET_API_KEY = os.getenv("BITGET_API_KEY")
BITGET_API_SECRET = os.getenv("BITGET_API_SECRET")
BITGET_API_PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE")
TRADE_BALANCE_USDT = float(os.getenv("TRADE_BALANCE_USDT", "0"))
BITGET_BASE = "https://api.bitget.com"

if not BITGET_API_KEY or not BITGET_API_SECRET or not BITGET_API_PASSPHRASE:
    app.logger.warning("⚠️ Missing Bitget API credentials in environment variables.")
if TRADE_BALANCE_USDT <= 0:
    app.logger.warning("⚠️ TRADE_BALANCE_USDT env var not set or zero. Bot may not trade.")
# =====================================================

def sign(message: str) -> str:
    mac = hmac.new(BITGET_API_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(mac).decode()

def get_headers(method: str, endpoint: str, body_str: str = "") -> dict:
    ts = str(int(time.time() * 1000))
    msg = f"{ts}{method}{endpoint}{body_str}"
    signature = sign(msg)
    return {
        "ACCESS-KEY": BITGET_API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": BITGET_API_PASSPHRASE,
        "Content-Type": "application/json",
        "locale": "en-US"
    }

# ---------------- Bitget API helpers ----------------
def fetch_positions(symbol):
    """Fetch current open positions for given symbol safely"""
    endpoint = "/api/mix/v1/position/allPosition"
    url = BITGET_BASE + endpoint
    headers = get_headers("GET", endpoint)
    try:
        r = requests.get(url, headers=headers, timeout=15)
        data = r.json()
    except Exception as e:
        app.logger.error(f"Error fetching positions: {e}")
        return []

    if not data or "data" not in data or data["data"] is None:
        app.logger.warning(f"No valid data in position response: {data}")
        return []
    return [p for p in data["data"] if p.get("symbol") == symbol]

def close_position(symbol, side):
    """Close existing position before opening opposite one"""
    positions = fetch_positions(symbol)
    if not positions:
        return {"msg": "No open positions to close."}

    for p in positions:
        hold_side = p.get("holdSide")
        pos_size = float(p.get("total") or 0)
        if pos_size <= 0:
            continue

        # Opposite close logic
        if (side == "buy" and hold_side == "short") or (side == "sell" and hold_side == "long"):
            close_side = "close_short" if hold_side == "short" else "close_long"
            endpoint = "/api/mix/v1/order/placeOrder"
            url = BITGET_BASE + endpoint
            body = {
                "symbol": symbol,
                "marginCoin": "USDT",
                "side": close_side,
                "orderType": "market",
                "size": str(pos_size),
                "productType": "umcbl"
            }
            headers = get_headers("POST", endpoint, json.dumps(body))
            try:
                r = requests.post(url, headers=headers, data=json.dumps(body), timeout=15)
                return {"closed": close_side, "resp": r.json()}
            except Exception as e:
                app.logger.error(f"Error closing position: {e}")
                return {"error": str(e)}
    return {"msg": "No opposite position found to close."}

def fetch_mark_price(symbol):
    endpoint = f"/api/mix/v1/market/ticker?symbol={symbol}&productType=umcbl"
    url = BITGET_BASE + endpoint
    headers = get_headers("GET", endpoint)
    r = requests.get(url, headers=headers, timeout=10)
    j = r.json()
    d = j.get("data")
    if not d:
        raise RuntimeError(f"Invalid ticker response: {j}")
    last = d.get("last") or d.get("lastPrice")
    if last is None:
        raise RuntimeError(f"Could not find price in response: {j}")
    return float(last)

def calc_size_from_notional(notional_usdt, mark_price):
    return round(notional_usdt / mark_price, 6)

def place_market_order(symbol, side, size, leverage=3):
    """Open a market order with given leverage"""
    endpoint = "/api/mix/v1/order/placeOrder"
    url = BITGET_BASE + endpoint
    body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "side": "open_long" if side == "buy" else "open_short",
        "orderType": "market",
        "size": str(size),
        "leverage": str(leverage),
        "productType": "umcbl",
        "timeInForceValue": "normal"
    }
    headers = get_headers("POST", endpoint, json.dumps(body))
    r = requests.post(url, headers=headers, data=json.dumps(body), timeout=15)
    return r.json()

# ---------------- Flask Webhook ----------------
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    symbol = payload.get("symbol")
    side = payload.get("side", "").lower()
    if not symbol or side not in ("buy", "sell"):
        return jsonify({"error": "Missing or invalid symbol/side"}), 400

    app.logger.info(f"📩 Received alert: {symbol} | {side}")

    # Step 1: Close any opposite position
    try:
        close_resp = close_position(symbol, side)
        app.logger.info(f"Close response: {close_resp}")
    except Exception as e:
        app.logger.error(f"Error closing opposite position: {e}")
        close_resp = {"error": str(e)}

    # Step 2: Open new position
    try:
        mark_price = fetch_mark_price(symbol)
        notional = TRADE_BALANCE_USDT * 3  # 3x cross leverage
        size = calc_size_from_notional(notional, mark_price)
        order_resp = place_market_order(symbol, side, size, leverage=3)
        app.logger.info(f"✅ Order placed: {order_resp}")
        return jsonify({
            "ok": True,
            "symbol": symbol,
            "side": side,
            "mark_price": mark_price,
            "size": size,
            "close_resp": close_resp,
            "order_resp": order_resp
        })
    except Exception as e:
        app.logger.exception("❌ Trade execution error")
        return jsonify({"error": str(e)}), 500

@app.route("/")
def home():
    return "✅ Bitget TradingView Bot is Live!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
