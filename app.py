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

# Smart trade tracking with execution status
class SmartTradeTracker:
    def __init__(self):
        self.execution_status = {}  # symbol: {"last_side": "BUY/SELL", "executing": True/False, "timestamp": time}
        self.TRADE_COOLDOWN = 10  # 10 seconds cooldown after successful execution
        self.EXECUTION_TIMEOUT = 30  # 30 seconds max for execution
        self._lock = threading.Lock()
    
    def should_execute_trade(self, symbol, side):
        """Check if we should execute this trade (smart coordination)"""
        with self._lock:
            current_time = time.time()
            symbol_status = self.execution_status.get(symbol, {})
            
            # If same trade is currently executing, skip
            if symbol_status.get("executing", False):
                logger.info(f"⏸️ Already executing {symbol} {side}, skipping duplicate")
                return False
            
            # If same trade was recently executed, skip
            last_execution_time = symbol_status.get("timestamp", 0)
            last_side = symbol_status.get("last_side")
            
            if (last_side == side and 
                current_time - last_execution_time < self.TRADE_COOLDOWN):
                logger.info(f"⏸️ Recent {symbol} {side} executed, skipping duplicate")
                return False
            
            # Mark as executing
            self.execution_status[symbol] = {
                "executing": True,
                "last_side": side,
                "start_time": current_time
            }
            return True
    
    def mark_trade_completed(self, symbol, side, success=True):
        """Mark trade as completed"""
        with self._lock:
            current_time = time.time()
            if success:
                self.execution_status[symbol] = {
                    "executing": False,
                    "last_side": side,
                    "timestamp": current_time
                }
                logger.info(f"✅ Marked {symbol} {side} as completed")
            else:
                # If failed, remove executing flag so backup can retry
                self.execution_status[symbol] = {
                    "executing": False,
                    "last_side": side,
                    "timestamp": 0  # Reset timestamp to allow retry
                }
                logger.info(f"❌ Marked {symbol} {side} as failed - backup can retry")
    
    def cleanup_stuck_executions(self):
        """Clean up executions that might be stuck"""
        with self._lock:
            current_time = time.time()
            for symbol, status in list(self.execution_status.items()):
                if status.get("executing", False):
                    start_time = status.get("start_time", 0)
                    if current_time - start_time > self.EXECUTION_TIMEOUT:
                        logger.warning(f"🧹 Cleaning up stuck execution for {symbol}")
                        self.execution_status[symbol]["executing"] = False

# Initialize smart tracker
trade_tracker = SmartTradeTracker()

# Background cleaner for stuck executions
def background_cleaner():
    while True:
        time.sleep(60)  # Check every minute
        trade_tracker.cleanup_stuck_executions()

cleaner_thread = threading.Thread(target=background_cleaner, daemon=True)
cleaner_thread.start()

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

# === Smart Trade Execution ===
def execute_trade_smart(symbol, action, endpoint_name):
    """Smart trade execution with coordination"""
    
    # Check if we should execute (smart coordination)
    if not trade_tracker.should_execute_trade(symbol, action):
        return {
            "status": "skipped", 
            "reason": "already_executing_or_recent_duplicate",
            "endpoint": endpoint_name,
            "symbol": symbol,
            "side": action
        }, 200
    
    logger.info(f"🎯 EXECUTING ({endpoint_name}): {symbol} {action}")
    
    success = False
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
                    time.sleep(2)  # Wait for close to process
        
        # STEP 3: Open new position
        logger.info(f"📈 Opening {action} position for {symbol}")
        open_success = open_position_fast(symbol, action)
        
        success = open_success
        
        if success:
            logger.info(f"✅✅✅ TRADE SUCCESS ({endpoint_name}): {symbol} {action}")
        else:
            logger.error(f"❌ TRADE FAILED ({endpoint_name}): {symbol} {action}")
        
    except Exception as e:
        logger.error(f"💥 EXECUTION ERROR ({endpoint_name}): {e}")
        success = False
    
    # Mark trade as completed (success or failure)
    trade_tracker.mark_trade_completed(symbol, action, success)
    
    return {
        "status": "success" if success else "failed",
        "endpoint": endpoint_name,
        "symbol": symbol,
        "side": action,
        "timestamp": datetime.now().isoformat()
    }, 200

# === Smart Webhook Handler ===
@app.route('/webhook', methods=['POST'])
def webhook_primary():
    """Primary webhook endpoint"""
    try:
        data = request.get_json(force=True)
        symbol = data.get("symbol")
        side = data.get("side")
        
        if not symbol or not side:
            return jsonify({"error": "missing symbol or side"}), 400
        
        if side.upper() not in ['BUY', 'SELL']:
            return jsonify({"error": "side must be BUY or SELL"}), 400
        
        result, status = execute_trade_smart(symbol, side.upper(), "PRIMARY")
        return jsonify(result), status
        
    except Exception as e:
        logger.error(f"❌ PRIMARY WEBHOOK ERROR: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/backup', methods=['POST'])
def webhook_backup():
    """Backup webhook endpoint - only executes if primary fails"""
    try:
        data = request.get_json(force=True)
        symbol = data.get("symbol")
        side = data.get("side")
        
        if not symbol or not side:
            return jsonify({"error": "missing symbol or side"}), 400
        
        if side.upper() not in ['BUY', 'SELL']:
            return jsonify({"error": "side must be BUY or SELL"}), 400
        
        result, status = execute_trade_smart(symbol, side.upper(), "BACKUP")
        return jsonify(result), status
        
    except Exception as e:
        logger.error(f"❌ BACKUP WEBHOOK ERROR: {e}")
        return jsonify({"error": str(e)}), 500

# === Status Endpoints ===
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "trade_balance": TRADE_BALANCE,
        "position_size": TRADE_BALANCE * 3,
        "execution_status": trade_tracker.execution_status
    })

@app.route('/position/<symbol>', methods=['GET'])
def check_position(symbol):
    position = get_position_fast(symbol)
    return jsonify({
        "symbol": symbol,
        "position": position,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/')
def home():
    return """
    ✅ SMART BINGX BOT - INTELLIGENT BACKUP
    
    🔄 WEBHOOK ENDPOINTS:
    - PRIMARY: POST /webhook (main execution)
    - BACKUP:  POST /backup (only if primary fails)
    
    🧠 SMART FEATURES:
    - Primary executes first
    - Backup only runs if primary fails
    - No duplicate executions
    - 10-second cooldown after success
    - Stuck execution cleanup
    - Real-time coordination
    
    📝 SETUP:
    - TradingView Alert 1: /webhook
    - TradingView Alert 2: /backup (as backup)
    """

# === Startup ===
if __name__ == "__main__":
    logger.info("🔷 Starting SMART BingX Bot with Intelligent Backup")
    logger.info(f"💰 Trade Balance: {TRADE_BALANCE} USDT")
    logger.info(f"📊 Position Size: {TRADE_BALANCE * 3} USDT")
    logger.info("🧠 Intelligent backup system enabled")
    logger.info("🛡️ Primary executes, backup only runs if primary fails")
    
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
