"""
Simple SMA crossover strategy utilities.

v1 approach (intentionally simple):
- Compute fast/slow SMA on recent closes from SQLite.
- Desired state: long when fast_sma > slow_sma, otherwise flat.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Optional


@dataclass(frozen=True)
class SmaSignal:
    symbol: str
    timeframe: str
    fast_window: int
    slow_window: int
    fast_sma: float
    slow_sma: float
    should_be_long: bool
    latest_close: float
    latest_ts: int


def _sma(values: Sequence[float], window: int) -> float:
    if window <= 0:
        raise ValueError("window must be > 0")
    if len(values) < window:
        raise ValueError(f"need at least {window} values to compute SMA")
    return sum(values[-window:]) / window


def compute_sma_signal(
    *,
    symbol: str,
    timeframe: str,
    closes: Sequence[float],
    timestamps: Sequence[int],
    fast_window: int,
    slow_window: int,
) -> SmaSignal:
    """
    Compute the SMA signal from close series.

    Args:
        closes: chronological closes (oldest->newest)
        timestamps: matching chronological timestamps (ms)
    """
    if len(closes) != len(timestamps):
        raise ValueError("closes and timestamps length mismatch")
    if not closes:
        raise ValueError("no close data")
    if fast_window >= slow_window:
        raise ValueError("fast_window must be < slow_window")
    if len(closes) < slow_window:
        raise ValueError(f"need at least {slow_window} candles, have {len(closes)}")

    fast = _sma(closes, fast_window)
    slow = _sma(closes, slow_window)
    latest_close = float(closes[-1])
    latest_ts = int(timestamps[-1])

    return SmaSignal(
        symbol=symbol,
        timeframe=timeframe,
        fast_window=fast_window,
        slow_window=slow_window,
        fast_sma=float(fast),
        slow_sma=float(slow),
        should_be_long=fast > slow,
        latest_close=latest_close,
        latest_ts=latest_ts,
    )

