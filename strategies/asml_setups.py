from datetime import datetime, time as dtime, timedelta
from collections import deque
import pandas as pd
import math


class MorningGapFill:
    """Morning Gap Fill setup (converted from ASML_Trading_Setups_Details.xlsx).

    Interpreted rules (LONG-only conversion):
      - Time window: default 08:05 - 09:00 (configurable)
      - Trigger: first market-open gap down relative to previous close >= `gap_min`
      - Minimum volume: `vol_min`
      - Entry: when price shows initial recovery (higher close) after gap down
      - SL: recent low (configurable buffer)
      - TP: distance to previous close or scaled by `tp_ratio`

    Notes:
      - The workbook lists the setup parameters; this class exposes config
        to tune thresholds and integrates with minute-candle feeds.
      - Before using, call `set_prev_close(price)` with the previous day's close.
    """

    def __init__(self, cfg=None):
        cfg = cfg or {}
        # time window strings 'HH:MM'
        self.start = self._parse_time(cfg.get("start", "08:05"))
        self.end = self._parse_time(cfg.get("end", "09:00"))
        self.gap_min = float(cfg.get("gap_min", 10.0))
        self.vol_min = int(cfg.get("vol_min", 5000))
        self.tp_ratio = float(cfg.get("tp_ratio", 1.5))
        self.sl_buffer = float(cfg.get("sl_buffer", 0.0))
        # ATR-based buffer parameters
        self.atr_k = float(cfg.get("atr_buffer_k", 0.30))
        self.atr_min = float(cfg.get("atr_min_buffer", 0.20))
        self.lookback = int(cfg.get("lookback", 5))

        self.prev_close = None
        self.first_open = None
        self.detected_gap = False
        self.active = False
        self.candle_history = deque(maxlen=1000)

    def _parse_time(self, s):
        h, m = (int(x) for x in s.split(":"))
        return dtime(hour=h, minute=m)

    def set_prev_close(self, price):
        self.prev_close = float(price)

    def load_history_from_excel(self, path, time_col="time", open_col="open", high_col="high", low_col="low", close_col="close", vol_col="volume"):
        """Load historical candles from an Excel file into candle_history.

        Expects ISO timestamps in the time_col. This helps compute ATR when
        live candle_history is not yet populated.
        """
        try:
            df = pd.read_excel(path, engine="openpyxl")
        except Exception:
            df = pd.read_excel(path)

        # If the file already has proper named columns, use them
        required = [time_col, open_col, high_col, low_col, close_col]
        if all(c in df.columns for c in required):
            data = df.copy()
            data = data.dropna(subset=[time_col, open_col, high_col, low_col, close_col])
            data[time_col] = pd.to_datetime(data[time_col], errors='coerce')
        else:
            # Try to auto-detect header row and column mapping (common export format)
            # Find first row that looks like a datetime in first column
            start_idx = None
            for i, v in enumerate(df.iloc[:, 0].values):
                if pd.notna(v) and isinstance(v, (pd.Timestamp, str)):
                    s = str(v)
                    if any(ch.isdigit() for ch in s) and ("-" in s or ":" in s):
                        start_idx = i
                        break
            if start_idx is None:
                return False
            data = df.iloc[start_idx:].copy()
            # Map likely columns: time, close, high, low, open, volume
            cols = list(data.columns)
            mapping = {}
            try:
                mapping[time_col] = cols[0]
                mapping[close_col] = cols[1]
                mapping[high_col] = cols[2]
                mapping[low_col] = cols[3]
                mapping[open_col] = cols[4]
                mapping[vol_col] = cols[5]
            except Exception:
                return False
            data = data.rename(columns=mapping)
            # ensure expected columns exist after rename
            if not all(c in data.columns for c in [time_col, open_col, high_col, low_col, close_col]):
                return False
            data = data.dropna(subset=[time_col, open_col, high_col, low_col, close_col])
            data[time_col] = pd.to_datetime(data[time_col], utc=True, errors='coerce')

        # clear existing history and append rows
        self.candle_history.clear()
        for _, row in data.iterrows():
            try:
                o = float(row[open_col])
                h = float(row[high_col])
                l = float(row[low_col])
                c = float(row[close_col])
            except Exception:
                continue
            candle = {
                "time": row[time_col],
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": int(row[vol_col]) if vol_col in row and not pd.isna(row[vol_col]) else 0,
            }
            self.candle_history.append(candle)
        return True

    def compute_atr(self, period=14, method="wilder"):
        """Compute ATR over `period` periods from `self.candle_history`.

        Returns the latest ATR value or None if insufficient data.
        """
        if len(self.candle_history) < period + 1:
            return None

        # Build lists of high, low, close
        highs = [float(c["high"]) for c in self.candle_history if c.get("high") is not None]
        lows = [float(c["low"]) for c in self.candle_history if c.get("low") is not None]
        closes = [float(c["close"]) for c in self.candle_history if c.get("close") is not None]

        # compute True Range series
        trs = []
        for i in range(1, len(closes)):
            high = highs[i]
            low = lows[i]
            prev_close = closes[i - 1]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)

        if len(trs) < period:
            return None

        # Wilder's smoothing
        if method == "wilder":
            # first ATR is simple average of first `period` TRs
            atr = sum(trs[:period]) / period
            for tr in trs[period:]:
                atr = (atr * (period - 1) + tr) / period
            return round(atr, 6)
        else:
            # simple moving average of last `period` TRs
            return round(sum(trs[-period:]) / period, 6)

    def _in_window(self, ts_iso):
        # ts_iso expected like 2026-02-18T08:05:00Z or similar
        try:
            ts = datetime.fromisoformat(ts_iso.replace("Z", ""))
        except Exception:
            return False
        t = ts.time()
        return (t >= self.start) and (t <= self.end)

    def on_candle(self, candle):
        """Process a 1-minute `candle` dict and return a signal dict or None.

        Candle keys: symbol, time (ISO), open, high, low, close, volume
        """
        self.candle_history.append(candle)

        # require previous close to be set
        if self.prev_close is None:
            return None

        if not self.first_open:
            # treat the first candle in the session as opening reference
            if self._in_window(candle.get("time", "")):
                self.first_open = float(candle["open"]) if candle.get("open") is not None else None
                # detect gap down
                gap = self.prev_close - self.first_open
                if gap >= self.gap_min and candle.get("volume", 0) >= self.vol_min:
                    self.detected_gap = True
                    # start watching for recovery
                return None
            else:
                return None

        # if a qualifying gap down was detected and we're in the time window
        if self.detected_gap and self._in_window(candle.get("time", "")):
            # quick entry rule: price shows a higher close compared to previous candle
            if len(self.candle_history) >= 2:
                prev = self.candle_history[-2]
                # require increasing close
                if float(candle["close"]) > float(prev["close"]):
                    entry = float(candle["close"])
                    # Determine SL buffer: if ATR available, use ATR-based buffer with floor
                    atr = self.compute_atr(period=14)
                    if atr is not None:
                        buffer = max(self.atr_min, round(self.atr_k * atr, 6))
                    else:
                        buffer = self.sl_buffer

                    # SL = lowest low of recent candles minus buffer
                    lows = [float(c.get("low", entry)) for c in list(self.candle_history)[-self.lookback:]]
                    sl = min(lows) - buffer
                    # TP = aim for fill toward prev_close (or use tp_ratio)
                    dist_to_fill = self.prev_close - entry
                    if dist_to_fill <= 0:
                        tp = entry + (entry - sl) * self.tp_ratio
                    else:
                        tp = entry + dist_to_fill  # aim to fill the gap

                    # create a LONG signal
                    signal = {
                        "side": "LONG",
                        "symbol": candle.get("symbol"),
                        "time": candle.get("time"),
                        "entry": round(entry, 4),
                        "sl": round(sl, 4),
                        "tp": round(tp, 4),
                        "meta": {
                            "setup_name": "Morning Gap Fill",
                            "prev_close": float(self.prev_close),
                            "first_open": float(self.first_open),
                        },
                    }
                    # reset detection to avoid duplicate signals
                    self.detected_gap = False
                    return signal

        return None


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _parse_time_str(s):
    h, m = (int(x) for x in s.split(":"))
    return dtime(hour=h, minute=m)


