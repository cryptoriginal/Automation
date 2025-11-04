MAX || [C.O.], [04-11-2025 08:31 AM]
import hmac
import hashlib
import time
import json
import requests
import base64
from flask import Flask, request, jsonify

# --- Configuration ---
# IMPORTANT: Replace these placeholders with your actual API credentials.
API_KEY = "bg_02bc5dd6473ee2005f097dd625e5e070"
API_SECRET = "fefb9196995ac05ab7f7e80dbff13a277f5b6992485a5378987ba80eed928a0d"
API_PASSPHRASE = "automatioN"

# Set your desired leverage (must be pre-set on the exchange, but good practice to include)
LEVERAGE = "10" 
# Set the desired size of your trade in base currency (e.g., 0.001 BTC or 0.1 ETH)
TRADE_SIZE = "0.005"
# Your TradingView Webhook Secret (must match the secret you set in TV alerts)
TV_SECRET = "Your_Secret_Webhook_Key" 

# Base URL for Bitget Mix (Futures) API
BASE_URL = "https://api.bitget.com" 

app = Flask(__name__)

# --- Bitget API Helper Class with V2 Signature Logic ---
class BitgetAPI:
    def __init__(self, key, secret, passphrase):
        self.key = key
        self.secret = secret
        self.passphrase = passphrase

    def _generate_signature(self, timestamp, method, request_path, body=None):
        """Generates the HMAC-SHA256 signature for Bitget API V2."""
        
        # 1. Concatenate the data string
        message = str(timestamp) + str.upper(method) + request_path
        if body is not None and body != "":
            message += body

        # 2. Hash the message
        # Convert secret to bytes
        secret_bytes = self.secret.encode('utf-8')
        
        # Generate the HMAC-SHA256 hash
        signature = hmac.new(secret_bytes, message.encode('utf-8'), hashlib.sha256).digest()
        
        # 3. Base64 encode the result
        return base64.b64encode(signature).decode('utf-8')

    def _send_request(self, method, request_path, params=None, body=None):
        """Helper to send authenticated requests."""
        timestamp = str(int(time.time() * 1000))
        
        body_str = json.dumps(body) if body else ""
        signature = self._generate_signature(timestamp, method, request_path, body_str)
        
        headers = {
            "Content-Type": "application/json",
            "ACCESS-KEY": self.key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.passphrase,
        }

        url = f"{BASE_URL}{request_path}"
        
        try:
            if method == "GET":
                response = requests.get(url, headers=headers, params=params)
            elif method == "POST":
                response = requests.post(url, headers=headers, data=body_str)
            else:
                raise ValueError("Unsupported HTTP method")

            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as err:
            print(f"HTTP Error: {err}")
            print(f"Response Content: {response.text}")
            return {"code": "ERROR", "msg": f"HTTP Error: {response.status_code} - {response.text}"}
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            return {"code": "ERROR", "msg": str(e)}

    # --- Trading Functions ---

    def get_position(self, symbol, product_type="USDT-FUTURES"):
        """Fetches the current position(s) for a given symbol."""
        path = "/api/v2/mix/position/single-position"
        params = {
            "symbol": symbol,
            "productType": product_type
        }
        return self._send_request("GET", path, params=params)

    def close_opposite_position(self, symbol, hold_side, product_type="USDT-FUTURES"):
        """Closes an existing position at market price based on the holdSide (long/short)."""
        print(f"Attempting to close existing {hold_side} position for {symbol}...")
        path = "/api/v2/mix/order/close-positions"
        body = {
            "symbol": symbol,
            "productType": product_type,
            "holdSide": hold_side, # This is CRITICAL for closing one side in Hedge Mode
        }
        return self._send_request("POST", path, body=body)

    def open_new_position(self, symbol, side, size, produ

MAX || [C.O.], [04-11-2025 08:31 AM]
ct_type="USDT-FUTURES", margin_coin="USDT"):
        """Opens a new market position (buy/sell)."""
        print(f"Attempting to open new {side} position for {symbol} with size {size}...")
        
        # CRITICAL: For placing an order, the side is 'buy' or 'sell'
        # The position is automatically opened as 'long' for 'buy' and 'short' for 'sell'
        # in Hedge Mode.
        body = {
            "symbol": symbol,
            "productType": product_type,
            "marginCoin": margin_coin,
            "side": side, 
            "orderType": "market",
            "size": size,
            "timeInForce": "GTC", # Good Till Cancelled
            "posSide": side, # 'long' for 'buy', 'short' for 'sell' 
            "leverage": LEVERAGE, # Use pre-defined leverage
            "tradeType": "open",
        }
        path = "/api/v2/mix/trade/place-order"
        return self._send_request("POST", path, body=body)

