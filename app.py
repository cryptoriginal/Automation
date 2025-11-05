import os
import time
import hmac
import hashlib
import json
import requests
from flask import Flask, request, jsonify
import threading
from queue import Queue

app = Flask(__name__)

# --- BingX Configuration ---
API_KEY = os.getenv("BINGX_API_KEY")
SECRET_KEY = os.getenv("BINGX_SECRET_KEY")
TRADE_BALANCE = float(os.getenv("TRADE_BALANCE_USDT", "50"))

BASE_URL = "https://open-api.bingx.com"

# Trade queue to prevent overlapping executions
trade_queue = Queue()
current_processing = False

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
def set_leverage(symbol, leverage=10):
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

# === Calculate Position Size - EXACT 3x ===
def calculate_position_size():
    """Calculate position size - EXACTLY 3x of TRADE_BALANCE"""
    position_size = TRADE_BALANCE * 3
    print(f"💰 Trade Balance: {TRADE_BALANCE} USDT")
    print(f"📊 Position Size (3x): {position_size} USDT")
    return round(position_size, 3)

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
    
    # STEP 0: Set leverage to 10x for sufficient margin
    print("⚙️ Setting leverage to 10x...")
    set_leverage(symbol, 10)
    time.sleep(2)
    
    # STEP 1: Calculate position size - EXACTLY 3x of TRADE_BALANCE
    trade_size = calculate_position_size()
    
    if trade_size <= 5:
        print("❌ Position size too small")
        return False
    
    print(f"📊 Final Position Size: {trade_size} USDT")
    
    # STEP 2: Get current position
    current_position = get_current_position(symbol)
    print(f"📊 Current position: {current_position}")
    
    # STEP 3: Close existing position if it exists
    if current_position:
        print(f"🔄 Closing existing {current_position['side']} position first...")
        if close_position(symbol, current_position["side"], current_position["quantity"]):
            print("✅ Position closed, waiting for settlement...")
            time.sleep(3)
        else:
            print("❌ Failed to close existing position, aborting trade")
            return False
    else:
        print("✅ No existing position to close")
    
    # STEP 4: Open new position
    success = False
    if action.upper() == "BUY":
        print("📈 Opening LONG position...")
        success = open_position(symbol, "BUY", trade_size)
    elif action.upper() == "SELL":
        print("📉 Opening SHORT position...")
        success = open_position(symbol, "SELL", trade_size)
    
    if success:
        print("✅✅✅ TRADE EXECUTED SUCCESSFULLY!")
    else:
        print("❌ Trade failed")
    
    print("=" * 60)
    return success

# === Process Trade Queue ===
def process_trade_queue():
    """Process trades from the queue one by one"""
    global current_processing
    
    while not trade_queue.empty():
        if current_processing:
            print("⏳ Another trade is currently processing, waiting...")
            time.sleep(2)
            continue
            
        current_processing = True
        trade_data = trade_queue.get()
        
        try:
            symbol = trade_data['symbol']
            side = trade_data['side']
            print(f"🔄 Processing queued trade: {symbol} - {side}")
            execute_trade(symbol, side)
        except Exception as e:
            print(f"❌ Error processing queued trade: {e}")
        finally:
            current_processing = False
            trade_queue.task_done()
            time.sleep(1)  # Small delay between queued trades

# === Webhook Endpoint with Queue ===
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
        
        # Add trade to queue and process immediately
        trade_queue.put({'symbol': symbol, 'side': side.upper()})
        
        # Start processing in background thread
        thread = threading.Thread(target=process_trade_queue)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            "status": "queued", 
            "message": "Trade added to queue",
            "symbol": symbol,
            "side": side,
            "position_size": TRADE_BALANCE * 3
        }), 200
        
    except Exception as e:
        print(f"❌ Webhook Error: {e}")
        return jsonify({"error": str(e)}), 500

# === Direct Trade Endpoint (Bypass queue) ===
@app.route('/trade', methods=['POST'])
def direct_trade():
    """Direct trade endpoint for immediate execution"""
    try:
        print("🎯 Direct Trade Request!")
        data = request.get_json(force=True)
        print(f"📩 Received payload: {data}")
        
        symbol = data.get("symbol")
        side = data.get("side")
        
        if not symbol or not side:
            return jsonify({"error": "missing symbol or side"}), 400
        
        if side.upper() not in ['BUY', 'SELL']:
            return jsonify({"error": "side must be 'BUY' or 'SELL'"}), 400
        
        # Execute trade immediately
        success = execute_trade(symbol, side.upper())
        
        return jsonify({
            "status": "executed" if success else "failed",
            "symbol": symbol,
            "side": side,
            "position_size": TRADE_BALANCE * 3
        }), 200
        
    except Exception as e:
        print(f"❌ Direct Trade Error: {e}")
        return jsonify({"error": str(e)}), 500

# === Utility Endpoints ===
@app.route('/')
def home():
    return """
    ✅ BingX Trading Bot - RELIABLE VERSION
    
    Usage:
    - Send POST to /webhook with JSON (Queued):
      {"symbol": "SOL-USDT", "side": "BUY"}
    
    - Send POST to /trade with JSON (Immediate):
      {"symbol": "SUI-USDT", "side": "SELL"}
    
    Features:
    - 🎯 EXACT 3x position size of TRADE_BALANCE
    - ⚡ Trade queue to prevent missed signals
    - 🔄 Processes one trade at a time
    - ✅ Works with ALL trading pairs
    """

@app.route('/position/<symbol>', methods=['GET'])
def check_position(symbol):
    """Check current position for ANY symbol"""
    position = get_current_position(symbol)
    return jsonify({
        "symbol": symbol,
        "position": position if position else "No position",
        "trade_balance": TRADE_BALANCE,
        "position_size": TRADE_BALANCE * 3
    })

@app.route('/queue', methods=['GET'])
def check_queue():
    """Check trade queue status"""
    return jsonify({
        "queue_size": trade_queue.qsize(),
        "currently_processing": current_processing,
        "trade_balance": TRADE_BALANCE,
        "position_size": TRADE_BALANCE * 3
    })

@app.route('/close/<symbol>', methods=['POST'])
def close_position_manual(symbol):
    """Manually close position for ANY symbol"""
    position = get_current_position(symbol)
    if position:
        success = close_position(symbol, position["side"], position["quantity"])
        return jsonify({"status": "success" if success else "error"})
    else:
        return jsonify({"status": "no_position"})

if __name__ == "__main__":
    print("🔷 Starting BingX Trading Bot - RELIABLE VERSION")
    print(f"💰 Trade Balance: {TRADE_BALANCE} USDT")
    print(f"📊 Position Size (EXACT 3x): {TRADE_BALANCE * 3} USDT")
    print("🎯 Supports ALL trading pairs")
    print("⚡ Trade queue enabled to prevent missed signals")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
