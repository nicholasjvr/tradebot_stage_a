"""
Database operations for storing market data
"""
import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Optional, Any, Iterable
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

        # -----------------------------
        # Stage B: Trading tables
        # -----------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mode TEXT NOT NULL,                 -- paper | live
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,                 -- buy | sell
                type TEXT NOT NULL,                 -- market | limit
                status TEXT NOT NULL,               -- open | closed | canceled | rejected | filled
                amount REAL,
                price REAL,
                filled REAL,
                average REAL,
                cost REAL,
                fee REAL,
                fee_currency TEXT,
                client_order_id TEXT,
                exchange_order_id TEXT,
                strategy TEXT,
                signal TEXT,
                reason TEXT,
                ts INTEGER,                         -- milliseconds
                raw_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                mode TEXT NOT NULL,
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                amount REAL NOT NULL,
                cost REAL NOT NULL,
                fee REAL,
                fee_currency TEXT,
                ts INTEGER,                         -- milliseconds
                raw_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(order_id) REFERENCES orders(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                mode TEXT NOT NULL,                 -- paper | live
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                base_qty REAL NOT NULL DEFAULT 0,
                avg_entry_price REAL,
                realized_pnl REAL NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (mode, exchange, symbol)
            )
        """)
        
        # Create indexes for faster queries
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_ohlcv_symbol_timeframe_timestamp "
            "ON ohlcv(symbol, timeframe, timestamp)"
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_timeframe ON ohlcv(symbol, timeframe)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ohlcv_timestamp ON ohlcv(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tickers_symbol ON tickers(symbol)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tickers_timestamp ON tickers(timestamp)")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_symbol_ts ON orders(symbol, ts)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_exchange_order_id ON orders(exchange_order_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fills_order_id ON fills(order_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol)")
        
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

    # -----------------------------
    # Stage B: Trading helpers
    # -----------------------------
    def get_latest_close(self, symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
        """Return latest OHLCV close + timestamp for symbol/timeframe."""
        self.connect()
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT timestamp, close
            FROM ohlcv
            WHERE symbol = ? AND timeframe = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (symbol, timeframe),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_recent_closes(self, symbol: str, timeframe: str, limit: int) -> List[Dict[str, Any]]:
        """Return most recent `limit` closes ordered ascending by timestamp."""
        self.connect()
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT timestamp, close
            FROM ohlcv
            WHERE symbol = ? AND timeframe = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (symbol, timeframe, limit),
        )
        rows = cursor.fetchall()
        # Reverse into chronological order
        return [dict(r) for r in reversed(rows)]

    def insert_order(
        self,
        *,
        mode: str,
        exchange: str,
        symbol: str,
        side: str,
        order_type: str,
        status: str,
        amount: Optional[float] = None,
        price: Optional[float] = None,
        filled: Optional[float] = None,
        average: Optional[float] = None,
        cost: Optional[float] = None,
        fee: Optional[float] = None,
        fee_currency: Optional[str] = None,
        client_order_id: Optional[str] = None,
        exchange_order_id: Optional[str] = None,
        strategy: Optional[str] = None,
        signal: Optional[str] = None,
        reason: Optional[str] = None,
        ts: Optional[int] = None,
        raw_json: Optional[str] = None,
    ) -> int:
        """Insert an order record and return its DB id."""
        self.connect()
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO orders (
                mode, exchange, symbol, side, type, status,
                amount, price, filled, average, cost,
                fee, fee_currency,
                client_order_id, exchange_order_id,
                strategy, signal, reason,
                ts, raw_json
            ) VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?, ?,
                ?, ?
            )
            """,
            (
                mode, exchange, symbol, side, order_type, status,
                amount, price, filled, average, cost,
                fee, fee_currency,
                client_order_id, exchange_order_id,
                strategy, signal, reason,
                ts, raw_json,
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def update_order(self, order_id: int, **fields: Any) -> None:
        """Update an order row with a whitelisted set of fields."""
        allowed = {
            "status", "filled", "average", "cost", "fee", "fee_currency",
            "client_order_id", "exchange_order_id", "raw_json", "ts", "price", "amount",
            "strategy", "signal", "reason",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        self.connect()
        cursor = self.conn.cursor()
        set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
        params: list[Any] = list(updates.values()) + [order_id]
        cursor.execute(f"UPDATE orders SET {set_clause} WHERE id = ?", params)
        self.conn.commit()

    def insert_fill(
        self,
        *,
        order_id: Optional[int],
        mode: str,
        exchange: str,
        symbol: str,
        side: str,
        price: float,
        amount: float,
        cost: float,
        fee: Optional[float] = None,
        fee_currency: Optional[str] = None,
        ts: Optional[int] = None,
        raw_json: Optional[str] = None,
    ) -> int:
        """Insert a fill record and return its DB id."""
        self.connect()
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO fills (
                order_id, mode, exchange, symbol, side,
                price, amount, cost,
                fee, fee_currency,
                ts, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id, mode, exchange, symbol, side,
                price, amount, cost,
                fee, fee_currency,
                ts, raw_json,
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def get_position(self, *, mode: str, exchange: str, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch current position row (if any)."""
        self.connect()
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT mode, exchange, symbol, base_qty, avg_entry_price, realized_pnl, updated_at
            FROM positions
            WHERE mode = ? AND exchange = ? AND symbol = ?
            """,
            (mode, exchange, symbol),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def upsert_position(
        self,
        *,
        mode: str,
        exchange: str,
        symbol: str,
        base_qty: float,
        avg_entry_price: Optional[float],
        realized_pnl: float,
    ) -> None:
        """Upsert position state."""
        self.connect()
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO positions (mode, exchange, symbol, base_qty, avg_entry_price, realized_pnl, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(mode, exchange, symbol) DO UPDATE SET
                base_qty = excluded.base_qty,
                avg_entry_price = excluded.avg_entry_price,
                realized_pnl = excluded.realized_pnl,
                updated_at = CURRENT_TIMESTAMP
            """,
            (mode, exchange, symbol, base_qty, avg_entry_price, realized_pnl),
        )
        self.conn.commit()

