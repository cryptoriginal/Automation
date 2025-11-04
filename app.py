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

# === Get ALL positions (both long and short) ===
def get_all_positions(symbol):
    """Get all positions for the symbol"""
    try:
        endpoint = f"/api/mix/v1/position/allPosition?symbol={symbol}&marginCoin=USDT"
        url = BASE_URL + endpoint
        request_path = f"/api/mix/v1/position/allPosition?symbol={symbol}&marginCoin=USDT"
        headers = make_headers("GET", request_path, "")
        r = requests.get(url, headers=headers, timeout=10)
        j = r.json()
        
        if j.get("code") in (0, "0"):
            positions = j.get("data", [])
            active_positions = []
            
            for pos in positions:
                total = float(pos.get("total", 0) or 0)
                if total > 0:
                    position_info = {
                        "holdSide": pos.get("holdSide", "").lower(),
                        "total": total,
                        "available": float(pos.get("available", 0) or 0),
                        "symbol": pos.get("symbol"),
                        "positionId": pos.get("positionId")
                    }
                    active_positions.append(position_info)
                    print(f"📊 Found: {position_info['holdSide']} - {position_info['total']}")
            
            return active_positions
        else:
            print("❌ Position fetch error:", j.get('msg'))
    except Exception as e:
        print("❌ Exception in get_all_positions:", e)
    
    return []

# === CLOSE ALL POSITIONS ===
def close_all_positions(symbol):
    """Close ALL positions for the symbol"""
    try:
        positions = get_all_positions(symbol)
        
        if not positions:
            print("✅ No positions to close")
            return True
        
        print(f"🔄 Closing {len(positions)} positions...")
        
        all_closed = True
        for pos in positions:
            if pos["holdSide"] == "long":
                close_side = "close_long"
            else:
                close_side = "close_short"
            
            close_size = pos["available"] if pos["available"] > 0 else pos["total"]
            
            # Close this position
            endpoint = "/api/mix/v1/order/placeOrder"
            payload = {
                "symbol": symbol,
                "marginCoin": "USDT",
                "size": str(close_size),
                "side": close_side,
                "orderType": "market",
                "timeInForceValue": "normal"
            }
            
            body = json.dumps(payload)
            headers = make_headers("POST", endpoint, body)
            url = BASE_URL + endpoint
            
            print(f"💥 Closing {pos['holdSide']}: {close_size}")
            r = requests.post(url, headers=headers, data=body, timeout=15)
            response_data = r.json()
            
            print("🌍 Close response:", response_data)
            
            if response_data.get("code") not in (0, "0"):
                all_closed = False
                print(f"❌ Failed to close {pos['holdSide']}")
        
        # Wait for closures to process
        print("⏳ Waiting for positions to close...")
        time.sleep(5)
        
        # Verify all positions are closed
        remaining_positions = get_all_positions(symbol)
        if not remaining_positions:
            print("✅ All positions closed successfully")
            return True
        else:
            print(f"❌ Still {len(remaining_positions)} positions remaining")
            return False
            
    except Exception as e:
        print("❌ Error in close_all_positions:", e)
        return False

# === OPEN POSITION ===
def open_position(symbol, side):
    """Open a new position"""
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
        
        print(f"📈 Opening {side_name}: {trade_size} USDT")
        r = requests.post(url, headers=headers, data=body, timeout=15)
        response_data = r.json()
        
        print("🌍 Open response:", response_data)
        
        if response_data.get("code") in (0, "0"):
            print(f"✅ {side_name} position opened successfully")
            return True
        else:
            print(f"❌ Open failed: {response_data.get('msg')}")
            return False
            
    except Exception as e:
        print("❌ Error opening position:", e)
        return False

# === SIMPLE WORKING STRATEGY ===
def execute_trade(symbol, side):
    """SIMPLE & WORKING: Close everything, then open new position"""
    print(f"🎯 Executing {side.upper()} for {symbol}")
    print("=" * 60)
    
    # STEP 1: Close ALL positions (both long and short)
    print("1️⃣ STEP 1: Closing ALL existing positions...")
    if not close_all_positions(symbol):
        print("❌ Failed to close positions, aborting")
        return
    
    # STEP 2: Wait to ensure closures are processed
    print("2️⃣ STEP 2: Waiting for closures to process...")
    time.sleep(3)
    
    # STEP 3: Open new position
    print(f"3️⃣ STEP 3: Opening new {side.upper()} position...")
    open_position(symbol, side)
    
    print("=" * 60)

# === Webhook ===
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        print("🚀 Webhook triggered!")
        data = request.get_json(force=True)
        print("📩 Received payload:", data)
        
        symbol = data.get("symbol")
        side = data.get("side")
        
        if not symbol or not side:
            return jsonify({"error": "missing symbol or side"}), 400
        
        if side.lower() not in ['buy', 'sell']:
            return jsonify({"error": "side must be 'buy' or 'sell'"}), 400
        
        # Execute the trade
        execute_trade(symbol, side)
        
        return jsonify({"status": "executed"}), 200
        
    except Exception as e:
        print("❌ Webhook Error:", e)
        return jsonify({"error": str(e)}), 500

@app.route('/')
def home():
    return "✅ Bitget Bot - SIMPLE & WORKING"

@app.route('/position/<symbol>', methods=['GET'])
def check_position(symbol):
    """Check current positions"""
    positions = get_all_positions(symbol)
    return jsonify({
        "symbol": symbol,
        "positions": positions,
        "total_positions": len(positions)
    })

@app.route('/close/<symbol>', methods=['POST'])
def close_manual(symbol):
    """Manual close endpoint"""
    success = close_all_positions(symbol)
    return jsonify({"status": "success" if success else "error"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
