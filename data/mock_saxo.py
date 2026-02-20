import random
import datetime as dt


class MockSaxoFeed:
    """Generate mock 1-minute candles for an underlying symbol.

    Yields dicts: {symbol, time, open, high, low, close, volume}
    """

    def __init__(self, symbol="ASML", start_price=1200.0):
        self.symbol = symbol
        self.price = float(start_price)
        self.time = dt.datetime.utcnow()

    def _next_candle(self):
        # random walk for price
        open_p = self.price
        drift = random.uniform(-0.8, 0.8)
        close = max(0.1, open_p + drift)
        high = max(open_p, close) + random.uniform(0, 0.5)
        low = min(open_p, close) - random.uniform(0, 0.5)
        volume = random.randint(100, 2000)
        candle = {
            "symbol": self.symbol,
            "time": self.time.isoformat() + "Z",
            "open": round(open_p, 4),
            "high": round(high, 4),
            "low": round(low, 4),
            "close": round(close, 4),
            "volume": int(volume),
        }
        # advance
        self.price = close
        self.time += dt.timedelta(minutes=1)
        return candle

    def stream_candles(self, limit=None):
        """Generator for candles. If limit is provided, stops after limit."""
        count = 0
        while True:
            yield self._next_candle()
            count += 1
            if limit and count >= limit:
                break
