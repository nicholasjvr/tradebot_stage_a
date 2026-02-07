"""
Stage B: Trading runner (paper first, optional live with safety gates).

Run:
    python -m bot.trader
"""

from __future__ import annotations

import json
import logging
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Iterable

from .config import (
    LOGS_DIR,
    EXCHANGE_NAME,
    PUBLIC_ONLY,
    ENABLE_LIVE_TRADING,
    SYMBOLS as ENV_SYMBOLS,
    TIMEFRAME as ENV_TIMEFRAME,
    TRADING_MODE as ENV_TRADING_MODE,
    ORDER_TYPE as ENV_ORDER_TYPE,
    FIXED_QUOTE_AMOUNT as ENV_FIXED_QUOTE_AMOUNT,
    SMA_FAST_WINDOW as ENV_SMA_FAST,
    SMA_SLOW_WINDOW as ENV_SMA_SLOW,
    TRADER_INTERVAL as ENV_TRADER_INTERVAL,
    PAPER_FEE_RATE as ENV_PAPER_FEE_RATE,
)
from .db import Database
from .exchange import Exchange
from .paper import paper_buy_fixed_quote, paper_sell_all
from .risk import enforce_min_notional, fixed_quote_sizing
from .strategy_sma import compute_sma_signal


log_file = LOGS_DIR / f"trader_{datetime.now().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def _prompt_str(prompt: str, default: str) -> str:
    raw = input(f"{prompt} [{default}]: ").strip()
    return raw or default


def _prompt_float(prompt: str, default: float) -> float:
    raw = input(f"{prompt} [{default}]: ").strip()
    if not raw:
        return float(default)
    return float(raw)


def _prompt_int(prompt: str, default: int) -> int:
    raw = input(f"{prompt} [{default}]: ").strip()
    if not raw:
        return int(default)
    return int(raw)


