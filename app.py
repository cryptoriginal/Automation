import os
import time
import hmac
import hashlib
import requests
import json
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

# --- Bitget Configuration ---
API_KEY = os.getenv("BITGET_API_KEY")
API_SECRET = os.getenv("BITGET_API_SECRET")
API_PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE")
TRADE_BALANCE = float(os.getenv("TRADE_BALANCE_USDT", "20"))

BASE_URL = "https://api.bitget.com"

# Trade tracking
class TradeTracker:
    def __init__(self):
        self.active_trades = {}
        self._lock = threading.Lock()
    
    def can_trade(self, symbol):
        """Simple cooldown check"""
        with self._lock:
            current_time = time.time()
            last_time = self.active_trades.get(symbol, 0)
            
            if current_time - last_time < 8:  # 8 second cooldown
                return False
            
            self.active_trades[symbol] = current_time
            return True

# Initialize tracker
trade_tracker = TradeTracker()

# === Bitget Signature ===
def bitget_signature(timestamp, method, request_path, body):
    """Generate Bitget signature"""
    if body is None:
        body = ""
    message = str(timestamp) + method + request_path + body
    mac = hmac.new(
        bytes(API_SECRET, encoding='utf8'), 
        bytes(message, encoding='utf-8'), 
        digestmod='sha256'
    )
    return mac.hexdigest()

def bitget_headers(method, request_path, body=""):
    """Generate Bitget headers"""
    timestamp = str(int(time.time() * 1000))
    signature = bitget_signature(timestamp, method, request_path, body)
    
    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json"
    }

# === Get Current Price ===
def get_current_price(symbol):
    """Get current market price - FIXED"""
    try:
        # Use correct symbol format for price API
        response = requests.get(
            f"{BASE_URL}/api/mix/v1/market/ticker",
            params={"symbol": symbol},
            timeout=10
        )
        data = response.json()
        
        if data.get("code") == "00000":
            price = float(data["data"]["last"])
            logger.info(f"✅ Price for {symbol}: ${price}")
            return price
        else:
            logger.error(f"❌ Price fetch failed: {data}")
            return None
    except Exception as e:
        logger.error(f"❌ Price error: {e}")
        return None

# === Get Current Position ===
def get_current_position(symbol):
    """Get current position - FIXED"""
    try:
        request_path = "/api/mix/v1/position/singlePosition"
        params = {"symbol": symbol, "productType": "umcbl"}
        
        headers = bitget_headers("GET", request_path)
        response = requests.get(
            f"{BASE_URL}{request_path}",
            params=params,
            headers=headers,
            timeout=10
        )
        data = response.json()
        
        logger.info(f"📊 Position response: {data}")
        
        if data.get("code") == "00000" and data.get("data"):
            position = data["data"]
            total_amount = float(position.get("total", 0))
            
            if total_amount > 0:
                return {
                    "side": position.get("holdSide", "long"),
                    "quantity": total_amount,
                    "available": float(position.get("available", 0))
                }
        return None
        
    except Exception as e:
        logger.error(f"❌ Position error: {e}")
        return None

# === Set Leverage ===
def set_leverage(symbol, leverage=10):
    """Set leverage for the symbol - FIXED"""
    try:
        request_path = "/api/mix/v1/account/setLeverage"
        
        leverage_data = {
            "symbol": symbol,
            "productType": "umcbl",
            "marginCoin": "USDT",
            "leverage": str(leverage)
        }
        
        body = json.dumps(leverage_data)
        headers = bitget_headers("POST", request_path, body)
        
        response = requests.post(
            f"{BASE_URL}{request_path}",
            json=leverage_data,
            headers=headers,
            timeout=10
        )
        data = response.json()
        
        if data.get("code") == "00000":
            logger.info(f"⚙️ Leverage set to {leverage}x for {symbol}")
            return True
        else:
            logger.warning(f"⚠️ Leverage set: {data.get('msg')}")
            # Continue anyway - leverage might already be set
            return True
            
    except Exception as e:
        logger.error(f"❌ Leverage error: {e}")
        return True  # Continue anyway

# === Calculate Position Size in USDT ===
def calculate_position_size(symbol):
    """Calculate position size based on USDT value"""
    try:
        # Get current price
        current_price = get_current_price(symbol)
        if not current_price:
            logger.error(f"❌ Cannot get current price for {symbol}")
            return None
        
        # Calculate USDT value (3x trade balance)
        usdt_value = TRADE_BALANCE * 3
        
        # Calculate quantity based on price
        quantity = usdt_value / current_price
        
        # Apply minimum quantity rules
        min_quantity = 1.0  # Minimum 1 token
        if quantity < min_quantity:
            quantity = min_quantity
            logger.info(f"📏 Adjusted to minimum quantity: {quantity}")
        
        quantity = round(quantity, 3)  # Bitget precision
        
        logger.info(f"💰 USDT Value: {TRADE_BALANCE} × 3 = {usdt_value} USDT")
        logger.info(f"📊 Price: ${current_price} → Quantity: {quantity}")
        
        return quantity
        
    except Exception as e:
        logger.error(f"❌ Quantity calculation error: {e}")
        return None

