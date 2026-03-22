"""ASML H/L Tranche Strategie Calculator.

Gelaagde verkoopstrategie gekoppeld aan historische H/L patroondata
(prev day / prev week high/low), dag-van-de-week modifiers en
Nasdaq cross-exchange signalen.
"""

import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data.fetcher import fetch_daily, extract_prev_week_hl
from turbo.translate import turbo_prijs

# ---------------------------------------------------------------------------
# Historische statistieken — 6 maanden Amsterdam bounce data
# ---------------------------------------------------------------------------

HL_STATS = {
    "prev_day_high":  {"touch": 0.62, "bounce": 0.60, "avg_move": 12.00},
    "prev_day_low":   {"touch": 0.52, "bounce": 0.58, "avg_move": 12.98},
    "prev_week_high": {"touch": 0.24, "bounce": 0.76, "avg_move": 18.68},
    "prev_week_low":  {"touch": 0.17, "bounce": 0.62, "avg_move": 11.20},
}

# Dag-van-de-week modifiers (procentpunten op bounce%)
DOW_MOD_LONG = {      # aanpassing bounce bij Prev Day High (LONG weerstand)
    "Maandag":  +19,
    "Dinsdag":   -4,
    "Woensdag": -13,
    "Donderdag": -2,
    "Vrijdag":   -2,
}

DOW_MOD_SHORT = {     # aanpassing bounce bij Prev Day Low (SHORT weerstand)
    "Maandag":   -2,
    "Dinsdag":  +13,
    "Woensdag":  +1,
    "Donderdag":  0,
    "Vrijdag":  -15,
}

# Nasdaq cross-exchange constanten
NASDAQ_AMS_PREMIUM = 0.93   # EUR
NASDAQ_CORRELATION = 0.995

# Turbo standaard defaults (hardcoded referentiewaarden)
DEFAULT_LONG = {
    "asml_koers":    1183.6,
    "financiering":  886.28,
    "stop_loss":     952.5,
    "leverage":      3.91,
    "max_leverage":  5.0,
    "ratio":         100,
    "isin":          "NLBNPNL3EX12",
}

DEFAULT_SHORT = {
    "asml_koers":    1183.4,
    "financiering":  1569.52,
    "stop_loss":     1451.9,
    "max_leverage":  5.0,
    "ratio":         100,
    "isin":          "NLBNPNL3FE71",
}


# ---------------------------------------------------------------------------
# Hulpfuncties — berekeningen
# ---------------------------------------------------------------------------

def _bounce_kleur(pct: float) -> str:
    if pct >= 70:
        return "🟢"
    if pct >= 50:
        return "🟡"
    return "🔴"


def _merge_dichtbij(candidates: list, merge_pct: float = 0.02) -> list:
    """Samenvoegen van niveaus die binnen merge_pct van elkaar liggen."""
    if not candidates:
        return candidates
    candidates = sorted(candidates, key=lambda x: x["asml_doel"])
    merged = [candidates[0].copy()]
    for lv in candidates[1:]:
        prev = merged[-1]
        if abs(lv["asml_doel"] - prev["asml_doel"]) / prev["asml_doel"] < merge_pct:
            merged[-1] = {
                "asml_doel":   round((prev["asml_doel"] + lv["asml_doel"]) / 2, 2),
                "niveau_type": f"{prev['niveau_type']} + {lv['niveau_type']}",
                "bounce_base": (prev["bounce_base"] + lv["bounce_base"]) / 2,
                "bounce_adj":  (prev["bounce_adj"]  + lv["bounce_adj"])  / 2,
            }
        else:
            merged.append(lv.copy())
    return merged


