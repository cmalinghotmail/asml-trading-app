def turbo_prijs(asml_prijs: float, financiering: float, ratio: float, side: str) -> float:
    """Bereken turbo prijs voor één ASML-niveau.

    Gebruik dit voor losse prijsconversies (bijv. box-niveaus, entry-indicator).
    Gebruik TurboTranslator.translate() voor volledige signalen met SL/TP en leverage.
    """
    if ratio <= 0:
        return 0.0
    if side == "LONG":
        return round((asml_prijs - financiering) / ratio, 2)
    return round((financiering - asml_prijs) / ratio, 2)


class TurboTranslator:
    """Translate ASML SL/TP levels to turbo prices using financing level and ratio.

    Inputs per translate() call:
      - asml_price : current ASML price (used to compute leverage at that level)
      - financing  : the financing level (financieringsniveau) for this turbo product
      - ratio      : the product ratio (e.g., 1, 10, 100)

    Outputs:
      - turbo_entry_price, turbo_sl_price, turbo_tp_price  (absolute turbo prices)
      - leverage  (computed from asml_price and financing — changes with ASML price)
    """

    def __init__(self, cfg=None):
        cfg = cfg or {}
        self.long_isin  = cfg.get("long_isin",  "")
        self.short_isin = cfg.get("short_isin", "")

    def translate(self, signal, asml_price=None, financing=None, ratio=None):
        """Translate ASML entry/SL/TP to turbo absolute prices.

        Args:
            signal    : dict with keys side, entry, sl, tp
            asml_price: ASML price at which leverage is computed (usually entry or current price)
            financing : financing level (financieringsniveau) for this turbo
            ratio     : product ratio (e.g., 1, 10, 100)

        Returns a dict with turbo_entry_price, turbo_sl_price, turbo_tp_price, leverage.
        Returns an error key when financing or ratio is missing.
        """
        entry = float(signal.get("entry"))
        sl    = float(signal.get("sl"))
        tp    = float(signal.get("tp"))
        side  = signal.get("side")

        result = {
            "long_isin":  self.long_isin,
            "short_isin": self.short_isin,
        }

        if financing is None or ratio is None or asml_price is None:
            result["error"] = "financing, ratio of asml_price ontbreekt"
            return result

        financing  = float(financing)
        ratio      = float(ratio)
        asml_price = float(asml_price)

        if side == "LONG":
            intrinsic  = asml_price - financing
            leverage   = asml_price / intrinsic if intrinsic > 0 else 0.0
            turbo_entry = (entry - financing) / ratio
            turbo_sl    = (sl    - financing) / ratio
            turbo_tp    = (tp    - financing) / ratio
        else:
            intrinsic  = financing - asml_price
            leverage   = asml_price / intrinsic if intrinsic > 0 else 0.0
            turbo_entry = (financing - entry) / ratio
            turbo_sl    = (financing - sl)    / ratio
            turbo_tp    = (financing - tp)    / ratio

        result.update({
            "financing":         round(financing, 2),
            "leverage":          round(leverage, 2),
            "ratio":             ratio,
            "turbo_entry_price": round(turbo_entry, 2),
            "turbo_sl_price":    round(turbo_sl,    2),
            "turbo_tp_price":    round(turbo_tp,    2),
        })
        return result
