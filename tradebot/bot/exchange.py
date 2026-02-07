"""
Exchange interface using ccxt library
"""
import time
import ccxt
import logging
from typing import List, Dict, Optional, Any
from ccxt.base.errors import NetworkError, DDoSProtection, RateLimitExceeded, ExchangeError
from .config import EXCHANGE_NAME, EXCHANGE_API_KEY, EXCHANGE_SECRET, EXCHANGE_SANDBOX, PUBLIC_ONLY

logger = logging.getLogger(__name__)


class Exchange:
    """Wrapper for ccxt exchange interface"""
    
    def __init__(self):
        """Initialize exchange connection"""
        exchange_class = getattr(ccxt, EXCHANGE_NAME)
        
        config = {
            # API keys are ignored when PUBLIC_ONLY is true (Stage A safety)
            'apiKey': EXCHANGE_API_KEY if EXCHANGE_API_KEY and not PUBLIC_ONLY else None,
            'secret': EXCHANGE_SECRET if EXCHANGE_SECRET and not PUBLIC_ONLY else None,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',  # spot, future, delivery
            }
        }
        
        # For sandbox/testing
        if EXCHANGE_SANDBOX:
            config['sandbox'] = True
        
        self.exchange = exchange_class(config)
        if EXCHANGE_SANDBOX:
            try:
                self.exchange.set_sandbox_mode(True)
            except Exception:
                logger.warning("Sandbox mode requested but not supported by exchange")

        if PUBLIC_ONLY and (EXCHANGE_API_KEY or EXCHANGE_SECRET):
            logger.warning("PUBLIC_ONLY=true: ignoring provided API keys; using public endpoints only")
        logger.info(f"Initialized {EXCHANGE_NAME} exchange (public-only={PUBLIC_ONLY}, sandbox={EXCHANGE_SANDBOX})")

    def _request_with_backoff(self, func, *args, **kwargs):
        """Execute exchange call with simple exponential backoff for rate limits/network errors."""
        backoff = 1
        attempts = 0
        last_err = None
        while attempts < 5:
            try:
                return func(*args, **kwargs)
            except (RateLimitExceeded, DDoSProtection) as e:
                last_err = e
                logger.warning(f"Rate limit hit; retrying in {backoff}s (attempt {attempts + 1}/5)")
            except NetworkError as e:
                last_err = e
                logger.warning(f"Network error; retrying in {backoff}s (attempt {attempts + 1}/5)")
            except ExchangeError as e:
                # Fail fast on exchange errors that are not transient
                logger.error(f"Exchange error: {e}")
                raise
            attempts += 1
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)
        logger.error(f"Exceeded retry budget for exchange call: {last_err}")
        raise last_err
    
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
            ohlcv = self._request_with_backoff(self.exchange.fetch_ohlcv, symbol, timeframe, limit=limit, since=since)
            logger.debug(f"Fetched {len(ohlcv)} candles for {symbol} {timeframe} (since={since})")
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
            ticker = self._request_with_backoff(self.exchange.fetch_ticker, symbol)
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

    # -----------------------------
    # Stage B: Authenticated helpers
    # -----------------------------
    def amount_to_precision(self, symbol: str, amount: float) -> str:
        return self.exchange.amount_to_precision(symbol, amount)

    def price_to_precision(self, symbol: str, price: float) -> str:
        return self.exchange.price_to_precision(symbol, price)

    def fetch_balance(self) -> Dict[str, Any]:
        """Fetch account balances (requires PUBLIC_ONLY=false)."""
        if PUBLIC_ONLY:
            raise RuntimeError("PUBLIC_ONLY=true: authenticated endpoints are disabled")
        return self._request_with_backoff(self.exchange.fetch_balance)

    def get_free_balance(self, asset: str) -> float:
        """Return free balance for an asset (requires PUBLIC_ONLY=false)."""
        bal = self.fetch_balance()
        free = bal.get("free", {}).get(asset)
        if free is None:
            # ccxt may return top-level currency objects too
            cur = bal.get(asset) or {}
            free = cur.get("free", 0.0)
        return float(free or 0.0)

    def create_order(
        self,
        *,
        symbol: str,
        order_type: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create an order (requires PUBLIC_ONLY=false).

        Note: For market orders, `price` must be None.
        """
        if PUBLIC_ONLY:
            raise RuntimeError("PUBLIC_ONLY=true: order placement is disabled")
        params = params or {}
        if order_type == "market":
            price = None
        try:
            return self._request_with_backoff(self.exchange.create_order, symbol, order_type, side, amount, price, params)
        except ExchangeError:
            raise
        except Exception as e:
            logger.error(f"Error creating order symbol={symbol} side={side} type={order_type}: {e}")
            raise