def _tranche_verdeling(n_totaal: int, n_tranches: int) -> list:
    """Verdeelsleutel 40/30/30, afgerond op veelvoud van 10."""
    if n_tranches <= 0:
        return []
    if n_tranches == 1:
        return [n_totaal]
    weights = [0.40, 0.30, 0.30][:n_tranches]
    sizes, resterend = [], n_totaal
    for i, w in enumerate(weights):
        if i == n_tranches - 1:
            sizes.append(max(10, resterend))
        else:
            s = max(10, round(n_totaal * w / 10) * 10)
            sizes.append(s)
            resterend -= s
    return sizes


# ---------------------------------------------------------------------------
# H/L niveaus ophalen via yfinance
# ---------------------------------------------------------------------------

def _fetch_hl_levels(ticker: str = "ASML.AS") -> dict:
    """Haal prev day H/L en prev week H/L op via yfinance."""
    result = {}
    try:
        df = fetch_daily(ticker, period="30d")
        if df is None:
            return result
        row = df.iloc[-1]
        result["prev_day_high"] = round(float(row["High"]), 2)
        result["prev_day_low"]  = round(float(row["Low"]),  2)
        result["prev_day_date"] = df.index[-1].date().isoformat()
        result.update(extract_prev_week_hl(df))
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
# Tranche builder
# ---------------------------------------------------------------------------

def _build_tranches(mode: str, asml_entry: float, asml_sl: float,
                    n_turbos: int, pdh, pdl, pwh, pwl,
                    financing: float, ratio: float,
                    dag_van_week: str) -> tuple:
    """
    Bouw tranche ladder. Geeft (tranches_list, turbo_entry_prijs) terug.
    """
    candidates = []

    if mode == "LONG":
        dow_mod = DOW_MOD_LONG.get(dag_van_week, 0)

        if pdh is not None and pdh > asml_entry and pdh > financing:
            b = HL_STATS["prev_day_high"]["bounce"] * 100
            candidates.append({
                "asml_doel":   pdh,
                "niveau_type": "Prev Day High",
                "bounce_base": b,
                "bounce_adj":  min(100.0, max(0.0, b + dow_mod)),
            })
        if pwh is not None and pwh > asml_entry and pwh > financing:
            b = HL_STATS["prev_week_high"]["bounce"] * 100
            candidates.append({
                "asml_doel":   pwh,
                "niveau_type": "Prev Week High",
                "bounce_base": b,
                "bounce_adj":  b,  # geen dag-modifier voor week-niveau LONG
            })

        candidates = _merge_dichtbij(candidates)

        if len(candidates) < 2:
            free = round(asml_entry * 1.18, 2)
            candidates.append({
                "asml_doel":   free,
                "niveau_type": "Vrij doel (+18%)",
                "bounce_base": 0.0,
                "bounce_adj":  0.0,
            })

        candidates = sorted(candidates, key=lambda x: x["asml_doel"])  # oplopend

    else:  # SHORT
        dow_mod = DOW_MOD_SHORT.get(dag_van_week, 0)

        if pdl is not None and pdl < asml_entry and pdl < financing:
            b = HL_STATS["prev_day_low"]["bounce"] * 100
            candidates.append({
                "asml_doel":   pdl,
                "niveau_type": "Prev Day Low",
                "bounce_base": b,
                "bounce_adj":  min(100.0, max(0.0, b + dow_mod)),
            })
        if pwl is not None and pwl < asml_entry and pwl < financing:
            b = HL_STATS["prev_week_low"]["bounce"] * 100
            candidates.append({
                "asml_doel":   pwl,
                "niveau_type": "Prev Week Low",
                "bounce_base": b,
                "bounce_adj":  b,  # geen dag-modifier voor week-niveau SHORT
            })

        # Niveaus voorbij stop loss overslaan (voor SHORT: SL > entry, niveau < asml_sl check n.v.t.)
        # Wel: niveau boven SL overslaan (zou knockout zijn)
        candidates = [c for c in candidates if c["asml_doel"] < asml_sl]

        candidates = _merge_dichtbij(candidates)

        if len(candidates) < 2:
            free = round(asml_entry * 0.82, 2)
            candidates.append({
                "asml_doel":   free,
                "niveau_type": "Vrij doel (−18%)",
                "bounce_base": 0.0,
                "bounce_adj":  0.0,
            })

        candidates = sorted(candidates, key=lambda x: x["asml_doel"], reverse=True)  # dalend

    candidates = candidates[:3]
    sizes = _tranche_verdeling(n_turbos, len(candidates))
    turbo_ep = turbo_prijs(asml_entry, financing, ratio, mode)

    tranches = []
    for i, (cand, size) in enumerate(zip(candidates, sizes)):
        doel = cand["asml_doel"]
        turbo_doel = turbo_prijs(doel, financing, ratio, mode)
        winst_per = turbo_doel - turbo_ep
        afstand_pct = (
            (doel - asml_entry) / asml_entry * 100 if mode == "LONG"
            else (asml_entry - doel) / asml_entry * 100
        )
        tranches.append({
            "Tranche":      f"T{i + 1}",
            "Grootte":      size,
            "ASML doel":    doel,
            "Niveau type":  cand["niveau_type"],
            "Bounce basis": cand["bounce_base"],
            "Bounce adj":   cand["bounce_adj"],
            "Afstand %":    round(afstand_pct, 2),
            "Turboprijs":   round(turbo_ep, 2),
            "Winst/turbo":  round(winst_per, 2),
            "Totale winst": round(winst_per * size, 2),
        })

    return tranches, turbo_ep


