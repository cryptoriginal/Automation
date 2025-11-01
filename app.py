# app.py
import os
import time
import json
import hmac
import hashlib
import logging
from flask import Flask, request, jsonify, abort
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
app = Flask(__name__)

# === Environment variables (set these in Render) ===
API_KEY      = os.getenv("MEXC_API_KEY", "")
API_SECRET   = os.getenv("MEXC_API_SECRET", "")
ALERT_SECRET = os.getenv("ALERT_SECRET", "")
DRY_RUN      = os.getenv("DRY_RUN", "true").lower() in ("1", "true", "yes")
USE_TESTNET  = os.getenv("USE_TESTNET", "false").lower() in ("1", "true", "yes")
LOG_WEBHOOK  = os.getenv("LOG_WEBHOOK", "true").lower() in ("1", "true", "yes")

# === MEXC endpoints - confirm in their docs if they change ===
# NOTE: verify contract/test/prod domains per MEXC docs
BASE_PROD = "https://contract.mexc.com"
BASE_TEST = "https://contract.mexc.com"   # change if MEXC testnet uses different host
BASE = BASE_TEST if USE_TESTNET else BASE_PROD

# Common contract order path — verify for your account/API version
ORDERS_PATH = "/api/v1/private/order/submit"

def sign_params(access_key: str, secret: str, params: dict, timestamp_ms: int):
    """
    Sign request according to common MEXC contract rule:
    signature = HMAC_SHA256(secret, accessKey + timestamp + json_body)
    """
    json_str = json.dumps(params, separators=(',', ':'), ensure_ascii=False) if params else ""
    target = access_key + str(timestamp_ms) + json_str
    signature = hmac.new(secret.encode(), target.encode(), hashlib.sha256).hexdigest()
    return signature, json_str

def place_futures_order(symbol, side, order_type="MARKET", quantity=None, price=None, leverage=3):
    ts = int(time.time() * 1000)
    body = {
        "symbol": symbol,
        "side": side,          # "BUY" / "SELL"
        "type": order_type,    # "MARKET" / "LIMIT" (use exactly as MEXC expects)
        "leverage": int(leverage)
    }
    if quantity is not None:
        # Many MEXC contract endpoints expect "size" field for contract quantity
        body["size"] = str(quantity)
    if price is not None:
        body["price"] = str(price)

    # remove None values
    body = {k:v for k,v in body.items() if v is not None}

    sig, json_body = sign_params(API_KEY, API_SECRET, body, ts)
    headers = {
        "ApiKey": API_KEY,
        "Request-Time": str(ts),
        "Signature": sig,
        "Content-Type": "application/json"
    }
    url = BASE + ORDERS_PATH
    logging.info("Order URL: %s", url)
    logging.info("Order payload: %s", json.dumps(body))
    if DRY_RUN:
        logging.info("DRY_RUN enabled — order not sent to MEXC")
        return {"status": "dry_run", "payload": body}
    try:
        resp = requests.post(url, headers=headers, data=json_body, timeout=15)
        logging.info("MEXC reply status: %s, body: %s", resp.status_code, resp.text)
        try:
            return resp.json()
        except Exception:
            return {"status_code": resp.status_code, "text": resp.text}
    except Exception as e:
        logging.exception("Error placing order")
        return {"error": str(e)}

@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.get_json(force=True, silent=True)
    if payload is None:
        logging.warning("No JSON payload received")
        return abort(400, "invalid payload")
    if LOG_WEBHOOK:
        logging.info("Webhook received: %s", json.dumps(payload))

    # basic validation using ALERT_SECRET inside payload
    if ALERT_SECRET and payload.get("secret") != ALERT_SECRET:
        logging.warning("Invalid alert secret")
        return abort(403, "invalid secret")

    symbol = payload.get("symbol")
    side = payload.get("side", "BUY").upper()
    order_type = payload.get("type", "MARKET").upper()
    qty_usd = payload.get("qty_usd")        # optional: USD size
    leverage = int(payload.get("leverage", 3))
    price = payload.get("price")            # optional for limit orders

    if not symbol:
        return abort(400, "symbol required")

    # If qty_usd provided, get current price and compute contract size (approx)
    quantity = None
    if qty_usd:
        try:
            ticker_url = f"{BASE}/api/v1/market/ticker?symbol={symbol}"
            r = requests.get(ticker_url, timeout=8)
            rj = r.json()
            price_now = None
            # adapt to response shape
            data = rj.get("data") if isinstance(rj, dict) else None
            if isinstance(data, dict):
                # try several common keys
                for k in ("lastPrice", "last", "price"):
                    if data.get(k):
                        price_now = float(data.get(k))
                        break
            if price_now is None:
                logging.error("Could not parse ticker price from MEXC response")
                return abort(502, "ticker parse fail")
            quantity = float(qty_usd) / price_now
        except Exception:
            logging.exception("Failed to fetch ticker")
            return abort(502, "failed to fetch ticker")

    result = place_futures_order(symbol=symbol, side=side, order_type=order_type,
                                 quantity=quantity, price=price, leverage=leverage)
    return jsonify({"status":"ok", "result": result})

@app.route("/", methods=["GET"])
def index():
    return "MEXC Webhook up"

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
