"""
Database operations for storing market data
"""
import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path
from .config import DB_PATH

logger = logging.getLogger(__name__)


class Database:
    """SQLite database interface for market data"""
    
    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize database connection
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path or DB_PATH
        self.conn = None
        logger.info(f"Database initialized at {self.db_path}")
    
    def connect(self):
        """Establish database connection"""
        if self.conn is None:
            self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self.conn.row_factory = sqlite3.Row  # Return rows as dictionaries
            # Harden SQLite for concurrent safe writes
            self.conn.execute("PRAGMA journal_mode=WAL;")
            self.conn.execute("PRAGMA synchronous=NORMAL;")
            self.conn.execute("PRAGMA busy_timeout=5000;")
            logger.debug("Database connection established (WAL enabled)")
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None
            logger.debug("Database connection closed")
    
    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()
    
    def create_tables(self):
        """Create database tables if they don't exist"""
        self.connect()
        cursor = self.conn.cursor()
        
        # OHLCV data table (deterministic composite primary key)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ohlcv (
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                close_time INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (symbol, timeframe, timestamp)
            )
        """)
        # Backward-compat: ensure close_time exists if table was created before this version
        cursor.execute("PRAGMA table_info(ohlcv)")
        existing_cols = {row['name'] for row in cursor.fetchall()}
        if 'close_time' not in existing_cols:
            cursor.execute("ALTER TABLE ohlcv ADD COLUMN close_time INTEGER")
        
        # Ticker data table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tickers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                bid REAL,
                ask REAL,
                last REAL,
                high REAL,
                low REAL,
                open REAL,
                close REAL,
                volume REAL,
                quote_volume REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, timestamp)
            )
        """)
        
        # Create indexes for faster queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_timeframe ON ohlcv(symbol, timeframe)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ohlcv_timestamp ON ohlcv(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tickers_symbol ON tickers(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tickers_timestamp ON tickers(timestamp)")
        
        self.conn.commit()
        logger.info("Database tables created/verified")
    
    def insert_ohlcv(self, symbol: str, timeframe: str, ohlcv_data: List[List]):
        """
        Insert OHLCV data into database
        
        Args:
            symbol: Trading pair (e.g., 'BTC/USDT')
            timeframe: Timeframe (e.g., '1m')
            ohlcv_data: List of [timestamp, open, high, low, close, volume]
        """
        self.connect()
        cursor = self.conn.cursor()
        
        inserted = 0
        updated = 0
        timeframe_ms = self._timeframe_to_ms(timeframe)
        
        for candle in ohlcv_data:
            timestamp, open_price, high, low, close_price, volume = candle
            close_time = timestamp + timeframe_ms - 1
            
            try:
                # Detect existing row to log insert vs update
                cursor.execute("""
                    SELECT 1 FROM ohlcv WHERE symbol = ? AND timeframe = ? AND timestamp = ?
                """, (symbol, timeframe, timestamp))
                exists = cursor.fetchone() is not None

                cursor.execute("""
                    INSERT INTO ohlcv (symbol, timeframe, timestamp, open, high, low, close, volume, close_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(symbol, timeframe, timestamp) DO UPDATE SET
                        open=excluded.open,
                        high=excluded.high,
                        low=excluded.low,
                        close=excluded.close,
                        volume=excluded.volume,
                        close_time=excluded.close_time
                """, (symbol, timeframe, timestamp, open_price, high, low, close_price, volume, close_time))
                
                if exists:
                    updated += 1
                else:
                    inserted += 1
            except Exception as e:
                logger.error(f"Error inserting OHLCV data: {e}")
        
        self.conn.commit()
        logger.debug(f"Inserted {inserted} OHLCV records, updated {updated} existing for {symbol}")
        return inserted, updated
    
    def insert_ticker(self, symbol: str, ticker_data: Dict):
        """
        Insert ticker data into database
        
        Args:
            symbol: Trading pair (e.g., 'BTC/USDT')
            ticker_data: Ticker dictionary from exchange
        """
        self.connect()
        cursor = self.conn.cursor()
        
        timestamp = ticker_data.get('timestamp') or int(datetime.now().timestamp() * 1000)
        
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO tickers 
                (symbol, timestamp, bid, ask, last, high, low, open, close, volume, quote_volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol,
                timestamp,
                ticker_data.get('bid'),
                ticker_data.get('ask'),
                ticker_data.get('last'),
                ticker_data.get('high'),
                ticker_data.get('low'),
                ticker_data.get('open'),
                ticker_data.get('close'),
                ticker_data.get('baseVolume'),
                ticker_data.get('quoteVolume')
            ))
            
            self.conn.commit()
            logger.debug(f"Inserted ticker data for {symbol}")
        except Exception as e:
            logger.error(f"Error inserting ticker data: {e}")
            raise
    
    def get_latest_timestamp(self, symbol: str, timeframe: str) -> Optional[int]:
        """
        Get the latest timestamp for a symbol/timeframe
        
        Args:
            symbol: Trading pair
            timeframe: Timeframe
        
        Returns:
            Latest timestamp in milliseconds, or None if no data exists
        """
        self.connect()
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT MAX(timestamp) as max_ts FROM ohlcv
            WHERE symbol = ? AND timeframe = ?
        """, (symbol, timeframe))
        
        result = cursor.fetchone()
        return result['max_ts'] if result and result['max_ts'] else None

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
    
    def get_ohlcv(self, symbol: str, timeframe: str, start_time: Optional[int] = None, 
                  end_time: Optional[int] = None, limit: Optional[int] = None) -> List[Dict]:
        """
        Retrieve OHLCV data from database
        
        Args:
            symbol: Trading pair
            timeframe: Timeframe
            start_time: Start timestamp (milliseconds)
            end_time: End timestamp (milliseconds)
            limit: Maximum number of records
        
        Returns:
            List of OHLCV records as dictionaries
        """
        self.connect()
        cursor = self.conn.cursor()
        
        query = "SELECT * FROM ohlcv WHERE symbol = ? AND timeframe = ?"
        params = [symbol, timeframe]
        
        if start_time:
            query += " AND timestamp >= ?"
            params.append(start_time)
        
        if end_time:
            query += " AND timestamp <= ?"
            params.append(end_time)
        
        query += " ORDER BY timestamp ASC"
        
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        return [dict(row) for row in rows]

