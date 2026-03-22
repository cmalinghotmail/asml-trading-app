"""Box Strategie — data ophalen en zone rendering.

Bevat de logica voor de Previous Day Box strategie:
- fetch_box_levels(): haalt prev-dag H/L/Mid op via yfinance
- render_box_zone(): rendert één LONG of SHORT zone in de Streamlit UI
"""

import streamlit as st

from data.fetcher import fetch_daily
from turbo.translate import TurboTranslator


def fetch_box_levels(ticker: str) -> dict | None:
    """Haal vorige volledige handelsdag High/Low/Mid op via yfinance.

    Weekend-afhandeling is automatisch: yfinance retourneert vrijdag als
    de meest recente completed trading day wanneer het weekend is.
    Fetcht ook ASML Nasdaq prev-dag H/L (in USD + EUR) en de USD/EUR koers.
    """
    try:
        df = fetch_daily(ticker, period="5d")
        if df is None:
            return None
        row  = df.iloc[-1]
        high = round(float(row["High"]), 2)
        low  = round(float(row["Low"]),  2)
        result = {
            "date": df.index[-1].date().isoformat(),
            "high": high,
            "low":  low,
            "mid":  round((high + low) / 2, 2),
        }
    except Exception:
        return None

    # ASML Nasdaq prev-dag H/L + USD/EUR koers
    try:
        df_nas = fetch_daily("ASML",     period="5d")
        df_fx  = fetch_daily("EURUSD=X", period="2d", exclude_today=False)
        if df_nas is not None and df_fx is not None:
            nas_row = df_nas.iloc[-1]
            usd_eur = round(1.0 / float(df_fx.iloc[-1]["Close"]), 6)
            nh_usd  = round(float(nas_row["High"]),  2)
            nl_usd  = round(float(nas_row["Low"]),   2)
            nc_usd  = round(float(nas_row["Close"]), 2)
            result["nasdaq_high_usd"]  = nh_usd
            result["nasdaq_low_usd"]   = nl_usd
            result["nasdaq_close_usd"] = nc_usd
            result["nasdaq_high_eur"]  = round(nh_usd * usd_eur, 2)
            result["nasdaq_low_eur"]   = round(nl_usd * usd_eur, 2)
            result["nasdaq_mid_eur"]   = round((nh_usd + nl_usd) / 2 * usd_eur, 2)
            result["nasdaq_close_eur"] = round(nc_usd * usd_eur, 2)
            result["usd_eur"]          = usd_eur
    except Exception:
        pass  # Nasdaq-data optioneel — Euronext box werkt zonder

    return result


def render_box_zone(col, side, key_pfx, def_entry, def_sl, def_tp, fin, rat,
                    turbo_naam="", turbo_isin=""):
    """Render één box-zone (LONG of SHORT) met ASML-inputs en turbo-output."""
    icon  = "🟢" if side == "LONG" else "🔴"
    title = "LONG zone  —  instap onderkant" if side == "LONG" else "SHORT zone  —  instap bovenkant"
    with col:
        with st.container(border=True):
            st.markdown(f"**{icon} {title}**")
            _product_label = "  |  ".join(filter(None, [turbo_naam, turbo_isin]))
            if _product_label:
                st.caption(_product_label)
            st.divider()

            c1, c2, c3 = st.columns(3)
            with c1:
                entry = st.number_input(
                    "ASML Entry", min_value=100.0, max_value=9000.0,
                    value=def_entry, step=0.5, format="%.2f",
                    key=f"{key_pfx}_entry",
                )
            with c2:
                sl = st.number_input(
                    "ASML SL", min_value=100.0, max_value=9000.0,
                    value=def_sl, step=0.5, format="%.2f",
                    key=f"{key_pfx}_sl",
                )
            with c3:
                tp = st.number_input(
                    "ASML TP", min_value=100.0, max_value=9000.0,
                    value=def_tp, step=0.5, format="%.2f",
                    key=f"{key_pfx}_tp",
                )

            if side == "LONG":
                _sl_dist = round(entry - sl, 2)
                _tp_dist = round(tp - entry, 2)
            else:
                _sl_dist = round(sl - entry, 2)
                _tp_dist = round(entry - tp, 2)
            st.caption(f"SL afstand: {_sl_dist:+.2f} EUR  |  TP afstand: {_tp_dist:+.2f} EUR")

            # Turbo berekening via financieringsniveau
            sig = {"side": side, "entry": entry, "sl": sl, "tp": tp}
            res = TurboTranslator({}).translate(sig, asml_price=entry, financing=fin, ratio=rat)
            turbo_entry = res.get("turbo_entry_price", 0.0)
            t_sl        = res.get("turbo_sl_price")
            t_tp        = res.get("turbo_tp_price")
            leverage    = res.get("leverage")

            st.divider()

            lc, rc = st.columns([1, 2])
            lc.markdown("**Turbo entry**")
            rc.markdown(f"**€ {turbo_entry:.2f}**")

            if t_sl is not None:
                _tsl_d  = abs(turbo_entry - t_sl)
                _ttp_d  = abs(t_tp - turbo_entry)
                _rr     = round(_ttp_d / _tsl_d, 2) if _tsl_d > 0 else 0.0
                _sl_pct = (t_sl / turbo_entry - 1) * 100 if turbo_entry else 0.0
                _tp_pct = (t_tp / turbo_entry - 1) * 100 if turbo_entry else 0.0

                for _lbl, _val in [
                    ("🔴 Turbo SL",  f"**€ {t_sl:.2f}**  *({_sl_pct:+.1f}% / −{_tsl_d:.2f})*"),
                    ("🟢 Turbo TP",  f"**€ {t_tp:.2f}**  *({_tp_pct:+.1f}% / +{_ttp_d:.2f})*"),
                    ("R/R",          f"**{_rr:.2f}**"),
                    ("Leverage",     f"{leverage:.2f}×" if leverage is not None else "—"),
                ]:
                    lc, rc = st.columns([1, 2])
                    lc.markdown(f"**{_lbl}**")
                    rc.markdown(_val)
            else:
                st.info("Stel het financieringsniveau in de zijbalk in.")
