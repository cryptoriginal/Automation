import os
import time
import hmac
import hashlib
import base64
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- Read env vars with fallback to BITGET_* names if present ---
API_KEY = os.getenv("API_KEY") or os.getenv("BITGET_API_KEY")
API_SECRET = os.getenv("API_SECRET") or os.getenv("BITGET_API_SECRET")
PASSPHRASE = os.getenv("PASSPHRASE") or os.getenv("BITGET_API_PASSPHRASE")
TRADE_BALANCE = float(os.getenv("TRADE_BALANCE_USDT", os.getenv("TRADE_BALANCE", "0.0")))

# Mask helper (do not print secrets)
def mask(s):
    if not s:
        return "None"
    if len(s) <= 6:
        return "***"
    return s[:3] + "..." + s[-3:]

# --- Startup status (visible in logs) ---
print("🔷 Starting app — environment check")
print("🔑 API Key loaded:", bool(API_KEY))
print("🔑 API Key (masked):", mask(API_KEY))
print("🔒 API Secret loaded:", bool(API_SECRET))
print("🔒 API Secret (masked):", mask(API_SECRET))
print("🧩 Passphrase loaded:", bool(PASSPHRASE))
print("🧩 Passphrase (masked):", mask(PASSPHRASE))
print("💰 Trade Balance (env):", TRADE_BALANCE)

BASE_URL = "https://api.bitget.com"

# === Signing ===
def bitget_signature(timestamp, method, request_path, body):
    message = f"{timestamp}{method.upper()}{request_path}{body}"
    mac = hmac.new(API_SECRET.encode('utf-8'), message.encode('utf-8'), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()

def make_headers(method, endpoint, body=""):
    timestamp = str(int(time.time() * 1000))
    sign = bitget_signature(timestamp, method, endpoint, body)
    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json"
    }

# === Position fetch (singlePosition) ===
def get_position(symbol):
    """Return dict with holdSide ('long'|'short'|'') and total size (float)"""
    try:
        endpoint = f"/api/mix/v1/position/singlePosition?symbol={symbol}&marginCoin=USDT"
        url = BASE_URL + "/api/mix/v1/position/singlePosition"
        # For GET with query we sign request_path as full path + query
        request_path = f"/api/mix/v1/position/singlePosition?symbol={symbol}&marginCoin=USDT"
        headers = make_headers("GET", request_path, "")
        r = requests.get(url, headers=headers, timeout=10)
        j = r.json()
        if j.get("code") in (0, "0"):
            d = j.get("data") or {}
            hold = d.get("holdSide") or None
            total = float(d.get("total", 0) or 0)
            return {"holdSide": hold, "total": total}
        # If API returns error, return empty
        print("⚠️ Position fetch returned:", r.status_code, r.text)
    except Exception as e:
        print("⚠️ Exception in get_position:", e)
    return {"holdSide": None, "total": 0.0}

# === Close opposite ===
def close_opposite(symbol, incoming_side):
    pos = get_position(symbol)
    if pos["total"] <= 0:
        return
    hold = (pos["holdSide"] or "").lower()
    if incoming_side.lower() == "buy" and hold == "short":
        print("🔻 Closing existing short before opening long")
        close_order(symbol, "close_short", pos["total"])
    elif incoming_side.lower() == "sell" and hold == "long":
        print("🔼 Closing existing long before opening short")
        close_order(symbol, "close_long", pos["total"])
    else:
        print("ℹ️ No opposite position to close (hold:", hold, "total:", pos["total"], ")")

def close_order(symbol, side_type, qty):
    try:
        endpoint = "/api/mix/v1/order/placeOrder"
        payload = {
            "symbol": symbol,
            "marginCoin": "USDT",
            "size": str(round(qty, 6)),
            "side": side_type,
            "orderType": "market",
            "timeInForceValue": "normal"
        }
        body = json.dumps(payload)
        headers = make_headers("POST", endpoint, body)
        url = BASE_URL + endpoint
        r = requests.post(url, headers=headers, data=body, timeout=15)
        print("💥 Close order sent:", payload)
        print("🌍 Bitget response:", r.status_code, r.text)
    except Exception as e:
        print("❌ Error closing order:", e)

# === Place order ===
def place_order(symbol, side):
    try:
        # 1) close opposite (safe) — will do nothing if none
        close_opposite(symbol, side)

        # 2) compute trade size as TRADE_BALANCE * 3 (full 3x multiplier)
        trade_size = round(TRADE_BALANCE * 3, 6)
        if trade_size <= 0:
            print("❌ Trade size is zero — set TRADE_BALANCE_USDT env var to >0")
            return

        endpoint = "/api/mix/v1/order/placeOrder"
        payload = {
            "symbol": symbol,
            "marginCoin": "USDT",
            "size": str(trade_size),
            "side": "open_long" if side.lower() == "buy" else "open_short",
            "orderType": "market",
            "timeInForceValue": "normal"
        }
        body = json.dumps(payload)
        headers = make_headers("POST", endpoint, body)
        url = BASE_URL + endpoint
        print("🧾 Sending order payload:", payload)
        r = requests.post(url, headers=headers, data=body, timeout=15)
        print("🌍 Bitget Response:", r.status_code, r.text)
    except Exception as e:
        print("❌ Exception placing order:", e)

# === Webhook ===
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        print("🚀 Webhook triggered!")
        data = request.get_json(force=True)
        print("📩 Received payload:", data)
        symbol = data.get("symbol")
        side = data.get("side")
        if not symbol or not side:
            return jsonify({"error": "missing symbol or side"}), 400
        place_order(symbol, side)
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print("❌ Webhook Error:", e)
        return jsonify({"error": str(e)}), 500

@app.route('/')
def home():
    return "✅ Bitget webhook running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))

