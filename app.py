import os
import json
import logging
from flask import Flask, request, jsonify
import requests
from datetime import datetime
from bitget import Bitget

# ===================== CONFIG =====================
API_KEY = os.getenv("BITGET_API_KEY")
API_SECRET = os.getenv("BITGET_API_SECRET")
API_PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE")

# 3× cross leverage setup
LEVERAGE = 3
MARGIN_MODE = "cross"  # or "isolated" if you want later

# Flask app
app = Flask(__name__)

# Logging setup
logging.basicConfig(level=logging.INFO)

# Bitget client
bitget = Bitget(
    api_key=API_KEY,
    api_secret=API_SECRET,
    passphrase=API_PASSPHRASE
)

# ===================================================

def get_available_balance():
    """Fetch USDT-M futures available balance safely."""
    try:
        # ✅ Correct endpoint for USDT-M futures
        response = bitget.get(
            "/api/mix/v1/account/account",
            params={"symbol": "BTCUSDT_UMCBL"}
        )

        if response and response.get("code") == "00000":
            balance_data = response.get("data", {})
            available = float(balance_data.get("available", 0))
            logging.info(f"💰 Available futures balance: {available} USDT")
            return available
        else:
            logging.error(f"⚠️ Invalid or empty balance response: {response}")
            return 0

    except Exception as e:
        logging.error(f"❌ Error fetching futures balance: {e}")
        return 0


def set_leverage(symbol):
    """Set 3× cross leverage."""
    try:
        payload = {
            "symbol": symbol,
            "marginMode": MARGIN_MODE,
            "leverage": str(LEVERAGE)
        }
        response = bitget.post("/api/mix/v1/account/setLeverage", body=payload)
        logging.info(f"🔧 Leverage set response: {response}")
    except Exception as e:
        logging.error(f"❌ Error setting leverage: {e}")


def place_order(symbol, side, balance):
    """Open order using 3× available balance."""
    try:
        # Use 100% of balance × 3× leverage
        order_value = balance * LEVERAGE
        logging.info(f"🚀 Using order size = {order_value:.2f} USDT (3× of {balance:.2f})")

        # Fetch mark price for entry estimation
        ticker_resp = bitget.get("/api/mix/v1/market/ticker", params={"symbol": symbol})
        mark_price = float(ticker_resp.get("data", {}).get("last", 0))
        if not mark_price:
            logging.warning(f"⚠️ Failed to get price for {symbol}")
            return

        # Calculate size
        size = round(order_value / mark_price, 3)
        logging.info(f"📏 Position size: {size} {symbol.split('_')[0]} at ~{mark_price}")

        # Prepare payload
        payload = {
            "symbol": symbol,
            "marginMode": MARGIN_MODE,
            "side": "open_long" if side == "buy" else "open_short",
            "orderType": "market",
            "size": str(size),
            "reduceOnly": False
        }

        # Send order
        order_resp = bitget.post("/api/mix/v1/order/placeOrder", body=payload)
        logging.info(f"📨 Order response: {order_resp}")

    except Exception as e:
        logging.error(f"❌ Error placing order: {e}")


@app.route("/webhook", methods=["POST"])
def webhook():
    """Handle TradingView alerts."""
    try:
        data = request.get_json()
        logging.info(f"📩 Received TradingView alert: {data}")

        symbol = data.get("symbol")
        side = data.get("side")

        if not symbol or not side:
            return jsonify({"error": "Missing 'symbol' or 'side'"}), 400

        # Step 1: Fetch balance
        balance = get_available_balance()
        if balance <= 0:
            logging.error("🚫 No available balance or failed to fetch balance.")
            return jsonify({"error": "No available balance"}), 400

        # Step 2: Set leverage
        set_leverage(symbol)

        # Step 3: Place order
        place_order(symbol, side, balance)

        return jsonify({"status": "Order executed"}), 200

    except Exception as e:
        logging.error(f"❌ Webhook processing error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/", methods=["GET"])
def home():
    return "✅ Your Bitget Futures Automation Service is live!"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
