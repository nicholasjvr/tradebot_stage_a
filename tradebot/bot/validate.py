"""
Data validation script - checks data quality and completeness
"""
import logging
import sys
from datetime import datetime, timedelta
from .db import Database
from .config import SYMBOLS, TIMEFRAME, DB_PATH

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class Validator:
    """Data validation class"""
    
    def __init__(self):
        """Initialize validator"""
        self.db = Database()
    
    def check_database_exists(self) -> bool:
        """Check if database file exists"""
        if not DB_PATH.exists():
            logger.error(f"Database file not found: {DB_PATH}")
            return False
        logger.info(f"[VALIDATOR] database_exists path={DB_PATH}")
        return True
    
    def check_table_counts(self):
        """Check record counts in tables"""
        self.db.connect()
        cursor = self.db.conn.cursor()
        
        # Check OHLCV counts
        cursor.execute("SELECT COUNT(*) as count FROM ohlcv")
        ohlcv_count = cursor.fetchone()['count']
        logger.info(f"[VALIDATOR] table=ohlcv count={ohlcv_count}")
        
        # Check ticker counts
        cursor.execute("SELECT COUNT(*) as count FROM tickers")
        ticker_count = cursor.fetchone()['count']
        logger.info(f"[VALIDATOR] table=tickers count={ticker_count}")
        
        # Count by symbol
        cursor.execute("""
            SELECT symbol, COUNT(*) as count 
            FROM ohlcv 
            GROUP BY symbol
        """)
        for row in cursor.fetchall():
            logger.info(f"[VALIDATOR] table=ohlcv symbol={row['symbol']} count={row['count']}")
    
    def check_data_gaps(self, symbol: str, hours: int = 24):
        """Check for gaps and regressions in data collection"""
        self.db.connect()
        cursor = self.db.conn.cursor()
        
        # Get timeframe in milliseconds
        timeframe_ms = self._timeframe_to_ms(TIMEFRAME)
        
        # Get data from last N hours
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = end_time - (hours * 3600 * 1000)
        
        cursor.execute("""
            SELECT timestamp 
            FROM ohlcv 
            WHERE symbol = ? AND timeframe = ? AND timestamp >= ?
            ORDER BY timestamp ASC
        """, (symbol, TIMEFRAME, start_time))
        
        timestamps = [row['timestamp'] for row in cursor.fetchall()]
        
        if not timestamps:
            logger.warning(f"[VALIDATOR] symbol={symbol} timeframe={TIMEFRAME} status=no_data window_hours={hours}")
            return
        
        gaps = []
        regressions = []
        for i in range(len(timestamps) - 1):
            gap = timestamps[i + 1] - timestamps[i]
            if gap > timeframe_ms:  # any gap bigger than one candle interval is suspicious
                gaps.append({
                    'start': timestamps[i],
                    'end': timestamps[i + 1],
                    'gap_ms': gap,
                    'gap_candles': gap / timeframe_ms
                })
            if timestamps[i + 1] <= timestamps[i]:
                regressions.append({
                    'prev': timestamps[i],
                    'curr': timestamps[i + 1]
                })
        
        if gaps:
            logger.warning(f"[VALIDATOR] symbol={symbol} timeframe={TIMEFRAME} gaps_detected={len(gaps)}")
            for gap in gaps[:10]:  # Show first 10 gaps
                start_dt = datetime.fromtimestamp(gap['start'] / 1000)
                end_dt = datetime.fromtimestamp(gap['end'] / 1000)
                logger.warning(
                    f"[VALIDATOR] symbol={symbol} gap_start={start_dt.isoformat()} gap_end={end_dt.isoformat()} "
                    f"missing_candles={gap['gap_candles']:.1f}"
                )
        else:
            logger.info(f"[VALIDATOR] symbol={symbol} timeframe={TIMEFRAME} gaps_detected=0")

        if regressions:
            logger.error(f"[VALIDATOR] symbol={symbol} regressions_detected={len(regressions)} (timestamps not strictly increasing)")
            for reg in regressions[:10]:
                prev_dt = datetime.fromtimestamp(reg['prev'] / 1000)
                curr_dt = datetime.fromtimestamp(reg['curr'] / 1000)
                logger.error(f"[VALIDATOR] symbol={symbol} regression prev={prev_dt.isoformat()} curr={curr_dt.isoformat()}")
        else:
            logger.info(f"[VALIDATOR] symbol={symbol} regressions_detected=0")
    
    def check_latest_data(self):
        """Check when data was last collected"""
        self.db.connect()
        cursor = self.db.conn.cursor()
        
        cursor.execute("""
            SELECT symbol, MAX(timestamp) as latest_ts 
            FROM ohlcv 
            GROUP BY symbol
        """)
        
        now = datetime.now()
        for row in cursor.fetchall():
            if row['latest_ts']:
                latest_dt = datetime.fromtimestamp(row['latest_ts'] / 1000)
                age = now - latest_dt
                age_minutes = age.total_seconds() / 60
                
                status = "fresh" if age_minutes < 5 else "stale"
                logger.info(f"[VALIDATOR] symbol={row['symbol']} latest_ts={latest_dt.isoformat()} age_min={age_minutes:.1f} status={status}")
            else:
                logger.warning(f"[VALIDATOR] symbol={row['symbol']} status=no_data")
    
    def check_data_quality(self, symbol: str):
        """Check data quality (nulls, zeros, etc.)"""
        self.db.connect()
        cursor = self.db.conn.cursor()
        
        # Check for null values
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM ohlcv 
            WHERE symbol = ? AND (
                open IS NULL OR high IS NULL OR low IS NULL OR 
                close IS NULL OR volume IS NULL
            )
        """, (symbol,))
        null_count = cursor.fetchone()['count']
        
        if null_count > 0:
            logger.warning(f"[VALIDATOR] symbol={symbol} null_values={null_count}")
        else:
            logger.info(f"[VALIDATOR] symbol={symbol} null_values=0")
        
        # Check for zero volume
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM ohlcv 
            WHERE symbol = ? AND volume = 0
        """, (symbol,))
        zero_vol_count = cursor.fetchone()['count']
        
        if zero_vol_count > 0:
            logger.warning(f"[VALIDATOR] symbol={symbol} zero_volume={zero_vol_count}")
        
        # Check for invalid OHLC relationships
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM ohlcv 
            WHERE symbol = ? AND (
                high < low OR 
                high < open OR 
                high < close OR
                low > open OR
                low > close
            )
        """, (symbol,))
        invalid_count = cursor.fetchone()['count']
        
        if invalid_count > 0:
            logger.error(f"[VALIDATOR] symbol={symbol} invalid_ohlc={invalid_count}")
        else:
            logger.info(f"[VALIDATOR] symbol={symbol} invalid_ohlc=0")
    
    def _timeframe_to_ms(self, timeframe: str) -> int:
        """Convert timeframe string to milliseconds"""
        unit = timeframe[-1]
        value = int(timeframe[:-1])
        
        multipliers = {
            'm': 60 * 1000,
            'h': 3600 * 1000,
            'd': 86400 * 1000,
            'w': 7 * 86400 * 1000
        }
        
        return value * multipliers.get(unit, 60 * 1000)
    
    def run_all_checks(self):
        """Run all validation checks"""
        logger.info("=" * 60)
        logger.info("Data Validation Report")
        logger.info("=" * 60)
        
        if not self.check_database_exists():
            return
        
        self.db.connect()
        
        logger.info("[VALIDATOR] step=record_counts")
        self.check_table_counts()
        
        logger.info("[VALIDATOR] step=latest_data")
        self.check_latest_data()
        
        logger.info("[VALIDATOR] step=data_quality")
        for symbol in SYMBOLS:
            symbol = symbol.strip()
            self.check_data_quality(symbol)
        
        logger.info("[VALIDATOR] step=data_gaps window_hours=24")
        for symbol in SYMBOLS:
            symbol = symbol.strip()
            self.check_data_gaps(symbol, hours=24)
        
        self.db.close()
        logger.info("=" * 60)
        logger.info("Validation complete")


def main():
    """Main entry point"""
    validator = Validator()
    validator.run_all_checks()


if __name__ == "__main__":
    main()

