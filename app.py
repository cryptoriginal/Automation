# app.py
from flask import Flask, request, jsonify
import os, time, json, hmac, hashlib, base64
import requests
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ========== CONFIG (use env vars on Render) ==========
BITGET_API_KEY = os.getenv("BITGET_API_KEY")
BITGET_API_SECRET = os.getenv("BITGET_API_SECRET")
BITGET_API_PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE")
# IMPORTANT: set this in Render to the USDT wallet amount you want the bot to use
# Example: 10  -> means you want to use 10 USDT wallet * 3x leverage => 30 USDT notional
TRADE_BALANCE_USDT = os.getenv("TRADE_BALANCE_USDT")  # string -> convert to float
BITGET_BASE = "https://api.bitget.com"
# =====================================================

if not (BITGET_API_KEY and BITGET_API_SECRET and BITGET_API_PASSPHRASE):
    app.logger.warning("One or more Bitget API credential env vars are missing. "
                       "Set BITGET_API_KEY, BITGET_API_SECRET, BITGET_API_PASSPHRASE in Render.")

if not TRADE_BALANCE_USDT:
    app.logger.warning("TRADE_BALANCE_USDT env var not set. The app will fail to trade without it.")

def sign(message: str) -> str:
    if BITGET_API_SECRET is None:
        raise RuntimeError("BITGET_API_SECRET is not set.")
    mac = hmac.new(BITGET_API_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(mac).decode()

def get_headers(method: str, endpoint: str, body_str: str = "") -> dict:
    ts = str(int(time.time() * 1000))
    message = f"{ts}{method}{endpoint}{body_str}"
    signature = sign(message)
    return {
        "ACCESS-KEY": BITGET_API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": BITGET_API_PASSPHRASE,
        "Content-Type": "application/json",
        "locale": "en-US"
    }

# --- Market utilities ---
def fetch_mark_price(symbol):
    endpoint = f"/api/mix/v1/market/ticker?symbol={symbol}&productType=umcbl"
    url = BITGET_BASE + endpoint
    headers = get_headers("GET", endpoint, "")
    r = requests.get(url, headers=headers, timeout=10)
    try:
        j = r.json()
    except Exception:
        raise RuntimeError(f"Failed to fetch ticker: HTTP {r.status_code} {r.text}")
    d = j.get("data")
    if not d:
        raise RuntimeError(f"Invalid ticker response: {j}")
    last = None
    if isinstance(d, dict):
        last = d.get("last") or d.get("lastPrice") or d.get("close") or d.get("price")
    elif isinstance(d, list) and d:
        last = d[0].get("last") or d[0].get("lastPrice")
    if last is None:
        raise RuntimeError(f"Could not find last price in ticker response: {j}")
    return float(last)

def calc_size_from_notional(notional_usdt, mark_price):
    if mark_price <= 0:
        raise RuntimeError("Invalid mark_price")
    size = notional_usdt / mark_price
    return round(size, 6)

# --- Order placement ---
def place_market_order(symbol, side, size, leverage=3, reduce_only=False):
    """
    side should be one of:
      - "open_long", "open_short", "close_long", "close_short"
    size = contract size (decimal)
    """
    endpoint = "/api/mix/v1/order/placeOrder"
    url = BITGET_BASE + endpoint
    body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "side": side,
        "orderType": "market",
        "size": str(size),
        "leverage": str(leverage),
        "productType": "umcbl"
    }
    # reduceOnly handling - bitget uses 'reduceOnly' in some API versions
    if reduce_only:
        body["reduceOnly"] = True
    body_str = json.dumps(body)
    headers = get_headers("POST", endpoint, body_str)
    r = requests.post(url, headers=headers, data=body_str, timeout=15)
    try:
        return r.json()
    except Exception:
        return {"http_status": r.status_code, "text": r.text}

# Helper mapping: incoming "buy/sell/long/short" -> actions
def get_action_for_signal(side_signal):
    s = side_signal.lower()
    if s in ("buy", "long"):
        # want to end up long: first close any short positions, then open long
        return {"close": "close_short", "open": "open_long"}
    elif s in ("sell", "short"):
        return {"close": "close_long", "open": "open_short"}
    else:
        return None

# ---------- TradingView webhook route -----------
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        # parse JSON many ways TradingView may send it
        try:
            payload = request.get_json(force=True)
        except Exception:
            raw = request.data.decode("utf-8", errors="ignore")
            try:
                payload = json.loads(raw)
            except Exception:
                return jsonify({"error": "invalid payload", "raw": raw}), 400

        # Expecting something like: {"symbol":"SUIUSDT_UMCBL","side":"buy"}
        symbol = payload.get("symbol")
        side_raw = payload.get("side", "buy")
        if not symbol:
            return jsonify({"error": "missing symbol in payload", "payload": payload}), 400

        action = get_action_for_signal(side_raw)
        if action is None:
            return jsonify({"error": "invalid side", "side": side_raw}), 400

        # Get configured wallet amount from env (we do NOT query Bitget for balance)
        if not TRADE_BALANCE_USDT:
            return jsonify({"error": "TRADE_BALANCE_USDT not set in env"}), 500
        try:
            wallet = float(TRADE_BALANCE_USDT)
        except Exception:
            return jsonify({"error": "TRADE_BALANCE_USDT invalid float", "value": TRADE_BALANCE_USDT}), 500

        leverage = 3  # fixed cross 3x as requested
        notional_usdt = round(wallet * leverage, 6)
        if notional_usdt <= 0:
            return jsonify({"error": "invalid notional calculated", "wallet": wallet}), 400

        # fetch mark price to compute contract size
        mark_price = fetch_mark_price(symbol)
        size = calc_size_from_notional(notional_usdt, mark_price)
        if size <= 0:
            return jsonify({"error": "calculated zero size", "size": size}), 400

        # 1) Close opposite positions first (reduceOnly)
        close_side = action["close"]
        app.logger.info("Closing opposite positions (reduceOnly) for %s using side=%s size=%s", symbol, close_side, size)
        close_resp = place_market_order(symbol, close_side, size, leverage=leverage, reduce_only=True)
        app.logger.info("Close response: %s", close_resp)

        # 2) Open requested position
        open_side = action["open"]
        app.logger.info("Placing open order for %s side=%s notional=%s size=%s lev=%s", symbol, open_side, notional_usdt, size, leverage)
        open_resp = place_market_order(symbol, open_side, size, leverage=leverage, reduce_only=False)
        app.logger.info("Open response: %s", open_resp)

        return jsonify({
            "ok": True,
            "symbol": symbol,
            "requested_side": side_raw,
            "wallet_used_usdt": wallet,
            "notional_usdt": notional_usdt,
            "mark_price": mark_price,
            "size": size,
            "close_resp": close_resp,
            "open_resp": open_resp
        })
    except Exception as e:
        app.logger.exception("Webhook processing error")
        return jsonify({"error": "exception", "detail": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
