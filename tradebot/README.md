# Tradebot - Cryptocurrency Market Data Collector

A lightweight cryptocurrency market data collector designed to run on a Raspberry Pi, collecting OHLCV and ticker data from exchanges using the ccxt library.

## Features

- 📊 Collects OHLCV (candlestick) data at configurable timeframes
- 📈 Collects real-time ticker data
- 💾 Stores data in SQLite database (single file, perfect for Pi)
- 🔄 Continuous data collection with configurable intervals
- ✅ Data validation and quality checks
- 📉 Built-in plotting capabilities
- 🚀 Systemd service support for auto-start

## Quick Start

### 1. Installation

```bash
# Clone or navigate to the project directory
cd tradebot

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration

Edit `.env` file:

```bash
# Exchange Configuration
EXCHANGE_NAME=binance
EXCHANGE_API_KEY=          # Optional for public data
EXCHANGE_SECRET=           # Optional for public data
EXCHANGE_SANDBOX=false

# Trading Configuration
SYMBOLS=BTC/USDT,ETH/USDT  # Comma-separated list
TIMEFRAME=1m               # 1m, 5m, 15m, 1h, 4h, 1d, etc.
COLLECTION_INTERVAL=60     # Seconds between collection cycles
```

### 3. Initialize Database

```bash
python scripts/init_db.py
```

This creates the SQLite database file at `db/marketdata.sqlite` with the required tables.

### 4. Run Collector

```bash
# Run once (for testing)
python -m bot.collector

# Or run continuously (default behavior)
python -m bot.collector
```

The collector will:
- Connect to the configured exchange
- Validate symbols
- Collect OHLCV and ticker data at the specified interval
- Store data in the SQLite database
- Log activity to `logs/collector_YYYYMMDD.log`

## Usage

### Data Collection

Start the collector:

```bash
python -m bot.collector
```

The collector runs continuously, collecting data every `COLLECTION_INTERVAL` seconds. Press `Ctrl+C` to stop gracefully.

### Data Validation

Check data quality and completeness:

```bash
python -m bot.validate
```

This will show:
- Record counts
- Latest data timestamps
- Data quality checks (nulls, invalid OHLC relationships)
- Data gaps in the last 24 hours

### Plotting

Plot OHLCV candlestick charts:

```bash
# Plot all symbols (last 24 hours)
python -m bot.plot

# Plot specific symbol
python -m bot.plot --symbol BTC/USDT --hours 24

# Plot and save to file
python -m bot.plot --symbol BTC/USDT --hours 12 --save plots/btc_12h.png

# Plot price trend instead of candlesticks
python -m bot.plot --symbol BTC/USDT --type trend
```

## Database Schema

### OHLCV Table

Stores candlestick data:

- `id`: Primary key
- `symbol`: Trading pair (e.g., 'BTC/USDT')
- `timeframe`: Timeframe (e.g., '1m')
- `timestamp`: Unix timestamp in milliseconds
- `open`, `high`, `low`, `close`: OHLC prices
- `volume`: Trading volume
- `created_at`: Record creation timestamp

### Tickers Table

Stores ticker/snapshot data:

- `id`: Primary key
- `symbol`: Trading pair
- `timestamp`: Unix timestamp in milliseconds
- `bid`, `ask`, `last`: Bid/ask/last prices
- `high`, `low`, `open`, `close`: Price data
- `volume`, `quote_volume`: Volume data
- `created_at`: Record creation timestamp

## Systemd Service

To run the collector as a systemd service on Linux:

1. Copy the service file:

```bash
sudo cp tradebot.service /etc/systemd/system/
```

2. Edit the service file to match your paths:

```bash
sudo nano /etc/systemd/system/tradebot.service
```

Update `WorkingDirectory` and `ExecStart` paths.

3. Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable tradebot.service
sudo systemctl start tradebot.service
```

4. Check status:

```bash
sudo systemctl status tradebot.service
```

5. View logs:

```bash
sudo journalctl -u tradebot.service -f
```

## Project Structure

```
tradebot/
├── bot/
│   ├── __init__.py       # Package initialization
│   ├── config.py         # Configuration management
│   ├── exchange.py       # Exchange interface (ccxt)
│   ├── db.py             # Database operations
│   ├── collector.py      # Main collection script
│   ├── validate.py       # Data validation
│   └── plot.py           # Plotting utilities
├── db/
│   └── marketdata.sqlite # SQLite database (created by init)
├── logs/                 # Log files
├── scripts/
│   └── init_db.py        # Database initializer
├── .env                  # Environment variables
├── requirements.txt      # Python dependencies
├── README.md            # This file
└── tradebot.service      # Systemd service config
```

## Tips

- **No API keys needed**: For Binance, you can collect public OHLCV and ticker data without API keys
- **Start small**: Begin with 2-3 symbols and 1-minute timeframe to test
- **Monitor logs**: Check `logs/` directory regularly for any issues
- **Validate data**: Run `validate.py` periodically to ensure data quality
- **Storage**: SQLite files can grow large over time. Consider archiving old data periodically
- **Raspberry Pi**: Works great on Pi 4 with 4GB+ RAM. Monitor CPU/memory usage initially

## Troubleshooting

### "No valid symbols found"
- Check that symbols are correctly formatted (e.g., 'BTC/USDT' not 'BTCUSDT')
- Verify exchange name is correct
- Check internet connection

### "Database locked" errors
- Ensure only one collector instance is running
- Check for stale database connections

### High memory usage
- Reduce number of symbols
- Increase `COLLECTION_INTERVAL` to collect less frequently
- Consider archiving old data

## License

MIT License - feel free to use and modify as needed!

