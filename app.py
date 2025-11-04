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
            available = float(data.get("available", 0) or 0)
            
            return hold_side, total, available
        else:
            print("❌ Position fetch error:", j.get('msg'))
    except Exception as e:
        print("❌ Exception in get_current_position:", e)
    
    return None, 0, 0

# === Close position at market price ===
def close_position_market(symbol, side=None):
    """Close position at market price"""
    try:
        # If no side specified, get current position
        if not side:
            current_side, current_size, available = get_current_position(symbol)
            if not current_side or current_size == 0:
                print("✅ No position to close")
                return True
            side = current_side
        
        # Determine close side
        if side.lower() == "long":
            close_side = "close_long"
            side_name = "LONG"
        else:
            close_side = "close_short" 
            side_name = "SHORT"
        
        # Get position size
        current_side, current_size, available = get_current_position(symbol)
        close_size = available if available > 0 else current_size
        
        if close_size <= 0:
            print("❌ No position size to close")
            return False
        
        # Place close order at market
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
        
        print(f"💥 Closing {side_name} position at market: {close_size}")
        r = requests.post(url, headers=headers, data=body, timeout=15)
        response_data = r.json()
        
        print("🌍 Close response:", response_data)
        
        if response_data.get("code") in (0, "0"):
            print("✅ Close order placed successfully at market price")
            
            # Wait and verify
            for i in range(8):
                time.sleep(1)
                new_side, new_total, _ = get_current_position(symbol)
                if new_total == 0:
                    print("✅ Position confirmed closed")
                    return True
                print(f"⏳ Waiting for close to complete... {i+1}/8")
            
            print("⚠️ Close may still be processing")
            return True
        else:
            print(f"❌ Close failed: {response_data.get('msg')}")
            return False
            
    except Exception as e:
        print("❌ Error closing position:", e)
        return False

# === Open position at market price ===
def open_position_market(symbol, side, size=None):
    """Open position at market price"""
    try:
        if not size:
            size = round(TRADE_BALANCE * 3, 6)
        
        if size <= 0:
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
            "size": str(size),
            "side": order_side,
            "orderType": "market",
            "timeInForceValue": "normal"
        }
        
        body = json.dumps(payload)
        headers = make_headers("POST", endpoint, body)
        url = BASE_URL + endpoint
        
        print(f"📈 Opening {side_name} at market: {size} USDT")
        r = requests.post(url, headers=headers, data=body, timeout=15)
        response_data = r.json()
        
        print("🌍 Open response:", response_data)
        
        if response_data.get("code") in (0, "0"):
            print(f"✅ {side_name} position opened successfully at market price")
            return True
        else:
            print(f"❌ Open failed: {response_data.get('msg')}")
            return False
            
    except Exception as e:
        print("❌ Error opening position:", e)
        return False

# === NEW: Handle TradingView alert commands ===
def handle_tradingview_alert(symbol, action, side=None):
    """
    Handle TradingView alert commands:
    - 'close': Close any existing position
    - 'open_long': Open long position (closes any existing first)
    - 'open_short': Open short position (closes any existing first) 
    - 'reverse_long': Close any position and open long
    - 'reverse_short': Close any position and open short
    """
    print(f"🎯 Processing {action.upper()} for {symbol}")
    print("=" * 50)
    
    if action == "close":
        # Just close any existing position
        return close_position_market(symbol)
    
    elif action == "open_long":
        # Close any existing position first, then open long
        close_position_market(symbol)
        time.sleep(2)
        return open_position_market(symbol, "buy")
    
    elif action == "open_short":
        # Close any existing position first, then open short  
        close_position_market(symbol)
        time.sleep(2)
        return open_position_market(symbol, "sell")
    
    elif action == "reverse_long":
        # Close any existing and open long
        close_position_market(symbol)
        time.sleep(2)
        return open_position_market(symbol, "buy")
    
    elif action == "reverse_short":
        # Close any existing and open short
        close_position_market(symbol)
        time.sleep(2)
        return open_position_market(symbol, "sell")
    
    else:
        print(f"❌ Unknown action: {action}")
        return False

# === Webhook for TradingView alerts ===
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        print("🚀 TradingView Webhook triggered!")
        data = request.get_json(force=True)
        print("📩 Received payload:", data)
        
        symbol = data.get("symbol")
        action = data.get("action")  # close, open_long, open_short, reverse_long, reverse_short
        side = data.get("side")      # buy, sell (for backward compatibility)
        
        if not symbol:
            return jsonify({"error": "missing symbol"}), 400
        
        # Backward compatibility: if action not provided, use side
        if not action and side:
            if side.lower() == "buy":
                action = "reverse_long"
            else:
                action = "reverse_short"
        elif not action:
            return jsonify({"error": "missing action or side"}), 400
        
        # Process the alert
        success = handle_tradingview_alert(symbol, action)
        
        if success:
            return jsonify({"status": "success", "action": action, "symbol": symbol}), 200
        else:
            return jsonify({"status": "error", "action": action, "symbol": symbol}), 500
        
    except Exception as e:
        print("❌ Webhook Error:", e)
        return jsonify({"error": str(e)}), 500

@app.route('/')
def home():
    return """
    ✅ Bitget TradingView Bot - WORKING
    
    Available actions:
    - close: Close any existing position
    - open_long: Close any existing and open LONG
    - open_short: Close any existing and open SHORT  
    - reverse_long: Close any existing and open LONG
    - reverse_short: Close any existing and open SHORT
    
    Usage in TradingView:
    {
      "symbol": "BTCUSDT_UMCBL",
      "action": "reverse_long"
    }
    """

@app.route('/position/<symbol>', methods=['GET'])
def check_position(symbol):
    """Check current position"""
    side, total, available = get_current_position(symbol)
    return jsonify({
        "symbol": symbol,
        "position_side": side,
        "position_size": total,
        "available": available
    })

@app.route('/close/<symbol>', methods=['POST'])
def close_position_manual(symbol):
    """Manual close endpoint"""
    success = close_position_market(symbol)
    return jsonify({"status": "success" if success else "error"})

@app.route('/open/<symbol>/<side>', methods=['POST'])
def open_position_manual(symbol, side):
    """Manual open endpoint"""
    success = open_position_market(symbol, side)
    return jsonify({"status": "success" if success else "error"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
