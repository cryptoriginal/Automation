import os
import json
import logging
from flask import Flask, request, jsonify
from bitget.paths.mix_v1_order_place.post import ApiForpost as PlaceOrder
from bitget.paths.mix_v1_account_set_leverage.post import ApiForpost as SetLeverage
from bitget.paths.mix_v1_account_set_margin_mode.post import ApiForpost as SetMarginMode
from bitget import ApiClient, Configuration
from bitget.apis.mix_api import MixApi

app = Flask(__name__)

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
API_KEY = os.getenv("BITGET_API_KEY")
API_SECRET = os.getenv("BITGET_API_SECRET")
API_PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE")
TRADE_BALANCE_USDT = float(os.getenv("TRADE_BALANCE_USDT", "100"))
BASE_URL = "https://api.bitget.com"

# Connect Bitget client
configuration = Configuration(
    host=BASE_URL,
    api_key=API_KEY,
    api_secret=API_SECRET,
    passphrase=API_PASSPHRASE
)
client = ApiClient(configuration)
mix_api = MixApi(client)

@app.route('/')
def home():
    return "✅ Bitget Auto-Trader is live"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = json.loads(request.data)
        symbol = data.get('symbol')
        side = data.get('side').lower()

        if not symbol or side not in ["buy", "sell"]:
            return jsonify({"error": "Invalid alert data"}), 400

        logger.info(f"🚀 Received alert: {symbol} - {side}")

        # --- Set leverage & margin mode ---
        try:
            SetMarginMode(mix_api.api_client).post({
                "symbol": symbol,
                "marginMode": "crossed"
            })
            SetLeverage(mix_api.api_client).post({
                "symbol": symbol,
                "leverage": 3,
                "marginCoin": "USDT"
            })
            logger.info(f"Leverage & margin set: 3x Cross for {symbol}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to set leverage/margin: {e}")

        # --- Determine direction & force-close opposite ---
        opposite_side = "sell" if side == "buy" else "buy"

        try:
            # Force-close by sending an opposite order first
            PlaceOrder(mix_api.api_client).post({
                "symbol": symbol,
                "marginCoin": "USDT",
                "side": opposite_side,
                "orderType": "market",
                "size": "1",  # minimal close order
                "reduceOnly": True
            })
            logger.info(f"🧹 Forced closed {opposite_side} position before new entry.")
        except Exception as e:
            logger.warning(f"⚠️ Skip close error: {e}")

        # --- Place new trade ---
        order_value = TRADE_BALANCE_USDT * 3
        qty = round(order_value / 1, 2)  # placeholder; Bitget auto-calculates by size or margin

        response = PlaceOrder(mix_api.api_client).post({
            "symbol": symbol,
            "marginCoin": "USDT",
            "side": side,
            "orderType": "market",
            "size": str(qty)
        })

        logger.info(f"✅ Order response: {response}")
        return jsonify({"message": "Trade executed", "details": response}), 200

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    logger.info("🚀 Starting Bitget Auto-Trader Service")
    app.run(host='0.0.0.0', port=port)
