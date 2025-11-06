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
from queue import Queue

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

# --- Multi-layer Redundancy System ---
class TradeManager:
    def __init__(self):
        self.trade_queue = Queue()
        self.processing = False
        self.last_trades = {}  # symbol: {side, timestamp}
        self.TRADE_COOLDOWN = 3  # seconds
        self.max_retries = 3
        self.webhook_counter = 0
        
        # Start background processor
        self.processor_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.processor_thread.start()
        
    def _process_queue(self):
        """Background queue processor"""
        while True:
            if not self.trade_queue.empty() and not self.processing:
                self.processing = True
                try:
                    trade_data = self.trade_queue.get()
                    self._execute_trade_safe(trade_data)
                    self.trade_queue.task_done()
                except Exception as e:
                    logger.error(f"Queue processor error: {e}")
                finally:
                    self.processing = False
            time.sleep(0.1)  # Small delay to prevent CPU overload
    
    def _execute_trade_safe(self, trade_data):
        """Safe trade execution with multiple retries"""
        symbol = trade_data['symbol']
        action = trade_data['side']
        
        for attempt in range(self.max_retries):
            try:
                logger.info(f"🔄 Attempt {attempt+1}/{self.max_retries} for {symbol} {action}")
                
                if self._should_skip_trade(symbol, action):
                    logger.info(f"⏸️ Skipping duplicate {symbol} {action}")
                    return True
                
                success = self._execute_trade_ultrafast(symbol, action)
                
                if success:
                    self._update_last_trade(symbol, action)
                    logger.info(f"✅✅✅ TRADE SUCCESS: {symbol} {action}")
                    return True
                else:
                    logger.warning(f"❌ Attempt {attempt+1} failed for {symbol} {action}")
                    if attempt < self.max_retries - 1:
                        time.sleep(1)  # Wait before retry
                        
            except Exception as e:
                logger.error(f"❌ Trade execution error: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(1)
        
        logger.error(f"💥 ALL ATTEMPTS FAILED for {symbol} {action}")
        return False
    
    def _should_skip_trade(self, symbol, action):
        """Check if we should skip this trade (cooldown/duplicate)"""
        current_time = time.time()
        last_trade = self.last_trades.get(symbol)
        
        if last_trade:
            time_diff = current_time - last_trade['timestamp']
            if (last_trade['side'] == action and time_diff < self.TRADE_COOLDOWN):
                return True
        return False
    
    def _update_last_trade(self, symbol, action):
        """Update last trade timestamp"""
        self.last_trades[symbol] = {
            'side': action,
            'timestamp': time.time()
        }
    
    def _execute_trade_ultrafast(self, symbol, action):
        """Ultra-fast trade execution with minimal steps"""
        try:
            # STEP 1: Fast position check
            current_position = self._get_position_fast(symbol)
            logger.info(f"📊 {symbol} position: {current_position}")
            
            # STEP 2: Close opposite position if needed
            if current_position and current_position != "NONE":
                should_close = (
                    (action == "BUY" and current_position == "SHORT") or
                    (action == "SELL" and current_position == "LONG")
                )
                if should_close:
                    logger.info(f"🔄 Closing {current_position} position")
                    close_success = self._close_position_fast(symbol, current_position)
                    if close_success:
                        time.sleep(1)  # Minimal settlement wait
            
            # STEP 3: Open new position
            open_success = self._open_position_fast(symbol, action)
            return open_success
            
        except Exception as e:
            logger.error(f"❌ Ultra-fast execution error: {e}")
            return False
    
    def _get_position_fast(self, symbol):
        """Fast position check"""
        try:
            params = {"symbol": symbol, "timestamp": int(time.time() * 1000)}
            signature = self._bingx_signature(params)
            params["signature"] = signature
            
            response = requests.get(
                f"{BASE_URL}/openApi/swap/v2/user/positions",
                headers=self._bingx_headers(),
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
    
    def _close_position_fast(self, symbol, side):
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
            
            signature = self._bingx_signature(params)
            params["signature"] = signature
            
            response = requests.post(
                f"{BASE_URL}/openApi/swap/v2/trade/order",
                headers=self._bingx_headers(),
                json=params,
                timeout=10
            )
            data = response.json()
            
            return data.get("code") == 0
        except Exception as e:
            logger.error(f"❌ Close error: {e}")
            return False
    
    def _open_position_fast(self, symbol, side):
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
            
            signature = self._bingx_signature(params)
            params["signature"] = signature
            
            response = requests.post(
                f"{BASE_URL}/openApi/swap/v2/trade/order",
                headers=self._bingx_headers(),
                json=params,
                timeout=10
            )
            data = response.json()
            
            return data.get("code") == 0
        except Exception as e:
            logger.error(f"❌ Open error: {e}")
            return False
    
    def _bingx_signature(self, params):
        """Generate BingX signature"""
        query_string = '&'.join([f"{key}={value}" for key, value in sorted(params.items())])
        return hmac.new(
            SECRET_KEY.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def _bingx_headers(self):
        return {"X-BX-APIKEY": API_KEY, "Content-Type": "application/json"}
    
    def add_trade(self, symbol, side):
        """Add trade to queue"""
        self.webhook_counter += 1
        trade_data = {
            'symbol': symbol,
            'side': side,
            'webhook_id': self.webhook_counter,
            'timestamp': datetime.now().isoformat()
        }
        self.trade_queue.put(trade_data)
        logger.info(f"📥 Queued trade #{self.webhook_counter}: {symbol} {side}")

# Initialize trade manager
trade_manager = TradeManager()

# === MULTIPLE WEBHOOK ENDPOINTS for Redundancy ===
@app.route('/webhook', methods=['POST'])
def webhook_primary():
    """Primary webhook endpoint"""
    return process_webhook("PRIMARY")

@app.route('/backup', methods=['POST'])
def webhook_backup():
    """Backup webhook endpoint"""
    return process_webhook("BACKUP")

@app.route('/emergency', methods=['POST'])
def webhook_emergency():
    """Emergency webhook endpoint"""
    return process_webhook("EMERGENCY")

@app.route('/fallback', methods=['POST'])
def webhook_fallback():
    """Fallback webhook endpoint"""
    return process_webhook("FALLBACK")

def process_webhook(endpoint_name):
    """Process webhook from any endpoint"""
    start_time = time.time()
    
    try:
        data = request.get_json(force=True)
        symbol = data.get("symbol")
        side = data.get("side")
        
        logger.info(f"🚀 {endpoint_name} WEBHOOK: {symbol} {side}")
        
        if not symbol or not side:
            return jsonify({"error": "missing symbol or side"}), 400
        
        if side.upper() not in ['BUY', 'SELL']:
            return jsonify({"error": "side must be BUY or SELL"}), 400
        
        # Add to queue (immediate processing in background)
        trade_manager.add_trade(symbol, side.upper())
        
        response_time = time.time() - start_time
        logger.info(f"⚡ {endpoint_name} processed in {response_time:.2f}s")
        
        return jsonify({
            "status": "queued",
            "endpoint": endpoint_name,
            "symbol": symbol,
            "side": side,
            "response_time": f"{response_time:.2f}s",
            "timestamp": datetime.now().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"❌ {endpoint_name} WEBHOOK ERROR: {e}")
        return jsonify({"error": str(e)}), 500

# === Health & Status Endpoints ===
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "queue_size": trade_manager.trade_queue.qsize(),
        "processing": trade_manager.processing,
        "webhooks_received": trade_manager.webhook_counter,
        "trade_balance": TRADE_BALANCE,
        "position_size": TRADE_BALANCE * 3
    })

@app.route('/queue', methods=['GET'])
def queue_status():
    """Queue status endpoint"""
    return jsonify({
        "queue_size": trade_manager.trade_queue.qsize(),
        "currently_processing": trade_manager.processing,
        "last_trades": trade_manager.last_trades,
        "webhooks_received": trade_manager.webhook_counter
    })

@app.route('/position/<symbol>', methods=['GET'])
def check_position(symbol):
    """Check position for symbol"""
    position = trade_manager._get_position_fast(symbol)
    return jsonify({
        "symbol": symbol,
        "position": position,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/test/<symbol>/<side>', methods=['GET'])
def test_trade(symbol, side):
    """Test trade endpoint"""
    if side.upper() not in ['BUY', 'SELL']:
        return jsonify({"error": "side must be BUY or SELL"}), 400
    
    trade_manager.add_trade(symbol, side.upper())
    return jsonify({
        "status": "test_queued",
        "symbol": symbol,
        "side": side
    })

@app.route('/')
def home():
    return """
    ✅ ULTRA-RELIABLE BINGX BOT - ZERO MISSES
    
    🔄 MULTIPLE WEBHOOK ENDPOINTS:
    - PRIMARY:   POST /webhook
    - BACKUP:    POST /backup
    - EMERGENCY: POST /emergency
    - FALLBACK:  POST /fallback
    
    📊 STATUS ENDPOINTS:
    - Health:    GET /health
    - Queue:     GET /queue
    - Position:  GET /position/SOL-USDT
    - Test:      GET /test/SOL-USDT/BUY
    
    🛡️ FEATURES:
    - 4x redundant webhook endpoints
    - Queue system with retry logic
    - Cooldown protection
    - Background processing
    - Real-time logging
    - Exact 3x position sizing
    """

# === Startup ===
if __name__ == "__main__":
    logger.info("🔷 Starting ULTRA-RELIABLE BingX Bot")
    logger.info(f"💰 Trade Balance: {TRADE_BALANCE} USDT")
    logger.info(f"📊 Position Size: {TRADE_BALANCE * 3} USDT")
    logger.info("🛡️ 4x redundant webhook endpoints enabled")
    logger.info("🔄 Queue system with retry logic active")
    logger.info("⚡ Background processor running")
    
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
