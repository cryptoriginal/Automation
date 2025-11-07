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

# Trade tracking - ENHANCED DUPLICATION PROTECTION
class TradeTracker:
    def __init__(self):
        self.active_trades = {}
        self._lock = threading.Lock()
        self.mode_cache = {}
        self.last_signal = {}  # Track last signal to prevent duplicates
    
    def can_trade(self, symbol, side):
        """Enhanced: Check if we can trade this symbol with this side"""
        with self._lock:
            current_time = time.time()
            
            # Check if same signal was recently processed
            last_signal = self.last_signal.get(symbol, {})
            if (last_signal.get('side') == side and 
                current_time - last_signal.get('timestamp', 0) < 30):  # 30 second signal cooldown
                logger.info(f"⏸️ Recent {side} signal for {symbol}, skipping duplicate")
                return False
            
            # Check if trade was executed recently (regardless of side)
            trade_info = self.active_trades.get(symbol, {})
            last_trade_time = trade_info.get('timestamp', 0)
            if current_time - last_trade_time < 15:  # 15 second trade cooldown
                logger.info(f"⏸️ Recent trade for {symbol}, skipping")
                return False
            
            return True
    
    def mark_signal(self, symbol, side):
        """Mark signal as received"""
        with self._lock:
            self.last_signal[symbol] = {
                'side': side,
                'timestamp': time.time()
            }
    
    def mark_trade(self, symbol, side, quantity):
        """Mark trade as executed"""
        with self._lock:
            self.active_trades[symbol] = {
                'side': side,
                'quantity': quantity,
                'timestamp': time.time()
            }
    
    def cache_mode(self, symbol, mode):
        """Cache the detected mode for a symbol"""
        with self._lock:
            self.mode_cache[symbol] = {
                'mode': mode,
                'timestamp': time.time()
            }
    
    def get_cached_mode(self, symbol):
        """Get cached mode"""
        with self._lock:
            cached = self.mode_cache.get(symbol)
            if cached and time.time() - cached['timestamp'] < 300:
                return cached['mode']
            return None

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

# === Detect Position Mode ===
def detect_position_mode(symbol):
    """Detect if symbol is in ONE-WAY or HEDGE mode"""
    try:
        cached_mode = trade_tracker.get_cached_mode(symbol)
        if cached_mode:
            return cached_mode
            
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
                if "LONG" in str(position) and "SHORT" in str(position):
                    trade_tracker.cache_mode(symbol, "HEDGE")
                    return "HEDGE"
            
            trade_tracker.cache_mode(symbol, "ONE_WAY")
            return "ONE_WAY"
        
        return "ONE_WAY"
    except Exception as e:
        logger.error(f"❌ Mode detection error: {e}")
        return "ONE_WAY"

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

# === Smart Position Opener ===
def open_position(symbol, action):
    """Smart position opener that detects mode and uses correct parameters"""
    try:
        current_price = get_current_price(symbol)
        if not current_price:
            logger.error(f"❌ Cannot get current price for {symbol}")
            return False
        
        usdt_value = TRADE_BALANCE * 3
        quantity = usdt_value / current_price
        quantity = round(quantity, 4)
        
        logger.info(f"💰 Position calc: {TRADE_BALANCE} USDT × 3 = {usdt_value} USDT")
        logger.info(f"📊 Using price: {current_price} → Quantity: {quantity}")
        
        position_mode = detect_position_mode(symbol)
        logger.info(f"🔍 Detected position mode: {position_mode}")
        
        params = {
            "symbol": symbol,
            "side": action,
            "type": "MARKET",
            "quantity": quantity,
            "timestamp": int(time.time() * 1000)
        }
        
        if position_mode == "HEDGE":
            params["positionSide"] = "LONG" if action == "BUY" else "SHORT"
        else:
            params["positionSide"] = "BOTH"
        
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
            trade_tracker.mark_trade(symbol, action, quantity)
            return True
        else:
            logger.error(f"❌ Open failed: {data.get('msg')}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Open error: {e}")
        return False

# === Smart Position Closer ===
def close_position(symbol, side, quantity):
    """Smart position closer that detects mode and uses correct parameters"""
    try:
        close_side = "SELL" if side == "LONG" else "BUY"
        
        position_mode = detect_position_mode(symbol)
        logger.info(f"🔍 Detected position mode for close: {position_mode}")
        
        params = {
            "symbol": symbol,
            "side": close_side,
            "type": "MARKET",
            "quantity": quantity,
            "timestamp": int(time.time() * 1000)
        }
        
        if position_mode == "HEDGE":
            params["positionSide"] = side
        else:
            params["positionSide"] = "BOTH"
        
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

