"""ASML Trading Monitor — Streamlit web UI.

Run locally:
    streamlit run streamlit_app.py

Access from any device on the same network (or server):
    http://<server-ip>:8501
"""

import time
import sys
import os
import datetime
import pandas as pd
import plotly.graph_objects as go

import streamlit as st

# Ensure the app root is on sys.path so relative imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.engine import TradingEngine
from turbo.translate import TurboTranslator


# ---------------------------------------------------------------------------
# Chart builder
# ---------------------------------------------------------------------------

def _build_chart(candles, entry_val, sl_val, tp_val, signals,
                 turbo_sl=None, turbo_tp=None, turbo_entry=None):
    """Plotly candlestick chart with SL/TP lines, turbo annotations, zoom buttons."""
    if not candles:
        return None

    times  = [c["time"] for c in candles]
    opens  = [float(c["open"])  for c in candles]
    highs  = [float(c["high"])  for c in candles]
    lows   = [float(c["low"])   for c in candles]
    closes = [float(c["close"]) for c in candles]

    fig = go.Figure()

    # --- Candlesticks ---
    fig.add_trace(go.Candlestick(
        x=times, open=opens, high=highs, low=lows, close=closes,
        name="ASML",
        increasing_line_color="#26a69a",
        decreasing_line_color="#ef5350",
        showlegend=False,
    ))

    # --- Signal markers (yellow triangle) ---
    times_set = set(times)
    for sig in signals[-10:]:
        sig_time = sig.get("time", "")
        if sig_time in times_set:
            fig.add_trace(go.Scatter(
                x=[sig_time],
                y=[float(sig["entry"])],
                mode="markers",
                marker=dict(
                    symbol="triangle-up" if sig.get("side") == "LONG" else "triangle-down",
                    size=14, color="#ffd700",
                    line=dict(color="#000000", width=1),
                ),
                showlegend=False,
                hovertemplate=f"{sig.get('meta', {}).get('setup_name', '')} "
                              f"{sig.get('side', '')} @ {sig['entry']:.2f}<extra></extra>",
            ))

    # --- Horizontal lines ---
    def _hline(y, color, dash, label, turbo_txt=""):
        fig.add_shape(
            type="line", xref="paper", yref="y",
            x0=0, x1=1, y0=y, y1=y,
            line=dict(color=color, width=1.5, dash=dash),
        )
        fig.add_annotation(
            x=1.01, xref="paper", y=y, yref="y",
            text=f"{label}<br>€ {y:.2f}{turbo_txt}",
            showarrow=False,
            font=dict(color=color, size=10),
            xanchor="left", align="left",
            bgcolor="#0e1117", borderpad=2,
        )

    if entry_val is not None:
        _hline(entry_val, "#4fa3e0", "solid", "Entry")

    turbo_sl_txt = f"<br><b>Turbo SL € {turbo_sl:.2f}</b>" if turbo_sl is not None else ""
    _hline(sl_val, "#ef5350", "dash", "SL", turbo_sl_txt)

    turbo_tp_txt = f"<br><b>Turbo TP € {turbo_tp:.2f}</b>" if turbo_tp is not None else ""
    _hline(tp_val, "#26a69a", "dash", "TP", turbo_tp_txt)

    # --- Layout ---
    fig.update_layout(
        plot_bgcolor="#1a1f2e",
        paper_bgcolor="#0e1117",
        font=dict(color="#fafafa", size=11),
        xaxis_rangeslider_visible=False,
        height=430,
        margin=dict(l=10, r=190, t=40, b=10),
        xaxis=dict(
            gridcolor="#2a2f3e",
            showgrid=True,
            rangeselector=dict(
                buttons=[
                    dict(count=15, label="15m", step="minute", stepmode="backward"),
                    dict(count=30, label="30m", step="minute", stepmode="backward"),
                    dict(count=1,  label="1u",  step="hour",   stepmode="backward"),
                    dict(step="all", label="Alles"),
                ],
                bgcolor="#1a2035",
                activecolor="#00a6ed",
                bordercolor="#2a2f3e",
                font=dict(color="#fafafa", size=10),
                x=0, y=1.04,
            ),
        ),
        yaxis=dict(gridcolor="#2a2f3e", showgrid=True, tickformat="€.2f"),
        hovermode="x unified",
    )

    return fig


