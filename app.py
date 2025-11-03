import os
import time
import hmac
import hashlib
import base64
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- Read env vars with fallback to BITGET_* names if present ---
API_KEY = os.getenv("API_KEY") or os.getenv("BITGET_API_KEY")
API_SECRET = os.getenv("API_SECRET") or os.getenv("BITGET_API_SECRET")
PASSPHRASE = os.getenv("PASSPHRASE") or os.getenv("BITGET_API_PASSPHRASE")
TRADE_BALANCE = float(os.getenv("TRADE_BALANCE_USDT", os.getenv("TRADE_BALANCE", "0.0")))

# Mask helper (do not print secrets)
def mask(s):
    if not s:
        return "None"
    if len(s) <= 6:
        return "***"
    return s[:3] + "..." + s[-3:]

# --- Startup status (visible in logs) ---
print("🔷 Starting app — environment check")
print("🔑 API Key loaded:", bool(API_KEY))
print("🔑 API Key (masked):", mask(API_KEY))
print("🔒 API Secret loaded:", bool(API_SECRET))
print("🔒 API Secret (masked):", mask(API_SECRET))
print("🧩 Passphrase loaded:", bool(PASSPHRASE))
print("🧩 Passphrase (masked):", mask(PASSPHRASE))
print("💰 Trade Balance (env):", TRADE_BALANCE)

BASE_URL = "https://api.bitget.com"

# === Signing ===
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

# === Get current position ===
def get_current_position(symbol):
    """Get current position for the symbol"""
    try:
        endpoint = f"/api/mix/v1/position/singlePosition?symbol={symbol}&marginCoin=USDT"
        url = BASE_URL + endpoint
        request_path = f"/api/mix/v1/position/singlePosition?symbol={symbol}&marginCoin=USDT"
        headers = make_headers("GET", request_path, "")
        r = requests.get(url, headers=headers, timeout=10)
        j = r.json()
        
        if j.get("code") in (0, "0"):
            data = j.get("data") or {}
            hold_side = data.get("holdSide", "").lower()
            total = float(data.get("total", 0) or 0)
            
            if total > 0:
                print(f"📊 Current position: {hold_side.upper()} - {total}")
                return hold_side, total
            else:
                print("📊 No current position")
                return None, 0
        else:
            print("⚠️ Position fetch returned:", r.status_code, r.text)
    except Exception as e:
        print("⚠️ Exception in get_current_position:", e)
    
    return None, 0

# === SIMPLE REVERSE TRADE APPROACH ===
def place_reverse_trade(symbol, side):
    """Simple reverse trade approach - just place the opposite trade"""
    try:
        print(f"🎯 REVERSE TRADE for {symbol} - {side.upper()}")
        print("=" * 50)
        
        # STEP 1: Check current position
        current_side, current_size = get_current_position(symbol)
        
        # STEP 2: Determine what trade to place
        trade_size = round(TRADE_BALANCE * 3, 6)
        if trade_size <= 0:
            print("❌ Trade size is zero — set TRADE_BALANCE_USDT env var to >0")
            return
        
        # Determine order side based on desired position
        if side.lower() == "buy":
            order_side = "open_long"
            target_side = "long"
        else:
            order_side = "open_short" 
            target_side = "short"
        
        print(f"💡 Target: {target_side.upper()}")
        print(f"💡 Current: {current_side.upper() if current_side else 'NONE'}")
        print(f"💰 Trade size: {trade_size} USDT")
        
        # STEP 3: Place the trade (Bitget hedge mode will handle the reversal)
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
        print("🧾 Placing order:", payload)
        
        r = requests.post(url, headers=headers, data=body, timeout=15)
        response_data = r.json()
        print("🌍 Bitget Response:", r.status_code, r.text)
        
        if response_data.get("code") in (0, "0"):
            print("✅✅✅ ORDER EXECUTED SUCCESSFULLY!")
            
            # Explain what happened
            if current_side:
                if (side.lower() == "buy" and current_side == "short") or (side.lower() == "sell" and current_side == "long"):
                    print("🔄 POSITION REVERSED: Old position closed, new position opened")
                else:
                    print("📈 POSITION INCREASED: Same direction, position size increased")
            else:
                print("🆕 NEW POSITION: No previous position, new position opened")
                
            # Final check
            print("\n🔍 Final position check...")
            time.sleep(3)
            final_side, final_size = get_current_position(symbol)
            print(f"   ✅ Final: {final_side.upper() if final_side else 'NO POSITION'} - {final_size}")
            
        else:
            print("❌ Order failed:", response_data.get('msg', 'Unknown error'))
            
        print("=" * 50)
            
    except Exception as e:
        print("❌ Exception placing order:", e)