# ---------------------------------------------------------------------------
# Plotly prijsladder
# ---------------------------------------------------------------------------

def _build_ladder_chart(mode: str, asml_entry: float, asml_sl: float,
                        tranches: list, pdh, pdl, pwh, pwl,
                        nasdaq_open_verwacht) -> go.Figure:
    fig = go.Figure()

    all_vals = [asml_entry, asml_sl]
    for t in tranches:
        all_vals.append(t["ASML doel"])
    for v in [pdh, pdl, pwh, pwl, nasdaq_open_verwacht]:
        if v is not None:
            all_vals.append(v)
    y_min = min(all_vals) * 0.983
    y_max = max(all_vals) * 1.017

    # Achtergrondlijnen H/L niveaus
    for val, color, dash, label in [
        (pdh,  "#6e7080", "dash",     "Prev Day High"),
        (pdl,  "#6e7080", "dot",      "Prev Day Low"),
        (pwh,  "#5a5a7a", "dashdot",  "Prev Week High"),
        (pwl,  "#5a5a7a", "longdash", "Prev Week Low"),
    ]:
        if val is None:
            continue
        fig.add_shape(
            type="line", xref="paper", yref="y",
            x0=0.04, x1=0.96, y0=val, y1=val,
            line=dict(color=color, width=1, dash=dash),
        )
        fig.add_annotation(
            x=0.03, xref="paper", y=val, yref="y",
            text=f"{label}  € {val:.2f}",
            showarrow=False,
            font=dict(color=color, size=9),
            xanchor="right",
        )

    # Nasdaq verwachte open
    if nasdaq_open_verwacht is not None:
        fig.add_shape(
            type="line", xref="paper", yref="y",
            x0=0.04, x1=0.96, y0=nasdaq_open_verwacht, y1=nasdaq_open_verwacht,
            line=dict(color="#ffd700", width=1.5, dash="dot"),
        )
        fig.add_annotation(
            x=0.97, xref="paper", y=nasdaq_open_verwacht, yref="y",
            text=f"Nasdaq open  € {nasdaq_open_verwacht:.2f}",
            showarrow=False,
            font=dict(color="#ffd700", size=9),
            xanchor="left",
        )

    # Stop loss lijn
    fig.add_shape(
        type="line", xref="paper", yref="y",
        x0=0.04, x1=0.96, y0=asml_sl, y1=asml_sl,
        line=dict(color="#ef5350", width=2, dash="dash"),
    )
    fig.add_annotation(
        x=0.97, xref="paper", y=asml_sl, yref="y",
        text=f"Stop loss  € {asml_sl:.2f}",
        showarrow=False,
        font=dict(color="#ef5350", size=10),
        xanchor="left",
    )

    # Entry-pin
    fig.add_trace(go.Scatter(
        x=[0.5], y=[asml_entry],
        mode="markers",
        marker=dict(size=20, color="#ffd700", symbol="circle",
                    line=dict(color="#000000", width=2)),
        name=f"Entry  € {asml_entry:.2f}",
        hovertemplate=f"Entry: € {asml_entry:.2f}<extra></extra>",
    ))

    # Tranche-markeringen
    kleuren = ["#26a69a", "#4fa3e0", "#ffa726", "#ab47bc"]
    for i, t in enumerate(tranches):
        kleur = kleuren[i % len(kleuren)]
        bp = t["Bounce adj"] if t["Bounce adj"] > 0 else t["Bounce basis"]
        fig.add_trace(go.Scatter(
            x=[0.5], y=[t["ASML doel"]],
            mode="markers+text",
            marker=dict(size=18, color=kleur, symbol="diamond",
                        line=dict(color="white", width=1)),
            text=[t["Tranche"]],
            textposition="middle right",
            textfont=dict(color="white", size=10),
            name=f"{t['Tranche']}: {t['Niveau type']}  € {t['ASML doel']:.2f}",
            hovertemplate=(
                f"<b>{t['Tranche']}: {t['Niveau type']}</b><br>"
                f"ASML doel: € {t['ASML doel']:.2f}<br>"
                f"Grootte: {t['Grootte']} turbos<br>"
                f"Bounce: {bp:.0f}%<br>"
                f"Winst/turbo: € {t['Winst/turbo']:.2f}<br>"
                f"Totale winst: € {t['Totale winst']:.2f}<extra></extra>"
            ),
        ))

    fig.update_layout(
        plot_bgcolor="#1a1f2e",
        paper_bgcolor="#0e1117",
        font=dict(color="#fafafa", size=11),
        height=420,
        margin=dict(l=10, r=200, t=30, b=10),
        xaxis=dict(visible=False, range=[0, 1]),
        yaxis=dict(
            gridcolor="#2a2f3e",
            showgrid=True,
            tickprefix="€ ",
            tickformat=".2f",
            range=[y_min, y_max],
            title="ASML koers (EUR)",
        ),
        legend=dict(
            x=1.01, y=1, xanchor="left",
            bgcolor="#1a1f2e",
            bordercolor="#2a2f3e",
            font=dict(size=9),
        ),
    )
    return fig


