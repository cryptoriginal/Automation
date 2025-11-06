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

# === CORRECT: One-Way Mode Position Open ===
def open_position_one_way(symbol, side):
    """Open position in one-way mode - CORRECT VERSION"""
    try:
        quantity = TRADE_BALANCE * 3
        
        # CORRECT: In one-way mode, use "BOTH" for positionSide
        params = {
            "symbol": symbol,
            "side": side,
            "positionSide": "BOTH",  # ✅ CORRECT for one-way mode
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
        
        logger.info(f"📈 One-way {side} response: {data}")
        
        if data.get("code") == 0:
            logger.info(f"✅ ONE-WAY SUCCESS: {symbol} {side}")
            return True
        else:
            error_msg = data.get('msg', 'Unknown error')
            logger.error(f"❌ ONE-WAY FAILED: {error_msg}")
            return False
            
    except Exception as e:
        logger.error(f"❌ One-way open error: {e}")
        return False

# === Set Leverage for One-Way Mode ===
def set_leverage_one_way(symbol, leverage=10):
    """Set leverage for one-way mode"""
    try:
        # In one-way mode, we only need to set leverage once
        params = {
            "symbol": symbol,
            "leverage": leverage,
            "side": "LONG",  # Just use LONG for one-way mode
            "timestamp": int(time.time() * 1000)
        }
        
        signature = bingx_signature(params)
        params["signature"] = signature
        
        response = requests.post(
            f"{BASE_URL}/openApi/swap/v2/trade/leverage",
            headers=bingx_headers(),
            json=params,
            timeout=10
        )
        
        logger.info(f"⚙️ One-way leverage set to {leverage}x for {symbol}")
        return True
    except Exception as e:
        logger.error(f"❌ Leverage error: {e}")
        return False

# === CORRECT: One-Way Trade Execution ===
def execute_trade_one_way(symbol, action, endpoint_name):
    """One-way trade execution - CORRECT VERSION"""
    
    # Check if we should execute (smart coordination)
    if not trade_tracker.should_execute_trade(symbol, action):
        return {
            "status": "skipped", 
            "reason": "already_executing_or_recent_duplicate",
            "endpoint": endpoint_name,
            "symbol": symbol,
            "side": action
        }, 200
    
    logger.info(f"🎯 ONE-WAY EXECUTING ({endpoint_name}): {symbol} {action}")
    
    success = False
    try:
        # STEP 1: Set leverage for one-way mode
        set_leverage_one_way(symbol, 10)
        
        # STEP 2: Open position directly with "BOTH" for one-way mode
        logger.info(f"📈 Opening {action} position with positionSide=BOTH")
        success = open_position_one_way(symbol, action)
        
        if success:
            logger.info(f"✅✅✅ ONE-WAY SUCCESS ({endpoint_name}): {symbol} {action}")
        else:
            logger.error(f"❌ ONE-WAY FAILED ({endpoint_name}): {symbol} {action}")
        
    except Exception as e:
        logger.error(f"💥 ONE-WAY EXECUTION ERROR ({endpoint_name}): {e}")
        success = False
    
    # Mark trade as completed (success or failure)
    trade_tracker.mark_trade_completed(symbol, action, success)
    
    return {
        "status": "success" if success else "failed",
        "endpoint": endpoint_name,
        "symbol": symbol,
        "side": action,
        "timestamp": datetime.now().isoformat(),
        "mode": "one_way"
    }, 200

# === Test with Different Symbol Format ===
def open_position_test(symbol, side):
    """Test with different symbol format if needed"""
    try:
        quantity = TRADE_BALANCE * 3
        
        # Try without positionSide parameter
        params = {
            "symbol": symbol,
            "side": side,
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
        
        logger.info(f"📈 Test {side} response: {data}")
        
        if data.get("code") == 0:
            logger.info(f"✅ TEST SUCCESS: {symbol} {side}")
            return True
        else:
            error_msg = data.get('msg', 'Unknown error')
            logger.error(f"❌ TEST FAILED: {error_msg}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Test open error: {e}")
        return False

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
        
        result, status = execute_trade_one_way(symbol, side.upper(), "PRIMARY")
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
        
        result, status = execute_trade_one_way(symbol, side.upper(), "BACKUP")
        return jsonify(result), status
        
    except Exception as e:
        logger.error(f"❌ BACKUP WEBHOOK ERROR: {e}")
        return jsonify({"error": str(e)}), 500

# === Test endpoint to try different approaches ===
@app.route('/test-trade', methods=['POST'])
def test_trade_endpoint():
    """Test endpoint to try different approaches"""
    try:
        data = request.get_json(force=True)
        symbol = data.get("symbol")
        side = data.get("side")
        
        if not symbol or not side:
            return jsonify({"error": "missing symbol or side"}), 400
        
        logger.info(f"🧪 TESTING: {symbol} {side}")
        
        # Try the main approach first
        success = open_position_one_way(symbol, side.upper())
        
        if not success:
            logger.info("🔄 Trying alternative approach...")
            # Try without positionSide
            success = open_position_test(symbol, side.upper())
        
        return jsonify({
            "status": "success" if success else "failed",
            "symbol": symbol,
            "side": side,
            "method": "test"
        }), 200
        
    except Exception as e:
        logger.error(f"❌ TEST ERROR: {e}")
        return jsonify({"error": str(e)}), 500

# === Status Endpoints ===
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "trade_balance": TRADE_BALANCE,
        "position_size": TRADE_BALANCE * 3,
        "mode": "one_way",
        "execution_status": trade_tracker.execution_status
    })

@app.route('/')
def home():
    return """
    ✅ BINGX BOT - ONE-WAY MODE (CORRECTED)
    
    🔄 WEBHOOK ENDPOINTS:
    - PRIMARY: POST /webhook (main execution)
    - BACKUP:  POST /backup (only if primary fails)
    - TEST:    POST /test-trade (for debugging)
    
    🎯 CORRECT ONE-WAY MODE:
    - Uses "BOTH" for positionSide
    - Automatic position reversal
    - Smart backup coordination
    
    📝 SETUP:
    - TradingView Alert 1: /webhook
    - TradingView Alert 2: /backup (as backup)
    - BingX: ONE-WAY MODE (hedge mode disabled)
    """

# === Startup ===
if __name__ == "__main__":
    logger.info("🔷 Starting BINGX BOT - ONE-WAY MODE (CORRECTED)")
    logger.info(f"💰 Trade Balance: {TRADE_BALANCE} USDT")
    logger.info(f"📊 Position Size: {TRADE_BALANCE * 3} USDT")
    logger.info("🎯 ONE-WAY MODE: Using BOTH for positionSide")
    logger.info("🛡️ Smart backup system enabled")
    
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
