import os
import time
import hmac
import hashlib
import base64
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- Configuration ---
API_KEY = os.getenv("API_KEY") or os.getenv("BITGET_API_KEY")
API_SECRET = os.getenv("API_SECRET") or os.getenv("BITGET_API_SECRET")
PASSPHRASE = os.getenv("PASSPHRASE") or os.getenv("BITGET_API_PASSPHRASE")
TRADE_BALANCE = float(os.getenv("TRADE_BALANCE_USDT", os.getenv("TRADE_BALANCE", "0.0")))

BASE_URL = "https://api.bitget.com"

def bitget_signature(timestamp, method, request_path, body):
    message = f"{timestamp}{method.upper()}{request_path}{body}"
    mac = hmac.new(API_SECRET.encode('utf-8'), message.encode('utf-8'), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()

def make_headers(method, endpoint, body=""):
    timestamp = str(int(time.time() * 1000))
    sign = bitget_signature(timestamp, method, endpoint, body)
    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json"
    }

# === ULTRA SIMPLE: Just place the trade ===
def place_trade(symbol, side):
    """ULTRA SIMPLE: Just place the trade and let Bitget handle position management"""
    try:
        trade_size = round(TRADE_BALANCE * 3, 6)
        if trade_size <= 0:
            print("❌ Invalid trade size")
            return False
        
        if side.lower() == "buy":
            order_side = "open_long"
            side_name = "LONG"
        else:
            order_side = "open_short" 
            side_name = "SHORT"
        
        endpoint = "/api/mix/v1/order/placeOrder"
        payload = {
            "symbol": symbol,
            "marginCoin": "USDT",
            "size": str(trade_size),
            "side": order_side,
            "orderType": "market",
            "timeInForceValue": "normal"
        }
        
        body = json.dumps(payload)
        headers = make_headers("POST", endpoint, body)
        url = BASE_URL + endpoint
        
        print(f"📈 Placing {side_name} order: {trade_size} USDT")
        r = requests.post(url, headers=headers, data=body, timeout=15)
        response = r.json()
        
        print(f"🌍 Response: {response}")
        
        if response.get("code") in (0, "0"):
            print(f"✅ {side_name} ORDER PLACED SUCCESSFULLY!")
            return True
        else:
            print(f"❌ Order failed: {response.get('msg')}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        symbol = data.get("symbol")
        side = data.get("side")
        
        if not symbol or not side:
            return jsonify({"error": "missing symbol or side"}), 400
        
        if side.lower() not in ['buy', 'sell']:
            return jsonify({"error": "side must be 'buy' or 'sell'"}), 400
        
        print(f"🚀 TradingView Alert: {side.upper()} {symbol}")
        
        # JUST PLACE THE TRADE - let Bitget handle position management
        place_trade(symbol, side)
        
        return jsonify({"status": "executed"}), 200
        
    except Exception as e:
        print(f"❌ Webhook Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/')
def home():
    return "✅ Bitget Bot - ULTRA SIMPLE WORKING VERSION"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
