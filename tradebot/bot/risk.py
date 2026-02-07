"""
Minimal risk/sizing helpers for Stage B.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SizingResult:
    quote_amount: float
    price: float
    base_amount: float


def fixed_quote_sizing(*, quote_amount: float, price: float) -> SizingResult:
    if quote_amount <= 0:
        raise ValueError("quote_amount must be > 0")
    if price <= 0:
        raise ValueError("price must be > 0")
    base_amount = quote_amount / price
    return SizingResult(quote_amount=float(quote_amount), price=float(price), base_amount=float(base_amount))


def enforce_min_notional(*, quote_amount: float, min_notional: float = 10.0) -> None:
    """
    Binance spot commonly enforces min notional. We keep this as a simple guard.
    """
    if quote_amount < min_notional:
        raise ValueError(f"quote_amount {quote_amount} < min_notional {min_notional}")

