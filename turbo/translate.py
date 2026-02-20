class TurboTranslator:
    """Translate ASML SL/TP levels to turbo prices using financing level and ratio.

    New translation uses these inputs per signal:
      - asml_price: the ASML price used to derive financing
      - turbo_price: the current turbo market price (user-provided)
      - ratio: the product ratio (e.g., 1, 10, 100)

    The translator keeps a `leverage` value for compatibility and reporting.
    """

    def __init__(self, cfg=None):
        cfg = cfg or {}
        # store leverage rounded to 2 decimals (for reporting only)
        self.leverage = round(float(cfg.get("leverage", 10.0)), 2)
        self.long_isin = cfg.get("long_isin", "")
        self.short_isin = cfg.get("short_isin", "")

    def translate(self, signal, asml_price=None, turbo_price=None, ratio=None):
        """Translate ASML SL/TP to turbo absolute prices.

        If `turbo_price` or `ratio` is missing, falls back to distance/lev mapping
        (legacy behavior) returning turbo distances instead of absolute prices.

        Returns a dict containing either `turbo_sl_price` and `turbo_tp_price`
        (absolute turbo prices) when possible, or `turbo_sl_distance` and
        `turbo_tp_distance` when only leverage-based fallback is available.
        """
        entry = float(signal.get("entry"))
        sl = float(signal.get("sl"))
        tp = float(signal.get("tp"))
        side = signal.get("side")

        result = {
            "leverage": self.leverage,
            "long_isin": self.long_isin,
            "short_isin": self.short_isin,
        }

        # If we have turbo_price and ratio, compute financing and map levels
        if turbo_price is not None and ratio is not None and asml_price is not None:
            turbo_price = float(turbo_price)
            ratio = float(ratio)
            asml_price = float(asml_price)

            intrinsic = turbo_price * ratio
            # Financing level depends on side
            if side == "LONG":
                financing = asml_price - intrinsic
                turbo_sl = (sl - financing) / ratio
                turbo_tp = (tp - financing) / ratio
            else:
                financing = asml_price + intrinsic
                turbo_sl = (financing - sl) / ratio
                turbo_tp = (financing - tp) / ratio

            result.update({
                "financing": round(financing, 6),
                "ratio": ratio,
                "turbo_price": round(turbo_price, 6),
                "turbo_sl_price": round(turbo_sl, 2),
                "turbo_tp_price": round(turbo_tp, 2),
            })
            return result

        # Fallback: use legacy distance / leverage mapping
        if side == "LONG":
            underlying_sl_dist = abs(entry - sl)
            underlying_tp_dist = abs(tp - entry)
        else:
            underlying_sl_dist = abs(sl - entry)
            underlying_tp_dist = abs(entry - tp)

        turbo_sl = underlying_sl_dist / self.leverage
        turbo_tp = underlying_tp_dist / self.leverage
        result.update({
            "turbo_sl_distance": round(turbo_sl, 4),
            "turbo_tp_distance": round(turbo_tp, 4),
        })
        return result
