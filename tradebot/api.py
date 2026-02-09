"""
Simple Flask API to serve market data for bots/training
Run with: python api.py
Access at: http://localhost:5000/ohlcv?symbol=BTC/USDT&limit=100
Charts: http://localhost:5000/dashboard
"""
from flask import Flask, request, jsonify, send_from_directory
from pathlib import Path
from bot.db import Database
from bot.config import DAILY_BUDGET_QUOTE, PNL_THRESHOLD, ZAR_PER_USDT
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

@app.route("/chart/symbols")
def chart_symbols():
    """Distinct symbols from ohlcv (for dropdowns)."""
    try:
        with Database() as db:
            rows = db.conn.execute(
                "SELECT DISTINCT symbol FROM ohlcv ORDER BY symbol"
            ).fetchall()
        return jsonify([row["symbol"] for row in rows])
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


@app.route("/chart/orders")
def chart_orders():
    """Recent orders (paper or live). Query param: limit (default 15)."""
    limit = min(int(request.args.get("limit", 15)), 100)
    try:
        with Database() as db:
            rows = db.conn.execute(
                "SELECT id, mode, symbol, side, type, status, amount, price, filled, ts, created_at "
                "FROM orders ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return jsonify([dict(row) for row in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/chart/fills")
def chart_fills():
    """Recent fills with order link. Query param: limit (default 10)."""
    limit = min(int(request.args.get("limit", 10)), 100)
    try:
        with Database() as db:
            rows = db.conn.execute(
                "SELECT f.id, f.symbol, f.side, f.price, f.amount, f.cost, f.ts, f.order_id "
                "FROM fills f ORDER BY f.ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return jsonify([dict(row) for row in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/chart/positions")
def chart_positions():
    """Current positions (paper or live)."""
    try:
        with Database() as db:
            rows = db.conn.execute(
                "SELECT mode, exchange, symbol, base_qty, avg_entry_price, realized_pnl, updated_at "
                "FROM positions ORDER BY symbol"
            ).fetchall()
        return jsonify([dict(row) for row in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/chart/pnl_summary")
def chart_pnl_summary():
    """Paper trading: realized PnL, spent today, daily budget, and vs threshold."""
    try:
        with Database() as db:
            realized_pnl = db.get_paper_realized_pnl_total()
            spent_today = db.get_paper_spent_today()
        above_threshold = None
        if PNL_THRESHOLD is not None:
            above_threshold = realized_pnl >= PNL_THRESHOLD
        payload = {
            "realized_pnl": round(realized_pnl, 4),
            "spent_today": round(spent_today, 4),
            "daily_budget": DAILY_BUDGET_QUOTE,
            "pnl_threshold": PNL_THRESHOLD,
            "above_threshold": above_threshold,
        }
        if ZAR_PER_USDT is not None and ZAR_PER_USDT > 0:
            payload["zar_per_usdt"] = ZAR_PER_USDT
            payload["realized_pnl_zar"] = round(realized_pnl * ZAR_PER_USDT, 2)
            payload["spent_today_zar"] = round(spent_today * ZAR_PER_USDT, 2)
            payload["daily_budget_zar"] = round(DAILY_BUDGET_QUOTE * ZAR_PER_USDT, 2) if DAILY_BUDGET_QUOTE is not None else None
            payload["pnl_threshold_zar"] = round(PNL_THRESHOLD * ZAR_PER_USDT, 2) if PNL_THRESHOLD is not None else None
        return jsonify(payload)
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
            "/chart/symbols": "Distinct symbols (for dropdowns)",
            "/chart/candle_counts": "Candle counts per symbol/timeframe",
            "/chart/orders?limit=15": "Recent orders",
            "/chart/fills?limit=10": "Recent fills",
            "/chart/positions": "Current positions",
            "/chart/pnl_summary": "Paper PnL, spent today, budget, threshold",
            "/dashboard": "Web dashboard with charts"
        }
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)