def _ts_in_window(ts_iso, start, end):
    try:
        ts = datetime.fromisoformat(ts_iso.replace("Z", ""))
    except Exception:
        return False
    t = ts.time()
    return start <= t <= end


# ---------------------------------------------------------------------------
# Morning Momentum  (09:15 – 10:00)
# ---------------------------------------------------------------------------

class MorningMomentum:
    """Morning Momentum setup.

    Detects sustained directional momentum early in the trading session.
    Requires `n_confirm` consecutive candles each showing:
      - LONG:  higher high AND higher low than the previous candle
      - SHORT: lower low  AND lower high than the previous candle
    plus a volume check on the trigger candle.

    Config keys:
      start, end        — time window strings 'HH:MM'
      vol_min           — minimum volume on trigger candle
      n_confirm         — number of consecutive confirming candles (default 2)
      tp_ratio          — reward/risk multiplier (default 1.75)
      sl_lookback       — candles to look back for SL level (default 3)
    """

    def __init__(self, cfg=None):
        cfg = cfg or {}
        self.start = _parse_time_str(cfg.get("start", "09:15"))
        self.end = _parse_time_str(cfg.get("end", "10:00"))
        self.vol_min = int(cfg.get("vol_min", 3000))
        self.n_confirm = int(cfg.get("n_confirm", 2))
        self.tp_ratio = float(cfg.get("tp_ratio", 1.75))
        self.sl_lookback = int(cfg.get("sl_lookback", 3))

        self.candle_history = deque(maxlen=500)
        self.signal_fired = False

    def on_candle(self, candle):
        self.candle_history.append(candle)

        if self.signal_fired:
            return None
        if not _ts_in_window(candle.get("time", ""), self.start, self.end):
            return None
        if candle.get("volume", 0) < self.vol_min:
            return None
        if len(self.candle_history) < self.n_confirm + 1:
            return None

        recent = list(self.candle_history)[-(self.n_confirm + 1):]

        long_ok = all(
            float(recent[i + 1]["high"]) > float(recent[i]["high"]) and
            float(recent[i + 1]["low"]) > float(recent[i]["low"])
            for i in range(self.n_confirm)
        )
        short_ok = all(
            float(recent[i + 1]["low"]) < float(recent[i]["low"]) and
            float(recent[i + 1]["high"]) < float(recent[i]["high"])
            for i in range(self.n_confirm)
        )

        if not long_ok and not short_ok:
            return None

        side = "LONG" if long_ok else "SHORT"
        entry = float(candle["close"])
        lookback = list(self.candle_history)[-self.sl_lookback:]

        if side == "LONG":
            sl = min(float(c["low"]) for c in lookback)
            tp = entry + abs(entry - sl) * self.tp_ratio
        else:
            sl = max(float(c["high"]) for c in lookback)
            tp = entry - abs(sl - entry) * self.tp_ratio

        self.signal_fired = True
        return {
            "side": side,
            "symbol": candle.get("symbol"),
            "time": candle.get("time"),
            "entry": round(entry, 4),
            "sl": round(sl, 4),
            "tp": round(tp, 4),
            "meta": {"setup_name": "Morning Momentum"},
        }


