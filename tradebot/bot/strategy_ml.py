"""
ML-based trading strategy.

Uses a trained RandomForest to predict "should we be long?" from OHLCV features.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Any, Optional

import joblib
import numpy as np

from .features import build_features, FEATURE_NAMES

logger = logging.getLogger(__name__)

# Module-level cache: (model_path, mtime) -> payload
_model_cache: Dict[tuple, dict] = {}


@dataclass(frozen=True)
class MlSignal:
    symbol: str
    timeframe: str
    should_be_long: bool
    confidence: float
    latest_close: float
    latest_ts: int


def _load_model(model_path: Path) -> dict:
    """Load model from disk, with caching by path and mtime."""
    mtime = model_path.stat().st_mtime
    key = (str(model_path.resolve()), mtime)
    if key not in _model_cache:
        payload = joblib.load(model_path)
        if "model" not in payload or "feature_names" not in payload:
            raise ValueError(f"Invalid model file: missing model or feature_names")
        _model_cache[key] = payload
        logger.info(f"[ML] loaded model from {model_path} (mtime={mtime})")
    return _model_cache[key]


def compute_ml_signal(
    *,
    symbol: str,
    timeframe: str,
    ohlcv_rows: List[Dict[str, Any]],
    model_path: Path,
    lookback: int = 60,
) -> MlSignal:
    """
    Compute ML signal from OHLCV data.

    Args:
        symbol: Trading pair (for logging).
        timeframe: Timeframe (for logging).
        ohlcv_rows: Full OHLCV rows (chronological), need at least lookback.
        model_path: Path to .pkl model file.
        lookback: Feature lookback window (must match training).

    Returns:
        MlSignal with should_be_long, confidence (proba of class 1).
    """
    model_path = Path(model_path)
    if not model_path.exists():
        raise FileNotFoundError(f"Model file not found: {model_path}")

    payload = _load_model(model_path)
    clf = payload["model"]
    saved_features = payload["feature_names"]

    if saved_features != FEATURE_NAMES:
        raise ValueError(
            f"Feature mismatch: model has {saved_features}, current features are {FEATURE_NAMES}"
        )

    if len(ohlcv_rows) < lookback:
        raise ValueError(f"Need at least {lookback} OHLCV rows, got {len(ohlcv_rows)}")

    X, timestamps = build_features(ohlcv_rows, lookback=lookback)
    if len(X) == 0:
        raise ValueError("No feature rows produced")

    last_row = X[-1:].astype(np.float64)
    pred = int(clf.predict(last_row)[0])
    proba = clf.predict_proba(last_row)[0]
    # Class 1 = long
    confidence = float(proba[1]) if len(proba) > 1 else float(proba[0])

    latest_close = float(ohlcv_rows[-1]["close"])
    latest_ts = int(ohlcv_rows[-1]["timestamp"])

    return MlSignal(
        symbol=symbol,
        timeframe=timeframe,
        should_be_long=(pred == 1),
        confidence=confidence,
        latest_close=latest_close,
        latest_ts=latest_ts,
    )
