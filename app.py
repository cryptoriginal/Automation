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

# === FIXED: Get all positions ===
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
                        "symbol": pos.get("symbol")
                    }
                    active_positions.append(position_info)
                    print(f"📊 Found: {position_info['holdSide']} - {position_info['total']}")
            
            return active_positions
        else:
            print(f"❌ Position fetch error: {j.get('msg')}")
            return []
    except Exception as e:
        print(f"❌ Exception in get_all_positions: {e}")
        return []

# === FIXED: Nuclear close ===
def nuclear_close(symbol):
    """FIXED NUCLEAR OPTION: Close all positions"""
    try:
        print("💣 NUCLEAR OPTION ACTIVATED!")
        
        # 1. Get all current positions
        positions = get_all_positions(symbol)
        
        if not positions:
            print("✅ No positions to close")
            return True
        
        print(f"🔄 Closing {len(positions)} positions...")
        
        # 2. Close each position
        for pos in positions:
            hold_side = pos["holdSide"]
            close_size = pos["available"] if pos["available"] > 0 else pos["total"]
            
            if hold_side == "long":
                close_side = "close_long"
            else:
                close_side = "close_short"
            
            # Close position
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
            
            print(f"💥 Closing {hold_side} position: {close_size}")
            r = requests.post(url, headers=headers, data=body, timeout=15)
            response_data = r.json()
            
            print(f"🌍 Close response: {response_data}")
            
            if response_data.get("code") in (0, "0"):
                print(f"✅ {hold_side} position close order placed")
            else:
                print(f"❌ Failed to close {hold_side}: {response_data.get('msg')}")
        
        # 3. Wait and verify
        print("⏳ Waiting for positions to close...")
        time.sleep(5)
        
        # 4. Check if positions are actually closed
        remaining = get_all_positions(symbol)
        if not remaining:
            print("✅ ALL POSITIONS CLOSED SUCCESSFULLY!")
            return True
        else:
            print(f"⚠️ Still {len(remaining)} positions open after nuclear close")
            return False
        
    except Exception as e:
        print(f"❌ Nuclear close failed: {e}")
        return False

# === Simple trade ===  
def simple_trade(symbol, side):
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
        response = r.json()
        print(f"🌍 Response: {response}")
        
        if response.get("code") in (0, "0"):
            print(f"✅ {side_name} POSITION OPENED SUCCESSFULLY!")
            return True
        else:
            print(f"❌ Open failed: {response.get('msg')}")
            return False
        
    except Exception as e:
        print(f"❌ Error opening position: {e}")
        return False

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        symbol = data.get("symbol")
        side = data.get("side")
        mode = data.get("mode", "nuclear")
        
        if not symbol or not side:
            return jsonify({"error": "missing symbol or side"}), 400
        
        print(f"🚀 {mode.upper()} MODE: {side.upper()} for {symbol}")
        
        if mode == "nuclear":
            # Close everything first, then open
            nuclear_close(symbol)
            time.sleep(3)
            simple_trade(symbol, side)
        else:
            # Just open the position
            simple_trade(symbol, side)
        
        return jsonify({"status": "executed"}), 200
        
    except Exception as e:
        print(f"❌ Webhook Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/position/<symbol>', methods=['GET'])
def check_position(symbol):
    """Check current positions"""
    positions = get_all_positions(symbol)
    return jsonify({
        "symbol": symbol,
        "positions": positions,
        "total_positions": len(positions)
    })

@app.route('/nuke/<symbol>', methods=['POST'])
def nuke(symbol):
    """Manual nuclear close"""
    success = nuclear_close(symbol)
    return jsonify({"status": "nuked" if success else "failed"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
