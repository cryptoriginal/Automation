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
TRADE_BALANCE = float(os.getenv("TRADE_BALANCE_USDT", "50"))

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
        
        if data.get("code") == 0 and "data" in data:
            positions = data["data"]
            for position in positions:
                position_amt = float(position.get("positionAmt", 0))
                if position_amt != 0:
                    return {
                        "side": "LONG" if position_amt > 0 else "SHORT",
                        "quantity": abs(position_amt),
                    }
        return None
    except Exception as e:
        print(f"❌ Error getting position: {e}")
        return None

# === Set Leverage ===
def set_leverage(symbol, leverage=3):
    """Set leverage for the symbol"""
    try:
        # Set for LONG side
        params_long = {
            "symbol": symbol,
            "leverage": leverage,
            "side": "LONG",
            "timestamp": int(time.time() * 1000)
        }
        
        signature_long = bingx_signature(params_long, SECRET_KEY)
        params_long["signature"] = signature_long
        
        url = f"{BASE_URL}/openApi/swap/v2/trade/leverage"
        response_long = requests.post(url, headers=bingx_headers(), json=params_long, timeout=15)
        
        # Set for SHORT side
        params_short = {
            "symbol": symbol,
            "leverage": leverage,
            "side": "SHORT", 
            "timestamp": int(time.time() * 1000)
        }
        
        signature_short = bingx_signature(params_short, SECRET_KEY)
        params_short["signature"] = signature_short
        
        response_short = requests.post(url, headers=bingx_headers(), json=params_short, timeout=15)
        
        print(f"⚙️ Setting leverage to {leverage}x for {symbol}")
        return True
    except Exception as e:
        print(f"❌ Error setting leverage: {e}")
        return False

# === Close Position ===
def close_position(symbol, side, quantity):
    """Close existing position"""
    try:
        if side == "LONG":
            close_side = "SELL"
            position_side = "LONG"
        else:
            close_side = "BUY"
            position_side = "SHORT"
        
        params = {
            "symbol": symbol,
            "side": close_side,
            "positionSide": position_side,
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
        if side == "BUY":
            position_side = "LONG"
        else:
            position_side = "SHORT"
        
        params = {
            "symbol": symbol,
            "side": side,
            "positionSide": position_side,
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
    """Main trade execution logic"""
    print(f"🎯 Executing {action} for {symbol}")
    print("=" * 60)
    
    # STEP 0: Set leverage to 3x
    print("⚙️ Setting leverage to 3x...")
    set_leverage(symbol, 3)
    time.sleep(1)
    
    # STEP 1: Calculate position size - EXACTLY 3x of TRADE_BALANCE
    trade_size = round(TRADE_BALANCE * 3, 3)
    
    print(f"💰 Trade Balance: {TRADE_BALANCE} USDT")
    print(f"📊 Position Size (3x): {trade_size} USDT")
    
    # STEP 2: Get current position
    current_position = get_current_position(symbol)
    print(f"📊 Current position: {current_position}")
    
    # STEP 3: Close existing position if it exists
    if current_position:
        print(f"🔄 Closing existing {current_position['side']} position first...")
        if close_position(symbol, current_position["side"], current_position["quantity"]):
            print("✅ Position closed, waiting for settlement...")
            time.sleep(2)
        else:
            print("❌ Failed to close existing position, aborting trade")
            return
    else:
        print("✅ No existing position to close")
    
    # STEP 4: Open new position
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
    
    Features:
    - 3x leverage exactly
    - Position size: TRADE_BALANCE * 3
    - Closes existing positions first
    - Works with any trading pair
    """

@app.route('/position/<symbol>', methods=['GET'])
def check_position(symbol):
    """Check current position for any symbol"""
    position = get_current_position(symbol)
    return jsonify({
        "symbol": symbol,
        "position": position if position else "No position",
        "trade_balance": TRADE_BALANCE,
        "position_size": TRADE_BALANCE * 3
    })

@app.route('/close/<symbol>', methods=['POST'])
def close_position_manual(symbol):
    """Manually close position for any symbol"""
    position = get_current_position(symbol)
    if position:
        success = close_position(symbol, position["side"], position["quantity"])
        return jsonify({"status": "success" if success else "error"})
    else:
        return jsonify({"status": "no_position"})

if __name__ == "__main__":
    print("🔷 Starting BingX Trading Bot")
    print(f"💰 Trade Balance: {TRADE_BALANCE} USDT")
    print(f"📊 Position Size (3x): {TRADE_BALANCE * 3} USDT")
    print("🎯 Supports ANY trading pair")
    print("⚙️ Fixed 3x leverage")
    print("🚀 Webhook ready for TradingView alerts")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
