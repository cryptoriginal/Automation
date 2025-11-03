import os
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# ======== ENVIRONMENT VARIABLE CHECK =========
def safe_check_env(var_name):
    value = os.getenv(var_name)
    return True if value and value.strip() != "" else False

api_key = os.getenv("API_KEY")
api_secret = os.getenv("API_SECRET")
passphrase = os.getenv("PASSPHRASE")
trade_balance = os.getenv("TRADE_BALANCE_USDT")

print("🔍 DEBUG ENV CHECK:")
print(f"API_KEY present? {safe_check_env('API_KEY')}")
print(f"API_SECRET present? {safe_check_env('API_SECRET')}")
print(f"PASSPHRASE present? {safe_check_env('PASSPHRASE')}")
print(f"TRADE_BALANCE_USDT value: {trade_balance}")

@app.route('/')
def home():
    return "✅ Service is live"

if __name__ == '__main__':
    print("🚀 Flask server starting...")
    app.run(host='0.0.0.0', port=5000)
