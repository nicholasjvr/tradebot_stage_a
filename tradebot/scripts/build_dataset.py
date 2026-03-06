"""
Build training dataset from OHLCV data.

Extracts features and labels for supervised ML strategy.
Run from project root: python scripts/build_dataset.py --symbol BTC/USDT --timeframe 7m ...
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.db import Database
from bot.features import build_features, FEATURE_NAMES


def generate_labels(
    closes: list[float],
    lookback: int,
    forward_candles: int,
    min_return: float,
) -> list[int]:
    """
    Generate labels for each feature row.

    Label = 1 (long) if close[i+N] > close[i] * (1 + min_return), else 0 (flat).
    Drops last forward_candles rows (no future data).
    """
    n = len(closes)
    n_rows = n - lookback - forward_candles
    if n_rows <= 0:
        return []

    labels = []
    for j in range(n_rows):
        i = lookback + j
        c_now = closes[i]
        c_future = closes[i + forward_candles]
        threshold = c_now * (1 + min_return)
        labels.append(1 if c_future > threshold else 0)
    return labels


def main():
    parser = argparse.ArgumentParser(description="Build ML training dataset from OHLCV")
    parser.add_argument("--symbol", type=str, default="BTC/USDT", help="Trading pair")
    parser.add_argument("--timeframe", type=str, default="7m", help="Candle timeframe")
    parser.add_argument("--lookback", type=int, default=60, help="Feature lookback window")
    parser.add_argument("--forward", type=int, default=5, help="Forward candles for label")
    parser.add_argument("--min-return", type=float, default=0.001, help="Min price rise for long label (0.001=0.1%%)")
    parser.add_argument("--limit", type=int, default=10000, help="Max OHLCV rows to fetch")
    parser.add_argument("--output", type=Path, default=Path("data/training.csv"), help="Output CSV path")
    parser.add_argument("--symbols", type=str, help="Comma-separated symbols (overrides --symbol)")
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",")] if args.symbols else [args.symbol]
    args.output.parent.mkdir(parents=True, exist_ok=True)

    db = Database()
    db.connect()

    all_rows = []
    for symbol in symbols:
        rows = db.get_recent_ohlcv(symbol, args.timeframe, limit=args.limit)
        if len(rows) < args.lookback + args.forward + 100:
            print(f"[WARN] symbol={symbol} insufficient data: have={len(rows)} need={args.lookback + args.forward + 100}")
            continue

        closes = [float(r["close"]) for r in rows]
        X, timestamps = build_features(rows, lookback=args.lookback)
        y = generate_labels(closes, args.lookback, args.forward, args.min_return)

        n_keep = min(len(X), len(y))
        X = X[:n_keep]
        timestamps = timestamps[:n_keep]
        y = y[:n_keep]

        for i in range(n_keep):
            row = {fn: X[i, j] for j, fn in enumerate(FEATURE_NAMES)}
            row["label"] = y[i]
            row["timestamp"] = timestamps[i]
            row["symbol"] = symbol
            all_rows.append(row)

    db.close()

    if len(all_rows) < 500:
        print(f"[ERROR] Insufficient rows after processing: {len(all_rows)}. Need at least 500.")
        sys.exit(1)

    columns = ["symbol", "timestamp"] + FEATURE_NAMES + ["label"]
    with open(args.output, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(all_rows)

    print(f"[OK] Wrote {len(all_rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
