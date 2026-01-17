"""
Main data collection script
"""
import time
import logging
import signal
import sys
from datetime import datetime
from pathlib import Path
from .config import (
    SYMBOLS, TIMEFRAME, COLLECTION_INTERVAL, LOGS_DIR,
    EXCHANGE_NAME, EXCHANGE_API_KEY, EXCHANGE_SECRET
)
from .exchange import Exchange
from .db import Database

# Configure logging
log_file = LOGS_DIR / f"collector_{datetime.now().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


class Collector:
    """Main data collection class"""
    
    def __init__(self):
        """Initialize collector"""
        self.exchange = Exchange()
        self.db = Database()
        self.running = False
        self.setup_signal_handlers()
        
        # Validate symbols
        self.valid_symbols = []
        for symbol in SYMBOLS:
            symbol = symbol.strip()
            if self.exchange.validate_symbol(symbol):
                self.valid_symbols.append(symbol)
                logger.info(f"[COLLECTOR] symbol={symbol} status=available")
            else:
                logger.warning(f"[COLLECTOR] symbol={symbol} status=unavailable exchange={EXCHANGE_NAME}")
        
        if not self.valid_symbols:
            logger.error("No valid symbols found! Check your SYMBOLS configuration.")
            sys.exit(1)
    
    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False
    
    def collect_ohlcv(self, symbol: str):
        """
        Collect OHLCV data for a symbol
        
        Args:
            symbol: Trading pair to collect data for
        """
        try:
            latest_ts = self.db.get_latest_timestamp(symbol, TIMEFRAME)
            since = latest_ts + 1 if latest_ts else None
            total_fetched = 0
            total_inserted = 0
            total_updated = 0

            while True:
                ohlcv_batch = self.exchange.fetch_ohlcv(
                    symbol,
                    TIMEFRAME,
                    limit=500,
                    since=since
                )
                if not ohlcv_batch:
                    break

                fetched = len(ohlcv_batch)
                total_fetched += fetched

                inserted, updated = self.db.insert_ohlcv(symbol, TIMEFRAME, ohlcv_batch)
                total_inserted += inserted
                total_updated += updated

                latest_open_time = ohlcv_batch[-1][0]
                since = latest_open_time + 1

                # If batch smaller than limit, we are caught up
                if fetched < 500:
                    break

            if total_fetched == 0:
                logger.info(f"[COLLECTOR] symbol={symbol} timeframe={TIMEFRAME} fetched=0 inserted=0 updated=0 latest_ts={latest_ts}")
            else:
                logger.info(
                    f"[COLLECTOR] symbol={symbol} timeframe={TIMEFRAME} fetched={total_fetched} "
                    f"inserted={total_inserted} updated={total_updated} latest_open={since - 1}"
                )

        except Exception as e:
            logger.error(f"[COLLECTOR] symbol={symbol} error={e}", exc_info=True)
    
    def collect_ticker(self, symbol: str):
        """
        Collect ticker data for a symbol
        
        Args:
            symbol: Trading pair to collect data for
        """
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            self.db.insert_ticker(symbol, ticker)
            logger.debug(f"{symbol}: Ticker collected - Last: {ticker.get('last')}")
        except Exception as e:
            logger.error(f"Error collecting ticker for {symbol}: {e}", exc_info=True)
    
    def run_once(self):
        """Run collection cycle once"""
        logger.info("Starting collection cycle...")
        
        for symbol in self.valid_symbols:
            try:
                self.collect_ohlcv(symbol)
                self.collect_ticker(symbol)
            except Exception as e:
                logger.error(f"[COLLECTOR] symbol={symbol} error=processing_failed detail={e}", exc_info=True)
        
        logger.info("Collection cycle completed")
    
    def run(self):
        """Run continuous collection loop"""
        logger.info("=" * 60)
        logger.info("Tradebot Collector Starting")
        logger.info(f"Exchange: {EXCHANGE_NAME}")
        logger.info(f"Symbols: {', '.join(self.valid_symbols)}")
        logger.info(f"Timeframe: {TIMEFRAME}")
        logger.info(f"Collection Interval: {COLLECTION_INTERVAL}s")
        logger.info("=" * 60)
        
        # Ensure database is initialized
        self.db.create_tables()
        
        self.running = True
        
        try:
            while self.running:
                cycle_start = time.time()
                
                self.run_once()
                
                # Calculate sleep time to maintain interval
                elapsed = time.time() - cycle_start
                sleep_time = max(0, COLLECTION_INTERVAL - elapsed)
                
                if sleep_time > 0:
                    logger.debug(f"Sleeping for {sleep_time:.2f} seconds")
                    time.sleep(sleep_time)
                else:
                    logger.warning(f"Collection cycle took {elapsed:.2f}s, longer than interval {COLLECTION_INTERVAL}s")
        
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            self.db.close()
            logger.info("Collector stopped")


def main():
    """Main entry point"""
    collector = Collector()
    collector.run()


if __name__ == "__main__":
    main()