# ---------------------------------------------------------------------------
# Nasdaq signaal blok
# ---------------------------------------------------------------------------

def _render_nasdaq_signaal(nasdaq_slot, pdh, pdl, pwh, pwl):
    with st.container(border=True):
        st.markdown("**🇺🇸 Nasdaq Signaal**")
        if nasdaq_slot is None or nasdaq_slot <= 0:
            st.info("Voer de Nasdaq slotkoers in om signalen te berekenen.")
            return

        ams_open = round(nasdaq_slot + NASDAQ_AMS_PREMIUM, 2)
        st.markdown(
            f"Amsterdam open verwachting: **€ {ams_open:.2f}**"
            f"  *(Nasdaq slot + {NASDAQ_AMS_PREMIUM:.2f} EUR)*"
        )
        st.caption(f"Correlatie Nasdaq → Amsterdam: **{NASDAQ_CORRELATION:.3f}**")
        st.divider()

        for label, niveau, boven_txt, onder_txt in [
            (
                "Prev Week High", pwh,
                "Nasdaq sloot **boven** prev week high → Amsterdam **break waarschijnlijk** (Nasdaq 64% kans)",
                "Nasdaq sloot **onder** prev week high → Amsterdam **bounce waarschijnlijk** (76% kans)",
            ),
            (
                "Prev Week Low", pwl,
                "Nasdaq sloot **onder** prev week low → Amsterdam **bounce waarschijnlijk** (62% kans)",
                "Nasdaq sloot **boven** prev week low → Nasdaq **bounce waarschijnlijk** (77% kans)",
            ),
        ]:
            if niveau is None:
                continue
            afstand = round(ams_open - niveau, 2)
            afstand_pct = round(afstand / niveau * 100, 2) if niveau else 0.0
            st.markdown(f"**{label}: € {niveau:.2f}**")
            st.caption(f"Afstand open verwachting: **{afstand:+.2f} EUR ({afstand_pct:+.2f}%)**")
            if label == "Prev Week High":
                if nasdaq_slot >= niveau:
                    st.warning(boven_txt)
                else:
                    st.success(onder_txt)
            else:
                if nasdaq_slot <= niveau:
                    st.warning(boven_txt)
                else:
                    st.success(onder_txt)


