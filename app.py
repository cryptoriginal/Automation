import json
import logging
import time
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify

# === Flask setup ===
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# === MEXC API ===
API_KEY = "mx0vglcToeWBx8cgA1"
API_SECRET = "4ff73650ded64544911de7fc0dd73f01"
BASE_URL = "https://api.mexc.com"

# === Webhook Secret ===
WEBHOOK_SECRET = "my_tv_secret_123"

# === Utility Functions ===
def get_server_time():
    try:
        r = requests.get(f"{BASE_URL}/api/v3/time", timeout=15)
        return r.json()["serverTime"]
    except Exception as e:
        logging.error("❌ Failed to fetch server time: %s", e)
        return int(time.time() * 1000)

def sign_request(params):
    query_string = "&".join([f"{key}={value}" for key, value in params.items()])
    signature = hmac.new(API_SECRET.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    return signature

def fetch_ticker(symbol):
    """Fetch latest ticker price with retry and 15s timeout"""
    url = f"{BASE_URL}/api/v3/ticker/price?symbol={symbol}"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        return float(response.json()["price"])
    except Exception as e:
        logging.warning("⚠️ First attempt failed (%s). Retrying once...", e)
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            return float(response.json()["price"])
        except Exception as e2:
            logging.error("❌ Failed to fetch ticker after retry: %s", e2)
            return None

def place_market_order(symbol, side, qty, leverage):
    try:
        # Adjust position mode and leverage
        params = {
            "symbol": symbol,
            "positionSide": "BOTH",
            "leverage": leverage,
            "timestamp": get_server_time()
        }
        params["signature"] = sign_request(params)
        requests.post(f"{BASE_URL}/api/v3/leverage", headers={"X-MBX-APIKEY": API_KEY}, params=params, timeout=15)

        order_params = {
            "symbol": symbol,
            "side": side.upper(),
            "type": "MARKET",
            "quantity": qty,
            "timestamp": get_server_time()
        }
        order_params["signature"] = sign_request(order_params)

        response = requests.post(f"{BASE_URL}/api/v3/order",
                                 headers={"X-MBX-APIKEY": API_KEY},
                                 params=order_params,
                                 timeout=15)

        if response.status_code == 200:
            logging.info("✅ Market %s order executed successfully for %s qty", side.upper(), qty)
        else:
            logging.error("❌ Order failed: %s", response.text)

    except Exception as e:
        logging.error("❌ Error placing order: %s", e)

# === Flask Route ===
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    logging.info("📩 Webhook received: %s", data)

    if not data or "secret" not in data or data["secret"] != WEBHOOK_SECRET:
        return jsonify({"error": "Unauthorized"}), 403

    symbol = data.get("symbol", "BTCUSDT")
    side = data.get("side", "BUY").upper()
    qty_usd = float(data.get("qty_usd", 10))
    leverage = int(data.get("leverage", 2))

    price = fetch_ticker(symbol)
    if price is None:
        logging.error("❌ Could not fetch price, aborting order.")
        return jsonify({"error": "Price fetch failed"}), 500

    qty = round(qty_usd / price, 4)
    logging.info("📊 Calculated quantity: %s %s @ %s USDT", qty, symbol, price)

    place_market_order(symbol, side, qty, leverage)

    return jsonify({"success": True, "message": f"{side} order executed for {symbol}"}), 200

# === Run Server ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
