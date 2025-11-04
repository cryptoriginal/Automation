import os
import time
import hmac
import hashlib
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- BingX Configuration ---
API_KEY = os.getenv("BINGX_API_KEY")
SECRET_KEY = os.getenv("BINGX_SECRET_KEY")
TRADE_BALANCE = float(os.getenv("TRADE_BALANCE_USDT", "25"))

BASE_URL = "https://open-api.bingx.com"

# === BingX Signature ===
def bingx_signature(params, secret_key):
    """Generate BingX signature"""
    query_string = '&'.join([f"{key}={value}" for key, value in sorted(params.items())])
    signature = hmac.new(
        secret_key.encode('utf-8'), 
        query_string.encode('utf-8'), 
        hashlib.sha256
    ).hexdigest()
    return signature

def bingx_headers():
    return {
        "X-BX-APIKEY": API_KEY,
        "Content-Type": "application/json"
    }

# === Get Current Position ===
def get_current_position(symbol):
    """Get current position for symbol"""
    try:
        params = {
            "symbol": symbol,
            "timestamp": int(time.time() * 1000)
        }
        
        signature = bingx_signature(params, SECRET_KEY)
        params["signature"] = signature
        
        url = f"{BASE_URL}/openApi/swap/v2/user/positions"
        response = requests.get(url, headers=bingx_headers(), params=params, timeout=10)
        data = response.json()
        
        if "data" in data and data["data"]:
            for position in data["data"]:
                if position["symbol"] == symbol and float(position["positionAmt"] or 0) != 0:
                    return {
                        "side": "LONG" if float(position["positionAmt"] or 0) > 0 else "SHORT",
                        "quantity": abs(float(position["positionAmt"] or 0)),
                        "leverage": position.get("leverage", 1)
                    }
        return None
    except Exception as e:
        print(f"❌ Error getting position: {e}")
        return None

# === Close Position ===
def close_position(symbol, side, quantity):
    """Close existing position"""
    try:
        # For closing, use opposite side
        if side == "LONG":
            close_side = "SELL"
        else:
            close_side = "BUY"
        
        params = {
            "symbol": symbol,
            "side": close_side,
            "positionSide": "LONG" if side == "LONG" else "SHORT",
            "type": "MARKET",
            "quantity": abs(quantity),
            "timestamp": int(time.time() * 1000)
        }
        
        signature = bingx_signature(params, SECRET_KEY)
        params["signature"] = signature
        
        url = f"{BASE_URL}/openApi/swap/v2/trade/order"
        response = requests.post(url, headers=bingx_headers(), json=params, timeout=15)
        data = response.json()
        
        print(f"🔻 Closing {side} position: {quantity}")
        print(f"🌍 Close response: {data}")
        
        if data.get("code") == 0:
            print("✅ Position closed successfully")
            return True
        else:
            print(f"❌ Close failed: {data.get('msg')}")
            return False
            
    except Exception as e:
        print(f"❌ Error closing position: {e}")
        return False

# === Open Position ===
def open_position(symbol, side, quantity):
    """Open new position"""
    try:
        params = {
            "symbol": symbol,
            "side": side,
            "positionSide": "LONG" if side == "BUY" else "SHORT",
            "type": "MARKET",
            "quantity": quantity,
            "timestamp": int(time.time() * 1000)
        }
        
        signature = bingx_signature(params, SECRET_KEY)
        params["signature"] = signature
        
        url = f"{BASE_URL}/openApi/swap/v2/trade/order"
        response = requests.post(url, headers=bingx_headers(), json=params, timeout=15)
        data = response.json()
        
        print(f"📈 Opening {side} position: {quantity}")
        print(f"🌍 Open response: {data}")
        
        if data.get("code") == 0:
            print(f"✅ {side} position opened successfully")
            return True
        else:
            print(f"❌ Open failed: {data.get('msg')}")
            return False
            
    except Exception as e:
        print(f"❌ Error opening position: {e}")
        return False