# ---------------------------------------------------------------------------
# Opening Range Break  (08:05 – 08:45, range built 08:05 – 08:20)
# ---------------------------------------------------------------------------

class OpeningRangeBreak:
    """Opening Range Breakout setup.

    Phase 1 — range building (range_start to range_end, default 08:05-08:20):
        Record the highest high and lowest low of all candles in this window.
    Phase 2 — breakout watch (range_end to break_end, default 08:20-08:45):
        Fire a signal when close breaks above range_high (LONG) or
        below range_low (SHORT) with volume confirmation.

    When force_window=True (demo mode) the strategy is time-independent:
        - Phase 1 = first `range_n_candles` candles received (default 15)
        - Phase 2 = all subsequent candles until signal fires
    """

    def __init__(self, cfg=None):
        cfg = cfg or {}
        self.range_start = _parse_time_str(cfg.get("range_start", "08:05"))
        self.range_end = _parse_time_str(cfg.get("range_end", "08:20"))
        self.break_end = _parse_time_str(cfg.get("break_end", "08:45"))
        self.vol_min = int(cfg.get("vol_min", 5000))
        self.tp_ratio = float(cfg.get("tp_ratio", 1.3))
        self.range_n_candles = int(cfg.get("range_n_candles", 15))
        self.force_window = bool(cfg.get("force_window", False))

        self.range_high: float | None = None
        self.range_low: float | None = None
        self.range_built = False
        self.signal_fired = False
        self._candles_seen = 0

    def on_candle(self, candle):
        if self.signal_fired:
            return None

        ts = candle.get("time", "")
        h = float(candle["high"])
        lo = float(candle["low"])
        close = float(candle["close"])

        if self.force_window:
            # Phase 1: count-based range building
            if not self.range_built:
                self._candles_seen += 1
                self.range_high = h if self.range_high is None else max(self.range_high, h)
                self.range_low = lo if self.range_low is None else min(self.range_low, lo)
                if self._candles_seen >= self.range_n_candles:
                    self.range_built = True
                return None
            # Phase 2: watch for breakout (no time limit)
        else:
            # Time-based Phase 1
            try:
                t = datetime.fromisoformat(ts.replace("Z", "")).time()
            except Exception:
                return None

            if self.range_start <= t < self.range_end:
                self.range_high = h if self.range_high is None else max(self.range_high, h)
                self.range_low = lo if self.range_low is None else min(self.range_low, lo)
                return None

            if self.range_high is not None and not self.range_built:
                self.range_built = True

            if not self.range_built:
                return None
            if not (self.range_end <= t <= self.break_end):
                return None

        if candle.get("volume", 0) < self.vol_min:
            return None

        range_size = self.range_high - self.range_low
        if range_size <= 0:
            return None

        side = None
        if close > self.range_high:
            side = "LONG"
            sl = self.range_low
            tp = close + range_size * self.tp_ratio
        elif close < self.range_low:
            side = "SHORT"
            sl = self.range_high
            tp = close - range_size * self.tp_ratio

        if side:
            self.signal_fired = True
            return {
                "side": side,
                "symbol": candle.get("symbol"),
                "time": ts,
                "entry": round(close, 4),
                "sl": round(sl, 4),
                "tp": round(tp, 4),
                "meta": {
                    "setup_name": "Opening Range Break",
                    "range_high": round(self.range_high, 4),
                    "range_low": round(self.range_low, 4),
                    "range_size": round(range_size, 4),
                },
            }

        return None


