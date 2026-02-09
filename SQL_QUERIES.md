# Entering SQL and Running a Few Queries

This guide shows how to open your tradebot’s SQLite database and run some useful SQL queries. Handy for inspecting market data, orders, and positions without writing Python.

---

## 1. Entering SQL (SQLite shell)

Your tradebot stores data in **SQLite** at `tradebot/db/marketdata.sqlite`. To run SQL interactively, use the `sqlite3` command-line tool.

### On your Raspberry Pi (e.g. from USB project path)

From the project root (e.g. `/mnt/usb/projects/tradebot_stage_a`):

```bash
cd tradebot
sqlite3 db/marketdata.sqlite
```

If the DB file doesn’t exist yet, run `python -m scripts.init_db` first from the `tradebot` directory.

### On Windows (from your project folder)

From the repo root, in PowerShell or Command Prompt:

```powershell
cd tradebot
sqlite3 db\marketdata.sqlite
```

(If `sqlite3` isn’t in your PATH, use the full path to the sqlite3 executable or install SQLite and add it to PATH.)

Once the shell opens, you’ll see a prompt like:

```text
SQLite version 3.x.x
Enter ".help" for usage hints.
sqlite>
```

You’re now in the SQLite shell and can type SQL (and SQLite dot-commands).

### Useful SQLite shell commands

| Command        | Description                    |
|----------------|--------------------------------|
| `.tables`      | List all tables                |
| `.schema`      | Show CREATE statements         |
| `.schema ohlcv`| Show schema for table `ohlcv`  |
| `.headers on`  | Show column names in results   |
| `.mode column`  | Pretty column-aligned output   |
| `.quit` or `.exit` | Exit the shell             |

---

## 2. A Few SQL Queries (using your tradebot tables)

Your DB has tables such as: **ohlcv**, **tickers**, **orders**, **fills**, **positions**. Below are example queries you can paste into the `sqlite>` prompt (after `.headers on` and optionally `.mode column`).

### List tables

```sql
SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name;
```

### OHLCV: recent candles for one symbol/timeframe

```sql
SELECT symbol, timeframe, timestamp, open, high, low, close, volume
FROM ohlcv
WHERE symbol = 'BTC/USDT' AND timeframe = '1m'
ORDER BY timestamp DESC
LIMIT 20;
```

### OHLCV: count rows per symbol and timeframe

```sql
SELECT symbol, timeframe, COUNT(*) AS candle_count
FROM ohlcv
GROUP BY symbol, timeframe
ORDER BY symbol, timeframe;
```

### Tickers: latest tick per symbol

```sql
SELECT symbol, timestamp, bid, ask, last, volume
FROM tickers
ORDER BY timestamp DESC
LIMIT 10;
```

### Orders: recent orders (paper or live)

```sql
SELECT id, mode, symbol, side, type, status, amount, price, filled, ts, created_at
FROM orders
ORDER BY ts DESC
LIMIT 15;
```

### Positions: current positions

```sql
SELECT mode, exchange, symbol, base_qty, avg_entry_price, realized_pnl, updated_at
FROM positions
ORDER BY symbol;
```

### Fills: recent fills with order link

```sql
SELECT f.id, f.symbol, f.side, f.price, f.amount, f.cost, f.ts, f.order_id
FROM fills f
ORDER BY f.ts DESC
LIMIT 10;
```

---

## 3. Running a single query from the command line (no shell)

You can run one query without opening the interactive shell:

```bash
sqlite3 db/marketdata.sqlite "SELECT symbol, timeframe, COUNT(*) FROM ohlcv GROUP BY symbol, timeframe;"
```

On Windows, use the same with backslashes for the path if needed:

```powershell
sqlite3 db\marketdata.sqlite "SELECT symbol, timeframe, COUNT(*) FROM ohlcv GROUP BY symbol, timeframe;"
```

---

## 4. Quick reference: main columns

| Table     | Main columns (summary) |
|----------|-------------------------|
| **ohlcv**   | symbol, timeframe, timestamp, open, high, low, close, volume, close_time |
| **tickers** | symbol, timestamp, bid, ask, last, high, low, volume, quote_volume |
| **orders**  | mode, exchange, symbol, side, type, status, amount, price, filled, ts |
| **fills**   | order_id, symbol, side, price, amount, cost, fee, ts |
| **positions** | mode, exchange, symbol, base_qty, avg_entry_price, realized_pnl |

---

**Tip:** Run `.headers on` and `.mode column` in the SQLite shell before running the SELECTs above for readable, column-labeled output.

---

## 5. Viewing SQL results as charts in a web app

The tradebot API can turn SQL-backed data into charts you view in a browser:

1. **Start the API** (from the `tradebot` directory):
   ```bash
   python api.py
   ```
2. **Open the dashboard:** [http://localhost:5000/dashboard](http://localhost:5000/dashboard)

The dashboard uses:
- **OHLCV chart** – data from the `/ohlcv` endpoint (SQL: `SELECT * FROM ohlcv WHERE symbol=? …`).
- **Candle counts chart** – data from `/chart/candle_counts` (SQL: `SELECT symbol, timeframe, COUNT(*) FROM ohlcv GROUP BY symbol, timeframe`).

So the flow is: **SQL (in the API) → JSON → Chart.js in the browser**. To add more charts, add a new endpoint in `api.py` that runs a query and returns JSON, then add a new chart on the dashboard that fetches that URL and plots the result.


SELECT symbol, timeframe, timestamp, open, high, low, close, volume
FROM ohlcv
WHERE symbol = 'BTC/USDT' AND timeframe = '10m'
ORDER BY timestamp DESC
LIMIT 10;