# === Close Position ===
def close_position(symbol, side, quantity):
    """Close existing position - FIXED"""
    try:
        request_path = "/api/mix/v1/order/placeOrder"
        
        # For ONE-WAY mode, use simple buy/sell to close
        close_side = "sell" if side == "long" else "buy"
        
        order_data = {
            "symbol": symbol,
            "productType": "umcbl",
            "marginMode": "crossed",
            "marginCoin": "USDT",
            "size": str(quantity),
            "side": close_side,
            "orderType": "market",
            "tradeSide": "close"
        }
        
        body = json.dumps(order_data)
        headers = bitget_headers("POST", request_path, body)
        
        response = requests.post(
            f"{BASE_URL}{request_path}",
            json=order_data,
            headers=headers,
            timeout=15
        )
        data = response.json()
        
        logger.info(f"🔻 Close {side} response: {data}")
        
        if data.get("code") == "00000":
            logger.info(f"✅ Position close successful: {symbol} {side}")
            return True
        else:
            logger.error(f"❌ Close failed: {data.get('msg', 'Unknown error')}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Close error: {e}")
        return False

# === Open Position ===
def open_position(symbol, action):
    """Open new position in ONE-WAY mode - FIXED"""
    try:
        # Calculate position size based on USDT value
        quantity = calculate_position_size(symbol)
        if not quantity:
            logger.error(f"❌ Cannot calculate position size for {symbol}")
            return False
        
        request_path = "/api/mix/v1/order/placeOrder"
        
        # For ONE-WAY mode, use simple buy/sell
        bitget_side = "buy" if action == "BUY" else "sell"
        
        order_data = {
            "symbol": symbol,
            "productType": "umcbl",
            "marginMode": "crossed",
            "marginCoin": "USDT",
            "size": str(quantity),
            "side": bitget_side,
            "orderType": "market",
            "tradeSide": "open"
        }
        
        body = json.dumps(order_data)
        headers = bitget_headers("POST", request_path, body)
        
        response = requests.post(
            f"{BASE_URL}{request_path}",
            json=order_data,
            headers=headers,
            timeout=15
        )
        data = response.json()
        
        logger.info(f"📈 Open {action} response: {data}")
        
        if data.get("code") == "00000":
            logger.info(f"✅ Position open successful: {symbol} {action}")
            return True
        else:
            logger.error(f"❌ Open failed: {data.get('msg', 'Unknown error')}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Open error: {e}")
        return False

# === Trade Execution ===
def execute_trade(symbol, action, endpoint_name):
    """Main trade execution logic"""
    
    # Check cooldown
    if not trade_tracker.can_trade(symbol):
        return {
            "status": "skipped", 
            "reason": "cooldown_period",
            "endpoint": endpoint_name,
            "symbol": symbol,
            "side": action
        }, 200
    
    logger.info(f"🎯 EXECUTING ({endpoint_name}): {symbol} {action}")
    
    success = False
    try:
        # STEP 1: Set leverage (non-critical)
        set_leverage(symbol, 10)
        time.sleep(1)
        
        # STEP 2: Check current position
        current_position = get_current_position(symbol)
        logger.info(f"📊 Current position: {current_position}")
        
        # STEP 3: Close existing position if it exists
        if current_position:
            current_side = current_position["side"]
            current_qty = current_position["available"] if current_position["available"] > 0 else current_position["quantity"]
            
            logger.info(f"🔄 Closing existing {current_side} position")
            close_success = close_position(symbol, current_side, current_qty)
            
            if close_success:
                logger.info("✅ Position closed, waiting for settlement...")
                time.sleep(2)  # Wait for settlement
            else:
                logger.error("❌ Failed to close existing position, aborting trade")
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
        "timestamp": datetime.now().isoformat()
    }, 200

# === Webhook Handlers ===
@app.route('/webhook', methods=['POST'])
def webhook_primary():
    """Primary webhook endpoint"""
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
        
        # Format symbol for Bitget futures - CORRECT FORMAT
        if not symbol.endswith('USDT'):
            symbol = f"{symbol}USDT"
        # Use correct symbol format: SUIUSDT_UMCBL
        symbol = f"{symbol}_UMCBL"
        
        logger.info(f"🔔 PRIMARY SIGNAL: {symbol} {side}")
        result, status = execute_trade(symbol, side.upper(), "PRIMARY")
        return jsonify(result), status
        
    except Exception as e:
        logger.error(f"❌ PRIMARY WEBHOOK ERROR: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/backup', methods=['POST'])
def webhook_backup():
    """Backup webhook endpoint"""
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
        
        # Format symbol for Bitget futures - CORRECT FORMAT
        if not symbol.endswith('USDT'):
            symbol = f"{symbol}USDT"
        symbol = f"{symbol}_UMCBL"
        
        logger.info(f"🛡️ BACKUP SIGNAL: {symbol} {side}")
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
        "position_size_usdt": TRADE_BALANCE * 3,
        "exchange": "bitget",
        "mode": "one_way"
    })

@app.route('/')
def home():
    return """
    ✅ BITGET BOT - FIXED VERSION
    
    🔄 WEBHOOK ENDPOINTS:
    - PRIMARY: POST /webhook 
    - BACKUP:  POST /backup
    
    🎯 FEATURES:
    - ✅ 3x USDT value positions
    - ✅ Correct Bitget API endpoints
    - ✅ Proper symbol formatting
    - ✅ USDT-based sizing
    
    📝 TRADINGVIEW ALERT:
    {"symbol":"SUI","side":"BUY"}
    """

if __name__ == "__main__":
    logger.info("🚀 BITGET BOT STARTED - FIXED VERSION")
    logger.info(f"💰 Trade Balance: {TRADE_BALANCE} USDT")
    logger.info(f"📊 Position Size: {TRADE_BALANCE * 3} USDT")
    logger.info("🎯 Positions calculated in USDT value")
    logger.info("🔧 Fixed API endpoints and symbol formatting")
    
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
