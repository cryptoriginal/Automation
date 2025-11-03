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

# === Close ALL existing positions ===
def close_all_positions(symbol):
    """Close all existing positions (both long and short) for a symbol"""
    positions = get_all_positions(symbol)
    
    if not positions:
        print("✅ No existing positions to close")
        return True
    
    success = True
    for pos in positions:
        if pos["total"] > 0:
            hold_side = pos["holdSide"]
            close_side = "close_short" if hold_side == "short" else "close_long"
            quantity = pos["available"] if pos["available"] > 0 else pos["total"]
            
            print(f"🔻 Closing {hold_side} position: {quantity}")
            
            if not close_single_position(symbol, close_side, quantity):
                success = False
            else:
                # Wait a bit after closing to ensure order is processed
                time.sleep(2)
    
    return success

def close_single_position(symbol, side_type, qty, max_retries=3):
    """Close a single position with retry logic"""
    for attempt in range(max_retries):
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
            
            print(f"💥 Close order attempt {attempt + 1}:", payload)
            print("🌍 Bitget response:", r.status_code, r.text)
            
            if response_data.get("code") in (0, "0"):
                print(f"✅ Close order placed successfully")
                return True
            else:
                print(f"❌ Close order failed: {response_data.get('msg', 'Unknown error')}")
                
        except Exception as e:
            print(f"❌ Error closing order (attempt {attempt + 1}):", e)
        
        # Wait before retry
        if attempt < max_retries - 1:
            time.sleep(1)
    
    return False

# === Verify no positions exist ===
def verify_no_positions(symbol, max_checks=5, delay=2):
    """Verify that no positions exist for the symbol"""
    for check in range(max_checks):
        positions = get_all_positions(symbol)
        
        # Filter out positions with zero quantity
        active_positions = [p for p in positions if p["total"] > 0]
        
        if not active_positions:
            print("✅ Verified: No active positions")
            return True
        
        print(f"⚠️ Still {len(active_positions)} active positions, waiting... (check {check + 1}/{max_checks})")
        time.sleep(delay)
    
    print("❌ Verification failed: Positions still exist after multiple checks")
    return False

# === Place order with guaranteed single position ===
def place_order(symbol, side):
    try:
        print(f"🎯 Starting order process for {symbol} - {side}")
        
        # 1) Close ALL existing positions first
        print("🔄 Step 1: Closing all existing positions...")
        if not close_all_positions(symbol):
            print("❌ Failed to close some positions, aborting")
            return
        
        # 2) Verify all positions are closed
        print("🔍 Step 2: Verifying all positions are closed...")
        if not verify_no_positions(symbol):
            print("❌ Positions still exist after closing, aborting")
            return
        
        # 3) Compute trade size
        trade_size = round(TRADE_BALANCE * 3, 6)
        if trade_size <= 0:
            print("❌ Trade size is zero — set TRADE_BALANCE_USDT env var to >0")
            return

        # 4) Place the new order
        print("📈 Step 3: Placing new order...")
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
            print("✅ Order placed successfully!")
            
            # Final verification
            time.sleep(3)
            final_positions = get_all_positions(symbol)
            active_final = [p for p in final_positions if p["total"] > 0]
            print(f"📊 Final position status: {len(active_final)} active positions")
            
        else:
            print("❌ Order failed:", response_data.get('msg', 'Unknown error'))
            
    except Exception as e:
        print("❌ Exception placing order:", e)

# === Additional endpoint to check current positions ===
@app.route('/position/<symbol>', methods=['GET'])
def check_position(symbol):
    """Endpoint to check current positions for a symbol"""
    positions = get_all_positions(symbol)
    active_positions = [p for p in positions if p["total"] > 0]
    
    return jsonify({
        "symbol": symbol,
        "active_positions": len(active_positions),
        "positions": active_positions
    })

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
        place_order(symbol, side)
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print("❌ Webhook Error:", e)
        return jsonify({"error": str(e)}), 500

@app.route('/')
def home():
    return "✅ Bitget webhook running - Guaranteed Single Position"

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
