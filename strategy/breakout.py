import pandas as pd


class BreakoutStrategy:
    """Simple breakout setup.

    Config keys expected (under setups.breakout):
      - lookback: int (candles to keep)
      - vol_ma: int (rolling window for average volume)
      - vol_mult: float (min volume relative to avg)
      - tp_ratio: float (reward/risk)
    """

    def __init__(self, cfg=None):
        cfg = cfg or {}
        self.lookback = int(cfg.get("lookback", 20))
        self.vol_ma = int(cfg.get("vol_ma", 20))
        self.vol_mult = float(cfg.get("vol_mult", 1.5))
        self.tp_ratio = float(cfg.get("tp_ratio", 2.0))

        self.df = pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"]) 

    def on_candle(self, candle):
        # append
        row = {
            "time": candle["time"],
            "open": candle["open"],
            "high": candle["high"],
            "low": candle["low"],
            "close": candle["close"],
            "volume": candle["volume"],
        }
        self.df = pd.concat([self.df, pd.DataFrame([row])], ignore_index=True)
        if len(self.df) < max(self.lookback, self.vol_ma) + 1:
            return None

        df = self.df.copy().astype({"open": float, "high": float, "low": float, "close": float, "volume": int})

        latest = df.iloc[-1]
        prev_window = df.iloc[-(self.lookback + 1):-1]
        vol_ma = prev_window["volume"].rolling(self.vol_ma).mean().iloc[-1]
        if pd.isna(vol_ma):
            return None

        # breakout long: close > previous high
        prev_high = prev_window["high"].max()
        prev_low = prev_window["low"].min()

        entry = None
        side = None
        if latest["close"] > prev_high and latest["volume"] > vol_ma * self.vol_mult:
            side = "LONG"
            entry = latest["close"]
            sl = prev_low
            tp = entry + (entry - sl) * self.tp_ratio
        elif latest["close"] < prev_low and latest["volume"] > vol_ma * self.vol_mult:
            side = "SHORT"
            entry = latest["close"]
            sl = prev_high
            tp = entry - (sl - entry) * self.tp_ratio

        if side:
            return {
                "side": side,
                "symbol": candle.get("symbol"),
                "time": candle.get("time"),
                "entry": float(entry),
                "sl": float(round(sl, 4)),
                "tp": float(round(tp, 4)),
                "meta": {
                    "setup_name": "Breakout (generic)",
                },
            }

        return None
