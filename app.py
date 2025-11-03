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

# === Get ALL positions with detailed info ===
def get_all_positions(symbol):
    """Get all positions with detailed information including positionId"""
    try:
        endpoint = f"/api/mix/v1/position/allPosition?symbol={symbol}&marginCoin=USDT"
        url = BASE_URL + endpoint
        request_path = f"/api/mix/v1/position/allPosition?symbol={symbol}&marginCoin=USDT"
        headers = make_headers("GET", request_path, "")
        r = requests.get(url, headers=headers, timeout=10)
        j = r.json()
        
        if j.get("code") in (0, "0"):
            positions = j.get("data", [])
            print(f"📊 Found {len(positions)} positions for {symbol}")
            
            result = []
            for pos in positions:
                total_size = float(pos.get("total", 0) or 0)
                if total_size > 0:  # Only return positions with size > 0
                    position_info = {
                        "positionId": pos.get("positionId"),
                        "holdSide": pos.get("holdSide", "").lower(),
                        "total": total_size,
                        "available": float(pos.get("available", 0) or 0),
                        "symbol": pos.get("symbol"),
                        "marginCoin": pos.get("marginCoin"),
                        "openAvgPrice": pos.get("openAvgPrice"),
                        "leverage": pos.get("leverage")
                    }
                    print(f"   - {position_info['holdSide']}: {position_info['total']} (ID: {position_info['positionId']})")
                    result.append(position_info)
            return result
        else:
            print("⚠️ Position fetch returned:", r.status_code, r.text)
    except Exception as e:
        print("⚠️ Exception in get_all_positions:", e)
    return []

# === Close position by ID (PROPER way in hedge mode) ===
def close_position_by_id(symbol, position_id, hold_side, quantity):
    """Close a specific position by ID - this is the correct way in hedge mode"""
    try:
        endpoint = "/api/mix/v1/order/closePositions"
        
        # In hedge mode, we use reduceOnly and the specific position side
        if hold_side == "long":
            side = "close_long"
        else:
            side = "close_short"
            
        payload = {
            "symbol": symbol,
            "marginCoin": "USDT",
            "positionId": position_id,
            "size": str(round(quantity, 6)),
            "side": side,
            "orderType": "market"
        }
        
        body = json.dumps(payload)
        headers = make_headers("POST", endpoint, body)
        url = BASE_URL + endpoint
        r = requests.post(url, headers=headers, data=body, timeout=15)
        response_data = r.json()
        
        print(f"💥 Closing {hold_side} position ID {position_id}: {quantity}")
        print("🌍 Bitget response:", r.status_code, r.text)
        
        if response_data.get("code") in (0, "0"):
            print(f"✅ Position {position_id} close order placed successfully")
            return True
        else:
            print(f"❌ Position close failed: {response_data.get('msg', 'Unknown error')}")
            return False
                
    except Exception as e:
        print(f"❌ Error closing position {position_id}:", e)
        return False

# === Close ALL positions using position IDs ===
def close_all_positions(symbol):
    """Close all positions using their specific position IDs"""
    positions = get_all_positions(symbol)
    
    if not positions:
        print("✅ No positions to close")
        return True
    
    print(f"🔄 Closing {len(positions)} positions...")
    
    all_closed = True
    for pos in positions:
        if not close_position_by_id(symbol, pos["positionId"], pos["holdSide"], pos["available"]):
            all_closed = False
            print(f"❌ Failed to close {pos['holdSide']} position")
        else:
            print(f"✅ Close order sent for {pos['holdSide']} position")
    
    return all_closed

