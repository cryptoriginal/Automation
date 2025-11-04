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

# === NUCLEAR OPTION: Cancel ALL orders and close ALL positions ===
def nuclear_close(symbol):
    """NUCLEAR OPTION: Cancel all orders and close all positions"""
    try:
        print("💣 NUCLEAR OPTION ACTIVATED!")
        
        # 1. Cancel all pending orders
        endpoint = f"/api/mix/v1/order/cancel-all-orders?symbol={symbol}&marginCoin=USDT"
        url = BASE_URL + endpoint
        request_path = f"/api/mix/v1/order/cancel-all-orders?symbol={symbol}&marginCoin=USDT"
        headers = make_headers("POST", request_path, "")
        r = requests.post(url, headers=headers, timeout=10)
        print("✅ Canceled all orders:", r.json())
        
        time.sleep(2)
        
        # 2. Get all positions
        endpoint = f"/api/mix/v1/position/allPosition?symbol={symbol}&marginCoin=USDT"
        url = BASE_URL + endpoint
        request_path = f"/api/mix/v1/position/allPosition?symbol={symbol}&marginCoin=USDT"
        headers = make_headers("GET", request_path, "")
        r = requests.get(url, headers=headers, timeout=10)
        positions = r.json().get("data", [])
        
        # 3. Close each position individually
        for pos in positions:
            total = float(pos.get("total", 0) or 0)
            if total > 0:
                hold_side = pos.get("holdSide", "").lower()
                available = float(pos.get("available", 0) or 0)
                
                if hold_side == "long":
                    close_side = "close_long"
                else:
                    close_side = "close_short"
                
                # Close position
                endpoint = "/api/mix/v1/order/placeOrder"
                payload = {
                    "symbol": symbol,
                    "marginCoin": "USDT",
                    "size": str(available if available > 0 else total),
                    "side": close_side,
                    "orderType": "market",
                    "timeInForceValue": "normal"
                }
                
                body = json.dumps(payload)
                headers = make_headers("POST", endpoint, body)
                url = BASE_URL + endpoint
                r = requests.post(url, headers=headers, data=body, timeout=15)
                print(f"💥 Closed {hold_side}: {r.json()}")
        
        time.sleep(5)
        return True
        
    except Exception as e:
        print("❌ Nuclear close failed:", e)
        return False

# === SIMPLE: Just open the desired position ===  
def simple_trade(symbol, side):
    """ULTRA SIMPLE: Just open the position you want"""
    try:
        trade_size = round(TRADE_BALANCE * 3, 6)
        if trade_size <= 0:
            return False
        
        if side.lower() == "buy":
            order_side = "open_long"
        else:
            order_side = "open_short"
        
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
        
        print(f"📈 Opening {side}: {trade_size}")
        r = requests.post(url, headers=headers, data=body, timeout=15)
        response = r.json()
        print("🌍 Response:", response)
        
        return response.get("code") in (0, "0")
        
    except Exception as e:
        print("❌ Error:", e)
        return False

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        symbol = data.get("symbol")
        side = data.get("side")
        mode = data.get("mode", "nuclear")  # nuclear or simple
        
        if not symbol or not side:
            return jsonify({"error": "missing symbol or side"}), 400
        
        print(f"🚀 {mode.upper()} MODE: {side} for {symbol}")
        
        if mode == "nuclear":
            # Close everything first, then open
            nuclear_close(symbol)
            time.sleep(3)
            simple_trade(symbol, side)
        else:
            # Just open the position (let Bitget handle the rest)
            simple_trade(symbol, side)
        
        return jsonify({"status": "executed"}), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/nuke/<symbol>', methods=['POST'])
def nuke(symbol):
    """Manual nuclear close"""
    nuclear_close(symbol)
    return jsonify({"status": "nuked"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
