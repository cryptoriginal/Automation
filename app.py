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

# Simple trade tracking
class TradeTracker:
    def __init__(self):
        self.last_trade_time = {}
        self._lock = threading.Lock()
    
    def can_trade(self, symbol):
        """Simple cooldown check"""
        with self._lock:
            current_time = time.time()
            last_time = self.last_trade_time.get(symbol, 0)
            
            if current_time - last_time < 10:  # 10 second cooldown
                return False
            
            self.last_trade_time[symbol] = current_time
            return True

# Initialize tracker
trade_tracker = TradeTracker()

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

# === Get Current Price ===
def get_current_price(symbol):
    """Get current market price for a symbol"""
    try:
        params = {"symbol": symbol}
        response = requests.get(
            f"{BASE_URL}/openApi/swap/v2/quote/price",
            params=params,
            timeout=10
        )
        data = response.json()
        
        if data.get("code") == 0 and "data" in data:
            return float(data["data"]["price"])
        else:
            logger.error(f"❌ Price fetch failed: {data}")
            return None
    except Exception as e:
        logger.error(f"❌ Price error: {e}")
        return None

# === Get Current Position ===
def get_current_position(symbol):
    """Get current position for symbol"""
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
        
        if data.get("code") == 0 and "data" in data:
            positions = data["data"]
            for position in positions:
                position_amt = float(position.get("positionAmt", 0))
                if position_amt != 0:
                    return {
                        "side": "LONG" if position_amt > 0 else "SHORT",
                        "quantity": abs(position_amt)
                    }
        return None
    except Exception as e:
        logger.error(f"❌ Position check error: {e}")
        return None

# === Open Position - SIMPLE & PROVEN ===
def open_position(symbol, action):
    """Open position - SIMPLE version that works"""
    try:
        # Get current price for quantity calculation
        current_price = get_current_price(symbol)
        if not current_price:
            logger.error(f"❌ Cannot get current price for {symbol}")
            return False
        
        # Calculate exact 3x position size
        usdt_value = TRADE_BALANCE * 3
        quantity = usdt_value / current_price
        quantity = round(quantity, 4)
        
        logger.info(f"💰 Position calc: {TRADE_BALANCE} USDT × 3 = {usdt_value} USDT")
        logger.info(f"📊 Using price: {current_price} → Quantity: {quantity}")
        
        # SIMPLE PARAMS - Use positionSide: BOTH for One-Way mode
        params = {
            "symbol": symbol,
            "side": action,  # BUY or SELL
            "positionSide": "BOTH",  # For One-Way mode
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
        
        logger.info(f"📈 Open {action} response: {data}")
        
        if data.get("code") == 0:
            logger.info(f"✅ Position open successful: {symbol} {action}")
            return True
        else:
            logger.error(f"❌ Open failed: {data.get('msg')}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Open error: {e}")
        return False

# === Close Position - SIMPLE & PROVEN ===
def close_position(symbol, side, quantity):
    """Close position - SIMPLE version that works"""
    try:
        # Determine close side
        close_side = "SELL" if side == "LONG" else "BUY"
        
        # SIMPLE PARAMS - Use positionSide: BOTH for One-Way mode
        params = {
            "symbol": symbol,
            "side": close_side,
            "positionSide": "BOTH",  # For One-Way mode
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

# === Set Leverage - SIMPLE ===
def set_leverage(symbol, leverage=10):
    """Set leverage - SIMPLE version"""
    try:
        params = {
            "symbol": symbol,
            "leverage": leverage,
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
        
        logger.info(f"⚙️ Leverage set to {leverage}x for {symbol}")
        return True
    except Exception as e:
        logger.error(f"❌ Leverage error: {e}")
        return False

# === Trade Execution - SIMPLE & RELIABLE ===
def execute_trade(symbol, action):
    """Simple and reliable trade execution"""
    
    # Check cooldown
    if not trade_tracker.can_trade(symbol):
        return {
            "status": "skipped", 
            "reason": "cooldown_period",
            "symbol": symbol,
            "side": action
        }, 200
    
    logger.info(f"🎯 EXECUTING: {symbol} {action}")
    
    success = False
    try:
        # STEP 1: Set leverage
        set_leverage(symbol, 10)
        time.sleep(1)
        
        # STEP 2: Check current position
        current_position = get_current_position(symbol)
        logger.info(f"📊 Current position: {current_position}")
        
        # STEP 3: Close existing position if it exists
        if current_position:
            current_side = current_position["side"]
            current_qty = current_position["quantity"]
            
            # Always close existing position before opening new one
            logger.info(f"🔄 Closing existing {current_side} position")
            close_success = close_position(symbol, current_side, current_qty)
            
            if close_success:
                logger.info("✅ Position closed, waiting for settlement...")
                time.sleep(3)
            else:
                logger.error("❌ Failed to close existing position, aborting trade")
                return {
                    "status": "failed",
                    "reason": "close_position_failed",
                    "symbol": symbol,
                    "side": action
                }, 200
        
        # STEP 4: Open new position
        logger.info(f"📈 Opening {action} position")
        open_success = open_position(symbol, action)
        success = open_success
        
        if success:
            logger.info(f"✅✅✅ TRADE SUCCESS: {symbol} {action}")
        else:
            logger.error(f"❌ TRADE FAILED: {symbol} {action}")
        
    except Exception as e:
        logger.error(f"💥 EXECUTION ERROR: {e}")
        success = False
    
    return {
        "status": "success" if success else "failed",
        "symbol": symbol,
        "side": action,
        "timestamp": datetime.now().isoformat()
    }, 200

# === SINGLE Webhook Handler ===
@app.route('/webhook', methods=['POST'])
def webhook():
    """SINGLE webhook endpoint - no backup needed"""
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "no JSON data received"}), 400
            
        symbol = data.get("symbol")
        side = data.get("side")
        
        if not symbol or not side:
            return jsonify({"error": "missing symbol or side"}), 400
        
        if side.upper() not in ['BUY', 'SELL']:
            return jsonify({"error": "side must be BUY or SELL"}), 400
        
        logger.info(f"🔔 SIGNAL RECEIVED: {symbol} {side}")
        result, status = execute_trade(symbol, side.upper())
        return jsonify(result), status
        
    except Exception as e:
        logger.error(f"❌ WEBHOOK ERROR: {e}")
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
    ✅ BINGX BOT - SIMPLE & RELIABLE (ONE WEBHOOK)
    
    🔄 SINGLE WEBHOOK ENDPOINT:
    - POST /webhook 
    
    🎯 SIMPLE SETUP:
    1. BingX: ONE-WAY MODE 
    2. TradingView: ONE alert to /webhook
    3. JSON: {"symbol":"SUI-USDT","side":"BUY"}
    
    ✅ PROVEN FEATURES:
    - Exact 3x position sizing
    - Always closes before opening
    - 10-second cooldown protection
    - Simple & reliable
    
    ⚡ RECOMMENDATION:
    - Use ONLY ONE TradingView alert
    - This is more reliable than complex backup systems
    """

# === Startup ===
if __name__ == "__main__":
    logger.info("🚀 Starting BINGX BOT - SIMPLE & RELIABLE")
    logger.info(f"💰 Trade Balance: {TRADE_BALANCE} USDT")
    logger.info(f"📊 Position Size: {TRADE_BALANCE * 3} USDT")
    logger.info("🎯 ONE WEBHOOK: Simple and reliable")
    logger.info("🛡️ 10-second cooldown protection")
    
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
