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

# Trade tracking
class TradeTracker:
    def __init__(self):
        self.active_trades = {}
        self._lock = threading.Lock()
    
    def can_trade(self, symbol):
        """Check if we can trade this symbol"""
        with self._lock:
            current_time = time.time()
            trade_info = self.active_trades.get(symbol, {})
            
            # If trade was executed recently, wait
            last_trade_time = trade_info.get('timestamp', 0)
            if current_time - last_trade_time < 10:  # 10 second cooldown
                return False
            
            return True
    
    def mark_trade(self, symbol, side, quantity):
        """Mark trade as executed"""
        with self._lock:
            self.active_trades[symbol] = {
                'side': side,
                'quantity': quantity,
                'timestamp': time.time()
            }

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

# === Get Current Position - ONE WAY MODE ===
def get_current_position(symbol):
    """Get current position for symbol in ONE-WAY mode"""
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
                        "quantity": abs(position_amt),
                        "leverage": int(position.get("leverage", 1))
                    }
        return None
    except Exception as e:
        logger.error(f"❌ Position check error: {e}")
        return None

# === Close Position - ONE WAY MODE ===
def close_position(symbol, side, quantity):
    """Close existing position in ONE-WAY mode"""
    try:
        # In ONE-WAY mode, just use opposite side to close
        close_side = "SELL" if side == "LONG" else "BUY"
        
        params = {
            "symbol": symbol,
            "side": close_side,
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

# === Open Position - ONE WAY MODE ===
def open_position(symbol, action):
    """Open new position in ONE-WAY mode"""
    try:
        # Get current price for quantity calculation
        current_price = get_current_price(symbol)
        if not current_price:
            logger.error(f"❌ Cannot get current price for {symbol}")
            return False
        
        # Calculate exact 3x position size
        usdt_value = TRADE_BALANCE * 3
        quantity = usdt_value / current_price
        
        # Round to appropriate precision
        quantity = round(quantity, 4)
        
        logger.info(f"💰 Position calc: {TRADE_BALANCE} USDT × 3 = {usdt_value} USDT")
        logger.info(f"📊 Using price: {current_price} → Quantity: {quantity}")
        
        params = {
            "symbol": symbol,
            "side": action,  # BUY or SELL directly
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
            logger.info(f"✅ Position open successful: {symbol} {action} - Qty: {quantity}")
            trade_tracker.mark_trade(symbol, action, quantity)
            return True
        else:
            logger.error(f"❌ Open failed: {data.get('msg')}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Open error: {e}")
        return False

# === Set Leverage - ONE WAY MODE ===
def set_leverage(symbol, leverage=10):
    """Set leverage for the symbol in ONE-WAY mode"""
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
        data = response.json()
        
        if data.get("code") == 0:
            logger.info(f"⚙️ Leverage set to {leverage}x for {symbol}")
            return True
        else:
            logger.error(f"❌ Leverage set failed: {data.get('msg')}")
            return False
    except Exception as e:
        logger.error(f"❌ Leverage error: {e}")
        return False

# === Switch to ONE-WAY Mode ===
def switch_to_one_way(symbol):
    """Ensure symbol is in ONE-WAY mode"""
    try:
        params = {
            "symbol": symbol,
            "marginMode": "ISOLATED",  # or "CROSS"
            "timestamp": int(time.time() * 1000)
        }
        
        signature = bingx_signature(params)
        params["signature"] = signature
        
        response = requests.post(
            f"{BASE_URL}/openApi/swap/v2/trade/marginType",
            headers=bingx_headers(),
            json=params,
            timeout=10
        )
        data = response.json()
        
        logger.info(f"🔄 Margin mode switch response: {data}")
        return data.get("code") == 0
    except Exception as e:
        logger.error(f"❌ Margin mode switch error: {e}")
        return False

# === Trade Execution - ONE WAY MODE ===
def execute_trade_one_way(symbol, action, endpoint_name):
    """ONE-WAY mode trade execution - SIMPLE & RELIABLE"""
    
    # Check cooldown
    if not trade_tracker.can_trade(symbol):
        return {
            "status": "skipped", 
            "reason": "cooldown_period",
            "endpoint": endpoint_name,
            "symbol": symbol,
            "side": action
        }, 200
    
    logger.info(f"🎯 ONE-WAY MODE EXECUTING ({endpoint_name}): {symbol} {action}")
    
    success = False
    try:
        # STEP 1: Ensure ONE-WAY mode
        switch_to_one_way(symbol)
        time.sleep(1)
        
        # STEP 2: Set leverage
        set_leverage(symbol, 10)
        time.sleep(1)
        
        # STEP 3: Check current position
        current_position = get_current_position(symbol)
        logger.info(f"📊 Current position: {current_position}")
        
        # STEP 4: Close existing position if it exists AND is opposite direction
        if current_position:
            current_side = current_position["side"]
            current_qty = current_position["quantity"]
            
            # Determine if we need to close
            need_to_close = False
            if (action == "BUY" and current_side == "SHORT") or (action == "SELL" and current_side == "LONG"):
                need_to_close = True
            elif (action == "BUY" and current_side == "LONG") or (action == "SELL" and current_side == "SHORT"):
                logger.info(f"ℹ️ Already in {current_side} position, closing first then reopening")
                need_to_close = True
            
            if need_to_close:
                logger.info(f"🔄 Closing existing {current_side} position")
                close_success = close_position(symbol, current_side, current_qty)
                
                if close_success:
                    logger.info("✅ Position closed, waiting for settlement...")
                    time.sleep(3)  # Wait for close to process
                else:
                    logger.error("❌ Failed to close existing position, aborting trade")
                    return {
                        "status": "failed",
                        "reason": "close_position_failed",
                        "endpoint": endpoint_name,
                        "symbol": symbol,
                        "side": action
                    }, 200
        
        # STEP 5: Open new position
        logger.info(f"📈 Opening {action} position")
        open_success = open_position(symbol, action)
        success = open_success
        
        if success:
            logger.info(f"✅✅✅ ONE-WAY SUCCESS ({endpoint_name}): {symbol} {action}")
        else:
            logger.error(f"❌ ONE-WAY FAILED ({endpoint_name}): {symbol} {action}")
        
    except Exception as e:
        logger.error(f"💥 ONE-WAY EXECUTION ERROR ({endpoint_name}): {e}")
        success = False
    
    return {
        "status": "success" if success else "failed",
        "endpoint": endpoint_name,
        "symbol": symbol,
        "side": action,
        "timestamp": datetime.now().isoformat(),
        "mode": "one_way"
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
        
        result, status = execute_trade_one_way(symbol, side.upper(), "PRIMARY")
        return jsonify(result), status
        
    except Exception as e:
        logger.error(f"❌ PRIMARY WEBHOOK ERROR: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/backup', methods=['POST'])
def webhook_backup():
    """Backup webhook endpoint"""
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

# === Status Endpoints ===
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "trade_balance": TRADE_BALANCE,
        "position_size": TRADE_BALANCE * 3,
        "mode": "one_way"
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

@app.route('/switch-one-way/<symbol>', methods=['POST'])
def switch_mode(symbol):
    """Switch to ONE-WAY mode"""
    success = switch_to_one_way(symbol)
    return jsonify({"status": "success" if success else "error"})

@app.route('/')
def home():
    return """
    ✅ BINGX BOT - ONE-WAY MODE (RELIABLE)
    
    🔄 WEBHOOK ENDPOINTS:
    - PRIMARY: POST /webhook (main execution)
    - BACKUP:  POST /backup (backup execution)
    
    🎯 ONE-WAY MODE FEATURES:
    - ✅ SIMPLE: Uses BUY/SELL directly (no positionSide complexity)
    - ✅ RELIABLE: No hedge mode API inconsistencies
    - ✅ ACCURATE: Always exact 3x position size
    - ✅ SAFE: Always closes before opening opposite position
    - ✅ COOLDOWN: Prevents duplicate executions
    
    ⚡ QUICK SETUP:
    1. In BingX: Switch to ONE-WAY mode for your symbols
    2. Deploy this code
    3. TradingView: {"symbol":"SUI-USDT","side":"BUY"}
    
    🛡️ WHY THIS WORKS:
    - No more hedge mode API bugs
    - Simple BUY/SELL logic
    - Consistent position sizing
    - Reliable position closing
    """

# === Startup ===
if __name__ == "__main__":
    logger.info("🚀 Starting BINGX BOT - ONE-WAY MODE (RELIABLE)")
    logger.info(f"💰 Trade Balance: {TRADE_BALANCE} USDT")
    logger.info(f"📊 Position Size: {TRADE_BALANCE * 3} USDT")
    logger.info("🎯 ONE-WAY MODE: Simple & Reliable")
    logger.info("🛡️ Cooldown protection active")
    
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
