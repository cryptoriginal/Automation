from flask import Flask, request, jsonify
import requests
import json
import logging

app = Flask(__name__)

# Enable logging to Render logs
logging.basicConfig(level=logging.INFO)

# ==== CONFIG ====
BITGET_API_KEY = "YOUR_BITGET_API_KEY"
BITGET_API_SECRET = "YOUR_BITGET_API_SECRET"
BITGET_API_PASSPHRASE = "YOUR_BITGET_API_PASSPHRASE"
BITGET_API_URL = "https://api.bitget.com/api/mix/v1/order/placeOrder"

# ==== ROUTES ====

@app.route('/')
def home():
    return "🚀 Bitget Webhook Automation is Live!"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        content_type = request.headers.get('Content-Type', '')

        # Handle JSON alerts (preferred)
        if 'application/json' in content_type:
            data = request.get_json(force=True)
        else:
            # Handle plain text alert (from TradingView without JSON mode)
            raw = request.data.decode('utf-8').strip()
            logging.info(f"Received non-JSON alert: {raw}")
            data = parse_plain_text_alert(raw)

        if not data or 'symbol' not in data or 'side' not in data:
            logging.error(f"Invalid alert data: {data}")
            return jsonify({"status": "error", "message": "Invalid alert data"}), 400

        symbol = data['symbol']
        side = data['side'].lower()

        logging.info(f"✅ Webhook received: {symbol} - {side}")

        # Simulate Bitget trade placement
        result = execute_bitget_trade(symbol, side)

        return jsonify({"status": "success", "result": result}), 200

    except Exception as e:
        logging.error(f"❌ ERROR in webhook: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ==== HELPERS ====

def parse_plain_text_alert(text):
    """Parses alerts like: 'symbol=SUIUSDT_UMCBL, side=buy' or 'SUIUSDT_UMCBL buy'"""
    text = text.replace("\n", " ").strip().lower()
    symbol, side = None, None

    # Method 1: key=value pairs
    if "symbol=" in text:
        parts = [p.strip() for p in text.split(",")]
        for p in parts:
            if "symbol=" in p:
                symbol = p.split("=")[1].strip().upper()
            elif "side=" in p:
                side = p.split("=")[1].strip().lower()

    # Method 2: space-separated
    elif "buy" in text or "sell" in text:
        parts = text.split()
        for p in parts:
            if "usdt" in p:
                symbol = p.upper()
            elif p in ["buy", "sell"]:
                side = p.lower()

    return {"symbol": symbol, "side": side} if symbol and side else None


def execute_bitget_trade(symbol, side):
    """Simulate order placement. Replace with real Bitget API logic later."""
    logging.info(f"🚀 Executing {side.upper()} order for {symbol} on Bitget...")

    # Example payload
    payload = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "side": "open_long" if side == "buy" else "open_short",
        "orderType": "market",
        "size": "0.1",
        "leverage": "3"
    }

    # For testing, we won't actually send to Bitget API yet
    # You can uncomment the section below after adding API authentication

    # headers = {
    #     "ACCESS-KEY": BITGET_API_KEY,
    #     "ACCESS-SIGN": your_signature_function(payload),
    #     "ACCESS-TIMESTAMP": timestamp,
    #     "ACCESS-PASSPHRASE": BITGET_API_PASSPHRASE,
    #     "Content-Type": "application/json"
    # }
    #
    # response = requests.post(BITGET_API_URL, headers=headers, data=json.dumps(payload))
    # logging.info(f"Bitget Response: {response.text}")
    #
    # return response.json()

    return f"Simulated {side.upper()} order for {symbol}"

# ==== RUN APP ====
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)