# === Wait and verify positions are closed ===
def wait_for_positions_closed(symbol, max_wait=20, check_interval=2):
    """Wait and verify that all positions are closed"""
    print("⏳ Waiting for positions to close...")
    
    for i in range(max_wait // check_interval):
        positions = get_all_positions(symbol)
        if not positions:
            print("✅ All positions confirmed closed!")
            return True
        
        print(f"   Still {len(positions)} positions open, waiting... ({i + 1})")
        time.sleep(check_interval)
    
    print("❌ Positions still open after maximum wait time")
    return False

# === Place order with PROPER hedge mode handling ===
def place_order(symbol, side):
    try:
        print(f"🎯 Starting order process for {symbol} - {side}")
        print("=" * 60)
        
        # STEP 1: Check current positions
        print("📊 STEP 1: Checking current positions...")
        current_positions = get_all_positions(symbol)
        if current_positions:
            print(f"   Found {len(current_positions)} open positions")
            for pos in current_positions:
                print(f"   📍 {pos['holdSide'].upper()}: {pos['total']} (ID: {pos['positionId']})")
        else:
            print("   📍 No current positions")
        
        # STEP 2: Close ALL existing positions using position IDs
        print("\n🔄 STEP 2: Closing ALL existing positions...")
        close_success = close_all_positions(symbol)
        
        if not close_success:
            print("❌ Failed to send close orders for some positions")
        
        # STEP 3: Wait and verify positions are actually closed
        print("\n⏳ STEP 3: Waiting for positions to close...")
        positions_closed = wait_for_positions_closed(symbol)
        
        if not positions_closed:
            print("❌ CRITICAL: Positions still exist after closure attempts, ABORTING!")
            return
        
        print("✅ SUCCESS: All positions confirmed closed!")
        
        # STEP 4: Compute trade size
        trade_size = round(TRADE_BALANCE * 3, 6)
        if trade_size <= 0:
            print("❌ Trade size is zero — set TRADE_BALANCE_USDT env var to >0")
            return

        # STEP 5: Place the new order
        print(f"\n📈 STEP 4: Placing NEW {side.upper()} order...")
        endpoint = "/api/mix/v1/order/placeOrder"
        
        if side.lower() == "buy":
            order_side = "open_long"
        else:
            order_side = "open_short"
            
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
        print("🧾 Sending order payload:", payload)
        
        r = requests.post(url, headers=headers, data=body, timeout=15)
        response_data = r.json()
        print("🌍 Bitget Response:", r.status_code, r.text)
        
        if response_data.get("code") in (0, "0"):
            print("✅✅✅ NEW ORDER PLACED SUCCESSFULLY!")
            
            # Final check
            print("\n🔍 Final position check...")
            time.sleep(3)
            final_positions = get_all_positions(symbol)
            if final_positions:
                for pos in final_positions:
                    print(f"   ✅ Final position: {pos['holdSide'].upper()} - {pos['total']}")
            else:
                print("   ⚠️ No positions found - order may still be processing")
                
        else:
            print("❌ Order failed:", response_data.get('msg', 'Unknown error'))
            
        print("=" * 60)
            
    except Exception as e:
        print("❌ Exception placing order:", e)

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
        
        # Validate side
        if side.lower() not in ['buy', 'sell']:
            return jsonify({"error": "side must be 'buy' or 'sell'"}), 400
            
        place_order(symbol, side)
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print("❌ Webhook Error:", e)
        return jsonify({"error": str(e)}), 500

@app.route('/')
def home():
    return "✅ Bitget webhook running - HEDGE MODE Position Management"

@app.route('/position/<symbol>', methods=['GET'])
def check_position(symbol):
    """Endpoint to check current positions for a symbol"""
    positions = get_all_positions(symbol)
    return jsonify({
        "symbol": symbol,
        "active_positions": len(positions),
        "positions": positions
    })

@app.route('/close/<symbol>', methods=['POST'])
def close_positions_endpoint(symbol):
    """Manual endpoint to close all positions for a symbol"""
    try:
        success = close_all_positions(symbol)
        if success:
            return jsonify({"status": "success", "message": f"All positions closed for {symbol}"})
        else:
            return jsonify({"status": "error", "message": f"Failed to close some positions for {symbol}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
