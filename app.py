# app.py
from flask import Flask, request, jsonify
import os, time, json, hmac, hashlib, base64
import requests

app = Flask(__name__)

# ========== CONFIG (use env vars on Render) ==========
BITGET_API_KEY = os.getenv("BITGET_API_KEY")
BITGET_API_SECRET = os.getenv("BITGET_API_SECRET")
BITGET_API_PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE")
BITGET_BASE = "https://api.bitget.com"

# Safety quick-check
if not BITGET_API_KEY or not BITGET_API_SECRET or not BITGET_API_PASSPHRASE:
    print("WARNING: One or more Bitget API credential env vars are missing. "
          "Set BITGET_API_KEY, BITGET_API_SECRET, BITGET_API_PASSPHRASE in Render.")
# =====================================================

def sign(message: str) -> str:
    """HMAC-SHA256 then base64 as Bitget expects."""
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

# ---------- Helpers to call Bitget -----------
def fetch_futures_balance(margin_coin="USDT"):
    """
    Return available balance for margin_coin from Bitget futures account (umcbl productType).
    """
    endpoint = "/api/mix/v1/account/accounts?productType=umcbl"
    url = BITGET_BASE + endpoint
    headers = get_headers("GET", endpoint, "")
    r = requests.get(url, headers=headers, timeout=15)
    try:
        data = r.json()
    except Exception:
        raise RuntimeError(f"Failed to parse balance response: HTTP {r.status_code} {r.text}")
    # data structure may vary: inspect keys if needed
    # look for entries where marginCoin == margin_coin
    if not data or "data" not in data or not data["data"]:
        raise RuntimeError(f"Empty/invalid balance response: {data}")
    for item in data["data"]:
        if item.get("marginCoin") == margin_coin:
            # availableBalance or available may be provided; try common fields
            avail = item.get("available") or item.get("availableBalance") or item.get("balance")
            if avail is None:
                # sometimes nested in balances list; return raw item for debugging
                raise RuntimeError(f"Could not find available balance field in item: {item}")
            return float(avail)
    raise RuntimeError(f"No entry for margin coin {margin_coin} in balance response: {data}")

def fetch_mark_price(symbol):
    """
    Get current mark/last price for symbol via market tick endpoint.
    """
    endpoint = f"/api/mix/v1/market/ticker?symbol={symbol}&productType=umcbl"
    url = BITGET_BASE + endpoint
    headers = get_headers("GET", endpoint, "")
    r = requests.get(url, headers=headers, timeout=10)
    try:
        j = r.json()
    except Exception:
        raise RuntimeError(f"Failed to fetch ticker: HTTP {r.status_code} {r.text}")
    # common key: j["data"]["last"] or j["data"]["lastPrice"]
    d = j.get("data")
    if not d:
        raise RuntimeError(f"Invalid ticker response: {j}")
    # handle both dict and list
    last = d.get("last") or d.get("lastPrice") or d.get("close") or d.get("price")
    if last is None:
        # sometimes data is a list
        if isinstance(d, list) and d:
            last = d[0].get("last") or d[0].get("lastPrice")
    if last is None:
        raise RuntimeError(f"Could not find last price in ticker response: {j}")
    return float(last)

def calc_size_from_notional(notional_usdt, mark_price):
    """
    Convert notional USDT -> contract size.
    Default: size = notional / mark_price
    (If your instrument uses a different contract multiplier change this conversion.)
    """
    if mark_price <= 0:
        raise RuntimeError("Invalid mark_price")
    size = notional_usdt / mark_price
    # Bitget requires size maybe rounded to allowed precision; keep 6 decimals
    return round(size, 6)

def place_market_order(symbol, side, size, leverage=3):
    endpoint = "/api/mix/v1/order/placeOrder"
    url = BITGET_BASE + endpoint
    body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "side": side,            # "open_long"/"open_short" OR "buy"/"sell" depending on endpoint docs
        "orderType": "market",
        "size": str(size),
        "leverage": str(leverage),
        "productType": "umcbl",
        # timeInForceValue may be required in some cases: "normal"
    }
    # Some logs previously used: side "buy"/"sell" — other variants use open_long/open_short.
    # If exchange returns "side mismatch" try switching to open_long/open_short mapping (handled outside or by user)
    body_str = json.dumps(body)
    headers = get_headers("POST", endpoint, body_str)
    r = requests.post(url, headers=headers, data=body_str, timeout=15)
    try:
        return r.json()
    except Exception:
        return {"http_status": r.status_code, "text": r.text}

# --------- TradingView webhook route -----------
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        # TradingView sometimes sends text/plain; force JSON parsing:
        try:
            payload = request.get_json(force=True)
        except Exception:
            # fallback: try raw text that might be JSON string
            raw = request.data.decode("utf-8", errors="ignore")
            try:
                payload = json.loads(raw)
            except Exception:
                return jsonify({"error": "invalid payload", "raw": raw}), 400

        # Expected payload example:
        # {"symbol":"SUIUSDT_UMCBL","side":"buy"}
        symbol = payload.get("symbol")
        side_raw = payload.get("side", "buy")
        if not symbol:
            return jsonify({"error": "missing symbol in payload", "payload": payload}), 400

        # Normalize side -> Bitget expects "buy"/"sell" in some endpoints,
        # or "open_long"/"open_short" on others. We'll try 'buy'/'sell' first.
        side = side_raw.lower()
        if side not in ("buy", "sell", "open_long", "open_short"):
            # allow "long"/"short" too
            if side in ("long", "buy"):
                side = "buy"
            elif side in ("short", "sell"):
                side = "sell"
            else:
                return jsonify({"error": "invalid side", "side": side_raw}), 400

        # 1) Fetch balance (USDT) from Bitget futures account
        try:
            balance = fetch_futures_balance("USDT")
        except Exception as e:
            app.logger.error("Error fetching balance: %s", e)
            return jsonify({"error": "failed_fetch_balance", "detail": str(e)}), 500

        # 2) desired leverage is fixed 3x cross
        leverage = 3

        # 3) compute notional (use 100% wallet * leverage)
        notional_usdt = round(balance * leverage, 6)
        if notional_usdt <= 0:
            return jsonify({"error": "no_available_balance", "balance": balance}), 400

        # 4) fetch mark price to convert notional -> size
        try:
            mark_price = fetch_mark_price(symbol)
        except Exception as e:
            app.logger.error("Error fetching mark price: %s", e)
            return jsonify({"error": "failed_fetch_price", "detail": str(e)}), 500

        size = calc_size_from_notional(notional_usdt, mark_price)
        if size <= 0:
            return jsonify({"error": "calculated_zero_size", "size": size}), 400

        # 5) place order
        app.logger.info("Placing order: symbol=%s side=%s notional=%s mark=%s size=%s lev=%s",
                        symbol, side, notional_usdt, mark_price, size, leverage)
        order_resp = place_market_order(symbol, side, size, leverage)
        app.logger.info("Order response: %s", order_resp)
        return jsonify({"ok": True, "balance": balance, "notional_usdt": notional_usdt,
                        "mark_price": mark_price, "size": size, "order_resp": order_resp})
    except Exception as e:
        app.logger.exception("Webhook processing error")
        return jsonify({"error": "exception", "detail": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
