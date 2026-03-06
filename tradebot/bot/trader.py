"""
Stage B: Trading runner (paper first, optional live with safety gates).

Run:
    python -m bot.trader
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Iterable

from .config import (
    BASE_DIR,
    LOGS_DIR,
    EXCHANGE_NAME,
    PUBLIC_ONLY,
    ENABLE_LIVE_TRADING,
    RESAMPLE_TO,
    SYMBOLS as ENV_SYMBOLS,
    TIMEFRAME as ENV_TIMEFRAME,
    TRADER_TIMEFRAME as ENV_TRADER_TIMEFRAME,
    TRADING_MODE as ENV_TRADING_MODE,
    ORDER_TYPE as ENV_ORDER_TYPE,
    FIXED_QUOTE_AMOUNT as ENV_FIXED_QUOTE_AMOUNT,
    SMA_FAST_WINDOW as ENV_SMA_FAST,
    SMA_SLOW_WINDOW as ENV_SMA_SLOW,
    TRADER_INTERVAL as ENV_TRADER_INTERVAL,
    PAPER_FEE_RATE as ENV_PAPER_FEE_RATE,
    DAILY_BUDGET_QUOTE as ENV_DAILY_BUDGET_QUOTE,
    STRATEGY as ENV_STRATEGY,
    ML_MODEL_PATH as ENV_ML_MODEL_PATH,
    ML_LOOKBACK as ENV_ML_LOOKBACK,
    ML_CONFIDENCE_THRESHOLD as ENV_ML_CONFIDENCE_THRESHOLD,
)
from .db import Database
from .exchange import Exchange
from .paper import paper_buy_fixed_quote, paper_sell_all
from .risk import enforce_min_notional, fixed_quote_sizing
from .strategy_sma import compute_sma_signal
from .strategy_ml import compute_ml_signal


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


def _load_config_file(path: Path) -> dict:
    """Load trader config from YAML or JSON file."""
    text = path.read_text()
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            raise SystemExit("YAML config requires PyYAML. Install with: pip install PyYAML")
        return yaml.safe_load(text) or {}
    if path.suffix.lower() == ".json":
        return json.loads(text)
    raise ValueError(f"Unsupported config format: {path.suffix}. Use .yaml or .json")


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
    strategy: str  # sma | ml
    model_path: Optional[Path]  # required when strategy=ml
    ml_lookback: int
    ml_confidence_threshold: float


class Trader:
    def __init__(self, *, args: Optional[argparse.Namespace] = None, config_overrides: Optional[dict] = None):
        self.running = False
        self.exchange = Exchange()
        self.db = Database()
        self.setup_signal_handlers()

        self.cfg = self._build_config(args=args, config_overrides=config_overrides or {})
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

    def _build_config(
        self, *, args: Optional[argparse.Namespace] = None, config_overrides: dict
    ) -> TraderConfig:
        """Build config from CLI > config file > env > interactive prompt."""
        logger.info("=" * 60)
        logger.info("Tradebot Stage B Trader (paper first, guarded live)")
        logger.info("=" * 60)

        no_prompt = args is not None and getattr(args, "no_prompt", False)
        cfg = config_overrides

        def _get(cli_attr: Optional[str], cfg_key: str, env_val, prompt_fn):
            val = None
            if args is not None and cli_attr and getattr(args, cli_attr, None) is not None:
                val = getattr(args, cli_attr)
            if val is None and cfg and cfg.get(cfg_key) is not None:
                val = cfg[cfg_key]
            if val is None:
                val = env_val
            if val is None and no_prompt:
                raise SystemExit(f"Missing required config: {cfg_key}. Set via --{cli_attr or cfg_key}, config file, or .env")
            if val is None:
                val = prompt_fn()
            return val

        symbols_raw = None
        if args is not None and getattr(args, "symbols", None):
            symbols_raw = args.symbols
        if symbols_raw is None and cfg and cfg.get("symbols"):
            s = cfg["symbols"]
            symbols_raw = ",".join(s) if isinstance(s, list) else s
        if symbols_raw is None:
            symbols_raw = ",".join([s.strip() for s in ENV_SYMBOLS])
        if not no_prompt:
            symbols_raw = _prompt_str("Symbols (comma-separated)", symbols_raw)
        symbols = _parse_symbols(symbols_raw)

        timeframe = _get("timeframe", "timeframe", ENV_TRADER_TIMEFRAME, lambda: _prompt_str("Timeframe", ENV_TRADER_TIMEFRAME))
        if isinstance(timeframe, str):
            timeframe = timeframe.lower()
        mode = _get("mode", "mode", ENV_TRADING_MODE, lambda: _prompt_str("Mode (paper/live)", ENV_TRADING_MODE))
        if isinstance(mode, str):
            mode = mode.lower()
        order_type = _get("order_type", "order_type", ENV_ORDER_TYPE, lambda: _prompt_str("Order type (market/limit)", ENV_ORDER_TYPE))
        if isinstance(order_type, str):
            order_type = order_type.lower()
        fixed_quote_amount = _get("fixed_quote", "fixed_quote_amount", float(ENV_FIXED_QUOTE_AMOUNT), lambda: _prompt_float("Fixed quote amount per BUY (USDT)", float(ENV_FIXED_QUOTE_AMOUNT)))
        fixed_quote_amount = float(fixed_quote_amount)
        sma_fast = _get("sma_fast", "sma_fast_window", int(ENV_SMA_FAST), lambda: _prompt_int("SMA fast window (candles)", int(ENV_SMA_FAST)))
        sma_fast = int(sma_fast)
        sma_slow = _get("sma_slow", "sma_slow_window", int(ENV_SMA_SLOW), lambda: _prompt_int("SMA slow window (candles)", int(ENV_SMA_SLOW)))
        sma_slow = int(sma_slow)
        interval_s = _get("interval", "trader_interval", int(ENV_TRADER_INTERVAL), lambda: _prompt_int("Trader loop interval (seconds)", int(ENV_TRADER_INTERVAL)))
        interval_s = int(interval_s)
        paper_fee_rate = _get("paper_fee_rate", "paper_fee_rate", float(ENV_PAPER_FEE_RATE), lambda: _prompt_float("Paper fee rate (e.g., 0.001 = 0.1%)", float(ENV_PAPER_FEE_RATE)))
        paper_fee_rate = float(paper_fee_rate)

        strategy = _get("strategy", "strategy", ENV_STRATEGY, lambda: _prompt_str("Strategy (sma/ml)", ENV_STRATEGY))
        if isinstance(strategy, str):
            strategy = strategy.lower()
        if strategy not in {"sma", "ml"}:
            logger.warning(f"Invalid strategy '{strategy}', defaulting to sma")
            strategy = "sma"

        model_path_raw = None
        if args is not None and getattr(args, "model_path", None):
            model_path_raw = getattr(args, "model_path")
        if model_path_raw is None and cfg and cfg.get("model_path"):
            model_path_raw = cfg["model_path"]
        if model_path_raw is None:
            model_path_raw = ENV_ML_MODEL_PATH
        if isinstance(model_path_raw, str) and not model_path_raw.strip():
            model_path_raw = None
        if model_path_raw is None and no_prompt and strategy == "ml":
            raise SystemExit("STRATEGY=ml requires ML_MODEL_PATH. Set via --model-path, config, or .env")
        if model_path_raw is None and strategy == "ml":
            model_path_raw = _prompt_str("Model path (e.g. models/ml_strategy_v1.pkl)", "")

        model_path: Optional[Path] = None
        if model_path_raw:
            p = Path(model_path_raw)
            model_path = p if p.is_absolute() else (BASE_DIR / p)

        if strategy == "ml":
            if not model_path or not model_path.exists():
                raise SystemExit(f"ML strategy requires valid model file. Not found: {model_path}")

        ml_lookback = _get("ml_lookback", "ml_lookback", ENV_ML_LOOKBACK, lambda: _prompt_int("ML lookback (candles)", int(ENV_ML_LOOKBACK)))
        ml_lookback = int(ml_lookback)
        ml_confidence_threshold = _get("ml_confidence_threshold", "ml_confidence_threshold", ENV_ML_CONFIDENCE_THRESHOLD, lambda: _prompt_float("ML confidence threshold (e.g. 0.55)", float(ENV_ML_CONFIDENCE_THRESHOLD)))
        ml_confidence_threshold = float(ml_confidence_threshold)

        if mode not in {"paper", "live"}:
            logger.warning(f"Invalid mode '{mode}', defaulting to paper")
            mode = "paper"
        if order_type not in {"market", "limit"}:
            logger.warning(f"Invalid order_type '{order_type}', defaulting to market")
            order_type = "market"

        # Timeframe validation: warn if not in RESAMPLE_TO or base TIMEFRAME
        valid_tfs = set(RESAMPLE_TO) | {ENV_TIMEFRAME}
        if timeframe not in valid_tfs:
            logger.warning(f"Timeframe '{timeframe}' not in RESAMPLE_TO ({RESAMPLE_TO}) or TIMEFRAME ({ENV_TIMEFRAME}). Ensure collector resamples this timeframe.")

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
            strategy=strategy,
            model_path=model_path,
            ml_lookback=ml_lookback,
            ml_confidence_threshold=ml_confidence_threshold,
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
        need = self.cfg.ml_lookback if self.cfg.strategy == "ml" else self.cfg.sma_slow
        if self.cfg.strategy == "ml":
            rows = self.db.get_recent_ohlcv(symbol, self.cfg.timeframe, limit=need)
        else:
            rows = self.db.get_recent_closes(symbol, self.cfg.timeframe, limit=need)
        if len(rows) < need:
            logger.warning(
                f"[TRADER] symbol={symbol} status=insufficient_data have={len(rows)} need={need} "
                f"timeframe={self.cfg.timeframe}"
            )
            return False
        return True

    def _desired_long(self, symbol: str) -> Optional[bool]:
        if self.cfg.strategy == "sma":
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
                f"[SIGNAL] symbol={symbol} tf={self.cfg.timeframe} strategy=sma close={sig.latest_close:.6f} "
                f"fast={sig.fast_sma:.6f} slow={sig.slow_sma:.6f} should_long={int(sig.should_be_long)}"
            )
            return sig.should_be_long

        # strategy == "ml"
        rows = self.db.get_recent_ohlcv(symbol, self.cfg.timeframe, limit=self.cfg.ml_lookback)
        if len(rows) < self.cfg.ml_lookback:
            return None
        sig = compute_ml_signal(
            symbol=symbol,
            timeframe=self.cfg.timeframe,
            ohlcv_rows=rows,
            model_path=self.cfg.model_path,
            lookback=self.cfg.ml_lookback,
        )
        logger.info(
            f"[SIGNAL] symbol={symbol} tf={self.cfg.timeframe} strategy=ml close={sig.latest_close:.6f} "
            f"confidence={sig.confidence:.4f} should_long={int(sig.should_be_long)}"
        )
        if not sig.should_be_long:
            return False
        if sig.confidence < self.cfg.ml_confidence_threshold:
            logger.info(
                f"[TRADER] symbol={symbol} action=skip confidence={sig.confidence:.4f} "
                f"below threshold={self.cfg.ml_confidence_threshold}"
            )
            return False
        return True

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

        reason = "ml_long" if self.cfg.strategy == "ml" else "sma_long"
        self._persist_live_order(symbol=symbol, side="buy", order=order, ts=ts, reason=reason)

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

        reason = "ml_flat" if self.cfg.strategy == "ml" else "sma_flat"
        self._persist_live_order(symbol=symbol, side="sell", order=order, ts=ts, reason=reason)

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
            strategy="ml_crossover" if reason in ("ml_long", "ml_flat") else "sma_crossover",
            signal="long" if reason in ("sma_long", "ml_long") else "flat",
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
                        if ENV_DAILY_BUDGET_QUOTE is not None and ENV_DAILY_BUDGET_QUOTE > 0:
                            spent_today = self.db.get_paper_spent_today()
                            if spent_today + self.cfg.fixed_quote_amount > ENV_DAILY_BUDGET_QUOTE:
                                logger.info(
                                    f"[TRADER] symbol={symbol} action=skip_buy reason=daily_budget "
                                    f"spent_today={spent_today:.2f} budget={ENV_DAILY_BUDGET_QUOTE}"
                                )
                                continue
                        strat = "ml_crossover" if self.cfg.strategy == "ml" else "sma_crossover"
                        reason = "ml_long" if self.cfg.strategy == "ml" else "sma_long"
                        paper_buy_fixed_quote(
                            db=self.db,
                            exchange=EXCHANGE_NAME,
                            symbol=symbol,
                            quote_amount=self.cfg.fixed_quote_amount,
                            price=price,
                            fee_rate=self.cfg.paper_fee_rate,
                            timeframe=self.cfg.timeframe,
                            strategy=strat,
                            signal="long",
                            reason=reason,
                            order_type=self.cfg.order_type,
                            ts=ts,
                        )
                    else:
                        self._live_buy(symbol=symbol, quote_amount=self.cfg.fixed_quote_amount, price_hint=price, ts=ts)

                elif (not want_long) and is_long:
                    if self.cfg.mode == "paper":
                        strat = "ml_crossover" if self.cfg.strategy == "ml" else "sma_crossover"
                        reason = "ml_flat" if self.cfg.strategy == "ml" else "sma_flat"
                        paper_sell_all(
                            db=self.db,
                            exchange=EXCHANGE_NAME,
                            symbol=symbol,
                            price=price,
                            fee_rate=self.cfg.paper_fee_rate,
                            timeframe=self.cfg.timeframe,
                            strategy=strat,
                            signal="flat",
                            reason=reason,
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
        logger.info(f"Strategy: {self.cfg.strategy}")
        if self.cfg.strategy == "sma":
            logger.info(f"SMA fast/slow: {self.cfg.sma_fast}/{self.cfg.sma_slow}")
        else:
            logger.info(f"ML model: {self.cfg.model_path}")
            logger.info(f"ML lookback: {self.cfg.ml_lookback} confidence_threshold: {self.cfg.ml_confidence_threshold}")
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


def _parse_args():
    parser = argparse.ArgumentParser(description="Tradebot Stage B Trader (paper first, guarded live)")
    parser.add_argument("--symbols", type=str, help="Comma-separated symbols (e.g. BTC/USDT,ETH/USDT)")
    parser.add_argument("--strategy", type=str, choices=["sma", "ml"], help="Strategy: sma or ml")
    parser.add_argument("--model-path", dest="model_path", type=Path, help="Path to ML model .pkl (required when strategy=ml)")
    parser.add_argument("--timeframe", type=str, help="Strategy timeframe (e.g. 7m)")
    parser.add_argument("--mode", type=str, choices=["paper", "live"], help="Trading mode")
    parser.add_argument("--order-type", dest="order_type", type=str, choices=["market", "limit"], help="Order type")
    parser.add_argument("--fixed-quote", dest="fixed_quote", type=float, help="Fixed quote amount per BUY (USDT)")
    parser.add_argument("--sma-fast", dest="sma_fast", type=int, help="SMA fast window (candles)")
    parser.add_argument("--sma-slow", dest="sma_slow", type=int, help="SMA slow window (candles)")
    parser.add_argument("--interval", type=int, help="Trader loop interval (seconds)")
    parser.add_argument("--paper-fee-rate", dest="paper_fee_rate", type=float, help="Paper fee rate (e.g. 0.001)")
    parser.add_argument("--config", type=Path, help="Path to YAML/JSON config file")
    parser.add_argument("--no-prompt", dest="no_prompt", action="store_true", help="Use only env/config/CLI; exit if any required value missing")
    return parser.parse_args()


def main():
    args = _parse_args()
    config_overrides = {}
    if args.config:
        if not args.config.exists():
            raise SystemExit(f"Config file not found: {args.config}")
        config_overrides = _load_config_file(args.config)
    trader = Trader(args=args, config_overrides=config_overrides)
    trader.run()


if __name__ == "__main__":
    main()

