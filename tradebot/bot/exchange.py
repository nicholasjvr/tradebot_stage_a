"""
Exchange interface using ccxt library
"""
import ccxt
import logging
from typing import List, Dict, Optional
from .config import EXCHANGE_NAME, EXCHANGE_API_KEY, EXCHANGE_SECRET, EXCHANGE_SANDBOX

logger = logging.getLogger(__name__)


class Exchange:
    """Wrapper for ccxt exchange interface"""
    
    def __init__(self):
        """Initialize exchange connection"""
        exchange_class = getattr(ccxt, EXCHANGE_NAME)
        
        config = {
            'apiKey': EXCHANGE_API_KEY if EXCHANGE_API_KEY else None,
            'secret': EXCHANGE_SECRET if EXCHANGE_SECRET else None,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',  # spot, future, delivery
            }
        }
        
        # For sandbox/testing
        if EXCHANGE_SANDBOX:
            config['sandbox'] = True
        
        self.exchange = exchange_class(config)
        logger.info(f"Initialized {EXCHANGE_NAME} exchange")
    
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 1, since: Optional[int] = None) -> List[List]:
        """
        Fetch OHLCV (Open, High, Low, Close, Volume) data
        
        Args:
            symbol: Trading pair (e.g., 'BTC/USDT')
            timeframe: Timeframe (e.g., '1m', '5m', '1h')
            limit: Number of candles to fetch
            since: Timestamp in milliseconds (optional)
        
        Returns:
            List of [timestamp, open, high, low, close, volume]
        """
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit, since=since)
            logger.debug(f"Fetched {len(ohlcv)} candles for {symbol} {timeframe}")
            return ohlcv
        except Exception as e:
            logger.error(f"Error fetching OHLCV for {symbol}: {e}")
            raise
    
    def fetch_ticker(self, symbol: str) -> Dict:
        """
        Fetch current ticker data
        
        Args:
            symbol: Trading pair (e.g., 'BTC/USDT')
        
        Returns:
            Ticker data dictionary
        """
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            logger.debug(f"Fetched ticker for {symbol}")
            return ticker
        except Exception as e:
            logger.error(f"Error fetching ticker for {symbol}: {e}")
            raise
    
    def get_markets(self) -> Dict:
        """Get available markets"""
        try:
            markets = self.exchange.load_markets()
            return markets
        except Exception as e:
            logger.error(f"Error loading markets: {e}")
            raise
    
    def validate_symbol(self, symbol: str) -> bool:
        """Check if symbol is available on exchange"""
        try:
            markets = self.get_markets()
            return symbol in markets
        except Exception as e:
            logger.error(f"Error validating symbol {symbol}: {e}")
            return False

