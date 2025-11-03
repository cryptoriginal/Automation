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

# === Get ALL positions for the symbol ===
def get_all_positions(symbol):
    """Get all positions (both long and short) for a symbol"""
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
                if float(pos.get("total", 0) or 0) > 0:  # Only return positions with size > 0
                    position_info = {
                        "holdSide": pos.get("holdSide", "").lower(),
                        "total": float(pos.get("total", 0) or 0),
                        "available": float(pos.get("available", 0) or 0),
                        "symbol": pos.get("symbol"),
                        "marginCoin": pos.get("marginCoin")
                    }
                    print(f"   - {position_info['holdSide']}: {position_info['total']} (available: {position_info['available']})")
                    result.append(position_info)
            return result
        else:
            print("⚠️ Position fetch returned:", r.status_code, r.text)
    except Exception as e:
        print("⚠️ Exception in get_all_positions:", e)
    return []

# === Close ALL existing positions with aggressive retry ===
def close_all_positions(symbol):
    """Close all existing positions (both long and short) for a symbol"""
    max_attempts = 5
    attempt = 0
    
    while attempt < max_attempts:
        attempt += 1
        print(f"🔄 Closing positions attempt {attempt}/{max_attempts}")
        
        positions = get_all_positions(symbol)
        
        if not positions:
            print("✅ No positions to close")
            return True
        
        all_closed = True
        for pos in positions:
            if pos["total"] > 0:
                hold_side = pos["holdSide"]
                close_side = "close_short" if hold_side == "short" else "close_long"
                quantity = pos["available"] if pos["available"] > 0 else pos["total"]
                
                print(f"🔻 Closing {hold_side} position: {quantity}")
                
                if not close_single_position(symbol, close_side, quantity):
                    all_closed = False
                    print(f"❌ Failed to close {hold_side} position")
                else:
                    print(f"✅ Close order sent for {hold_side} position")
        
        # Wait for Bitget to process the close orders
        print("⏳ Waiting for position closure to process...")
        time.sleep(5)  # Increased wait time
        
        # Check if positions are actually closed
        remaining_positions = get_all_positions(symbol)
        if not remaining_positions:
            print("✅ All positions successfully closed")
            return True
        else:
            print(f"⚠️ Still {len(remaining_positions)} positions remaining, retrying...")
    
    print("❌ Failed to close all positions after maximum attempts")
    return False

def close_single_position(symbol, side_type, qty):
    """Close a single position"""
    try:
        endpoint = "/api/mix/v1/order/placeOrder"
        payload = {
            "symbol": symbol,
            "marginCoin": "USDT",
            "size": str(round(qty, 6)),
            "side": side_type,
            "orderType": "market",
            "timeInForceValue": "normal"
        }
        body = json.dumps(payload)
        headers = make_headers("POST", endpoint, body)
        url = BASE_URL + endpoint
        r = requests.post(url, headers=headers, data=body, timeout=15)
        response_data = r.json()
        
        print(f"💥 Close order:", payload)
        print("🌍 Bitget response:", r.status_code, r.text)
        
        if response_data.get("code") in (0, "0"):
            print(f"✅ Close order placed successfully")
            return True
        else:
            print(f"❌ Close order failed: {response_data.get('msg', 'Unknown error')}")
            return False
                
    except Exception as e:
        print(f"❌ Error closing order:", e)
        return False

# === SIMPLIFIED Place order - Close first, then open ===
def place_order(symbol, side):
    try:
        print(f"🎯 Starting order process for {symbol} - {side}")
        print("=" * 50)
        
        # STEP 1: Check current positions
        print("📊 STEP 1: Checking current positions...")
        current_positions = get_all_positions(symbol)
        if current_positions:
            for pos in current_positions:
                print(f"   📍 Current: {pos['holdSide']} - {pos['total']}")
        else:
            print("   📍 No current positions")
        
        # STEP 2: Close ALL existing positions first (AGGRESSIVE)
        print("\n🔄 STEP 2: Closing ALL existing positions...")
        close_success = close_all_positions(symbol)
        
        if not close_success:
            print("❌ CRITICAL: Failed to close existing positions, ABORTING trade!")
            return
        
        # STEP 3: Wait longer to ensure positions are closed
        print("\n⏳ STEP 3: Final verification - waiting for system to update...")
        time.sleep(8)  # Wait even longer for Bitget system
        
        # STEP 4: Final position check
        final_check = get_all_positions(symbol)
        if final_check:
            print("❌ CRITICAL: Positions still exist after closure, ABORTING!")
            for pos in final_check:
                print(f"   ❌ Still open: {pos['holdSide']} - {pos['total']}")
            return
        
        print("✅ SUCCESS: All positions confirmed closed!")
        
        # STEP 5: Compute trade size
        trade_size = round(TRADE_BALANCE * 3, 6)
        if trade_size <= 0:
            print("❌ Trade size is zero — set TRADE_BALANCE_USDT env var to >0")
            return

        # STEP 6: Place the new order
        print(f"\n📈 STEP 4: Placing NEW {side} order...")
        endpoint = "/api/mix/v1/order/placeOrder"
        payload = {
            "symbol": symbol,
            "marginCoin": "USDT",
            "size": str(trade_size),
            "side": "open_long" if side.lower() == "buy" else "open_short",
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
            
            # Final verification after order
            print("\n🔍 Final position check after new order...")
            time.sleep(5)
            final_positions = get_all_positions(symbol)
            if final_positions:
                for pos in final_positions:
                    print(f"   ✅ Final: {pos['holdSide']} - {pos['total']}")
            else:
                print("   ⚠️ No positions found after order placement")
                
        else:
            print("❌ Order failed:", response_data.get('msg', 'Unknown error'))
            
        print("=" * 50)
            
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
    return "✅ Bitget webhook running - AGGRESSIVE Position Management"

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