# === ALTERNATIVE: Close then open approach with reduceOnly ===
def close_then_open_trade(symbol, side):
    """Alternative: Close any existing position first, then open new one"""
    try:
        print(f"🎯 CLOSE THEN OPEN for {symbol} - {side.upper()}")
        print("=" * 50)
        
        # STEP 1: Check and close existing position
        current_side, current_size = get_current_position(symbol)
        
        if current_side and current_size > 0:
            print(f"🔻 Closing existing {current_side} position...")
            
            # Close existing position
            close_side = "close_short" if current_side == "short" else "close_long"
            endpoint = "/api/mix/v1/order/placeOrder"
            payload = {
                "symbol": symbol,
                "marginCoin": "USDT",
                "size": str(current_size),
                "side": close_side,
                "orderType": "market",
                "timeInForceValue": "normal"
            }
            
            body = json.dumps(payload)
            headers = make_headers("POST", endpoint, body)
            url = BASE_URL + endpoint
            r = requests.post(url, headers=headers, data=body, timeout=15)
            response_data = r.json()
            
            print("💥 Close order:", payload)
            print("🌍 Close response:", r.status_code, r.text)
            
            if response_data.get("code") in (0, "0"):
                print("✅ Position closed successfully")
                # Wait for close to process
                time.sleep(3)
            else:
                print("❌ Failed to close position")
                return
        
        # STEP 2: Place new position
        trade_size = round(TRADE_BALANCE * 3, 6)
        if trade_size <= 0:
            print("❌ Trade size is zero")
            return
        
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
        print("🧾 Placing new order:", payload)
        
        r = requests.post(url, headers=headers, data=body, timeout=15)
        response_data = r.json()
        print("🌍 Open response:", r.status_code, r.text)
        
        if response_data.get("code") in (0, "0"):
            print("✅✅✅ NEW POSITION OPENED SUCCESSFULLY!")
            
        print("=" * 50)
            
    except Exception as e:
        print("❌ Exception in close_then_open_trade:", e)

# === Webhook - Choose which method to use ===
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        print("🚀 Webhook triggered!")
        data = request.get_json(force=True)
        print("📩 Received payload:", data)
        symbol = data.get("symbol")
        side = data.get("side")
        strategy = data.get("strategy", "reverse")  # "reverse" or "closefirst"
        
        if not symbol or not side:
            return jsonify({"error": "missing symbol or side"}), 400
        
        if side.lower() not in ['buy', 'sell']:
            return jsonify({"error": "side must be 'buy' or 'sell'"}), 400
        
        # Choose strategy based on parameter
        if strategy == "closefirst":
            close_then_open_trade(symbol, side)
        else:
            place_reverse_trade(symbol, side)
            
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print("❌ Webhook Error:", e)
        return jsonify({"error": str(e)}), 500

@app.route('/')
def home():
    return "✅ Bitget webhook running - REVERSE TRADE APPROACH"

@app.route('/position/<symbol>', methods=['GET'])
def check_position(symbol):
    """Endpoint to check current position"""
    side, size = get_current_position(symbol)
    return jsonify({
        "symbol": symbol,
        "position_side": side,
        "position_size": size
    })

@app.route('/test/<symbol>/<side>', methods=['GET'])
def test_trade(symbol, side):
    """Test endpoint for manual trading"""
    if side.lower() not in ['buy', 'sell']:
        return jsonify({"error": "side must be 'buy' or 'sell'"}), 400
    place_reverse_trade(symbol, side)
    return jsonify({"status": "test_executed"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