# ---------------------------------------------------------------------------
# Closing Reversion  (16:00 – 16:25, VWAP mean-reversion)
# ---------------------------------------------------------------------------

class ClosingReversion:
    """Closing Reversion (VWAP mean-reversion) setup.

    Calculates VWAP over all candles received so far.
    During the closing window, fires a signal when price deviates more than
    `vwap_threshold` EUR from VWAP:
      - price > VWAP + threshold → SHORT (expect reversion back to VWAP)
      - price < VWAP - threshold → LONG  (expect reversion back to VWAP)

    Config keys:
      start, end         — closing window 'HH:MM'
      vol_min            — minimum volume on trigger candle
      vwap_threshold     — minimum deviation from VWAP to trigger (default 10.0)
      sl_buffer          — fixed SL distance from entry (default 4.0)
      tp_buffer          — buffer added/subtracted from VWAP as TP (default 2.0)
    """

    def __init__(self, cfg=None):
        cfg = cfg or {}
        self.start = _parse_time_str(cfg.get("start", "16:00"))
        self.end = _parse_time_str(cfg.get("end", "16:25"))
        self.vol_min = int(cfg.get("vol_min", 3000))
        self.vwap_threshold = float(cfg.get("vwap_threshold", 10.0))
        self.sl_buffer = float(cfg.get("sl_buffer", 4.0))
        self.tp_buffer = float(cfg.get("tp_buffer", 2.0))

        self.all_candles: deque = deque(maxlen=5000)
        self.signal_fired = False

    def _compute_vwap(self):
        total_vol = sum(c.get("volume", 0) for c in self.all_candles)
        if total_vol == 0:
            return None
        tpv = sum(
            ((float(c["high"]) + float(c["low"]) + float(c["close"])) / 3) * c.get("volume", 0)
            for c in self.all_candles
        )
        return round(tpv / total_vol, 4)

    def on_candle(self, candle):
        self.all_candles.append(candle)

        if self.signal_fired:
            return None
        if not _ts_in_window(candle.get("time", ""), self.start, self.end):
            return None
        if candle.get("volume", 0) < self.vol_min:
            return None
        if len(self.all_candles) < 10:
            return None

        vwap = self._compute_vwap()
        if vwap is None:
            return None

        close = float(candle["close"])
        deviation = close - vwap

        if abs(deviation) < self.vwap_threshold:
            return None

        if deviation > 0:
            side = "SHORT"
            entry = close
            sl = round(entry + self.sl_buffer, 4)
            tp = round(vwap + self.tp_buffer, 4)
        else:
            side = "LONG"
            entry = close
            sl = round(entry - self.sl_buffer, 4)
            tp = round(vwap - self.tp_buffer, 4)

        self.signal_fired = True
        return {
            "side": side,
            "symbol": candle.get("symbol"),
            "time": candle.get("time"),
            "entry": round(entry, 4),
            "sl": sl,
            "tp": tp,
            "meta": {
                "setup_name": "Closing Reversion",
                "vwap": vwap,
                "deviation": round(deviation, 4),
            },
        }