# ---------------------------------------------------------------------------
# Box strategie helpers
# ---------------------------------------------------------------------------

def _fetch_box_levels(ticker: str) -> dict | None:
    """Haal vorige volledige handelsdag High/Low/Mid op via yfinance.

    Weekend-afhandeling is automatisch: yfinance retourneert vrijdag als
    de meest recente completed trading day wanneer het weekend is.
    """
    import yfinance as yf
    today = datetime.date.today()
    try:
        df = yf.download(ticker, period="5d", interval="1d",
                         auto_adjust=True, progress=False)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        # Verwijder vandaag als die al in de data zit (partial trading day)
        if df.index[-1].date() >= today:
            df = df.iloc[:-1]
        if df.empty:
            return None
        row  = df.iloc[-1]
        high = round(float(row["High"]), 2)
        low  = round(float(row["Low"]),  2)
        return {
            "date": df.index[-1].date().isoformat(),
            "high": high,
            "low":  low,
            "mid":  round((high + low) / 2, 2),
        }
    except Exception:
        return None


def _render_box_zone(col, side, key_pfx, def_entry, def_sl, def_tp, lev, rat,
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

            # Turbo berekening — zelfde logica als bestaande calculator
            turbo_entry = round(entry / (lev * rat), 2) if lev > 0 and rat > 0 else 0.0
            sig = {"side": side, "entry": entry, "sl": sl, "tp": tp}
            res = TurboTranslator({"leverage": lev}).translate(
                sig, asml_price=entry, turbo_price=turbo_entry, ratio=rat,
            )
            t_sl        = res.get("turbo_sl_price")
            t_tp        = res.get("turbo_tp_price")
            financing   = res.get("financing")

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
                    ("🔴 Turbo SL",   f"**€ {t_sl:.2f}**  *({_sl_pct:+.1f}% / −{_tsl_d:.2f})*"),
                    ("🟢 Turbo TP",   f"**€ {t_tp:.2f}**  *({_tp_pct:+.1f}% / +{_ttp_d:.2f})*"),
                    ("R/R",           f"**{_rr:.2f}**"),
                    ("Financiering",  f"€ {financing:.2f}" if financing is not None else "—"),
                ]:
                    lc, rc = st.columns([1, 2])
                    lc.markdown(f"**{_lbl}**")
                    rc.markdown(_val)
            else:
                st.info("Controleer leverage en ratio.")


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="ASML Trading Monitor",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Compactere layout — verwijder Streamlit's standaard witruimte
st.markdown("""
<style>
.block-container { padding-top: 0.5rem !important; padding-bottom: 0.25rem !important; }
[data-testid="stVerticalBlock"] { gap: 0.3rem; }
hr { margin: 0.25rem 0 !important; }
[data-testid="stVerticalBlockBorderWrapper"] > div { padding: 0.5rem 0.75rem !important; }
section[data-testid="stSidebar"] > div:first-child { padding-top: 0.5rem !important; }
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0.2rem; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Engine singleton — lives in session_state so it survives Streamlit reruns
# ---------------------------------------------------------------------------

def _get_engine() -> TradingEngine:
    if "engine" not in st.session_state:
        st.session_state["engine"] = TradingEngine()
    return st.session_state["engine"]


engine = _get_engine()

# Initialiseer sidebar-defaults vanuit config (alleen als sleutel nog niet bestaat)
_cfg = engine.cfg
_tl  = _cfg.get("turbo_long",  {})
_ts  = _cfg.get("turbo_short", {})
for _k, _v in [
    ("turbo_long_name",      _tl.get("name",     "")),
    ("turbo_long_isin",      _tl.get("isin",     "")),
    ("turbo_long_leverage",  float(_tl.get("leverage", engine.leverage))),
    ("turbo_long_ratio",     int(_tl.get("ratio",    int(engine.ratio)))),
    ("turbo_short_name",     _ts.get("name",     "")),
    ("turbo_short_isin",     _ts.get("isin",     "")),
    ("turbo_short_leverage", float(_ts.get("leverage", engine.leverage))),
    ("turbo_short_ratio",    int(_ts.get("ratio",    int(engine.ratio)))),
]:
    if _k not in st.session_state:
        st.session_state[_k] = _v

# Box levels — auto-ophalen bij eerste run of bij ticker-wijziging
if ("box_levels" not in st.session_state
        or st.session_state.get("_box_ticker") != engine.ticker):
    st.session_state["box_levels"] = _fetch_box_levels(engine.ticker)
    st.session_state["_box_ticker"] = engine.ticker
    for _k in ["box_long_entry", "box_long_sl", "box_long_tp",
               "box_short_entry", "box_short_sl", "box_short_tp"]:
        st.session_state.pop(_k, None)

# ---------------------------------------------------------------------------
# Sidebar — configuration & controls
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("Instellingen")

    SETUP_OPTIONS = {
        "prev_day_box":        "Previous Day Box",
        "morning_gap":         "Morning Gap Fill       (08:05-09:00)",
        "morning_momentum":    "Morning Momentum       (09:15-10:00)",
        "opening_range_break": "Opening Range Break    (08:20-08:45)",
        "closing_reversion":   "Closing Reversion      (16:00-16:25)",
        "breakout":            "Breakout generiek",
    }
    setup_keys = list(SETUP_OPTIONS.keys())
    setup_labels = list(SETUP_OPTIONS.values())

    current_idx = setup_keys.index(engine.setup_name) if engine.setup_name in setup_keys else 0
    setup_label = st.selectbox(
        "Trading Setup",
        setup_labels,
        index=current_idx,
    )
    setup_choice = setup_keys[setup_labels.index(setup_label)]

    st.divider()
    ticker = st.text_input(
        "Ticker",
        value=engine.ticker,
        help="Euronext: ASML.AS  |  Nasdaq: ASML  |  voorbeeld: NVDA, RDSA.AS",
    )
    feed_mode = st.radio(
        "Data bron",
        options=["mock", "live"],
        index=0 if engine.feed_mode == "mock" else 1,
        format_func=lambda x: "Demo (mock data)" if x == "mock" else "Live (yfinance)",
        horizontal=True,
    )

    if st.button("🔄 Box data vernieuwen", use_container_width=True, key="box_refresh_sidebar"):
        for _k in ["box_levels", "_box_ticker", "box_long_entry", "box_long_sl", "box_long_tp",
                   "box_short_entry", "box_short_sl", "box_short_tp"]:
            st.session_state.pop(_k, None)
        st.rerun()

    st.divider()
    st.markdown("**🟢 Turbo LONG**")
    st.text_input("Naam", key="turbo_long_name", placeholder="bijv. TURBO LONG ASML")
    st.text_input("ISIN", key="turbo_long_isin", placeholder="bijv. NL0000000000")
    leverage_long = st.number_input(
        "Leverage", min_value=1.0, max_value=20.0,
        step=0.05, format="%.2f",
        key="turbo_long_leverage",
    )
    ratio_long = st.selectbox(
        "Ratio", options=[1, 10, 100],
        help="Product ratio (1, 10 of 100)", key="turbo_long_ratio",
    )
    st.markdown("**🔴 Turbo SHORT**")
    st.text_input("Naam", key="turbo_short_name", placeholder="bijv. TURBO SHORT ASML")
    st.text_input("ISIN", key="turbo_short_isin", placeholder="bijv. NL0000000001")
    leverage_short = st.number_input(
        "Leverage", min_value=1.0, max_value=20.0,
        step=0.05, format="%.2f",
        key="turbo_short_leverage",
    )
    ratio_short = st.selectbox(
        "Ratio", options=[1, 10, 100],
        help="Product ratio (1, 10 of 100)", key="turbo_short_ratio",
    )

    st.divider()

    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        start_clicked = st.button(
            "▶ Start",
            type="primary",
            use_container_width=True,
            disabled=engine.is_running(),
        )
    with btn_col2:
        stop_clicked = st.button(
            "■ Stop",
            use_container_width=True,
            disabled=not engine.is_running(),
        )

    if start_clicked:
        for _k in ("chart_sl", "chart_tp", "chart_asml_entry"):
            st.session_state.pop(_k, None)
        engine.start(
            setup_name=setup_choice,
            prev_close=float(engine.prev_close),
            leverage=float(leverage_long),
            ratio=float(ratio_long),
            ticker=ticker.strip(),
            feed_mode=feed_mode,
        )
        st.rerun()

    if stop_clicked:
        engine.stop()
        st.rerun()

    st.divider()
    st.caption("ASML Trading Monitor v1.0  \nFase 1 — Mock data")

# ---------------------------------------------------------------------------
# Read current state
# ---------------------------------------------------------------------------
state = engine.get_state()

# ---------------------------------------------------------------------------
# Header — title + live price inline
# ---------------------------------------------------------------------------
status_icons = {"running": "🟢", "stopped": "⚫", "starting": "🟡", "error": "🔴"}
icon = status_icons.get(state["status"], "⚫")

col_hdr = st.columns([3, 2])
with col_hdr[0]:
    st.markdown("#### ASML Trading Monitor")
    _feed_label = "live" if state.get("feed_mode") == "live" else "demo"
    st.caption(
        f"Status: {icon} {state['status'].upper()} &nbsp;|&nbsp; "
        f"{state.get('ticker', 'ASML.AS')} [{_feed_label}] &nbsp;|&nbsp; "
        f"Candles: {state['candle_count']} &nbsp;|&nbsp; "
        f"Setup: {state['setup_name']}"
    )
with col_hdr[1]:
    if state["current_price"] is not None:
        price = state["current_price"]
        pc    = state["prev_close"]
        diff  = price - pc
        diff_pct = (diff / pc) * 100 if pc else 0.0
        sign = "+" if diff >= 0 else ""
        color = "#26a69a" if diff >= 0 else "#ef5350"
        st.markdown(
            f"<span style='font-size:1.3rem; font-weight:700'>€ {price:,.2f}</span>"
            f"&nbsp; <span style='color:{color}; font-size:0.85rem'>{sign}{diff:.2f} ({sign}{diff_pct:.2f}%)</span>",
            unsafe_allow_html=True,
        )
        if state["current_candle"]:
            c = state["current_candle"]
            st.caption(f"O:{c['open']:.2f} H:{c['high']:.2f} L:{c['low']:.2f} Vol:{c['volume']}")
    else:
        st.caption("Wachten op data… Druk **Start** in de zijbalk.")

if state["error_msg"]:
    st.error(f"Fout in trading engine: {state['error_msg']}")

st.divider()

# ---------------------------------------------------------------------------
# Box Strategie sectie
# ---------------------------------------------------------------------------
_box       = st.session_state.get("box_levels")
_lev_long  = float(leverage_long)
_rat_long  = float(ratio_long)
_lev_short = float(leverage_short)
_rat_short = float(ratio_short)

if _box:
    _bd, _bh, _bl, _bm = _box["date"], _box["high"], _box["low"], _box["mid"]
else:
    _ref = state["current_price"] or float(state["prev_close"])
    _bh  = round(_ref * 1.005, 2)
    _bl  = round(_ref * 0.995, 2)
    _bm  = round(_ref, 2)
    _bd  = "—"

with st.container(border=True):
    # Titel + refresh
    _btitle_col, _brefresh_col = st.columns([6, 1])
    with _btitle_col:
        st.markdown(f"**📦 Box strategie** &nbsp;&nbsp; Vorige dag: **{_bd}**")
        if not _box:
            st.caption("⚠️ Geen box data — druk op **🔄 Box data vernieuwen** in de zijbalk.")
    with _brefresh_col:
        if st.button("🔄 Vernieuwen", key="box_refresh_main"):
            for _k in ["box_levels", "_box_ticker", "box_long_entry", "box_long_sl", "box_long_tp",
                       "box_short_entry", "box_short_sl", "box_short_tp"]:
                st.session_state.pop(_k, None)
            st.rerun()

    # Low | Mid | High in drie kolommen — turbo-waarden conditioneel eronder
    _t_long_name  = st.session_state.get("turbo_long_name",  "")
    _t_long_isin  = st.session_state.get("turbo_long_isin",  "")
    _t_short_name = st.session_state.get("turbo_short_name", "")
    _t_short_isin = st.session_state.get("turbo_short_isin", "")
    _has_long_t   = bool(_t_long_name or _t_long_isin)
    _has_short_t  = bool(_t_short_name or _t_short_isin)

    # Vaste dagkoers per turbo — berekend met de eigen leverage × ratio
    _turbo_at_low  = round(_bl / (_lev_long  * _rat_long),  2) if _lev_long  > 0 and _rat_long  > 0 else None
    _turbo_at_high = round(_bh / (_lev_short * _rat_short), 2) if _lev_short > 0 and _rat_short > 0 else None

    _col_l, _col_m, _col_h = st.columns(3)
    with _col_l:
        st.markdown(f"🟢 Low: **€ {_bl:,.2f}**")
        if _turbo_at_low is not None:
            st.markdown(f"Turbo Long: **€ {_turbo_at_low:.2f}**")
            _l_label = "  |  ".join(filter(None, [_t_long_name, _t_long_isin]))
            if _l_label:
                st.caption(_l_label)
    with _col_m:
        st.markdown(f"⚫ Mid: **€ {_bm:,.2f}**")
        _turbo_mid_long  = round(_bm / (_lev_long  * _rat_long),  2) if _lev_long  > 0 and _rat_long  > 0 else None
        _turbo_mid_short = round(_bm / (_lev_short * _rat_short), 2) if _lev_short > 0 and _rat_short > 0 else None
        if _turbo_mid_long is not None:
            st.markdown(f"🟢 Long: **€ {_turbo_mid_long:.2f}**")
        if _turbo_mid_short is not None:
            st.markdown(f"🔴 Short: **€ {_turbo_mid_short:.2f}**")
    with _col_h:
        st.markdown(f"🔴 High: **€ {_bh:,.2f}**")
        if _turbo_at_high is not None:
            st.markdown(f"Turbo Short: **€ {_turbo_at_high:.2f}**")
            _s_label = "  |  ".join(filter(None, [_t_short_name, _t_short_isin]))
            if _s_label:
                st.caption(_s_label)

    st.divider()

    _rng       = max(_bh - _bl, 1.0)
    _long_col, _short_col = st.columns(2, gap="small")

    _render_box_zone(
        _long_col, "LONG", "box_long",
        def_entry=_bl,
        def_sl=round(_bl - _rng * 0.15, 2),
        def_tp=_bm,
        lev=_lev_long, rat=_rat_long,
        turbo_naam=st.session_state.get("turbo_long_name", ""),
        turbo_isin=st.session_state.get("turbo_long_isin", ""),
    )
    _render_box_zone(
        _short_col, "SHORT", "box_short",
        def_entry=_bh,
        def_sl=round(_bh + _rng * 0.15, 2),
        def_tp=_bm,
        lev=_lev_short, rat=_rat_short,
        turbo_naam=st.session_state.get("turbo_short_name", ""),
        turbo_isin=st.session_state.get("turbo_short_isin", ""),
    )

st.divider()

# ---------------------------------------------------------------------------
# Chart prep — compute defaults and bounds
# ---------------------------------------------------------------------------
candles     = state["candle_history"]
last_signal = state["signals"][-1] if state["signals"] else None
cur_price   = state["current_price"] or float(state["prev_close"])

default_entry = round(float(last_signal["entry"]), 2) if last_signal else round(cur_price, 2)
default_sl    = round(float(last_signal["sl"]), 2)    if last_signal else round(cur_price * 0.994, 2)
default_tp    = round(float(last_signal["tp"]), 2)    if last_signal else round(cur_price * 1.008, 2)
default_side  = last_signal.get("side", "LONG")       if last_signal else "LONG"

# Wide fixed bounds — user can freely enter any ASML price level
ni_min = 100.0
ni_max = 9000.0

# ---------------------------------------------------------------------------
# SL/TP table (left) + Turbo Calculator table (right) — side by side
# ---------------------------------------------------------------------------
sltp_col, turbo_col = st.columns([1, 1], gap="small")

# --- Left: compact SL/TP table ---
with sltp_col:
    with st.container(border=True):
        # Header row
        h_lbl, h_val = st.columns([1, 2])
        h_lbl.markdown("**Niveau**")
        h_val.markdown("**Prijs (EUR)**")
        st.divider()

        # ASML Entry row — primaire input; turbo entry wordt hieruit berekend
        ae_lbl, ae_val = st.columns([1, 2])
        ae_lbl.markdown("📍 **ASML Entry**")
        with ae_val:
            chart_asml_entry = st.number_input(
                "ASML Entry",
                min_value=ni_min,
                max_value=ni_max,
                value=default_entry,
                step=0.5,
                format="%.2f",
                key="chart_asml_entry",
                label_visibility="collapsed",
            )

        # Turbo entry row — berekend uit ASML entry + leverage + ratio
        te_lbl, te_val = st.columns([1, 2])
        te_lbl.markdown("🔵 **Turbo entry**")
        _lev = float(leverage_long) if default_side == "LONG" else float(leverage_short)
        _rat = float(ratio_long)    if default_side == "LONG" else float(ratio_short)
        chart_turbo_entry = round(chart_asml_entry / (_lev * _rat), 2) if _lev > 0 and _rat > 0 else 0.0
        te_val.markdown(f"**€ {chart_turbo_entry:.2f}**")

        st.divider()

        # SL row
        sl_lbl, sl_val = st.columns([1, 2])
        sl_lbl.markdown("🔴 **Stop Loss**")
        with sl_val:
            chart_sl = st.number_input(
                "SL",
                min_value=ni_min,
                max_value=ni_max,
                value=default_sl,
                step=0.5,
                format="%.2f",
                key="chart_sl",
                label_visibility="collapsed",
            )
        _sl_dist = chart_asml_entry - chart_sl
        st.caption(f"Afstand entry: {_sl_dist:+.2f} EUR")

        st.divider()

        # TP row
        tp_lbl, tp_val = st.columns([1, 2])
        tp_lbl.markdown("🟢 **Take Profit**")
        with tp_val:
            chart_tp = st.number_input(
                "TP",
                min_value=ni_min,
                max_value=ni_max,
                value=default_tp,
                step=0.5,
                format="%.2f",
                key="chart_tp",
                label_visibility="collapsed",
            )
        _tp_dist = chart_tp - chart_asml_entry
        st.caption(f"Afstand entry: {_tp_dist:+.2f} EUR")

        # Signalen compact onder TP
        if state["signals"]:
            st.divider()
            st.markdown("**Signalen**")
            for s in reversed(state["signals"][-5:]):
                _s_icon = "🟢" if s.get("side") == "LONG" else "🔴"
                _s_t = str(s.get("time", ""))[:16].replace("T", " ")
                st.caption(
                    f"{_s_icon} {_s_t} &nbsp; "
                    f"E:{float(s['entry']):.0f} &nbsp;"
                    f"SL:{float(s['sl']):.0f} &nbsp;"
                    f"TP:{float(s['tp']):.0f}"
                )

# --- Right: Turbo Calculator — all values from main block + sidebar settings ---
_calc_side        = default_side
_calc_turbo_price = chart_turbo_entry
_calc_ratio       = float(ratio_long) if _calc_side == "LONG" else float(ratio_short)

with turbo_col:
    with st.container(border=True):
        if _calc_side == "LONG":
            _tname = st.session_state.get("turbo_long_name", "")
            _tisin = st.session_state.get("turbo_long_isin", "")
        else:
            _tname = st.session_state.get("turbo_short_name", "")
            _tisin = st.session_state.get("turbo_short_isin", "")
        _product_label = "  |  ".join(filter(None, [_tname, _tisin]))
        st.markdown(
            f"**Turbo Calculator**"
            f"{f'  —  {_product_label}' if _product_label else ''}"
        )

        def _drow(label, value):
            """Render one display row: bold label | value."""
            lc, rc = st.columns([1, 2])
            lc.markdown(f"**{label}**")
            rc.markdown(str(value))

        # Compute turbo translation — alles gebaseerd op chart_asml_entry + leverage-afgeleide turbo
        _dummy = {
            "side":  _calc_side,
            "entry": chart_asml_entry,
            "sl":    chart_sl,
            "tp":    chart_tp,
        }
        result = TurboTranslator({"leverage": state["leverage"]}).translate(
            _dummy,
            asml_price=chart_asml_entry,
            turbo_price=_calc_turbo_price,   # = chart_asml_entry / (leverage * ratio)
            ratio=_calc_ratio,
        )
        turbo_sl_price = result.get("turbo_sl_price")
        turbo_tp_price = result.get("turbo_tp_price")
        _financing     = result.get("financing")

        st.divider()

        # Result rows
        if turbo_sl_price is not None:
            _sl_d   = abs(_calc_turbo_price - turbo_sl_price)
            _tp_d   = abs(turbo_tp_price - _calc_turbo_price)
            _rr     = round(_tp_d / _sl_d, 2) if _sl_d > 0 else 0.0
            _sl_pct = (turbo_sl_price / _calc_turbo_price - 1) * 100 if _calc_turbo_price else 0.0
            _tp_pct = (turbo_tp_price / _calc_turbo_price - 1) * 100 if _calc_turbo_price else 0.0

            for _lbl, _val in [
                ("🔴 Turbo SL",  f"**€ {turbo_sl_price:.2f}**  *({_sl_pct:+.1f}% / −{_sl_d:.2f})*"),
                ("🟢 Turbo TP",  f"**€ {turbo_tp_price:.2f}**  *({_tp_pct:+.1f}% / +{_tp_d:.2f})*"),
                ("R/R",          f"**{_rr:.2f}**"),
                ("Financiering", f"€ {_financing:.2f}"),
            ]:
                lc, rc = st.columns([1, 2])
                lc.markdown(f"**{_lbl}**")
                rc.markdown(_val)
        else:
            st.info("Geen berekening mogelijk — controleer leverage en ratio.")

# ---------------------------------------------------------------------------
# Candlestick chart — full width, uses session_state turbo price for annotations
# ---------------------------------------------------------------------------
_prev_turbo_price = _calc_turbo_price
_prev_ratio       = _calc_ratio
_prev_side        = _calc_side

_dummy_chart = {"side": _prev_side, "entry": chart_asml_entry, "sl": chart_sl, "tp": chart_tp}
_result_chart = TurboTranslator({"leverage": state["leverage"]}).translate(
    _dummy_chart,
    asml_price=chart_asml_entry,
    turbo_price=_prev_turbo_price,
    ratio=_prev_ratio,
)

fig = _build_chart(
    candles=candles,
    entry_val=chart_asml_entry,
    sl_val=chart_sl,
    tp_val=chart_tp,
    signals=state["signals"],
    turbo_sl=_result_chart.get("turbo_sl_price"),
    turbo_tp=_result_chart.get("turbo_tp_price"),
    turbo_entry=_prev_turbo_price,
)
if fig:
    st.plotly_chart(
        fig,
        use_container_width=True,
        config={
            "editable": False,
            "edits": {"shapePosition": True},
        },
    )
else:
    st.info("Nog geen candle data. Druk **Start** in de zijbalk.")

# ---------------------------------------------------------------------------
# Auto-refresh when engine is running
# ---------------------------------------------------------------------------
if engine.is_running():
    time.sleep(3)
    st.rerun()
