from flask import Flask, request, jsonify
import os, time, json, hmac, hashlib, base64
import requests

app = Flask(__name__)

# ====== ENV CONFIG ======
BITGET_API_KEY = os.getenv("BITGET_API_KEY")
BITGET_API_SECRET = os.getenv("BITGET_API_SECRET")
BITGET_API_PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE")
BITGET_BASE = "https://api.bitget.com"

# ====== SIGNING HELPERS ======
def sign(message: str) -> str:
    mac = hmac.new(BITGET_API_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(mac).decode()

def get_headers(method: str, endpoint: str, body_str: str = "") -> dict:
    ts = str(int(time.time() * 1000))
    signature = sign(f"{ts}{method}{endpoint}{body_str}")
    return {
        "ACCESS-KEY": BITGET_API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": BITGET_API_PASSPHRASE,
        "Content-Type": "application/json",
        "locale": "en-US"
    }

# ====== BITGET API CALLS ======
def fetch_futures_balance(symbol="BTCUSDT_UMCBL"):
    """
    Fetch futures balance for given symbol (using the single-account endpoint).
    """
    endpoint = f"/api/mix/v1/account/account?symbol={symbol}"
    url = BITGET_BASE + endpoint
    headers = get_headers("GET", endpoint)
    r = requests.get(url, headers=headers, timeout=15)

    try:
        data = r.json()
    except Exception:
        raise RuntimeError(f"Failed to parse response: HTTP {r.status_code} {r.text}")

    if not data or "data" not in data or not data["data"]:
        raise RuntimeError(f"Invalid/empty balance response: {data}")

    item = data["data"]
    avail = item.get("available") or item.get("availableBalance") or item.get("usdtEquity")
    if avail is None:
        raise RuntimeError(f"Could not find balance field in response: {item}")

    return float(avail)

def fetch_mark_price(symbol):
    endpoint = f"/api/mix/v1/market/ticker?symbol={symbol}&productType=umcbl"
    url = BITGET_BASE + endpoint
    headers = get_headers("GET", endpoint)
    r = requests.get(url, headers=headers, timeout=10)
    j = r.json()
    d = j.get("data", {})
    last = d.get("last") or d.get("lastPrice") or d.get("close")
    return float(last)

def calc_size_from_notional(notional_usdt, mark_price):
    return round(notional_usdt / mark_price, 6)

def place_market_order(symbol, side, size, leverage=3):
    endpoint = "/api/mix/v1/order/placeOrder"
    url = BITGET_BASE + endpoint
    body = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "side": side,  # "buy" or "sell"
        "orderType": "market",
        "size": str(size),
        "leverage": str(leverage),
        "productType": "umcbl"
    }
    body_str = json.dumps(body)
    headers = get_headers("POST", endpoint, body_str)
    r = requests.post(url, headers=headers, data=body_str, timeout=15)
    return r.json()

# ====== MAIN ROUTE ======
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        payload = request.get_json(force=True)
        symbol = payload.get("symbol")
        side = payload.get("side", "buy").lower()

        if not symbol:
            return jsonify({"error": "missing symbol"}), 400

        if side not in ("buy", "sell", "long", "short"):
            return jsonify({"error": f"invalid side: {side}"}), 400
        side = "buy" if side in ("buy", "long", "open_long") else "sell"

        # Step 1: Get balance
        try:
            balance = fetch_futures_balance(symbol)
        except Exception as e:
            app.logger.error("Webhook error: %s", e)
            return jsonify({"error": "fetch_balance", "detail": str(e)}), 500

        if balance <= 0:
            return jsonify({"error": "no_balance", "balance": balance}), 400

        # Step 2: Get mark price
        mark = fetch_mark_price(symbol)

        # Step 3: Compute size & place order
        leverage = 3
        notional = round(balance * leverage, 6)
        size = calc_size_from_notional(notional, mark)

        order_resp = place_market_order(symbol, side, size, leverage)
        return jsonify({
            "ok": True,
            "balance": balance,
            "mark_price": mark,
            "size": size,
            "order_resp": order_resp
        })

    except Exception as e:
        app.logger.exception("Webhook failed")
        return jsonify({"error": "exception", "detail": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
