"""
Feature engineering for ML trading strategy.

Builds OHLCV-derived features from a rolling window of candles.
Each row = one candle timestamp with features computed from past lookback candles.
"""

from __future__ import annotations

from typing import List, Dict, Any, Tuple

import numpy as np


FEATURE_NAMES = [
    "return_1",
    "return_3",
    "return_5",
    "sma_fast",
    "sma_slow",
    "sma_cross",
    "volatility",
    "volume_ratio",
    "high_low_range",
]


def build_features(
    ohlcv_rows: List[Dict[str, Any]],
    lookback: int = 60,
    sma_fast_window: int = 10,
    sma_slow_window: int = 30,
) -> Tuple[np.ndarray, List[int]]:
    """
    Build feature matrix from OHLCV data.

    Args:
        ohlcv_rows: List of OHLCV dicts (chronological order), each with
            open, high, low, close, volume, timestamp.
        lookback: Minimum candles needed before first valid row.
        sma_fast_window: Fast SMA window.
        sma_slow_window: Slow SMA window.

    Returns:
        X: 2D array of shape (n_samples, n_features).
        timestamps: List of timestamps aligned with each row.
    """
    if len(ohlcv_rows) < lookback:
        return np.array([]).reshape(0, len(FEATURE_NAMES)), []

    closes = np.array([float(r["close"]) for r in ohlcv_rows])
    opens = np.array([float(r["open"]) for r in ohlcv_rows])
    highs = np.array([float(r["high"]) for r in ohlcv_rows])
    lows = np.array([float(r["low"]) for r in ohlcv_rows])
    volumes = np.array([float(r["volume"]) for r in ohlcv_rows])
    timestamps = [int(r["timestamp"]) for r in ohlcv_rows]

    # Returns: (close[i] - close[i-k]) / close[i-k] for k in 1, 3, 5
    returns = np.zeros_like(closes)
    returns[1:] = (closes[1:] - closes[:-1]) / np.where(closes[:-1] != 0, closes[:-1], 1e-10)

    n = len(closes)
    rows = []

    for i in range(lookback, n):
        window_closes = closes[i - lookback : i]
        window_returns = returns[i - lookback : i]
        window_volumes = volumes[i - lookback : i]

        # return_1, return_3, return_5: % change over last 1, 3, 5 candles
        c = closes[i]
        c_1 = closes[i - 1] if i >= 1 else c
        c_3 = closes[i - 3] if i >= 3 else c
        c_5 = closes[i - 5] if i >= 5 else c

        return_1 = (c - c_1) / c_1 if c_1 != 0 else 0.0
        return_3 = (c - c_3) / c_3 if c_3 != 0 else 0.0
        return_5 = (c - c_5) / c_5 if c_5 != 0 else 0.0

        # SMA fast, slow
        sma_fast = np.mean(window_closes[-sma_fast_window:]) if len(window_closes) >= sma_fast_window else np.mean(window_closes)
        sma_slow = np.mean(window_closes[-sma_slow_window:]) if len(window_closes) >= sma_slow_window else np.mean(window_closes)
        sma_cross = 1.0 if sma_fast > sma_slow else 0.0

        # Volatility: std dev of returns over lookback
        volatility = float(np.std(window_returns)) if len(window_returns) > 0 else 0.0

        # Volume ratio: current volume / mean volume over lookback
        mean_vol = np.mean(window_volumes)
        volume_ratio = volumes[i] / mean_vol if mean_vol > 0 else 1.0

        # High-low range: (high - low) / close for current candle
        high_low_range = (highs[i] - lows[i]) / c if c > 0 else 0.0

        rows.append([
            return_1,
            return_3,
            return_5,
            sma_fast,
            sma_slow,
            sma_cross,
            volatility,
            volume_ratio,
            high_low_range,
        ])

    X = np.array(rows, dtype=np.float64)
    out_timestamps = timestamps[lookback:]

    return X, out_timestamps
