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
            logger.debug("Database connection established")
    
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
        
        # OHLCV data table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ohlcv (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, timeframe, timestamp)
            )
        """)
        
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
        skipped = 0
        
        for candle in ohlcv_data:
            timestamp, open_price, high, low, close_price, volume = candle
            
            try:
                cursor.execute("""
                    INSERT OR IGNORE INTO ohlcv 
                    (symbol, timeframe, timestamp, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (symbol, timeframe, timestamp, open_price, high, low, close_price, volume))
                
                if cursor.rowcount > 0:
                    inserted += 1
                else:
                    skipped += 1
            except Exception as e:
                logger.error(f"Error inserting OHLCV data: {e}")
                skipped += 1
        
        self.conn.commit()
        logger.debug(f"Inserted {inserted} OHLCV records, skipped {skipped} duplicates for {symbol}")
        return inserted, skipped
    
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