# ---------------------------------------------------------------------------
# Scenario samenvatting
# ---------------------------------------------------------------------------

def _render_scenario(mode: str, asml_entry: float, asml_sl: float,
                     n_turbos: int, tranches: list,
                     financing: float, ratio: float):
    turbo_ep = turbo_prijs(asml_entry, financing, ratio, mode)
    totale_inleg = round(turbo_ep * n_turbos, 2)
    worst_case = -totale_inleg

    if mode == "LONG":
        break_even = round(financing + turbo_ep * ratio, 2)
    else:
        break_even = round(financing - turbo_ep * ratio, 2)

    totale_winst_3 = sum(t["Totale winst"] for t in tranches)

    vrijgemaakt_t1 = round(turbo_ep * tranches[0]["Grootte"], 2) if tranches else 0.0
    vrijgemaakt_t12 = (
        round(turbo_ep * (tranches[0]["Grootte"] + tranches[1]["Grootte"]), 2)
        if len(tranches) >= 2 else vrijgemaakt_t1
    )

    with st.container(border=True):
        st.markdown("**📊 Scenario Samenvatting**")
        for lbl, val in [
            ("Turbo entry prijs",      f"**€ {turbo_ep:.2f}**"),
            ("Totale inleg",           f"**€ {totale_inleg:,.2f}**  *({n_turbos} turbos)*"),
            ("Winst alle tranches",    f"**€ {totale_winst_3:,.2f}**"),
            ("Worst case (knockout)",  f"**€ {worst_case:,.2f}**  *(verlies totale inleg)*"),
            ("Break-even ASML",        f"**€ {break_even:.2f}**"),
            ("Vrijgemaakt na T1",      f"**€ {vrijgemaakt_t1:,.2f}**"),
            ("Vrijgemaakt na T1+T2",   f"**€ {vrijgemaakt_t12:,.2f}**"),
        ]:
            lc, rc = st.columns([2, 3])
            lc.markdown(lbl)
            rc.markdown(val)


# ---------------------------------------------------------------------------
# Hoofd render functie — wordt aangeroepen vanuit streamlit_app.py
# ---------------------------------------------------------------------------

