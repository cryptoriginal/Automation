from flask import Flask, jsonify, request
from dotenv import load_dotenv
import os
import requests
from bitget.configuration import Configuration
from bitget.api_client import ApiClient
from bitget.apis.mix_account_api import MixAccountApi
from bitget.apis.mix_order_api import MixOrderApi

load_dotenv()
app = Flask(__name__)

# ================================
# ✅ Bitget API credentials
# ================================
API_KEY = os.getenv("BITGET_API_KEY", "bg_5773fe57167e2e9abb7d87f6510f54b5")
API_SECRET = os.getenv("BITGET_API_SECRET", "cc3a0bc4771b871c989e68068206e9fc12a973350242ea136f34693ee64b69bb")
API_PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE", "automatioN")

# ================================
# ✅ Bitget API client setup
# ================================
config = Configuration(
    api_key={'ACCESS-KEY': API_KEY},
    api_secret_key=API_SECRET,
    api_passphrase=API_PASSPHRASE,
)
client = ApiClient(config)
account_api = MixAccountApi(client)
order_api = MixOrderApi(client)

# ================================
# ✅ Helper: Get current SUI price
# ================================
def get_sui_price():
    try:
        url = "https://api.bitget.com/api/mix/v1/market/ticker?symbol=SUIUSDT_UMCBL"
        r = requests.get(url).json()
        return float(r["data"]["last"])
    except Exception as e:
        print("⚠️ Failed to fetch SUI price:", e)
        return None

# ================================
# ✅ Helper: Get available USDT balance
# ================================
def get_available_balance():
    try:
        acc_data = account_api.mix_account_accounts(product_type="umcbl")
        usdt_info = next((x for x in acc_data["data"] if x["marginCoin"] == "USDT"), None)
        if usdt_info:
            return float(usdt_info["availableBalance"])
    except Exception as e:
        print("⚠️ Error fetching balance:", e)
    return 0.0

# ================================
# ✅ Trade endpoint (auto 3x)
# ================================
@app.route("/trade", methods=["POST"])
def trade():
    try:
        data = request.json
        direction = data.get("side", "open_long")  # open_long / open_short
        symbol = "SUIUSDT_UMCBL"
        margin_coin = "USDT"
        leverage = 3

        # Step 1️⃣: Get available balance
        available_balance = get_available_balance()
        if available_balance <= 0:
            return jsonify({"status": "error", "msg": "No available USDT balance"}), 400

        # Step 2️⃣: Fetch price
        sui_price = get_sui_price()
        if not sui_price:
            return jsonify({"status": "error", "msg": "Failed to fetch SUI price"}), 400

        # Step 3️⃣: Compute order size (100% × 3x)
        total_usdt_value = available_balance * 3
        size = round(total_usdt_value / sui_price, 2)  # round to 2 decimals for SUI
        print(f"💰 Available: {available_balance} | 3x Value: {total_usdt_value} | Size: {size}")

        # Step 4️⃣: Set leverage
        account_api.mix_account_set_leverage(symbol=symbol, margin_coin=margin_coin, leverage=str(leverage))

        # Step 5️⃣: Place market order
        response = order_api.mix_order_place(
            symbol=symbol,
            margin_coin=margin_coin,
            size=str(size),
            side=direction,
            order_type="market",
            time_in_force_value="normal"
        )

        return jsonify({"status": "success", "symbol": symbol, "side": direction, "leverage": leverage, "size": size, "response": response})

    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

# ================================
# ✅ Balance check endpoint
# ================================
@app.route("/balance", methods=["GET"])
def balance():
    try:
        balance = get_available_balance()
        return jsonify({"available_balance": balance})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})

# ================================
# ✅ Health endpoint
# ================================
@app.route("/")
def home():
    return jsonify({"status": "Bitget 3x Futures Bot is LIVE 🔥"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

