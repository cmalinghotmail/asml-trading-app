"""YFinanceFeed — real 1-minute OHLCV candles via yfinance.

Interface identiek aan MockSaxoFeed: stream_candles() generator.

Gedrag:
  1. Eerste aanroep: download de volledige dag (period="1d", interval="1m")
  2. Yield historische candles snel (replay van de dag tot nu)
  3. Daarna: poll elke POLL_INTERVAL seconden voor nieuwe candles
  4. Yield alleen candles nieuwer dan de laatste geziene tijdstempel

Tijdstempels worden omgezet van UTC → Europe/Amsterdam (CET/CEST).
Buiten handelstijd geeft yfinance de laatste handelsdag terug.
"""

import time
import pandas as pd
import pytz
import yfinance as yf

POLL_INTERVAL = 60  # seconden tussen live polls
CET = pytz.timezone("Europe/Amsterdam")


class YFinanceFeed:
    """Real-data feed via yfinance voor elk geldig ticker-symbool."""

    def __init__(self, ticker="ASML.AS"):
        self.ticker  = ticker
        self._last_ts = None   # ISO-string van de laatste geleverde candle

    def _fetch(self) -> list:
        """Download 1-min candles voor vandaag. Geeft lijst van candle-dicts terug."""
        df = yf.download(
            self.ticker,
            period="1d",
            interval="1m",
            auto_adjust=True,
            progress=False,
        )
        if df.empty:
            return []

        # yfinance geeft soms MultiIndex kolommen: ('Close', 'ASML.AS') → 'Close'
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        candles = []
        for ts, row in df.iterrows():
            # Zorg dat tijdstempel tijdzone-bewust is
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            ts_cet = ts.tz_convert(CET)

            candles.append({
                "symbol": self.ticker,
                "time":   ts_cet.isoformat(),
                "open":   round(float(row["Open"]),  4),
                "high":   round(float(row["High"]),  4),
                "low":    round(float(row["Low"]),   4),
                "close":  round(float(row["Close"]), 4),
                "volume": int(row["Volume"]),
            })
        return candles

    def stream_candles(self, limit=None):
        """Generator: historische candles direct, daarna elke 60s nieuwe candles."""
        count = 0

        # --- Initiële batch: de volledige dag tot nu ---
        for c in self._fetch():
            if self._last_ts is None or c["time"] > self._last_ts:
                self._last_ts = c["time"]
                yield c
                count += 1
                if limit and count >= limit:
                    return

        # --- Live-polling: wacht 60s, haal nieuwe candles op ---
        while True:
            time.sleep(POLL_INTERVAL)
            new = [c for c in self._fetch()
                   if c["time"] > (self._last_ts or "")]
            for c in new:
                self._last_ts = c["time"]
                yield c
                count += 1
                if limit and count >= limit:
                    return
