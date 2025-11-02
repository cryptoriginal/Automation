from flask import Flask, request, jsonify
import hmac
import hashlib
import base64
import time
import requests
import os

app = Flask(__name__)

# ==========================================================
# 🔍 TEST BITGET SIGNATURE WHEN APP STARTS
# ==========================================================
def test_bitget_signature():
    """Verifies that the API key, secret, and passphrase can generate a valid Bitget signature."""
    API_KEY = os.getenv("BITGET_API_KEY")
    API_SECRET = os.getenv("BITGET_SECRET_KEY")
    PASSPHRASE = os.getenv("BITGET_PASSPHRASE")

    print("\n=======================================")
    print("🔍 Testing Bitget Signature...")

    if not API_KEY or not API_SECRET or not PASSPHRASE:
        print("❌ One or more environment variables are missing!")
        print("Please set BITGET_API_KEY, BITGET_SECRET_KEY, and BITGET_PASSPHRASE in Render.")
        print("=======================================\n")
        return

    try:
        timestamp = str(int(time.time() * 1000))
        method = "GET"
        request_path = "/api/mix/v1/market/contracts?productType=umcbl"
        body = ""
        message = timestamp + method + request_path + body

        signature = base64.b64encode(
            hmac.new(API_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
        ).decode()

        print("✅ Signature generated successfully!")
        print("Timestamp:", timestamp)
        print("Example request:", request_path)
        print("Signature (first 50 chars):", signature[:50] + "...")
        print("Passphrase:", PASSPHRASE)
    except Exception as e:
        print("❌ Error while testing Bitget signature:", e)
    print("=======================================\n")

test_bitget_signature()

# ==========================================================
# 🧠 FUNCTION: CREATE BITGET SIGNATURE FOR AUTH REQUESTS
# ==========================================================
def bitget_signature(secret, timestamp, method, request_path, body=""):
    message = timestamp + method + request_path + body
    mac = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
    d = mac.digest()
    return base64.b64encode(d).decode()

# ==========================================================
# ⚙️ FUNCTION: SEND ORDER TO BITGET (MARKET ORDER ONLY)
# ==========================================================
def place_bitget_order(symbol, side):
    API_KEY = os.getenv("BITGET_API_KEY")
    API_SECRET = os.getenv("BITGET_SECRET_KEY")
    PASSPHRASE = os.getenv("BITGET_PASSPHRASE")

    base_url = "https://api.bitget.com"
    endpoint = "/api/mix/v1/order/placeOrder"
    url = base_url + endpoint

    timestamp = str(int(time.time() * 1000))
    method = "POST"

    # Ensure it's USDT-M perpetuals
    productType = "umcbl"

    # Market order only, 3x cross
    body_dict = {
        "symbol": symbol,
        "marginMode": "crossed",
        "marginCoin": "USDT",
        "side": side,              # "buy" or "sell"
        "orderType": "market",
        "size": "0.1",             # You can adjust quantity
        "leverage": "3",
        "timeInForceValue": "normal",
        "reduceOnly": False
    }

    import json
    body = json.dumps(body_dict)
    signature = bitget_signature(API_SECRET, timestamp, method, endpoint, body)

    headers = {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json"
    }

    print(f"\n🚀 Placing {side.upper()} order on {symbol} ...")
    response = requests.post(url, headers=headers, data=body)

    try:
        resp_json = response.json()
        print("✅ Order Result:", resp_json)
    except Exception:
        print("⚠️ Raw Response:", response.text)

    return response.text

# ==========================================================
# 🧠 FUNCTION: CLOSE OPPOSITE POSITION FIRST
# ==========================================================
def close_opposite_position(symbol, side):
    opposite = "sell" if side == "buy" else "buy"
    print(f"▼ Closing opposite positions for {symbol}")
    place_bitget_order(symbol, opposite)

# ==========================================================
# 📩 WEBHOOK: RECEIVE ALERT FROM TRADINGVIEW
# ==========================================================
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        print("📩 Alert received:", data)

        symbol = data.get('symbol')
        side = data.get('side')

        if not symbol or not side:
            return jsonify({"error": "Missing symbol or side"}), 400

        # Close opposite positions before placing new one
        close_opposite_position(symbol, side)

        # Place the actual order
        place_bitget_order(symbol, side)

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print("❌ Error in webhook:", e)
        return jsonify({"error": str(e)}), 500

# ==========================================================
# 🚀 START APP
# ==========================================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print(f"\n✅ Bot running on port {port}")
    app.run(host='0.0.0.0', port=port)