def _parse_symbols(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


def _base_asset(symbol: str) -> str:
    # ccxt unified symbols are usually BASE/QUOTE
    return symbol.split("/")[0].strip()


def _quote_asset(symbol: str) -> str:
    parts = symbol.split("/")
    return parts[1].strip() if len(parts) > 1 else "USDT"


@dataclass
class TraderConfig:
    mode: str  # paper | live
    symbols: list[str]
    timeframe: str
    order_type: str  # market | limit
    fixed_quote_amount: float
    sma_fast: int
    sma_slow: int
    interval_s: int
    paper_fee_rate: float


class Trader:
    def __init__(self):
        self.running = False
        self.exchange = Exchange()
        self.db = Database()
        self.setup_signal_handlers()

        self.cfg = self._prompt_config()
        self.valid_symbols = self._validate_symbols(self.cfg.symbols)
        if not self.valid_symbols:
            raise SystemExit("No valid symbols to trade. Check your input / exchange.")

        self.db.create_tables()

    def setup_signal_handlers(self):
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False

    def _prompt_config(self) -> TraderConfig:
        logger.info("=" * 60)
        logger.info("Tradebot Stage B Trader (paper first, guarded live)")
        logger.info("=" * 60)

        symbols = _parse_symbols(_prompt_str("Symbols (comma-separated)", ",".join([s.strip() for s in ENV_SYMBOLS])))
        timeframe = _prompt_str("Timeframe", ENV_TIMEFRAME)
        mode = _prompt_str("Mode (paper/live)", ENV_TRADING_MODE).lower()
        order_type = _prompt_str("Order type (market/limit)", ENV_ORDER_TYPE).lower()
        fixed_quote_amount = _prompt_float("Fixed quote amount per BUY (USDT)", float(ENV_FIXED_QUOTE_AMOUNT))
        sma_fast = _prompt_int("SMA fast window (candles)", int(ENV_SMA_FAST))
        sma_slow = _prompt_int("SMA slow window (candles)", int(ENV_SMA_SLOW))
        interval_s = _prompt_int("Trader loop interval (seconds)", int(ENV_TRADER_INTERVAL))
        paper_fee_rate = _prompt_float("Paper fee rate (e.g., 0.001 = 0.1%)", float(ENV_PAPER_FEE_RATE))

        if mode not in {"paper", "live"}:
            logger.warning(f"Invalid mode '{mode}', defaulting to paper")
            mode = "paper"
        if order_type not in {"market", "limit"}:
            logger.warning(f"Invalid order_type '{order_type}', defaulting to market")
            order_type = "market"

        # Safety gate: never allow live if PUBLIC_ONLY or ENABLE_LIVE_TRADING is false
        if mode == "live":
            if PUBLIC_ONLY:
                logger.warning("PUBLIC_ONLY=true: live trading not allowed; forcing paper mode")
                mode = "paper"
            elif not ENABLE_LIVE_TRADING:
                logger.warning("ENABLE_LIVE_TRADING=false: live trading not allowed; forcing paper mode")
                mode = "paper"
            else:
                confirm = input("Type LIVE to enable real orders (anything else = paper): ").strip()
                if confirm != "LIVE":
                    logger.warning("Live trading not confirmed; forcing paper mode")
                    mode = "paper"

        return TraderConfig(
            mode=mode,
            symbols=symbols,
            timeframe=timeframe,
            order_type=order_type,
            fixed_quote_amount=fixed_quote_amount,
            sma_fast=sma_fast,
            sma_slow=sma_slow,
            interval_s=interval_s,
            paper_fee_rate=paper_fee_rate,
        )

    def _validate_symbols(self, symbols: Iterable[str]) -> list[str]:
        out: list[str] = []
        for s in symbols:
            if self.exchange.validate_symbol(s):
                out.append(s)
                logger.info(f"[TRADER] symbol={s} status=available")
            else:
                logger.warning(f"[TRADER] symbol={s} status=unavailable exchange={EXCHANGE_NAME}")
        return out

    def _ensure_has_data(self, symbol: str) -> bool:
        rows = self.db.get_recent_closes(symbol, self.cfg.timeframe, limit=self.cfg.sma_slow)
        if len(rows) < self.cfg.sma_slow:
            logger.warning(
                f"[TRADER] symbol={symbol} status=insufficient_data have={len(rows)} need={self.cfg.sma_slow} "
                f"timeframe={self.cfg.timeframe}"
            )
            return False
        return True

    def _desired_long(self, symbol: str) -> Optional[bool]:
        rows = self.db.get_recent_closes(symbol, self.cfg.timeframe, limit=self.cfg.sma_slow)
        if len(rows) < self.cfg.sma_slow:
            return None
        closes = [float(r["close"]) for r in rows]
        tss = [int(r["timestamp"]) for r in rows]
        sig = compute_sma_signal(
            symbol=symbol,
            timeframe=self.cfg.timeframe,
            closes=closes,
            timestamps=tss,
            fast_window=self.cfg.sma_fast,
            slow_window=self.cfg.sma_slow,
        )
        logger.info(
            f"[SIGNAL] symbol={symbol} tf={self.cfg.timeframe} close={sig.latest_close:.6f} "
            f"fast={sig.fast_sma:.6f} slow={sig.slow_sma:.6f} should_long={int(sig.should_be_long)}"
        )
        return sig.should_be_long

    def _is_long(self, symbol: str) -> bool:
        pos = self.db.get_position(mode=self.cfg.mode, exchange=EXCHANGE_NAME, symbol=symbol)
        return bool(pos and float(pos.get("base_qty") or 0.0) > 0)

    def _live_buy(self, *, symbol: str, quote_amount: float, price_hint: float, ts: int) -> None:
        enforce_min_notional(quote_amount=quote_amount)
        sizing = fixed_quote_sizing(quote_amount=quote_amount, price=price_hint)
        amount_str = self.exchange.amount_to_precision(symbol, sizing.base_amount)
        amount = float(amount_str)

        params = {}
        if self.cfg.order_type == "limit":
            # Use IOC to avoid leaving long-lived limit orders unintentionally.
            params = {"timeInForce": "IOC"} if EXCHANGE_NAME == "binance" else {}
            order = self.exchange.create_order(
                symbol=symbol,
                order_type="limit",
                side="buy",
                amount=amount,
                price=price_hint,
                params=params,
            )
        else:
            order = self.exchange.create_order(
                symbol=symbol,
                order_type="market",
                side="buy",
                amount=amount,
                price=None,
                params=params,
            )

        self._persist_live_order(symbol=symbol, side="buy", order=order, ts=ts, reason="sma_long")

    def _live_sell(self, *, symbol: str, price_hint: float, ts: int) -> None:
        base = _base_asset(symbol)
        free_base = self.exchange.get_free_balance(base)
        if free_base <= 0:
            logger.warning(f"[LIVE] symbol={symbol} side=sell status=skipped reason=no_free_balance asset={base}")
            return
        amount_str = self.exchange.amount_to_precision(symbol, free_base)
        amount = float(amount_str)

        params = {}
        if self.cfg.order_type == "limit":
            params = {"timeInForce": "IOC"} if EXCHANGE_NAME == "binance" else {}
            order = self.exchange.create_order(
                symbol=symbol,
                order_type="limit",
                side="sell",
                amount=amount,
                price=price_hint,
                params=params,
            )
        else:
            order = self.exchange.create_order(
                symbol=symbol,
                order_type="market",
                side="sell",
                amount=amount,
                price=None,
                params=params,
            )

        self._persist_live_order(symbol=symbol, side="sell", order=order, ts=ts, reason="sma_flat")

    def _persist_live_order(self, *, symbol: str, side: str, order: dict, ts: int, reason: str) -> None:
        # ccxt order fields are exchange-dependent; persist what we can.
        exchange_order_id = order.get("id")
        status = (order.get("status") or "open").lower()
        filled = order.get("filled")
        average = order.get("average")
        cost = order.get("cost")
        amount = order.get("amount")
        order_type = (order.get("type") or self.cfg.order_type).lower()
        price = order.get("price")
        fee_obj = order.get("fee") or {}
        fee_cost = fee_obj.get("cost")
        fee_cur = fee_obj.get("currency")

        order_id = self.db.insert_order(
            mode="live",
            exchange=EXCHANGE_NAME,
            symbol=symbol,
            side=side,
            order_type=order_type,
            status=status,
            amount=float(amount) if amount is not None else None,
            price=float(price) if price is not None else None,
            filled=float(filled) if filled is not None else None,
            average=float(average) if average is not None else None,
            cost=float(cost) if cost is not None else None,
            fee=float(fee_cost) if fee_cost is not None else None,
            fee_currency=str(fee_cur) if fee_cur is not None else None,
            exchange_order_id=str(exchange_order_id) if exchange_order_id is not None else None,
            strategy="sma_crossover",
            signal="long" if reason == "sma_long" else "flat",
            reason=reason,
            ts=ts,
            raw_json=json.dumps(order, default=str, separators=(",", ":")),
        )

        # Best-effort fill row (some exchanges don't include trades)
        if filled and average:
            self.db.insert_fill(
                order_id=order_id,
                mode="live",
                exchange=EXCHANGE_NAME,
                symbol=symbol,
                side=side,
                price=float(average),
                amount=float(filled),
                cost=float(cost) if cost is not None else float(filled) * float(average),
                fee=float(fee_cost) if fee_cost is not None else None,
                fee_currency=str(fee_cur) if fee_cur is not None else None,
                ts=ts,
                raw_json=None,
            )

            # Update local position snapshot for strategy state (best-effort).
            fill_qty = float(filled)
            fill_price = float(average)
            pos = self.db.get_position(mode="live", exchange=EXCHANGE_NAME, symbol=symbol) or {
                "base_qty": 0.0,
                "avg_entry_price": None,
                "realized_pnl": 0.0,
            }
            old_qty = float(pos.get("base_qty") or 0.0)
            old_avg = pos.get("avg_entry_price")
            old_avg_f = float(old_avg) if old_avg is not None else 0.0
            realized = float(pos.get("realized_pnl") or 0.0)

            if side == "buy":
                new_qty = old_qty + fill_qty
                if old_qty <= 0:
                    new_avg = fill_price
                else:
                    new_avg = ((old_qty * old_avg_f) + (fill_qty * fill_price)) / new_qty
                self.db.upsert_position(
                    mode="live",
                    exchange=EXCHANGE_NAME,
                    symbol=symbol,
                    base_qty=new_qty,
                    avg_entry_price=new_avg,
                    realized_pnl=realized,
                )
            else:
                # Long-only: treat sell as reducing/closing position.
                sell_qty = min(old_qty, fill_qty)
                if old_qty > 0 and old_avg is not None:
                    # Fee already stored on order; we don't double-subtract here.
                    realized += (fill_price - old_avg_f) * sell_qty
                new_qty = max(0.0, old_qty - sell_qty)
                new_avg = old_avg_f if new_qty > 0 else None
                self.db.upsert_position(
                    mode="live",
                    exchange=EXCHANGE_NAME,
                    symbol=symbol,
                    base_qty=new_qty,
                    avg_entry_price=new_avg,
                    realized_pnl=realized,
                )

        logger.info(f"[LIVE] symbol={symbol} side={side} status={status} exchange_order_id={exchange_order_id}")

    def run_once(self):
        for symbol in self.valid_symbols:
            try:
                if not self._ensure_has_data(symbol):
                    continue

                want_long = self._desired_long(symbol)
                if want_long is None:
                    continue

                is_long = self._is_long(symbol)
                latest = self.db.get_latest_close(symbol, self.cfg.timeframe)
                if not latest:
                    continue
                price = float(latest["close"])
                ts = int(latest["timestamp"])

                if want_long and not is_long:
                    if self.cfg.mode == "paper":
                        enforce_min_notional(quote_amount=self.cfg.fixed_quote_amount)
                        paper_buy_fixed_quote(
                            db=self.db,
                            exchange=EXCHANGE_NAME,
                            symbol=symbol,
                            quote_amount=self.cfg.fixed_quote_amount,
                            price=price,
                            fee_rate=self.cfg.paper_fee_rate,
                            timeframe=self.cfg.timeframe,
                            strategy="sma_crossover",
                            signal="long",
                            reason="sma_long",
                            order_type=self.cfg.order_type,
                            ts=ts,
                        )
                    else:
                        self._live_buy(symbol=symbol, quote_amount=self.cfg.fixed_quote_amount, price_hint=price, ts=ts)

                elif (not want_long) and is_long:
                    if self.cfg.mode == "paper":
                        paper_sell_all(
                            db=self.db,
                            exchange=EXCHANGE_NAME,
                            symbol=symbol,
                            price=price,
                            fee_rate=self.cfg.paper_fee_rate,
                            timeframe=self.cfg.timeframe,
                            strategy="sma_crossover",
                            signal="flat",
                            reason="sma_flat",
                            order_type=self.cfg.order_type,
                            ts=ts,
                        )
                    else:
                        self._live_sell(symbol=symbol, price_hint=price, ts=ts)

                else:
                    logger.info(f"[TRADER] symbol={symbol} action=none want_long={int(want_long)} is_long={int(is_long)}")

            except Exception as e:
                logger.error(f"[TRADER] symbol={symbol} error={e}", exc_info=True)

    def run(self):
        logger.info("=" * 60)
        logger.info("Trader Starting")
        logger.info(f"Exchange: {EXCHANGE_NAME}")
        logger.info(f"Mode: {self.cfg.mode} (public_only={PUBLIC_ONLY} enable_live={ENABLE_LIVE_TRADING})")
        logger.info(f"Symbols: {', '.join(self.valid_symbols)}")
        logger.info(f"Timeframe: {self.cfg.timeframe}")
        logger.info(f"Order type: {self.cfg.order_type}")
        logger.info(f"Fixed quote amount: {self.cfg.fixed_quote_amount}")
        logger.info(f"SMA fast/slow: {self.cfg.sma_fast}/{self.cfg.sma_slow}")
        logger.info(f"Interval: {self.cfg.interval_s}s")
        logger.info("=" * 60)

        self.running = True
        try:
            while self.running:
                start = time.time()
                self.run_once()
                elapsed = time.time() - start
                sleep_s = max(0.0, self.cfg.interval_s - elapsed)
                if sleep_s > 0:
                    time.sleep(sleep_s)
                else:
                    logger.warning(f"Trader loop took {elapsed:.2f}s, longer than interval {self.cfg.interval_s}s")
        finally:
            self.db.close()
            logger.info("Trader stopped")


def main():
    Trader().run()


if __name__ == "__main__":
    main()

