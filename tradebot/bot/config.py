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
TIMEFRAME = os.getenv("TIMEFRAME", "1m")
COLLECTION_INTERVAL = int(os.getenv("COLLECTION_INTERVAL", "60"))  # seconds

# Ensure directories exist
DB_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

