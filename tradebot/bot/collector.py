"""
Main data collection script
"""
import argparse
import os
import time
import logging
import signal
import sys
from datetime import datetime
from typing import Dict, List, Optional
from .config import (
    SYMBOLS, TIMEFRAME, MULTI_TIMEFRAMES, RESAMPLE_TO, LOGS_DIR,
    EXCHANGE_NAME
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

DEFAULT_TIMEFRAME_INTERVALS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
}


def _parse_csv_list(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _timeframe_to_seconds(timeframe: str) -> int:
    unit = timeframe[-1].lower()
    value = int(timeframe[:-1])
    multipliers = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
        "w": 7 * 86400,
    }
    if unit not in multipliers or value <= 0:
        raise ValueError(f"Invalid timeframe format: {timeframe}")
    return value * multipliers[unit]


class Collector:
    """Main data collection class"""
    
    def __init__(self, symbols: Optional[List[str]] = None, timeframes: Optional[List[str]] = None):
        """Initialize collector"""
        self.exchange = Exchange()
        self.db = Database()
        self.running = False
        self.setup_signal_handlers()

        self.symbols = self._resolve_symbols(symbols)
        self.timeframes = self._resolve_timeframes(timeframes)
        self.collection_interval_override = self._read_collection_interval_override()
        self.timeframe_intervals = self._build_timeframe_intervals(self.timeframes)
        self.base_interval = min(self.timeframe_intervals.values())
        self.last_run: Dict[str, Optional[float]] = {tf: None for tf in self.timeframes}
        
        # Validate symbols
        self.valid_symbols = []
        for symbol in self.symbols:
            symbol = symbol.strip()
            if self.exchange.validate_symbol(symbol):
                self.valid_symbols.append(symbol)
                logger.info(f"[COLLECTOR] symbol={symbol} status=available")
            else:
                logger.warning(f"[COLLECTOR] symbol={symbol} status=unavailable exchange={EXCHANGE_NAME}")
        
        if not self.valid_symbols:
            logger.error("No valid symbols found! Check your SYMBOLS configuration.")
            sys.exit(1)

        # Optional: warn if exchange does not advertise timeframe
        advertised = getattr(self.exchange.exchange, "timeframes", None) or {}
        if advertised:
            for tf in self.timeframes:
                if tf not in advertised:
                    logger.warning(f"[COLLECTOR] timeframe={tf} status=unadvertised exchange={EXCHANGE_NAME}")
    
    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False

    def _read_collection_interval_override(self) -> Optional[int]:
        raw = os.getenv("COLLECTION_INTERVAL")
        if raw is None:
            return None
        try:
            value = int(raw)
        except ValueError:
            logger.error(f"Invalid COLLECTION_INTERVAL: {raw}")
            sys.exit(1)
        if value <= 0:
            logger.error(f"Invalid COLLECTION_INTERVAL (must be > 0): {value}")
            sys.exit(1)
        return value

    def _resolve_symbols(self, symbols: Optional[List[str]]) -> List[str]:
        if symbols is None:
            return [s.strip() for s in SYMBOLS if s.strip()]
        if isinstance(symbols, str):
            return _parse_csv_list(symbols)
        return [s.strip() for s in symbols if s and s.strip()]

    def _resolve_timeframes(self, timeframes: Optional[List[str]]) -> List[str]:
        if timeframes:
            if isinstance(timeframes, str):
                resolved = _parse_csv_list(timeframes)
            else:
                resolved = [t.strip() for t in timeframes if t and t.strip()]
        elif MULTI_TIMEFRAMES:
            resolved = _parse_csv_list(MULTI_TIMEFRAMES)
        else:
            resolved = [TIMEFRAME]
        if not resolved:
            logger.error("No valid timeframes found! Check TIMEFRAME/MULTI_TIMEFRAMES.")
            sys.exit(1)
        return resolved

    def _build_timeframe_intervals(self, timeframes: List[str]) -> Dict[str, int]:
        intervals: Dict[str, int] = {}
        for tf in timeframes:
            if self.collection_interval_override:
                intervals[tf] = self.collection_interval_override
                continue
            try:
                interval = DEFAULT_TIMEFRAME_INTERVALS.get(tf) or _timeframe_to_seconds(tf)
            except ValueError as e:
                logger.error(str(e))
                sys.exit(1)
            intervals[tf] = interval
        return intervals

    def _format_schedule(self) -> str:
        parts = [f"{tf}={self.timeframe_intervals[tf]}s" for tf in self.timeframes]
        return ", ".join(parts)
    
    def collect_ohlcv(self, symbol: str, timeframe: str):
        """
        Collect OHLCV data for a symbol
        
        Args:
            symbol: Trading pair to collect data for
        """
        try:
            latest_ts = self.db.get_latest_timestamp(symbol, timeframe)
            since = latest_ts + 1 if latest_ts else None
            total_fetched = 0
            total_inserted = 0
            total_updated = 0

            while True:
                ohlcv_batch = self.exchange.fetch_ohlcv(
                    symbol,
                    timeframe,
                    limit=500,
                    since=since
                )
                if not ohlcv_batch:
                    break

                fetched = len(ohlcv_batch)
                total_fetched += fetched

                inserted, updated = self.db.insert_ohlcv(symbol, timeframe, ohlcv_batch)
                total_inserted += inserted
                total_updated += updated

                latest_open_time = ohlcv_batch[-1][0]
                since = latest_open_time + 1

                # If batch smaller than limit, we are caught up
                if fetched < 500:
                    break

            if total_fetched == 0:
                latest_open = latest_ts if latest_ts is not None else None
                logger.info(
                    f"[COLLECTOR] symbol={symbol} timeframe={timeframe} fetched=0 inserted=0 updated=0 "
                    f"latest_open={latest_open}"
                )
            else:
                logger.info(
                    f"[COLLECTOR] symbol={symbol} timeframe={timeframe} fetched={total_fetched} "
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
    
    def run_once(self, due_timeframes: List[str]):
        """Run collection cycle once"""
        logger.info(f"Starting collection cycle for timeframes: {', '.join(due_timeframes)}")
        
        for symbol in self.valid_symbols:
            try:
                for timeframe in due_timeframes:
                    self.collect_ohlcv(symbol, timeframe)
                # Build 5m, 7m, 30m (etc.) from 1m so trader can use 7m
                for to_tf in RESAMPLE_TO:
                    try:
                        ins, upd = self.db.resample_ohlcv(symbol, "1m", to_tf)
                        if ins or upd:
                            logger.info(f"[COLLECTOR] symbol={symbol} resample 1m->{to_tf} inserted={ins} updated={upd}")
                    except Exception as e:
                        logger.warning(f"[COLLECTOR] symbol={symbol} resample 1m->{to_tf} error={e}")
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
        logger.info(f"Timeframes: {', '.join(self.timeframes)}")
        logger.info(f"Schedule: {self._format_schedule()} (base_tick={self.base_interval}s)")
        if self.collection_interval_override:
            logger.info(f"Collection Interval Override: {self.collection_interval_override}s")
        logger.info("=" * 60)
        
        # Ensure database is initialized
        self.db.create_tables()
        
        self.running = True
        
        try:
            while self.running:
                cycle_start = time.time()

                now = time.time()
                due_timeframes: List[str] = []
                for tf, interval in self.timeframe_intervals.items():
                    last = self.last_run.get(tf)
                    if last is None or (now - last) >= interval:
                        due_timeframes.append(tf)

                if due_timeframes:
                    self.run_once(due_timeframes)
                    finished = time.time()
                    for tf in due_timeframes:
                        self.last_run[tf] = finished
                else:
                    logger.debug("No timeframes due this tick")

                # Calculate sleep time to maintain base tick
                elapsed = time.time() - cycle_start
                sleep_time = max(0, self.base_interval - elapsed)
                
                if sleep_time > 0:
                    logger.debug(f"Sleeping for {sleep_time:.2f} seconds")
                    time.sleep(sleep_time)
                else:
                    logger.warning(
                        f"Collection cycle took {elapsed:.2f}s, longer than base tick {self.base_interval}s"
                    )
        
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            self.db.close()
            logger.info("Collector stopped")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Tradebot data collector")
    parser.add_argument("--symbols", help="Comma-separated symbols to collect (overrides SYMBOLS)")
    parser.add_argument("--timeframes", help="Comma-separated timeframes (overrides TIMEFRAME/MULTI_TIMEFRAMES)")
    args = parser.parse_args()

    collector = Collector(
        symbols=_parse_csv_list(args.symbols) if args.symbols else None,
        timeframes=_parse_csv_list(args.timeframes) if args.timeframes else None,
    )
    collector.run()


if __name__ == "__main__":
    main()