def render_hl_tranche_tab(financing_long: float = 0.0, ratio_long: int = 100,
                           financing_short: float = 0.0, ratio_short: int = 100):
    """Render de H/L Tranche Strategie Calculator tab."""

    # Session state initialisatie
    _defaults = {
        "hl_modus":        "LONG",
        "hl_n_turbos":     100,
        "hl_asml_entry":   DEFAULT_LONG["asml_koers"],
        "hl_sl_long":      DEFAULT_LONG["stop_loss"],
        "hl_sl_short":     DEFAULT_SHORT["stop_loss"],
        "hl_nasdaq_slot":  0.0,
        "hl_dag":          "Maandag",
        "hl_pdh":          0.0,
        "hl_pdl":          0.0,
        "hl_pwh":          0.0,
        "hl_pwl":          0.0,
    }
    for k, v in _defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # Synchroniseer Nasdaq slot altijd vanuit box_levels (zelfde bron als Trading Monitor tab)
    _box = st.session_state.get("box_levels")
    if _box and _box.get("nasdaq_close_eur"):
        st.session_state["hl_nasdaq_slot"] = float(_box["nasdaq_close_eur"])

    st.markdown("### H/L Tranche Strategie Calculator")
    st.caption(
        "Gelaagde verkoopstrategie op basis van historische Amsterdam bounce-statistieken.  "
        "Statistieken gebaseerd op 6 maanden ASML op Euronext Amsterdam."
    )

    # -----------------------------------------------------------------------
    # Invoerkolommen
    # -----------------------------------------------------------------------
    col_pos, col_niv = st.columns([1, 1], gap="medium")

    with col_pos:
        with st.container(border=True):
            st.markdown("**Positie instelling**")

            modus = st.radio(
                "Modus",
                options=["LONG", "SHORT"],
                horizontal=True,
                key="hl_modus",
            )

            n_turbos = st.slider(
                "Aantal turbos",
                min_value=25, max_value=1000, step=25,
                key="hl_n_turbos",
            )

            asml_entry = st.number_input(
                "ASML instapkoers (EUR)",
                min_value=100.0, max_value=9000.0, step=0.5, format="%.2f",
                key="hl_asml_entry",
            )

            # Financiering en ratio: uit sidebar (gedeelde state)
            if modus == "LONG":
                fin = financing_long  if financing_long  > 1.0 else DEFAULT_LONG["financiering"]
                rat = float(ratio_long if ratio_long > 0 else DEFAULT_LONG["ratio"])
                sl_key = "hl_sl_long"
            else:
                fin = financing_short if financing_short > 1.0 else DEFAULT_SHORT["financiering"]
                rat = float(ratio_short if ratio_short > 0 else DEFAULT_SHORT["ratio"])
                sl_key = "hl_sl_short"

            asml_sl = st.number_input(
                "Stop loss ASML niveau (EUR)",
                min_value=100.0, max_value=9000.0, step=0.5, format="%.2f",
                key=sl_key,
                help="Knock-out drempel van de turbo",
            )

            turbo_ep = turbo_prijs(asml_entry, fin, rat, modus)
            if modus == "LONG":
                _lev = asml_entry / (asml_entry - fin) if (asml_entry - fin) > 0 else 0.0
            else:
                _lev = asml_entry / (fin - asml_entry) if (fin - asml_entry) > 0 else 0.0

            st.caption(
                f"Turbo entry: **€ {turbo_ep:.2f}**  |  "
                f"Financiering: **€ {fin:.2f}**  |  "
                f"Ratio: **{int(rat)}**  |  "
                f"Leverage: **{_lev:.2f}×**"
            )

    with col_niv:
        with st.container(border=True):
            st.markdown("**H/L Niveaus**")

            _lbl_col, _btn_col = st.columns([3, 1])
            with _lbl_col:
                st.caption("Prev day/week H/L via yfinance ophalen:")
            with _btn_col:
                if st.button("🔄 Ophalen", key="hl_fetch_btn", width="stretch"):
                    with st.spinner("Ophalen…"):
                        levels = _fetch_hl_levels("ASML.AS")
                    if levels:
                        for _fk, _sk in [
                            ("prev_day_high",  "hl_pdh"),
                            ("prev_day_low",   "hl_pdl"),
                            ("prev_week_high", "hl_pwh"),
                            ("prev_week_low",  "hl_pwl"),
                        ]:
                            if levels.get(_fk):
                                st.session_state[_sk] = levels[_fk]
                        st.rerun()
                    else:
                        st.error("Ophalen mislukt — controleer verbinding.")

            c1, c2 = st.columns(2)
            with c1:
                pdh = st.number_input(
                    "Prev Day High (EUR)",
                    min_value=0.0, max_value=9000.0, step=0.5, format="%.2f",
                    key="hl_pdh",
                )
                pwh = st.number_input(
                    "Prev Week High (EUR)",
                    min_value=0.0, max_value=9000.0, step=0.5, format="%.2f",
                    key="hl_pwh",
                )
            with c2:
                pdl = st.number_input(
                    "Prev Day Low (EUR)",
                    min_value=0.0, max_value=9000.0, step=0.5, format="%.2f",
                    key="hl_pdl",
                )
                pwl = st.number_input(
                    "Prev Week Low (EUR)",
                    min_value=0.0, max_value=9000.0, step=0.5, format="%.2f",
                    key="hl_pwl",
                )

            nasdaq_slot = st.number_input(
                "Nasdaq slotkoers vorige avond (EUR)",
                min_value=0.0, max_value=9000.0, step=0.5, format="%.2f",
                key="hl_nasdaq_slot",
                help="ASML Nasdaq slotkoers omgerekend naar EUR (zie box-blok hierboven)",
            )

            dag_van_week = st.selectbox(
                "Dag van de week",
                options=["Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag"],
                key="hl_dag",
            )

    # -----------------------------------------------------------------------
    # Berekeningen
    # -----------------------------------------------------------------------
    pdh_v = pdh  if pdh  > 0 else None
    pdl_v = pdl  if pdl  > 0 else None
    pwh_v = pwh  if pwh  > 0 else None
    pwl_v = pwl  if pwl  > 0 else None
    nas_v = nasdaq_slot if nasdaq_slot > 0 else None
    nasdaq_open_v = round(nas_v + NASDAQ_AMS_PREMIUM, 2) if nas_v else None

    tranches, turbo_ep = _build_tranches(
        mode=modus,
        asml_entry=asml_entry,
        asml_sl=asml_sl,
        n_turbos=n_turbos,
        pdh=pdh_v, pdl=pdl_v, pwh=pwh_v, pwl=pwl_v,
        financing=fin, ratio=rat,
        dag_van_week=dag_van_week,
    )

    st.divider()

    # -----------------------------------------------------------------------
    # Tranche tabel
    # -----------------------------------------------------------------------
    with st.container(border=True):
        st.markdown("**📋 Tranche Ladder**")

        if not tranches:
            st.warning(
                "Geen geldige niveaus gevonden. "
                "Controleer of de H/L niveaus correct zijn t.o.v. de instapkoers."
            )
        else:
            _COL_W = [0.7, 0.8, 1.2, 1.8, 1.5, 0.9, 1.2, 1.2, 1.4]
            _HDRS  = [
                "Tranche", "Grootte", "ASML doel", "Niveau type",
                "Bounce kans", "Afstand %", "Turboprijs", "Winst/turbo", "Totale winst",
            ]
            for hc, hl in zip(st.columns(_COL_W), _HDRS):
                hc.markdown(f"**{hl}**")
            st.divider()

            for t in tranches:
                bp = t["Bounce adj"] if t["Bounce adj"] > 0 else t["Bounce basis"]
                if t["Bounce basis"] > 0:
                    delta = t["Bounce adj"] - t["Bounce basis"]
                    bounce_str = (
                        f"{_bounce_kleur(bp)} {bp:.0f}%"
                        + (f" *({delta:+.0f}% dag)*" if delta != 0 else "")
                    )
                else:
                    bounce_str = "—"

                for rc, rv in zip(st.columns(_COL_W), [
                    f"**{t['Tranche']}**",
                    str(t["Grootte"]),
                    f"€ {t['ASML doel']:.2f}",
                    t["Niveau type"],
                    bounce_str,
                    f"{t['Afstand %']:.2f}%",
                    f"€ {t['Turboprijs']:.2f}",
                    f"€ {t['Winst/turbo']:.2f}",
                    f"**€ {t['Totale winst']:.2f}**",
                ]):
                    rc.markdown(rv)

            # T4 — trailing stop (resterend)
            resterend = n_turbos - sum(t["Grootte"] for t in tranches)
            if resterend > 0:
                for tc, tv in zip(st.columns(_COL_W), [
                    "**T4**", str(resterend), "Trailing",
                    "Trailing stop", "—", "—",
                    f"€ {turbo_ep:.2f}", "—", "—",
                ]):
                    tc.markdown(tv)

        # CSV export
        if tranches:
            _lines = [
                "Tranche,Grootte,ASML doel,Niveau type,"
                "Bounce kans %,Afstand %,Turboprijs,Winst/turbo,Totale winst"
            ]
            for t in tranches:
                bp = t["Bounce adj"] if t["Bounce adj"] > 0 else t["Bounce basis"]
                _lines.append(
                    f"{t['Tranche']},{t['Grootte']},{t['ASML doel']:.2f},"
                    f"{t['Niveau type']},{bp:.0f},{t['Afstand %']:.2f},"
                    f"{t['Turboprijs']:.2f},{t['Winst/turbo']:.2f},{t['Totale winst']:.2f}"
                )
            st.download_button(
                "📥 Exporteer als CSV",
                data="\n".join(_lines),
                file_name="tranche_ladder.csv",
                mime="text/csv",
                key="hl_export_csv",
            )

    st.divider()

    # -----------------------------------------------------------------------
    # Nasdaq signaal  +  Scenario samenvatting naast elkaar
    # -----------------------------------------------------------------------
    sig_col, scen_col = st.columns([1, 1], gap="medium")
    with sig_col:
        _render_nasdaq_signaal(nas_v, pdh_v, pdl_v, pwh_v, pwl_v)
    with scen_col:
        _render_scenario(modus, asml_entry, asml_sl, n_turbos, tranches, fin, rat)

    st.divider()

    # -----------------------------------------------------------------------
    # Visuele prijsladder
    # -----------------------------------------------------------------------
    with st.container(border=True):
        st.markdown("**📈 Visuele Prijsladder**")
        if tranches:
            fig = _build_ladder_chart(
                mode=modus,
                asml_entry=asml_entry,
                asml_sl=asml_sl,
                tranches=tranches,
                pdh=pdh_v, pdl=pdl_v, pwh=pwh_v, pwl=pwl_v,
                nasdaq_open_verwacht=nasdaq_open_v,
            )
            st.plotly_chart(fig, width="stretch", config={"editable": False})
        else:
            st.info("Voer geldige H/L niveaus in om de prijsladder te tonen.")

    # -----------------------------------------------------------------------
    # Statistieken referentietabel (inklapbaar)
    # -----------------------------------------------------------------------
    with st.expander("📖 H/L Statistieken referentie (6 mnd Amsterdam)"):
        st.table([
            {
                "Niveau":        lbl,
                "Touch rate":    f"{HL_STATS[k]['touch'] * 100:.0f}%",
                "Bounce kans":   f"{HL_STATS[k]['bounce'] * 100:.0f}%",
                "Gem. move EUR": f"€ {HL_STATS[k]['avg_move']:.2f}",
            }
            for k, lbl in [
                ("prev_day_high",  "Prev Day High"),
                ("prev_day_low",   "Prev Day Low"),
                ("prev_week_high", "Prev Week High"),
                ("prev_week_low",  "Prev Week Low"),
            ]
        ])

        c_long, c_short = st.columns(2)
        with c_long:
            st.markdown("**Dag-modifiers LONG** *(Prev Day High)*")
            st.table([{"Dag": d, "Modifier": f"{m:+d}%"} for d, m in DOW_MOD_LONG.items()])
        with c_short:
            st.markdown("**Dag-modifiers SHORT** *(Prev Day Low)*")
            st.table([{"Dag": d, "Modifier": f"{m:+d}%"} for d, m in DOW_MOD_SHORT.items()])
