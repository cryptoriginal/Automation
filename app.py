import os
import time
import json
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ==================== Load Environment Variables ====================
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
PASSPHRASE = os.getenv("PASSPHRASE")
TRADE_BALANCE_USDT = float(os.getenv("TRADE_BALANCE_USDT", "0"))

print(f"🔑 API Key loaded: {bool(API_KEY)}")
print(f"🔐 API Secret loaded: {bool(API_SECRET)}")
print(f"🧩 Passphrase loaded: {bool(PASSPHRASE)}")
print(f"💰 Trade Balance (env): {TRADE_BALANCE_USDT}")

# ==================== Helper: Bitget Auth Header ====================
def bitget_signature(timestamp, method, request_path, body_str=""):
    pre_sign = f"{timestamp}{method}{request_path}{body_str}"
    signature = hmac.new(API_SECRET.encode("utf-8"), pre_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return signature

def get_headers(method, endpoint, body=""):
    timestamp = str(int(time.time() * 1000))
    signature = bitget_signature(timestamp, method, endpoint, body)
    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json"
    }

# ==================== Place Order Function ====================
def place_order(symbol, side):
    try:
        url = "https://api.bitget.com/api/mix/v1/order/placeOrder"
        order_side = "open_long" if side.lower() == "buy" else "open_short"

        # 3x multiplier
        trade_value = TRADE_BALANCE_USDT * 3
        size = round(trade_value / 10, 3)  # approximate size calc, adjust as needed

        payload = {
            "symbol": symbol,
            "marginCoin": "USDT",
            "size": str(size),
            "side": order_side,
            "orderType": "market",
            "timeInForceValue": "normal"
        }

        body_str = json.dumps(payload)
        headers = get_headers("POST", "/api/mix/v1/order/placeOrder", body_str)

        print(f"📝 Sending order payload: {payload}")

        response = requests.post(url, headers=headers, data=body_str)
        print(f"🌐 Bitget Response: {response.status_code} | {response.text}")

        if response.status_code == 200:
            return jsonify({"success": True, "data": response.json()}), 200
        else:
            return jsonify({"success": False, "error": response.text}), 400

    except Exception as e:
        print(f"❌ Order placement error: {e}")
        return jsonify({"error": str(e)}), 500

# ==================== Webhook Route ====================
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        print("📬 Webhook triggered!")
        print(f"🧾 Raw headers: {dict(request.headers)}")

        # Try to get JSON
        try:
            data = request.get_json(force=True, silent=False)
        except Exception as json_err:
            print(f"⚠️ JSON parse error: {json_err}")
            print(f"📦 Raw body: {request.data}")
            return jsonify({"error": "Invalid JSON", "body": request.data.decode()}), 400

        print(f"📩 Received payload: {data}")

        if not data or 'symbol' not in data or 'side' not in data:
            return jsonify({"error": "Missing symbol/side"}), 400

        symbol = data['symbol']
        side = data['side']

        print(f"🚀 Executing trade for {symbol} ({side})")
        return place_order(symbol, side)

    except Exception as e:
        print(f"❌ Webhook Exception: {e}")
        return jsonify({"error": str(e)}), 500

# ==================== Root Route ====================
@app.route('/')
def home():
    return "✅ Automation bot running!"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)

