"""
Configuration management for the tradebot
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Base directory
BASE_DIR = Path(__file__).parent.parent

# Database configuration
DB_DIR = BASE_DIR / "db"
DB_PATH = DB_DIR / "marketdata.sqlite"

# Logs directory
LOGS_DIR = BASE_DIR / "logs"

# Exchange configuration (Stage A is public-data only)
EXCHANGE_NAME = os.getenv("EXCHANGE_NAME", "binance")
EXCHANGE_API_KEY = os.getenv("EXCHANGE_API_KEY", "")
EXCHANGE_SECRET = os.getenv("EXCHANGE_SECRET", "")
# PUBLIC_ONLY forces all requests to public endpoints; API keys are ignored when true
PUBLIC_ONLY = os.getenv("PUBLIC_ONLY", "true").lower() == "true"
EXCHANGE_SANDBOX = os.getenv("EXCHANGE_SANDBOX", "false").lower() == "true"

# Trading configuration
SYMBOLS = os.getenv("SYMBOLS", "BTC/USDT,ETH/USDT").split(",")
# Collector: use 1m only so we can resample to 5m, 7m, 30m
TIMEFRAME = os.getenv("TIMEFRAME", "1m")
MULTI_TIMEFRAMES = os.getenv("MULTI_TIMEFRAMES", "").strip()
# Timeframes to build from 1m (comma-separated, e.g. 5m,7m,30m). Trader uses 7m.
RESAMPLE_TO = os.getenv("RESAMPLE_TO", "5m,7m,30m").strip()
RESAMPLE_TO = [t.strip() for t in RESAMPLE_TO.split(",") if t.strip()] if RESAMPLE_TO else []
# Trader strategy runs on this timeframe (must be in RESAMPLE_TO or collected)
TRADER_TIMEFRAME = os.getenv("TRADER_TIMEFRAME", "7m").strip() or "7m"
COLLECTION_INTERVAL = int(os.getenv("COLLECTION_INTERVAL", "60"))  # seconds

# -----------------------------
# Stage B: Trading configuration
# -----------------------------
# Default trading mode. Interactive prompts in `bot.trader` can override these at runtime.
# Allowed: "paper", "live"
TRADING_MODE = os.getenv("TRADING_MODE", "paper").strip().lower()

# Safety gate for live trading:
# - You must set PUBLIC_ONLY=false AND ENABLE_LIVE_TRADING=true to allow authenticated order placement.
ENABLE_LIVE_TRADING = os.getenv("ENABLE_LIVE_TRADING", "false").strip().lower() == "true"

# Order types supported by v1 trader
# Allowed: "market", "limit"
ORDER_TYPE = os.getenv("ORDER_TYPE", "market").strip().lower()

# Position sizing (fixed quote amount per buy, in USDT for USDT-quoted symbols)
FIXED_QUOTE_AMOUNT = float(os.getenv("FIXED_QUOTE_AMOUNT", "25"))

# Strategy defaults (SMA crossover windows, in number of candles)
SMA_FAST_WINDOW = int(os.getenv("SMA_FAST_WINDOW", "10"))
SMA_SLOW_WINDOW = int(os.getenv("SMA_SLOW_WINDOW", "30"))

# Trader loop interval (seconds). Defaults to COLLECTION_INTERVAL.
TRADER_INTERVAL = int(os.getenv("TRADER_INTERVAL", str(COLLECTION_INTERVAL)))

# Paper trading assumptions
PAPER_FEE_RATE = float(os.getenv("PAPER_FEE_RATE", "0.001"))  # 0.1% default

# Daily budget for paper trading (quote currency, e.g. USDT). No limit if unset or 0.
# Example: 1000 ZAR/day ≈ 55 USDT → set DAILY_BUDGET_QUOTE=55
_raw_budget = os.getenv("DAILY_BUDGET_QUOTE", "").strip()
try:
    DAILY_BUDGET_QUOTE = float(_raw_budget) if _raw_budget else None
except ValueError:
    DAILY_BUDGET_QUOTE = None

# Optional PnL threshold (USDT) for dashboard: "above/below threshold" indicator.
_raw_threshold = os.getenv("PNL_THRESHOLD", "").strip()
try:
    PNL_THRESHOLD = float(_raw_threshold) if _raw_threshold else None
except ValueError:
    PNL_THRESHOLD = None

# Optional: show amounts in ZAR on dashboard. Rate = how many ZAR per 1 USDT (e.g. 18.5).
_raw_zar = os.getenv("ZAR_PER_USDT", "").strip()
try:
    ZAR_PER_USDT = float(_raw_zar) if _raw_zar else None
except ValueError:
    ZAR_PER_USDT = None

# Ensure directories exist
DB_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