# Initialize API client
bg_api = BitgetAPI(API_KEY, API_SECRET, API_PASSPHRASE)


# --- Webhook Endpoint ---
@app.route("/webhook", methods=["POST"])
def webhook_handler():
    """
    Handles incoming TradingView webhook alerts.
    The expected payload is a JSON object like this:
    {
        "secret": "Your_Secret_Webhook_Key",
        "symbol": "BTCUSDT",
        "action": "buy",  // or "sell"
        "size": "0.005"   // Optional: override the default TRADE_SIZE
    }
    """
    
    try:
        data = request.json
        
        # 1. Security Check
        if data.get("secret") != TV_SECRET:
            print("ERROR: Invalid webhook secret.")
            return jsonify({"status": "error", "message": "Invalid secret"}), 401

        symbol = data.get("symbol").upper().replace('/', '') # e.g., BTCUSDT
        action = data.get("action").lower() # 'buy' or 'sell'
        trade_size = data.get("size", TRADE_SIZE) # Use payload size or default

        if action not in ["buy", "sell"]:
            print(f"Invalid action received: {action}")
            return jsonify({"status": "error", "message": "Invalid action"}), 400

        print(f"--- Received {action.upper()} signal for {symbol} ---")

        # Determine the position sides for current action
        if action == "buy":
            current_hold_side = "long"
            opposite_hold_side = "short"
            new_order_side = "buy"
        else: # action == "sell"
            current_hold_side = "short"
            opposite_hold_side = "long"
            new_order_side = "sell"
            
        # 2. Check for opposite position (CRITICAL STEP)
        position_data = bg_api.get_position(symbol)
        
        if position_data.get("code") != "00000":
            print(f"Error fetching position: {position_data.get('msg')}")
            # Continue, as we might still open the new position if no current position is the reason for the error
        
        # Bitget returns a list of positions (up to 2 in hedge mode)
        positions = position_data.get("data", {}).get("list", [])

        opposite_position_exists = False
        for pos in positions:
            # Check if there is an existing position in the opposite direction
            if pos.get("holdSide") == opposite_hold_side and float(pos.get("total", 0)) > 0:
                opposite_position_exists = True
                break
        
        # 3. Close Opposite Position (Step 1)
        if opposite_position_exists:
            print(f"Found existing {opposite_hold_side} position. Closing it now...")
            close_response = bg_api.close_opposite_position(symbol, opposite_hold_side)
            
            if close_response.get("code") == "00000":
                print(f"Successfully sent market close order for {opposite_hold_side}.")
                # In a real-world bot, you might want to wait a few seconds here 
                # and confirm the close before opening the new position, but for a 
                # simple script, proceeding is often sufficient if the close-position API is fast.
                time.sleep(1) # Small delay to allow the close to process

MAX || [C.O.], [04-11-2025 08:31 AM]
else:
                print(f"ERROR closing {opposite_hold_side} position: {close_response.get('msg')}")
                # You may want to STOP here if the close fails to prevent opening a hedge position
                # For this example, we log and proceed to open the new trade
        else:
            print(f"No existing {opposite_hold_side} position found. Proceeding to open new trade.")


        # 4. Open New Position (Step 2)
        open_response = bg_api.open_new_position(symbol, new_order_side, trade_size)

        if open_response.get("code") == "00000":
            print(f"Successfully placed new {new_order_side} order.")
            return jsonify({
                "status": "success",
                "message": f"Closed opposite position (if any) and opened new {new_order_side} trade.",
                "order_id": open_response.get("data", {}).get("orderId"),
                "symbol": symbol
            })
        else:
            print(f"ERROR opening new {new_order_side} position: {open_response.get('msg')}")
            return jsonify({
                "status": "error",
                "message": f"Failed to open new {new_order_side} trade.",
                "bitget_response": open_response.get("msg")
            }), 500

    except Exception as e:
        print(f"Unhandled exception: {e}")
        return jsonify({"status": "error", "message": f"Internal Server Error: {e}"}), 500

if __name__ == "__main__":
    # Log the fact that the server is starting
    print("Starting Bitget Webhook Listener...")
    print(f"Listening for TradingView signals on /webhook")
    # Run the Flask app
    app.run(host="0.0.0.0", port=80)
