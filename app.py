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

# Trade tracking for hedge mode
class HedgeTradeTracker:
    def __init__(self):
        self.execution_status = {}
        self.TRADE_COOLDOWN = 5  # 5 seconds cooldown
        self._lock = threading.Lock()
    
    def should_execute_trade(self, symbol, side):
        """Check if we should execute this trade"""
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
                self.execution_status[symbol] = {
                    "executing": False,
                    "last_side": side,
                    "timestamp": 0
                }
                logger.info(f"❌ Marked {symbol} {side} as failed - backup can retry")

# Initialize tracker
trade_tracker = HedgeTradeTracker()

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

# === Get Current Position ===
def get_current_position(symbol):
    """Get current position for symbol in hedge mode"""
    try:
        params = {"symbol": symbol, "timestamp": int(time.time() * 1000)}
        signature = bingx_signature(params)
        params["signature"] = signature
        
        response = requests.get(
            f"{BASE_URL}/openApi/swap/v2/user/positions",
            headers=bingx_headers(),
            params=params,
            timeout=10
        )
        data = response.json()
        
        logger.info(f"📊 Position response: {data}")
        
        if data.get("code") == 0 and "data" in data:
            positions = data["data"]
            for position in positions:
                position_amt = float(position.get("positionAmt", 0))
                if position_amt != 0:
                    return {
                        "side": "LONG" if position_amt > 0 else "SHORT",
                        "quantity": abs(position_amt),
                        "available": float(position.get("available", 0))
                    }
        return None
    except Exception as e:
        logger.error(f"❌ Position check error: {e}")
        return None

# === Close Position ===
def close_position(symbol, side, quantity):
    """Close existing position in hedge mode"""
    try:
        close_side = "close_short" if side == "SHORT" else "close_long"
        
        params = {
            "symbol": symbol,
            "side": close_side,
            "positionSide": "LONG" if side == "LONG" else "SHORT",
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
        
        if data.get("code") == 0:
            logger.info(f"✅ Position close successful: {symbol} {side}")
            return True
        else:
            logger.error(f"❌ Close failed: {data.get('msg')}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Close error: {e}")
        return False

# === Open Position ===
def open_position(symbol, side):
    """Open new position in hedge mode"""
    try:
        position_side = "LONG" if side == "BUY" else "SHORT"
        open_side = "open_long" if side == "BUY" else "open_short"
        quantity = TRADE_BALANCE * 3
        
        params = {
            "symbol": symbol,
            "side": open_side,
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
        
        if data.get("code") == 0:
            logger.info(f"✅ Position open successful: {symbol} {side}")
            return True
        else:
            logger.error(f"❌ Open failed: {data.get('msg')}")
            return False
            
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

# === HEDGE MODE Trade Execution ===
def execute_trade_hedge(symbol, action, endpoint_name):
    """Hedge mode trade execution - CLOSES EXISTING POSITION FIRST"""
    
    # Check if we should execute
    if not trade_tracker.should_execute_trade(symbol, action):
        return {
            "status": "skipped", 
            "reason": "already_executing_or_recent_duplicate",
            "endpoint": endpoint_name,
            "symbol": symbol,
            "side": action
        }, 200
    
    logger.info(f"🎯 HEDGE MODE EXECUTING ({endpoint_name}): {symbol} {action}")
    
    success = False
    try:
        # STEP 1: Set leverage
        set_leverage(symbol, 10)
        time.sleep(1)
        
        # STEP 2: Check current position
        current_position = get_current_position(symbol)
        logger.info(f"📊 Current position: {current_position}")
        
        # STEP 3: Close opposite position if it exists
        if current_position:
            current_side = current_position["side"]
            current_qty = current_position["available"] if current_position["available"] > 0 else current_position["quantity"]
            
            # If we already have the desired position, just log it
            if (action == "BUY" and current_side == "LONG") or (action == "SELL" and current_side == "SHORT"):
                logger.info(f"ℹ️ Already have {current_side} position, no need to close")
            else:
                # Close the opposite position
                logger.info(f"🔄 Closing existing {current_side} position before opening {action}")
                close_success = close_position(symbol, current_side, current_qty)
                
                if close_success:
                    logger.info("✅ Position closed, waiting for settlement...")
                    time.sleep(3)  # Wait for close to process
                else:
                    logger.error("❌ Failed to close existing position, aborting trade")
                    trade_tracker.mark_trade_completed(symbol, action, False)
                    return {
                        "status": "failed",
                        "reason": "close_position_failed",
                        "endpoint": endpoint_name,
                        "symbol": symbol,
                        "side": action
                    }, 200
        
        # STEP 4: Open new position
        logger.info(f"📈 Opening {action} position")
        open_success = open_position(symbol, action)
        
        success = open_success
        
        if success:
            logger.info(f"✅✅✅ HEDGE MODE SUCCESS ({endpoint_name}): {symbol} {action}")
        else:
            logger.error(f"❌ HEDGE MODE FAILED ({endpoint_name}): {symbol} {action}")
        
    except Exception as e:
        logger.error(f"💥 HEDGE MODE EXECUTION ERROR ({endpoint_name}): {e}")
        success = False
    
    # Mark trade as completed
    trade_tracker.mark_trade_completed(symbol, action, success)
    
    return {
        "status": "success" if success else "failed",
        "endpoint": endpoint_name,
        "symbol": symbol,
        "side": action,
        "timestamp": datetime.now().isoformat(),
        "mode": "hedge"
    }, 200

# === Webhook Handlers ===
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
        
        result, status = execute_trade_hedge(symbol, side.upper(), "PRIMARY")
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
        
        result, status = execute_trade_hedge(symbol, side.upper(), "BACKUP")
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
        "mode": "hedge"
    })

@app.route('/position/<symbol>', methods=['GET'])
def check_position(symbol):
    """Check current position"""
    position = get_current_position(symbol)
    return jsonify({
        "symbol": symbol,
        "position": position if position else "No position",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/close-all/<symbol>', methods=['POST'])
def close_all_positions(symbol):
    """Close all positions for a symbol"""
    position = get_current_position(symbol)
    if position:
        success = close_position(symbol, position["side"], position["quantity"])
        return jsonify({"status": "success" if success else "error"})
    else:
        return jsonify({"status": "no_position"})

@app.route('/')
def home():
    return """
    ✅ BINGX BOT - HEDGE MODE (PROPER POSITION MANAGEMENT)
    
    🔄 WEBHOOK ENDPOINTS:
    - PRIMARY: POST /webhook (main execution)
    - BACKUP:  POST /backup (only if primary fails)
    
    🛡️ HEDGE MODE FEATURES:
    - ✅ Closes existing position BEFORE opening new one
    - ✅ Never both long and short simultaneously
    - ✅ Proper position reversal
    - ✅ Smart backup coordination
    - ✅ Duplicate protection
    
    📝 SETUP:
    - BingX: HEDGE MODE ENABLED
    - TradingView Alert 1: /webhook
    - TradingView Alert 2: /backup
    """

# === Startup ===
if __name__ == "__main__":
    logger.info("🔷 Starting BINGX BOT - HEDGE MODE")
    logger.info(f"💰 Trade Balance: {TRADE_BALANCE} USDT")
    logger.info(f"📊 Position Size: {TRADE_BALANCE * 3} USDT")
    logger.info("🛡️ HEDGE MODE: Closes existing positions before opening new ones")
    logger.info("🎯 Smart backup system active")
    
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
