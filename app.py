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

# === Position fetch (singlePosition) ===
def get_position(symbol):
    """Return dict with holdSide ('long'|'short'|'') and total size (float)"""
    try:
        endpoint = f"/api/mix/v1/position/singlePosition?symbol={symbol}&marginCoin=USDT"
        url = BASE_URL + "/api/mix/v1/position/singlePosition"
        # For GET with query we sign request_path as full path + query
        request_path = f"/api/mix/v1/position/singlePosition?symbol={symbol}&marginCoin=USDT"
        headers = make_headers("GET", request_path, "")
        r = requests.get(url, headers=headers, timeout=10)
        j = r.json()
        if j.get("code") in (0, "0"):
            d = j.get("data") or {}
            hold = d.get("holdSide") or None
            total = float(d.get("total", 0) or 0)
            available = float(d.get("available", 0) or 0)
            return {"holdSide": hold, "total": total, "available": available}
        # If API returns error, return empty
        print("⚠️ Position fetch returned:", r.status_code, r.text)
    except Exception as e:
        print("⚠️ Exception in get_position:", e)
    return {"holdSide": None, "total": 0.0, "available": 0.0}

# === Close position with retry and verification ===
def close_position(symbol, side_type, qty, max_retries=3):
    """Close position with retry logic and verification"""
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
                # Wait a bit for the close to process
                time.sleep(2)
                return True
            else:
                print(f"❌ Close order failed: {response_data.get('msg', 'Unknown error')}")
                
        except Exception as e:
            print(f"❌ Error closing order (attempt {attempt + 1}):", e)
        
        # Wait before retry
        if attempt < max_retries - 1:
            time.sleep(1)
    
    return False

# === Close opposite position with verification ===
def close_opposite_position(symbol, incoming_side):
    """Close opposite position and verify it's closed before proceeding"""
    max_checks = 5
    check_delay = 1
    
    for check in range(max_checks):
        pos = get_position(symbol)
        if pos["total"] <= 0:
            print("✅ No existing position to close")
            return True
            
        hold = (pos["holdSide"] or "").lower()
        incoming = incoming_side.lower()
        
        print(f"🔍 Position check {check + 1}: holdSide={hold}, total={pos['total']}")
        
        # Check if we need to close opposite position
        if (incoming == "buy" and hold == "short") or (incoming == "sell" and hold == "long"):
            print(f"🔄 Closing opposite {hold} position before opening {incoming}")
            
            side_type = "close_short" if hold == "short" else "close_long"
            if close_position(symbol, side_type, pos["available"] if pos["available"] > 0 else pos["total"]):
                # Verify position is closed
                time.sleep(check_delay)
                new_pos = get_position(symbol)
                if new_pos["total"] <= 0:
                    print("✅ Opposite position successfully closed")
                    return True
                else:
                    print(f"⚠️ Position still open: {new_pos['total']}, retrying...")
            else:
                print("❌ Failed to close opposite position")
        else:
            # Same side position exists, no need to close
            print(f"ℹ️ Existing position is same side ({hold}), no need to close")
            return True
            
        time.sleep(check_delay)
    
    print("❌ Failed to close opposite position after multiple attempts")
    return False

# === Place order with improved logic ===
def place_order(symbol, side):
    try:
        print(f"🎯 Starting order process for {symbol} - {side}")
        
        # 1) Close opposite position and verify
        if not close_opposite_position(symbol, side):
            print("❌ Cannot proceed with new order due to position close failure")
            return

        # 2) Compute trade size
        trade_size = round(TRADE_BALANCE * 3, 6)
        if trade_size <= 0:
            print("❌ Trade size is zero — set TRADE_BALANCE_USDT env var to >0")
            return

        # 3) Double-check no opposite position exists
        final_check = get_position(symbol)
        final_hold = (final_check["holdSide"] or "").lower()
        incoming = side.lower()
        
        # If there's still an opposite position, abort
        if (incoming == "buy" and final_hold == "short") or (incoming == "sell" and final_hold == "long"):
            print("❌ Opposite position still exists, aborting order")
            return

        # 4) Place the new order
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
        else:
            print("❌ Order failed:", response_data.get('msg', 'Unknown error'))
            
    except Exception as e:
        print("❌ Exception placing order:", e)

# === Additional endpoint to check current position ===
@app.route('/position/<symbol>', methods=['GET'])
def check_position(symbol):
    """Endpoint to check current position for a symbol"""
    pos = get_position(symbol)
    return jsonify({
        "symbol": symbol,
        "holdSide": pos["holdSide"],
        "total": pos["total"],
        "available": pos["available"]
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
    return "✅ Bitget webhook running - Enhanced version with position management"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
