from flask import Flask, request, jsonify
import requests
import hmac
import hashlib
import base64
import time
import json
import os

app = Flask(__name__)

BLOFIN_API_KEY = os.getenv("BLOFIN_API_KEY")
BLOFIN_API_SECRET = os.getenv("BLOFIN_API_SECRET")
BLOFIN_API_PASSPHRASE = os.getenv("BLOFIN_API_PASSPHRASE")
BASE_URL = "https://api.blofin.com"

def blofin_signature(timestamp, method, request_path, body):
    body_str = json.dumps(body) if body else ""
    message = f"{timestamp}{method.upper()}{request_path}{body_str}"
    mac = hmac.new(
        BLOFIN_API_SECRET.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    )
    return base64.b64encode(mac.digest()).decode()

def place_order(symbol, side, qty, order_type="market"):
    endpoint = "/api/v1/trade/order"
    url = BASE_URL + endpoint
    timestamp = str(int(time.time()))

    body = {
        "instId": symbol,
        "tdMode": "cross",
        "side": side,
        "ordType": order_type,
        "sz": str(qty)
    }

    headers = {
        "Content-Type": "application/json",
        "ACCESS-KEY": BLOFIN_API_KEY,
        "ACCESS-SIGN": blofin_signature(timestamp, "POST", endpoint, body),
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": BLOFIN_API_PASSPHRASE,
    }

    print("==== Sending order to Blofin ====")
    print("URL:", url)
    print("Headers:", headers)
    print("Body:", body)

    response = requests.post(url, headers=headers, json=body)
    print("Blofin raw response:", response.text)

    try:
        return response.json()
    except Exception as e:
        return {"error": "Invalid JSON response", "raw": response.text, "exception": str(e)}

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON payload received"}), 400

        print("Alert received:", data)
        symbol = data.get("symbol")
        side = data.get("side")
        qty = data.get("qty", 0.05)
        order_type = data.get("type", "market")

        result = place_order(symbol, side, qty, order_type)
        print("Order result:", result)
        return jsonify({"status": "success", "exchange_response": result})

    except Exception as e:
        print("Error:", e)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/')
def home():
    return "✅ Blofin TradingView Webhook Bot is running!"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)

