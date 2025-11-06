import os
import time
import hmac
import hashlib
import json
import requests
from flask import Flask, request, jsonify
import threading
import logging
from datetime import datetime

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- BingX Configuration ---
API_KEY = os.getenv("BINGX_API_KEY")
SECRET_KEY = os.getenv("BINGX_SECRET_KEY")
TRADE_BALANCE = float(os.getenv("TRADE_BALANCE_USDT", "50"))

BASE_URL = "https://open-api.bingx.com"

# Track last trade to prevent duplicates
last_trade = {"symbol": None, "side": None, "timestamp": 0}
TRADE_COOLDOWN = 2  seconds

# === BingX Signature ===
def bingx_signature(params, secret_key):
    query_string = '&'.join([f"{key}={value}" for key, value in sorted(params.items())])
    signature = hmac.new(secret_key.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
    return signature

def bingx_headers():
    return {"X-BX-APIKEY": API_KEY, "Content-Type": "application/json"}

# === Fast Position Check ===
def get_current_position_fast(symbol):
    """Fast position check with timeout"""
    try:
        params = {"symbol": symbol, "timestamp": int(time.time() * 1000)}
        signature = bingx_signature(params, SECRET_KEY)
        params["signature"] = signature
        
        url = f"{BASE_URL}/openApi/swap/v2/user/positions"
        response = requests.get(url, headers=bingx_headers(), params=params, timeout=5)
        data = response.json()
        
        if data.get("code") == 0 and "data" in data:
            for position in data["data"]:
                position_amt = float(position.get("positionAmt", 0))
                if position_amt != 0:
                    return "LONG" if position_amt > 0 else "SHORT"
        return "NONE"
    except Exception as e:
        logger.error(f"Position check error: {e}")
        return "UNKNOWN"

# === Fast Close Position ===
def close_position_fast(symbol, side):
    """Fast position close"""
    try:
        close_side = "SELL" if side == "LONG" else "BUY"
        position_side = "LONG" if side == "LONG" else "SHORT"
        
        # Get position size quickly
        current_side = get_current_position_fast(symbol)
        if current_side != side:
            return True  # Already closed or no position
            
        # Use maximum available quantity
        quantity = TRADE_BALANCE * 3
        
        params = {
            "symbol": symbol,
            "side": close_side,
            "positionSide": position_side,
            "type": "MARKET",
            "quantity": quantity,
            "timestamp": int(time.time() * 1000)
        }
        
        signature = bingx_signature(params, SECRET_KEY)
        params["signature"] = signature
        
        url = f"{BASE_URL}/openApi/swap/v2/trade/order"
        response = requests.post(url, headers=bingx_headers(), json=params, timeout=10)
        data = response.json()
        
        logger.info(f"Close {side} for {symbol}: {data}")
        return data.get("code") == 0
    except Exception as e:
        logger.error(f"Close error: {e}")
        return False

# === Fast Open Position ===
def open_position_fast(symbol, side):
    """Fast position open"""
    try:
        position_side = "LONG" if side == "BUY" else "SHORT"
        quantity = TRADE_BALANCE * 3
        
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
        response = requests.post(url, headers=bingx_headers(), json=params, timeout=10)
        data = response.json()
        
        logger.info(f"Open {side} for {symbol}: {data}")
        return data.get("code") == 0
    except Exception as e:
        logger.error(f"Open error: {e}")
        return False

# === ULTRA-FAST Trade Execution ===
def execute_trade_ultrafast(symbol, action):
    """Ultra-fast trade execution - minimal delays"""
    current_time = time.time()
    
    # Check cooldown
    if (last_trade["symbol"] == symbol and 
        last_trade["side"] == action and 
        current_time - last_trade["timestamp"] < TRADE_COOLDOWN):
        logger.info(f"⏸️ Cooldown active for {symbol} {action}")
        return True
    
    logger.info(f"🎯 ULTRA-FAST: {action} for {symbol}")
    
    try:
        # STEP 1: Check current position (FAST)
        current_position = get_current_position_fast(symbol)
        logger.info(f"📊 Current {symbol}: {current_position}")
        
        # STEP 2: Close opposite position if needed (FAST)
        if current_position != "NONE" and current_position != "UNKNOWN":
            if (action == "BUY" and current_position == "SHORT") or (action == "SELL" and current_position == "LONG"):
                logger.info(f"🔄 Fast closing {current_position}")
                close_success = close_position_fast(symbol, current_position)
                if close_success:
                    time.sleep(1)  # Minimal wait
                # Continue even if close fails - try to open anyway
        
        # STEP 3: Open new position (FAST)
        open_success = open_position_fast(symbol, action)
        
        # Update last trade
        last_trade.update({
            "symbol": symbol, 
            "side": action, 
            "timestamp": current_time
        })
        
        if open_success:
            logger.info(f"✅✅✅ ULTRA-FAST EXECUTION SUCCESS: {symbol} {action}")
        else:
            logger.info(f"❌ ULTRA-FAST EXECUTION FAILED: {symbol} {action}")
            
        return open_success
        
    except Exception as e:
        logger.error(f"❌ ULTRA-FAST EXECUTION ERROR: {e}")
        return False

# === Webhook with Immediate Execution ===
@app.route('/webhook', methods=['POST'])
def webhook():
    """Immediate execution webhook - NO QUEUE"""
    start_time = time.time()
    
    try:
        data = request.get_json(force=True)
        symbol = data.get("symbol")
        side = data.get("side")
        
        logger.info(f"🚀 IMMEDIATE WEBHOOK: {symbol} {side} at {datetime.now()}")
        
        if not symbol or not side:
            return jsonify({"error": "missing symbol or side"}), 400
        
        if side.upper() not in ['BUY', 'SELL']:
            return jsonify({"error": "side must be BUY or SELL"}), 400
        
        # Execute IMMEDIATELY in background thread
        thread = threading.Thread(target=execute_trade_ultrafast, args=(symbol, side.upper()))
        thread.daemon = True
        thread.start()
        
        response_time = time.time() - start_time
        logger.info(f"⚡ Webhook processed in {response_time:.2f}s")
        
        return jsonify({
            "status": "executing",
            "symbol": symbol,
            "side": side,
            "response_time": f"{response_time:.2f}s",
            "timestamp": datetime.now().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"❌ WEBHOOK ERROR: {e}")
        return jsonify({"error": str(e)}), 500

# === Backup Webhook Endpoint ===
@app.route('/backup', methods=['POST'])
def backup_webhook():
    """Backup webhook endpoint"""
    return webhook()

# === Health Check ===
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "trade_balance": TRADE_BALANCE,
        "position_size": TRADE_BALANCE * 3
    })

@app.route('/')
def home():
    return """
    ✅ ULTRA-RELIABLE BingX Bot
    
    MAIN Webhook: POST /webhook
    BACKUP Webhook: POST /backup
    
    Features:
    - ⚡ Ultra-fast execution (< 3s total)
    - 🔄 Immediate processing (no queue)
    - 📊 Fast position checks
    - 🎯 Exact 3x position size
    """

if __name__ == "__main__":
    logger.info("🔷 Starting ULTRA-RELIABLE BingX Bot")
    logger.info(f"💰 Trade Balance: {TRADE_BALANCE} USDT")
    logger.info(f"📊 Position Size: {TRADE_BALANCE * 3} USDT")
    logger.info("⚡ Ultra-fast execution enabled")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
