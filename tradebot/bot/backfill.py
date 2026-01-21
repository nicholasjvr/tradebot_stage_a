"""
One-shot backfill utility.

This is useful after the collector has been stopped for some time: it will fetch
any missing OHLCV candles and write them into the SQLite DB, then exit.
"""

import argparse
import logging
import sys
from datetime import datetime

from .config import SYMBOLS, TIMEFRAME, EXCHANGE_NAME
from .db import Database
from .exchange import Exchange


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def _now_ms() -> int:
    return int(datetime.now().timestamp() * 1000)


def _backfill_symbol(exchange: Exchange, db: Database, symbol: str, timeframe: str, since: int | None) -> tuple[int, int, int]:
    """
    Backfill OHLCV for a symbol until caught up.

    Returns:
        (total_fetched, total_inserted, total_updated)
    """
    latest_ts = db.get_latest_timestamp(symbol, timeframe)
    effective_since = since
    if effective_since is None and latest_ts:
        effective_since = latest_ts + 1

    total_fetched = 0
    total_inserted = 0
    total_updated = 0

    while True:
        ohlcv_batch = exchange.fetch_ohlcv(
            symbol,
            timeframe,
            limit=500,
            since=effective_since,
        )
        if not ohlcv_batch:
            break

        fetched = len(ohlcv_batch)
        total_fetched += fetched

        inserted, updated = db.insert_ohlcv(symbol, timeframe, ohlcv_batch)
        total_inserted += inserted
        total_updated += updated

        latest_open_time = ohlcv_batch[-1][0]
        effective_since = latest_open_time + 1

        # If batch smaller than limit, we are caught up for this since-window.
        if fetched < 500:
            break

    return total_fetched, total_inserted, total_updated


def main():
    parser = argparse.ArgumentParser(description="Backfill missed OHLCV candles into the SQLite DB, then exit.")
    parser.add_argument("--symbol", type=str, help="Symbol to backfill (default: all configured symbols)")
    parser.add_argument("--timeframe", type=str, default=TIMEFRAME, help=f"Timeframe (default: {TIMEFRAME})")
    parser.add_argument("--since", type=int, help="Start timestamp in ms (overrides DB latest_ts logic)")
    parser.add_argument("--hours", type=float, help="Backfill from now-hours (overrides DB latest_ts logic)")
    args = parser.parse_args()

    timeframe = args.timeframe
    if args.hours is not None:
        since = _now_ms() - int(args.hours * 3600 * 1000)
    else:
        since = args.since

    exchange = Exchange()
    db = Database()
    db.create_tables()

    symbols = [args.symbol] if args.symbol else [s.strip() for s in SYMBOLS]

    valid_symbols: list[str] = []
    for s in symbols:
        if exchange.validate_symbol(s):
            valid_symbols.append(s)
            logger.info(f"[BACKFILL] symbol={s} status=available exchange={EXCHANGE_NAME}")
        else:
            logger.warning(f"[BACKFILL] symbol={s} status=unavailable exchange={EXCHANGE_NAME}")

    if not valid_symbols:
        logger.error("No valid symbols to backfill. Check SYMBOLS / --symbol.")
        sys.exit(1)

    for s in valid_symbols:
        try:
            total_fetched, total_inserted, total_updated = _backfill_symbol(exchange, db, s, timeframe, since)
            logger.info(
                f"[BACKFILL] symbol={s} timeframe={timeframe} fetched={total_fetched} "
                f"inserted={total_inserted} updated={total_updated} since={since}"
            )
        except Exception as e:
            logger.error(f"[BACKFILL] symbol={s} error={e}", exc_info=True)

    db.close()
    logger.info("[BACKFILL] done")


if __name__ == "__main__":
    main()

