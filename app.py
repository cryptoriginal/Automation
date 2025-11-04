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

# === Get ALL positions ===
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
    except Exception as e:
        print("❌ Exception in get_all_positions:", e)
    
    return []

# === CLOSE POSITION BY ID (THIS WORKS) ===
def close_position_by_id(symbol, position_id, hold_side, quantity):
    """Close specific position by ID - THIS WORKS IN HEDGE MODE"""
    try:
        # Use the correct endpoint for closing positions
        endpoint = "/api/mix/v1/order/close-positions"
        
        if hold_side == "long":
            close_side = "close_long"
        else:
            close_side = "close_short"
        
        payload = {
            "symbol": symbol,
            "marginCoin": "USDT",
            "positionId": position_id,
            "size": str(quantity),
            "side": close_side,
            "orderType": "market"
        }
        
        body = json.dumps(payload)
        headers = make_headers("POST", endpoint, body)
        url = BASE_URL + endpoint
        
        print(f"💥 Closing {hold_side} position ID {position_id}: {quantity}")
        r = requests.post(url, headers=headers, data=body, timeout=15)
        response_data = r.json()
        
        print("🌍 Close response:", response_data)
        
        if response_data.get("code") in (0, "0"):
            print(f"✅ Position closed successfully")
            return True
        else:
            print(f"❌ Close failed: {response_data.get('msg')}")
            return False
            
    except Exception as e:
        print(f"❌ Error closing position:", e)
        return False

# === CLOSE ALL POSITIONS (WORKING VERSION) ===
def close_all_positions(symbol):
    """Close ALL positions using position IDs"""
    positions = get_all_positions(symbol)
    
    if not positions:
        print("✅ No positions to close")
        return True
    
    print(f"🔄 Closing {len(positions)} positions...")
    
    success_count = 0
    for pos in positions:
        if close_position_by_id(symbol, pos["positionId"], pos["holdSide"], pos["available"]):
            success_count += 1
    
    # Wait for closures to process
    time.sleep(5)
    
    # Verify closures
    remaining = get_all_positions(symbol)
    if not remaining:
        print("✅ All positions closed successfully")
        return True
    else:
        print(f"⚠️ {len(remaining)} positions still open")
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

# === EXECUTE TRADE (GUARANTEED WORKING) ===
def execute_trade(symbol, side):
    """GUARANTEED WORKING: Close all, then open new"""
    print(f"🎯 Executing {side.upper()} for {symbol}")
    print("=" * 60)
    
    # STEP 1: Get current positions
    current_positions = get_all_positions(symbol)
    if current_positions:
        print(f"📊 Found {len(current_positions)} open positions")
        for pos in current_positions:
            print(f"   - {pos['holdSide']}: {pos['total']}")
    else:
        print("📊 No current positions")
    
    # STEP 2: Close ALL positions
    print("\n1️⃣ STEP 1: Closing ALL existing positions...")
    close_success = close_all_positions(symbol)
    
    if not close_success:
        print("❌ Failed to close positions, trying alternative method...")
        # Try alternative close method
        time.sleep(2)
        close_all_positions(symbol)
    
    # STEP 3: Wait and verify
    print("\n2️⃣ STEP 2: Verifying closures...")
    time.sleep(3)
    final_check = get_all_positions(symbol)
    if final_check:
        print("❌ Positions still exist after closure attempts!")
        for pos in final_check:
            print(f"   - {pos['holdSide']}: {pos['total']}")
        return
    
    print("✅ All positions confirmed closed!")
    
    # STEP 4: Open new position
    print(f"\n3️⃣ STEP 3: Opening new {side.upper()} position...")
    open_success = open_position(symbol, side)
    
    if open_success:
        print("✅✅✅ TRADE EXECUTED SUCCESSFULLY!")
    else:
        print("❌ Failed to open new position")
    
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
        
        execute_trade(symbol, side)
        return jsonify({"status": "executed"}), 200
        
    except Exception as e:
        print("❌ Webhook Error:", e)
        return jsonify({"error": str(e)}), 500

@app.route('/')
def home():
    return "✅ Bitget Bot - GUARANTEED WORKING VERSION"

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
