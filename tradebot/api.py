"""
Simple Flask API to serve market data for bots/training
Run with: python api.py
Access at: http://localhost:5000/ohlcv?symbol=BTC/USDT&limit=100
Charts: http://localhost:5000/dashboard
"""
from flask import Flask, request, jsonify, send_from_directory
from pathlib import Path
from bot.db import Database
import logging

logging.basicConfig(level=logging.INFO)
app = Flask(__name__, static_folder="static")

@app.route('/ohlcv')
def get_ohlcv():
    """Get OHLCV data. Query params: symbol, limit (default 100)"""
    symbol = request.args.get('symbol')
    limit = int(request.args.get('limit', 100))
    if not symbol:
        return jsonify({"error": "symbol parameter required"}), 400
    
    try:
        with Database() as db:
            rows = db.conn.execute(
                "SELECT * FROM ohlcv WHERE symbol=? ORDER BY timestamp DESC LIMIT ?",
                (symbol, limit)
            ).fetchall()
            data = [dict(row) for row in rows]
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/tickers')
def get_tickers():
    """Get ticker data. Query params: symbol, limit (default 100)"""
    symbol = request.args.get('symbol')
    limit = int(request.args.get('limit', 100))
    if not symbol:
        return jsonify({"error": "symbol parameter required"}), 400
    
    try:
        with Database() as db:
            rows = db.conn.execute(
                "SELECT * FROM tickers WHERE symbol=? ORDER BY timestamp DESC LIMIT ?",
                (symbol, limit)
            ).fetchall()
            data = [dict(row) for row in rows]
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/chart/candle_counts")
def chart_candle_counts():
    """Chart-ready data: candle counts per symbol/timeframe (SQL → JSON for charts)."""
    try:
        with Database() as db:
            rows = db.conn.execute(
                "SELECT symbol, timeframe, COUNT(*) AS candle_count "
                "FROM ohlcv GROUP BY symbol, timeframe ORDER BY symbol, timeframe"
            ).fetchall()
        return jsonify([dict(row) for row in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/dashboard")
def dashboard():
    """Serve the chart dashboard (SQL queries → charts)."""
    return send_from_directory(app.static_folder, "dashboard.html")


@app.route('/')
def index():
    """API info"""
    return jsonify({
        "message": "Tradebot Data API",
        "endpoints": {
            "/ohlcv?symbol=BTC/USDT&limit=100": "Get OHLCV data",
            "/tickers?symbol=BTC/USDT&limit=100": "Get ticker data",
            "/chart/candle_counts": "Candle counts per symbol/timeframe (for charts)",
            "/dashboard": "Web dashboard with charts"
        }
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)