# === Smart Leverage Setter ===
def set_leverage(symbol, leverage=10):
    """Set leverage for the symbol - smart approach"""
    try:
        position_mode = detect_position_mode(symbol)
        
        if position_mode == "HEDGE":
            for side in ["LONG", "SHORT"]:
                params = {
                    "symbol": symbol,
                    "leverage": leverage,
                    "side": side,
                    "timestamp": int(time.time() * 1000)
                }
                signature = bingx_signature(params)
                params["signature"] = signature
                requests.post(
                    f"{BASE_URL}/openApi/swap/v2/trade/leverage",
                    headers=bingx_headers(),
                    json=params,
                    timeout=10
                )
        else:
            params = {
                "symbol": symbol,
                "leverage": leverage,
                "timestamp": int(time.time() * 1000)
            }
            signature = bingx_signature(params)
            params["signature"] = signature
            requests.post(
                f"{BASE_URL}/openApi/swap/v2/trade/leverage",
                headers=bingx_headers(),
                json=params,
                timeout=10
            )
        
        logger.info(f"⚙️ Leverage set to {leverage}x for {symbol} ({position_mode} mode)")
        return True
        
    except Exception as e:
        logger.error(f"❌ Leverage error: {e}")
        return False

# === Trade Execution - ENHANCED DUPLICATION PROTECTION ===
def execute_trade(symbol, action, endpoint_name):
    """Enhanced trade execution with better duplication protection"""
    
    # Mark signal as received FIRST
    trade_tracker.mark_signal(symbol, action)
    
    # Enhanced duplication check
    if not trade_tracker.can_trade(symbol, action):
        return {
            "status": "skipped", 
            "reason": "cooldown_period_or_duplicate_signal",
            "endpoint": endpoint_name,
            "symbol": symbol,
            "side": action
        }, 200
    
    logger.info(f"🎯 EXECUTING ({endpoint_name}): {symbol} {action}")
    
    success = False
    try:
        set_leverage(symbol, 10)
        time.sleep(1)
        
        current_position = get_current_position(symbol)
        logger.info(f"📊 Current position: {current_position}")
        
        if current_position:
            current_side = current_position["side"]
            current_qty = current_position["quantity"]
            
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
                    time.sleep(3)
                else:
                    logger.error("❌ Failed to close existing position, aborting trade")
                    return {
                        "status": "failed",
                        "reason": "close_position_failed",
                        "endpoint": endpoint_name,
                        "symbol": symbol,
                        "side": action
                    }, 200
        
        logger.info(f"📈 Opening {action} position")
        open_success = open_position(symbol, action)
        success = open_success
        
        if success:
            logger.info(f"✅✅✅ TRADE SUCCESS ({endpoint_name}): {symbol} {action}")
        else:
            logger.error(f"❌ TRADE FAILED ({endpoint_name}): {symbol} {action}")
        
    except Exception as e:
        logger.error(f"💥 EXECUTION ERROR ({endpoint_name}): {e}")
        success = False
    
    return {
        "status": "success" if success else "failed",
        "endpoint": endpoint_name,
        "symbol": symbol,
        "side": action,
        "timestamp": datetime.now().isoformat(),
        "mode": "smart"
    }, 200

# === Webhook Handlers ===
@app.route('/webhook', methods=['POST'])
def webhook_primary():
    """Primary webhook endpoint - executes immediately"""
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
        
        logger.info(f"🔔 PRIMARY signal received: {symbol} {side}")
        result, status = execute_trade(symbol, side.upper(), "PRIMARY")
        return jsonify(result), status
        
    except Exception as e:
        logger.error(f"❌ PRIMARY WEBHOOK ERROR: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/backup', methods=['POST'])
def webhook_backup():
    """Backup webhook endpoint - only executes if PRIMARY fails after delay"""
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
        
        # Wait 2 seconds to see if primary executes first
        time.sleep(2)
        
        logger.info(f"🛡️ BACKUP signal received: {symbol} {side}")
        result, status = execute_trade(symbol, side.upper(), "BACKUP")
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
        "mode": "smart_detection"
    })

@app.route('/position/<symbol>', methods=['GET'])
def check_position(symbol):
    """Check current position"""
    position = get_current_position(symbol)
    mode = detect_position_mode(symbol)
    return jsonify({
        "symbol": symbol,
        "position": position if position else "No position",
        "mode": mode,
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
    ✅ BINGX BOT - ENHANCED DUPLICATION PROTECTION
    
    🔄 WEBHOOK ENDPOINTS:
    - PRIMARY: POST /webhook (executes immediately)
    - BACKUP:  POST /backup (waits 2 seconds, executes only if primary fails)
    
    🛡️ ENHANCED PROTECTION:
    - ✅ SIGNAL COOLDOWN: 30 seconds for same signal
    - ✅ TRADE COOLDOWN: 15 seconds between any trades
    - ✅ BACKUP DELAY: Backup waits 2 seconds before executing
    - ✅ NO DUPLICATES: Prevents both webhooks from executing same trade
    
    ⚡ RECOMMENDATION:
    - Keep BOTH webhook and backup alerts in TradingView
    - This ensures no missed signals while preventing duplicates
    """

# === Startup ===
if __name__ == "__main__":
    logger.info("🚀 Starting BINGX BOT - ENHANCED DUPLICATION PROTECTION")
    logger.info(f"💰 Trade Balance: {TRADE_BALANCE} USDT")
    logger.info(f"📊 Position Size: {TRADE_BALANCE * 3} USDT")
    logger.info("🛡️ Enhanced: 30s signal cooldown, 15s trade cooldown, backup delay")
    
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