# === Execute Trade Logic ===
def execute_trade(symbol, action):
    """Main trade execution logic - CLOSE FIRST, THEN OPEN NEW"""
    print(f"🎯 Executing {action} for {symbol}")
    print("=" * 60)
    
    # Calculate trade size (3x leverage of TRADE_BALANCE)
    trade_size = round(TRADE_BALANCE * 3, 3)
    
    if trade_size <= 0:
        print("❌ Invalid trade size")
        return
    
    print(f"💰 Trade Balance: {TRADE_BALANCE} USDT")
    print(f"📊 Position Size (3x): {trade_size} USDT")
    
    # STEP 1: Get current position
    current_position = get_current_position(symbol)
    print(f"📊 Current position: {current_position}")
    
    # STEP 2: Close existing position if it exists
    if current_position:
        print(f"🔄 Closing existing {current_position['side']} position first...")
        if close_position(symbol, current_position["side"], current_position["quantity"]):
            print("✅ Position closed, waiting for settlement...")
            time.sleep(2)  # Wait for close to process
        else:
            print("❌ Failed to close existing position, aborting trade")
            return
    else:
        print("✅ No existing position to close")
    
    # STEP 3: Open new position
    if action.upper() == "BUY":
        print("📈 Opening LONG position...")
        open_position(symbol, "BUY", trade_size)
    elif action.upper() == "SELL":
        print("📉 Opening SHORT position...")
        open_position(symbol, "SELL", trade_size)
    
    print("=" * 60)

# === Webhook Endpoint ===
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        print("🚀 TradingView Webhook Triggered!")
        data = request.get_json(force=True)
        print(f"📩 Received payload: {data}")
        
        symbol = data.get("symbol")
        side = data.get("side")
        
        if not symbol or not side:
            return jsonify({"error": "missing symbol or side"}), 400
        
        if side.upper() not in ['BUY', 'SELL']:
            return jsonify({"error": "side must be 'BUY' or 'SELL'"}), 400
        
        # Execute the trade
        execute_trade(symbol, side.upper())
        
        return jsonify({"status": "success", "message": "Trade executed"}), 200
        
    except Exception as e:
        print(f"❌ Webhook Error: {e}")
        return jsonify({"error": str(e)}), 500

# === Utility Endpoints ===
@app.route('/')
def home():
    return """
    ✅ BingX Trading Bot - ACTIVE
    
    Usage:
    - Send POST to /webhook with JSON:
      {"symbol": "SOL-USDT", "side": "BUY"}
      {"symbol": "SUI-USDT", "side": "SELL"}
    
    Supported pairs: SOL-USDT, SUI-USDT, or any BingX futures pair
    
    Endpoints:
    - GET /position/SOL-USDT - Check current position
    - POST /close/SOL-USDT - Close position manually
    """

@app.route('/position/<symbol>', methods=['GET'])
def check_position(symbol):
    """Check current position for a symbol"""
    position = get_current_position(symbol)
    return jsonify({
        "symbol": symbol,
        "position": position if position else "No position",
        "trade_balance": TRADE_BALANCE,
        "calculated_size": round(TRADE_BALANCE * 3, 3)
    })

@app.route('/close/<symbol>', methods=['POST'])
def close_position_manual(symbol):
    """Manually close position for a symbol"""
    position = get_current_position(symbol)
    if position:
        success = close_position(symbol, position["side"], position["quantity"])
        return jsonify({"status": "success" if success else "error"})
    else:
        return jsonify({"status": "no_position"})

@app.route('/test', methods=['GET'])
def test():
    """Test endpoint"""
    return jsonify({
        "status": "active",
        "timestamp": time.time(),
        "trade_balance": TRADE_BALANCE,
        "position_size": TRADE_BALANCE * 3
    })

if __name__ == "__main__":
    print("🔷 Starting BingX Trading Bot")
    print(f"💰 Trade Balance: {TRADE_BALANCE} USDT")
    print(f"📊 Position Size (3x): {TRADE_BALANCE * 3} USDT")
    print("🎯 Supported pairs: SOL-USDT, SUI-USDT, etc.")
    print("🚀 Webhook ready at: /webhook")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
