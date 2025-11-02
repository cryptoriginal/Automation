from flask import Flask, jsonify, request
from dotenv import load_dotenv
import os
from bitget.bitget_api import BitgetApi

# Load environment variables
load_dotenv()

app = Flask(__name__)

# ====================================
# ✅ Your Bitget API keys go here
# (for security, you can also set them in Render → Environment)
# ====================================
API_KEY = os.getenv("BITGET_API_KEY", "bg_5773fe57167e2e9abb7d87f6510f54b5")
API_SECRET = os.getenv("BITGET_API_SECRET", "cc3a0bc4771b871c989e68068206e9fc12a973350242ea136f34693ee64b69bb")
API_PASS = os.getenv("BITGET_API_PASSPHRASE", "automatioN")

# ====================================
# ✅ Initialize Bitget API client
# ====================================
bitget = BitgetApi(api_key=API_KEY, secret_key=API_SECRET, passphrase=API_PASS)

@app.route('/')
def home():
    return jsonify({"status": "Bitget Futures Bot is running!"})

# ====================================
# ✅ Endpoint to place a Futures Order
# ====================================
@app.route('/order', methods=['POST'])
def order():
    try:
        data = request.json
        symbol = data.get('symbol', 'BTCUSDT_UMCBL')
        side = data.get('side', 'buy')
        size = data.get('size', 0.01)
        price = data.get('price', None)  # market order if None
        leverage = data.get('leverage', 3)

        # Set leverage
        bitget.mix_account_set_leverage(symbol=symbol, marginCoin="USDT", leverage=str(leverage), holdSide=side)

        # Place order
        order = bitget.mix_order_place(
            symbol=symbol,
            marginCoin="USDT",
            size=str(size),
            side=side,
            orderType="market" if price is None else "limit",
            price=str(price) if price else "",
            timeInForceValue="normal"
        )

        return jsonify({"status": "success", "order": order})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# ====================================
# ✅ Endpoint to get account balance
# ====================================
@app.route('/balance', methods=['GET'])
def balance():
    try:
        balances = bitget.mix_account_accounts(productType="UMCBL")
        return jsonify(balances)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# ====================================
# ✅ Flask app runner
# ====================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

