import os
import json
import logging
from flask import Flask, request, jsonify
from bitget.um_futures import UMFutures

# -------------------- Setup --------------------
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Environment variables
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
PASSPHRASE = os.getenv("PASSPHRASE")
TRADE_BALANCE_USDT = float(os.getenv("TRADE_BALANCE_USDT", "0"))

# Check ENV vars
logging.info("🔍 DEBUG ENV CHECK:")
logging.info(f"API_KEY present? {'True' if API_KEY else 'False'}")
logging.info(f"API_SECRET present? {'True' if API_SECRET else 'False'}")
logging.info(f"PASSPHRASE present? {'True' if PASSPHRASE else 'False'}")
logging.info(f"TRADE_BALANCE_USDT value: {TRADE_BALANCE_USDT}")

# Initialize Bitget Futures client
bitget = UMFutures(API_KEY, API_SECRET, PASSPHRASE, use_server_time=True)

# -------------------- Core Trading Logic --------------------
def close_open_positions(symbol):
    """Close any open long or short position for this symbol before opening a new one."""
    try:
        pos_data = bitget.positions(symbol=symbol)
        logging.info(f"Position data fetched: {pos_data}")

        if pos_data.get("code") == "00000":
            for pos in pos_data.get("data", []):
                size = float(pos.get("total", 0))
                side = pos.get("holdSide", "").lower()

                if size > 0:
                    # Determine opposite side for closing
                    close_side = "close_long" if side == "long" else "close_short"
                    logging.info(f"Closing {side} position of size {size} on {symbol}")
                    close_resp = bitget.place_order(
                        symbol=symbol,
                        marginCoin="USDT",
                        size=str(size),
                        side=close_side,
                        orderType="market",
                        timeInForceValue="normal"
                    )
                    logging.info(f"Close response: {close_resp}")
        else:
            logging.warning(f"Could not fetch position: {pos_data}")
    except Exception as e:
        logging.error(f"Error closing positions: {e}")

def place_order(symbol, side):
    """Close any existing position and open new one per signal."""
    try:
        # Step 1: Close any open position first
        close_open_positions(symbol)

        # Step 2: Calculate trade size (3x env balance)
        size = TRADE_BALANCE_USDT * 3
        logging.info(f"Calculated position size: {size}")

        # Step 3: Determine side
        order_side = "open_long" if side == "buy" else "open_short"

        # Step 4: Place the order
        logging.info(f"Placing {side.upper()} order for {symbol}")
        order_resp = bitget.place_order(
            symbol=symbol,
            marginCoin="USDT",
            size=str(size),
            side=order_side,
            orderType="market",
            timeInForceValue="normal"
        )
        logging.info(f"Bitget order response: {order_resp}")
        return order_resp

    except Exception as e:
        logging.error(f"Error placing order: {e}")
        return {"error": str(e)}

# -------------------- Webhook Route --------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    logging.info(f"📩 Received payload: {data}")

    symbol = data.get("symbol")
    side = data.get("side")

    if not symbol or side not in ["buy", "sell"]:
        return jsonify({"error": "Invalid payload"}), 400

    result = place_order(symbol, side)
    return jsonify(result)

# -------------------- Home Route --------------------
@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "running", "message": "Trading automation active"})

# -------------------- Run App --------------------
if __name__ == "__main__":
    logging.info("🚀 App is running...")
    app.run(host="0.0.0.0", port=10000)
