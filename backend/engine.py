"""TradingEngine — background thread that runs the trading loop.

Reads candles from a feed, passes them through the selected strategy,
and stores detected signals in a thread-safe shared state that the
Streamlit UI can read on every rerun.
"""

import threading
import time
import yaml

from data.mock_saxo import MockSaxoFeed
from data.yfinance_feed import YFinanceFeed
from strategies.asml_setups import (
    MorningGapFill,
    MorningMomentum,
    OpeningRangeBreak,
    ClosingReversion,
)
from strategy.breakout import BreakoutStrategy
from turbo.translate import TurboTranslator


def _load_config(path="config.yaml"):
    import os
    if not os.path.exists(path):
        # Fallback voor Streamlit Community Cloud (geen config.yaml in repo)
        fallback = os.path.join(os.path.dirname(path) or ".", "config.example.yaml")
        path = fallback
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class TradingEngine:
    """Runs a trading loop in a daemon thread and exposes shared state.

    Usage:
        engine = TradingEngine()
        engine.start(setup_name="morning_gap", prev_close=1210.0, leverage=3.5, ratio=10)

        # From Streamlit (any rerun):
        state = engine.get_state()

        engine.stop()
    """

    MAX_SIGNALS = 50  # keep only the most recent signals

    def __init__(self, config_path="config.yaml"):
        self._lock = threading.Lock()
        self._running = False
        self._thread = None

        self.cfg = _load_config(config_path)

        # Defaults from config — overrideable via start()
        turbo_cfg = self.cfg.get("turbo", {})
        self.setup_name = self.cfg.get("demo_setup", "morning_gap")
        self.prev_close = float(self.cfg.get("demo_prev_close", 1210.0))
        self.leverage = float(turbo_cfg.get("leverage", 3.50))
        self.ratio = float(turbo_cfg.get("ratio", 10))
        self.ticker = self.cfg.get("underlying_symbol", "ASML.AS")
        self.feed_mode = "mock"   # "mock" of "live"

        # Shared state (always access via get_state() or inside _lock)
        self.current_price: float | None = None
        self.current_candle: dict | None = None
        self.signals: list = []
        self.candle_history: list = []   # last 100 candles for chart
        self.candle_count: int = 0
        self.status: str = "stopped"
        self.error_msg: str | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, setup_name=None, prev_close=None, leverage=None, ratio=None,
              ticker=None, feed_mode=None):
        """(Re)start the trading loop with optional new parameters."""
        # Stop and wait for any running thread first
        if self._thread and self._thread.is_alive():
            self._running = False
            self._thread.join(timeout=3.0)

        # Apply new parameters
        if setup_name is not None:
            self.setup_name = setup_name
        if prev_close is not None:
            self.prev_close = float(prev_close)
        if leverage is not None:
            self.leverage = float(leverage)
        if ratio is not None:
            self.ratio = float(ratio)
        if ticker is not None:
            self.ticker = ticker
        if feed_mode is not None:
            self.feed_mode = feed_mode

        # Reset state
        with self._lock:
            self.signals = []
            self.candle_history = []
            self.candle_count = 0
            self.current_price = None
            self.current_candle = None
            self.error_msg = None
            self.status = "starting"
            self._running = True

        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Signal the trading loop to stop."""
        self._running = False
        with self._lock:
            self.status = "stopped"

    def is_running(self) -> bool:
        return self._running

    def get_state(self) -> dict:
        """Return a snapshot of the shared state (thread-safe)."""
        with self._lock:
            return {
                "current_price": self.current_price,
                "current_candle": dict(self.current_candle) if self.current_candle else None,
                "signals": list(self.signals),
                "candle_history": list(self.candle_history),
                "candle_count": self.candle_count,
                "status": self.status,
                "error_msg": self.error_msg,
                "setup_name": self.setup_name,
                "prev_close": self.prev_close,
                "leverage": self.leverage,
                "ratio": self.ratio,
                "ticker": self.ticker,
                "feed_mode": self.feed_mode,
            }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_strategy(self):
        cfg = self.cfg
        force = cfg.get("demo_force_window", True)
        setups = cfg.get("setups", {})

        if self.setup_name == "morning_gap":
            s_cfg = setups.get("morning_gap", {}).copy()
            if force:
                s_cfg["start"] = "00:00"
                s_cfg["end"] = "23:59"
            strategy = MorningGapFill(s_cfg)
            strategy.set_prev_close(self.prev_close)
            return strategy

        if self.setup_name == "morning_momentum":
            s_cfg = setups.get("morning_momentum", {}).copy()
            if force:
                s_cfg["start"] = "00:00"
                s_cfg["end"] = "23:59"
            return MorningMomentum(s_cfg)

        if self.setup_name == "opening_range_break":
            s_cfg = setups.get("opening_range_break", {}).copy()
            if force:
                s_cfg["force_window"] = True
            return OpeningRangeBreak(s_cfg)

        if self.setup_name == "closing_reversion":
            s_cfg = setups.get("closing_reversion", {}).copy()
            if force:
                s_cfg["start"] = "00:00"
                s_cfg["end"] = "23:59"
            return ClosingReversion(s_cfg)

        return BreakoutStrategy(setups.get("breakout", {}))

    def _run_loop(self):
        cfg = self.cfg

        if self.feed_mode == "live":
            feed = YFinanceFeed(ticker=self.ticker)
        else:
            # Demo: random-walk feed vanaf ~1% onder prev_close
            start_price = round(self.prev_close * 0.99, 2)
            feed = MockSaxoFeed(symbol=self.ticker, start_price=start_price)

        strategy = self._build_strategy()

        turbo_cfg = cfg.get("turbo", {}).copy()
        turbo_cfg["leverage"] = self.leverage
        turbo = TurboTranslator(turbo_cfg)

        with self._lock:
            self.status = "running"

        _buf: list = []
        CHART_CANDLES = 100

        try:
            for candle in feed.stream_candles():
                if not self._running:
                    break

                _buf.append(candle)
                if len(_buf) > CHART_CANDLES:
                    _buf = _buf[-CHART_CANDLES:]

                with self._lock:
                    self.current_price = float(candle["close"])
                    self.current_candle = candle
                    self.candle_count += 1
                    self.candle_history = list(_buf)

                signal = strategy.on_candle(candle)
                if signal:
                    asml_price = float(signal["entry"])
                    turbo_vals = turbo.translate(
                        signal,
                        asml_price=asml_price,
                        turbo_price=None,   # user supplies this in the calculator
                        ratio=self.ratio,
                    )
                    signal["turbo"] = turbo_vals

                    with self._lock:
                        self.signals.append(signal)
                        if len(self.signals) > self.MAX_SIGNALS:
                            self.signals = self.signals[-self.MAX_SIGNALS:]

                if self.feed_mode == "mock":
                    time.sleep(0.1)  # 100 ms per candle in demo mode

        except Exception as exc:
            with self._lock:
                self.status = "error"
                self.error_msg = str(exc)
            return

        with self._lock:
            if self.status != "error":
                self.status = "stopped"
