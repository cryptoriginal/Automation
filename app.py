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
            
            if current_time - last_time < 10:
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
    message = str(timestamp) + method.upper() + request_path + body
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
    """Get current market price - CORRECTED"""
    try:
        # Use clean symbol without _UMCBL for price API
        clean_symbol = symbol.replace("UMCBL", "USDT").replace("_", "")
        logger.info(f"🔍 Fetching price for: {clean_symbol}")
        
        response = requests.get(
            f"{BASE_URL}/api/mix/v1/market/ticker",
            params={"symbol": clean_symbol},
            timeout=10
        )
        data = response.json()
        
        if data.get("code") == "00000":
            price = float(data["data"]["last"])
            logger.info(f"✅ Price: ${price}")
            return price
        else:
            logger.error(f"❌ Price fetch failed: {data}")
            return None
    except Exception as e:
        logger.error(f"❌ Price error: {e}")
        return None

# === Get Current Position ===
def get_current_position(symbol):
    """Get current position - SIMPLIFIED"""
    try:
        request_path = "/api/mix/v1/position/all-position"
        params = {"productType": "umcbl"}
        
        headers = bitget_headers("GET", request_path)
        response = requests.get(
            f"{BASE_URL}{request_path}",
            params=params,
            headers=headers,
            timeout=10
        )
        data = response.json()
        
        if data.get("code") == "00000" and data.get("data"):
            for position in data["data"]:
                if position["symbol"] == symbol and float(position.get("total", 0)) > 0:
                    return {
                        "side": position.get("holdSide", "long"),
                        "quantity": float(position.get("total", 0))
                    }
        return None
        
    except Exception as e:
        logger.error(f"❌ Position error: {e}")
        return None

# === Calculate Position Size ===
def calculate_position_size(symbol):
    """Calculate position size based on 3x USDT value"""
    try:
        current_price = get_current_price(symbol)
        if not current_price:
            return None
        
        # Calculate USDT value (3x trade balance)
        usdt_value = TRADE_BALANCE * 3
        
        # Calculate quantity based on price
        quantity = usdt_value / current_price
        
        # Apply minimum quantity and precision
        quantity = max(quantity, 1.0)
        quantity = round(quantity, 3)
        
        logger.info(f"💰 {TRADE_BALANCE} × 3 = {usdt_value} USDT")
        logger.info(f"📊 ${current_price} → {quantity} tokens")
        
        return quantity
        
    except Exception as e:
        logger.error(f"❌ Quantity calculation error: {e}")
        return None

# === Place Order ===
def place_order(symbol, side, quantity, trade_side="open"):
    """Place order - CORRECTED"""
    try:
        request_path = "/api/mix/v1/order/placeOrder"
        
        order_data = {
            "symbol": symbol,
            "productType": "umcbl",
            "marginMode": "crossed",
            "marginCoin": "USDT",
            "size": str(quantity),
            "side": side,
            "orderType": "market",
            "tradeSide": trade_side
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
        
        logger.info(f"📊 Order response: {data}")
        
        if data.get("code") == "00000":
            return True
        else:
            logger.error(f"❌ Order failed: {data.get('msg', 'Unknown error')}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Order error: {e}")
        return False

# === Trade Execution ===
def execute_trade(symbol, action):
    """Main trade execution logic"""
    
    if not trade_tracker.can_trade(symbol):
        return {"status": "skipped", "reason": "cooldown"}, 200
    
    logger.info(f"🎯 EXECUTING: {symbol} {action}")
    
    success = False
    try:
        # Check current position
        current_position = get_current_position(symbol)
        logger.info(f"📊 Current position: {current_position}")
        
        # Close existing position if it exists
        if current_position:
            current_side = current_position["side"]
            current_qty = current_position["quantity"]
            
            logger.info(f"🔄 Closing {current_side} position")
            close_side = "sell" if current_side == "long" else "buy"
            close_success = place_order(symbol, close_side, current_qty, "close")
            
            if close_success:
                logger.info("✅ Position closed, waiting...")
                time.sleep(2)
            else:
                logger.error("❌ Failed to close position")
                return {"status": "failed", "reason": "close_failed"}, 200
        
        # Calculate and open new position
        quantity = calculate_position_size(symbol)
        if not quantity:
            return {"status": "failed", "reason": "price_fetch_failed"}, 200
        
        logger.info(f"📈 Opening {action} position")
        open_side = "buy" if action == "BUY" else "sell"
        open_success = place_order(symbol, open_side, quantity, "open")
        success = open_success
        
        if success:
            logger.info(f"✅✅✅ SUCCESS: {symbol} {action}")
        else:
            logger.error(f"❌ FAILED: {symbol} {action}")
        
    except Exception as e:
        logger.error(f"💥 EXECUTION ERROR: {e}")
        success = False
    
    return {
        "status": "success" if success else "failed",
        "symbol": symbol,
        "side": action,
        "timestamp": datetime.now().isoformat()
    }, 200

# === Webhook Handler ===
@app.route('/webhook', methods=['POST'])
def webhook():
    """Single webhook endpoint"""
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "no JSON data"}), 400
            
        symbol = data.get("symbol")
        side = data.get("side")
        
        if not symbol or not side:
            return jsonify({"error": "missing symbol or side"}), 400
        
        if side.upper() not in ['BUY', 'SELL']:
            return jsonify({"error": "side must be BUY or SELL"}), 400
        
        # CORRECT Bitget symbol format
        if not symbol.endswith('USDT'):
            symbol = f"{symbol}USDT"
        symbol = f"{symbol}UMCBL"  # Correct format: SUIUSDTUMCBL
        
        logger.info(f"🔔 SIGNAL: {symbol} {side}")
        result, status = execute_trade(symbol, side.upper())
        return jsonify(result), status
        
    except Exception as e:
        logger.error(f"❌ WEBHOOK ERROR: {e}")
        return jsonify({"error": str(e)}), 500

# === Test Endpoint ===
@app.route('/test', methods=['GET'])
def test():
    """Test API connection"""
    try:
        symbol = "SUIUSDTUMCBL"
        
        # Test price
        price = get_current_price(symbol)
        
        # Test position check
        position = get_current_position(symbol)
        
        return jsonify({
            "status": "connected",
            "symbol": symbol,
            "price": price,
            "position": position,
            "trade_balance": TRADE_BALANCE,
            "position_size_usdt": TRADE_BALANCE * 3
        })
        
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "healthy",
        "exchange": "bitget",
        "position_size_usdt": TRADE_BALANCE * 3
    })

@app.route('/')
def home():
    return """
    ✅ BITGET BOT - CORRECTED VERSION
    
    🔄 WEBHOOK: POST /webhook
    🧪 TEST: GET /test
    
    📝 TRADINGVIEW ALERTS:
    BUY: {"symbol":"SUI","side":"BUY"}
    SELL: {"symbol":"SUI","side":"SELL"}
    
    ✅ Uses correct symbol format: SUIUSDTUMCBL
    ✅ 3x USDT value positions
    ✅ One-way mode
    """

if __name__ == "__main__":
    logger.info("🚀 BITGET BOT STARTED - CORRECTED")
    logger.info(f"💰 Trade Balance: {TRADE_BALANCE} USDT")
    logger.info(f"📊 Position Size: {TRADE_BALANCE * 3} USDT")
    logger.info("🎯 Correct symbol format: SUIUSDTUMCBL")
    
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
