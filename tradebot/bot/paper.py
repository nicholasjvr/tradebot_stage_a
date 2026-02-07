"""
Paper trading execution engine.

Records orders/fills/positions into SQLite using `bot.db.Database`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .db import Database

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PaperFill:
    order_id: int
    symbol: str
    side: str
    price: float
    amount: float
    cost: float
    fee: float
    fee_currency: str
    ts: int


def _now_ms() -> int:
    return int(datetime.now().timestamp() * 1000)


def paper_buy_fixed_quote(
    *,
    db: Database,
    exchange: str,
    symbol: str,
    quote_amount: float,
    price: float,
    fee_rate: float,
    timeframe: str,
    strategy: str,
    signal: str,
    reason: str,
    order_type: str = "market",
    ts: Optional[int] = None,
) -> PaperFill:
    """
    Simulate a BUY using a fixed quote amount at `price`.
    Fee model: quote-based fee (fee = cost * fee_rate).
    """
    mode = "paper"
    ts = int(ts if ts is not None else _now_ms())

    base_amount = quote_amount / price
    cost = quote_amount
    fee = cost * fee_rate
    fee_currency = "USDT"

    # Insert order
    order_id = db.insert_order(
        mode=mode,
        exchange=exchange,
        symbol=symbol,
        side="buy",
        order_type=order_type,
        status="filled",
        amount=base_amount,
        price=price,
        filled=base_amount,
        average=price,
        cost=cost,
        fee=fee,
        fee_currency=fee_currency,
        strategy=strategy,
        signal=signal,
        reason=reason,
        ts=ts,
        raw_json=json.dumps(
            {"engine": "paper", "quote_amount": quote_amount, "fee_rate": fee_rate, "timeframe": timeframe},
            separators=(",", ":"),
        ),
    )

    db.insert_fill(
        order_id=order_id,
        mode=mode,
        exchange=exchange,
        symbol=symbol,
        side="buy",
        price=price,
        amount=base_amount,
        cost=cost,
        fee=fee,
        fee_currency=fee_currency,
        ts=ts,
        raw_json=None,
    )

    pos = db.get_position(mode=mode, exchange=exchange, symbol=symbol) or {
        "base_qty": 0.0,
        "avg_entry_price": None,
        "realized_pnl": 0.0,
    }
    old_qty = float(pos["base_qty"] or 0.0)
    old_avg = pos["avg_entry_price"]
    old_avg_f = float(old_avg) if old_avg is not None else 0.0
    realized = float(pos["realized_pnl"] or 0.0)

    new_qty = old_qty + base_amount
    if new_qty <= 0:
        new_avg = None
    elif old_qty <= 0:
        new_avg = price
    else:
        new_avg = ((old_qty * old_avg_f) + (base_amount * price)) / new_qty

    db.upsert_position(
        mode=mode,
        exchange=exchange,
        symbol=symbol,
        base_qty=new_qty,
        avg_entry_price=new_avg,
        realized_pnl=realized,
    )

    logger.info(
        f"[PAPER] symbol={symbol} side=buy quote={quote_amount:.2f} price={price:.6f} "
        f"base={base_amount:.8f} fee={fee:.6f} pos_base={new_qty:.8f}"
    )

    return PaperFill(
        order_id=order_id,
        symbol=symbol,
        side="buy",
        price=float(price),
        amount=float(base_amount),
        cost=float(cost),
        fee=float(fee),
        fee_currency=fee_currency,
        ts=ts,
    )


def paper_sell_all(
    *,
    db: Database,
    exchange: str,
    symbol: str,
    price: float,
    fee_rate: float,
    timeframe: str,
    strategy: str,
    signal: str,
    reason: str,
    order_type: str = "market",
    ts: Optional[int] = None,
) -> Optional[PaperFill]:
    """
    Simulate a SELL of the entire position at `price`.
    Fee model: quote-based fee (fee = proceeds * fee_rate).
    """
    mode = "paper"
    ts = int(ts if ts is not None else _now_ms())

    pos = db.get_position(mode=mode, exchange=exchange, symbol=symbol)
    if not pos or float(pos["base_qty"] or 0.0) <= 0:
        logger.info(f"[PAPER] symbol={symbol} side=sell status=skipped reason=no_position")
        return None

    base_amount = float(pos["base_qty"])
    avg_entry = pos["avg_entry_price"]
    avg_entry_price = float(avg_entry) if avg_entry is not None else None
    realized = float(pos["realized_pnl"] or 0.0)

    proceeds = base_amount * price
    fee = proceeds * fee_rate
    fee_currency = "USDT"

    trade_pnl = 0.0
    if avg_entry_price is not None:
        trade_pnl = (price - avg_entry_price) * base_amount - fee
    new_realized = realized + trade_pnl

    order_id = db.insert_order(
        mode=mode,
        exchange=exchange,
        symbol=symbol,
        side="sell",
        order_type=order_type,
        status="filled",
        amount=base_amount,
        price=price,
        filled=base_amount,
        average=price,
        cost=proceeds,
        fee=fee,
        fee_currency=fee_currency,
        strategy=strategy,
        signal=signal,
        reason=reason,
        ts=ts,
        raw_json=json.dumps(
            {"engine": "paper", "fee_rate": fee_rate, "timeframe": timeframe, "avg_entry_price": avg_entry_price},
            separators=(",", ":"),
        ),
    )

    db.insert_fill(
        order_id=order_id,
        mode=mode,
        exchange=exchange,
        symbol=symbol,
        side="sell",
        price=price,
        amount=base_amount,
        cost=proceeds,
        fee=fee,
        fee_currency=fee_currency,
        ts=ts,
        raw_json=None,
    )

    db.upsert_position(
        mode=mode,
        exchange=exchange,
        symbol=symbol,
        base_qty=0.0,
        avg_entry_price=None,
        realized_pnl=new_realized,
    )

    logger.info(
        f"[PAPER] symbol={symbol} side=sell base={base_amount:.8f} price={price:.6f} "
        f"fee={fee:.6f} trade_pnl={trade_pnl:.6f} realized_pnl={new_realized:.6f}"
    )

    return PaperFill(
        order_id=order_id,
        symbol=symbol,
        side="sell",
        price=float(price),
        amount=float(base_amount),
        cost=float(proceeds),
        fee=float(fee),
        fee_currency=fee_currency,
        ts=ts,
    )

