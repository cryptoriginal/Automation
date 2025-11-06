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

# Configure detailed logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- BingX Configuration ---
API_KEY = os.getenv("BINGX_API_KEY")
SECRET_KEY = os.getenv("BINGX_SECRET_KEY")
TRADE_BALANCE = float(os.getenv("TRADE_BALANCE_USDT", "50"))

BASE_URL = "https://open-api.bingx.com"

# Global variables for trade tracking
last_trade_time = 0
TRADE_COOLDOWN = 2  # seconds

# === BingX Signature ===
def bingx_signature(params):
    """Generate BingX signature"""
    query_string = '&'.join([f"{key}={value}" for key, value in sorted(params.items())])
    return hmac.new(
        SECRET_KEY.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

def bingx_headers():
    return {"X-BX-APIKEY": API_KEY, "Content-Type": "application/json"}

# === Fast Position Check ===
def get_position_fast(symbol):
    """Fast position check"""
    try:
        params = {"symbol": symbol, "timestamp": int(time.time() * 1000)}
        signature = bingx_signature(params)
        params["signature"] = signature
        
        response = requests.get(
            f"{BASE_URL}/openApi/swap/v2/user/positions",
            headers=bingx_headers(),
            params=params,
            timeout=5
        )
        data = response.json()
        
        if data.get("code") == 0 and "data" in data:
            for position in data["data"]:
                position_amt = float(position.get("positionAmt", 0))
                if position_amt != 0:
                    return "LONG" if position_amt > 0 else "SHORT"
        return "NONE"
    except Exception as e:
        logger.error(f"❌ Position check error: {e}")
        return "UNKNOWN"

# === Fast Close Position ===
def close_position_fast(symbol, side):
    """Fast position close"""
    try:
        close_side = "SELL" if side == "LONG" else "BUY"
        position_side = "LONG" if side == "LONG" else "SHORT"
        quantity = TRADE_BALANCE * 3
        
        params = {
            "symbol": symbol,
            "side": close_side,
            "positionSide": position_side,
            "type": "MARKET",
            "quantity": quantity,
            "timestamp": int(time.time() * 1000)
        }
        
        signature = bingx_signature(params)
        params["signature"] = signature
        
        response = requests.post(
            f"{BASE_URL}/openApi/swap/v2/trade/order",
            headers=bingx_headers(),
            json=params,
            timeout=10
        )
        data = response.json()
        
        logger.info(f"🔻 Close {side} response: {data}")
        return data.get("code") == 0
    except Exception as e:
        logger.error(f"❌ Close error: {e}")
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
        
        signature = bingx_signature(params)
        params["signature"] = signature
        
        response = requests.post(
            f"{BASE_URL}/openApi/swap/v2/trade/order",
            headers=bingx_headers(),
            json=params,
            timeout=10
        )
        data = response.json()
        
        logger.info(f"📈 Open {side} response: {data}")
        return data.get("code") == 0
    except Exception as e:
        logger.error(f"❌ Open error: {e}")
        return False

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
        
        signature_long = bingx_signature(params_long)
        params_long["signature"] = signature_long
        
        response_long = requests.post(
            f"{BASE_URL}/openApi/swap/v2/trade/leverage",
            headers=bingx_headers(),
            json=params_long,
            timeout=10
        )
        
        # Set for SHORT side
        params_short = {
            "symbol": symbol,
            "leverage": leverage,
            "side": "SHORT", 
            "timestamp": int(time.time() * 1000)
        }
        
        signature_short = bingx_signature(params_short)
        params_short["signature"] = signature_short
        
        response_short = requests.post(
            f"{BASE_URL}/openApi/swap/v2/trade/leverage",
            headers=bingx_headers(),
            json=params_short,
            timeout=10
        )
        
        logger.info(f"⚙️ Leverage set to {leverage}x for {symbol}")
        return True
    except Exception as e:
        logger.error(f"❌ Leverage error: {e}")
        return False

# === Execute Trade IMMEDIATELY ===
def execute_trade_immediately(symbol, action):
    """Execute trade immediately - no queue, no delays"""
    global last_trade_time
    
    current_time = time.time()
    
    # Check cooldown
    if current_time - last_trade_time < TRADE_COOLDOWN:
        logger.info(f"⏸️ Cooldown active, skipping {symbol} {action}")
        return True
    
    logger.info(f"🎯 EXECUTING: {symbol} {action}")
    
    try:
        # STEP 0: Set leverage
        set_leverage(symbol, 10)
        
        # STEP 1: Check current position
        current_position = get_position_fast(symbol)
        logger.info(f"📊 Current {symbol} position: {current_position}")
        
        # STEP 2: Close opposite position if needed
        if current_position != "NONE" and current_position != "UNKNOWN":
            if (action == "BUY" and current_position == "SHORT") or (action == "SELL" and current_position == "LONG"):
                logger.info(f"🔄 Closing {current_position} position")
                close_success = close_position_fast(symbol, current_position)
                if close_success:
                    time.sleep(1)  # Wait for close to process
        
        # STEP 3: Open new position
        logger.info(f"📈 Opening {action} position for {symbol}")
        open_success = open_position_fast(symbol, action)
        
        # Update last trade time
        last_trade_time = current_time
        
        if open_success:
            logger.info(f"✅✅✅ TRADE SUCCESS: {symbol} {action}")
        else:
            logger.error(f"❌ TRADE FAILED: {symbol} {action}")
        
        return open_success
        
    except Exception as e:
        logger.error(f"💥 EXECUTION ERROR: {e}")
        return False

# === Webhook Handler ===
def handle_webhook(symbol, side, endpoint_name):
    """Handle webhook request"""
    start_time = time.time()
    
    logger.info(f"🚀 {endpoint_name} WEBHOOK: {symbol} {side}")
    
    # Validate inputs
    if not symbol or not side:
        return {"error": "missing symbol or side"}, 400
    
    if side.upper() not in ['BUY', 'SELL']:
        return {"error": "side must be BUY or SELL"}, 400
    
    # Execute trade IMMEDIATELY in background thread
    thread = threading.Thread(
        target=execute_trade_immediately, 
        args=(symbol, side.upper()),
        daemon=True
    )
    thread.start()
    
    response_time = time.time() - start_time
    
    return {
        "status": "executing",
        "endpoint": endpoint_name,
        "symbol": symbol,
        "side": side,
        "response_time": f"{response_time:.2f}s",
        "timestamp": datetime.now().isoformat()
    }, 200

# === MULTIPLE WEBHOOK ENDPOINTS ===
@app.route('/webhook', methods=['POST'])
def webhook_primary():
    """Primary webhook endpoint"""
    try:
        data = request.get_json(force=True)
        result, status = handle_webhook(
            data.get("symbol"), 
            data.get("side"), 
            "PRIMARY"
        )
        return jsonify(result), status
    except Exception as e:
        logger.error(f"❌ PRIMARY WEBHOOK ERROR: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/backup', methods=['POST'])
def webhook_backup():
    """Backup webhook endpoint"""
    try:
        data = request.get_json(force=True)
        result, status = handle_webhook(
            data.get("symbol"), 
            data.get("side"), 
            "BACKUP"
        )
        return jsonify(result), status
    except Exception as e:
        logger.error(f"❌ BACKUP WEBHOOK ERROR: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/emergency', methods=['POST'])
def webhook_emergency():
    """Emergency webhook endpoint"""
    try:
        data = request.get_json(force=True)
        result, status = handle_webhook(
            data.get("symbol"), 
            data.get("side"), 
            "EMERGENCY"
        )
        return jsonify(result), status
    except Exception as e:
        logger.error(f"❌ EMERGENCY WEBHOOK ERROR: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/fallback', methods=['POST'])
def webhook_fallback():
    """Fallback webhook endpoint"""
    try:
        data = request.get_json(force=True)
        result, status = handle_webhook(
            data.get("symbol"), 
            data.get("side"), 
            "FALLBACK"
        )
        return jsonify(result), status
    except Exception as e:
        logger.error(f"❌ FALLBACK WEBHOOK ERROR: {e}")
        return jsonify({"error": str(e)}), 500

# === Status Endpoints ===
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "trade_balance": TRADE_BALANCE,
        "position_size": TRADE_BALANCE * 3
    })

@app.route('/position/<symbol>', methods=['GET'])
def check_position(symbol):
    position = get_position_fast(symbol)
    return jsonify({
        "symbol": symbol,
        "position": position,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/test/<symbol>/<side>', methods=['GET'])
def test_trade(symbol, side):
    if side.upper() not in ['BUY', 'SELL']:
        return jsonify({"error": "side must be BUY or SELL"}), 400
    
    success = execute_trade_immediately(symbol, side.upper())
    return jsonify({
        "status": "success" if success else "failed",
        "symbol": symbol,
        "side": side
    })

@app.route('/')
def home():
    return """
    ✅ ULTRA-RELIABLE BINGX BOT - IMMEDIATE EXECUTION
    
    🔄 WEBHOOK ENDPOINTS:
    - PRIMARY:   POST /webhook
    - BACKUP:    POST /backup
    - EMERGENCY: POST /emergency
    - FALLBACK:  POST /fallback
    
    🛡️ FEATURES:
    - Immediate execution (no queue delays)
    - 4x redundant webhooks
    - Cooldown protection
    - Exact 3x position sizing
    - Real-time logging
    """

# === Startup ===
if __name__ == "__main__":
    logger.info("🔷 Starting IMMEDIATE-EXECUTION BingX Bot")
    logger.info(f"💰 Trade Balance: {TRADE_BALANCE} USDT")
    logger.info(f"📊 Position Size: {TRADE_BALANCE * 3} USDT")
    logger.info("🛡️ 4x redundant webhook endpoints enabled")
    logger.info("⚡ Immediate execution (no queue delays)")
    
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
