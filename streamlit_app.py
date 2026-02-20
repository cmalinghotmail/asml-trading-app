"""ASML Trading Monitor — Streamlit web UI.

Run locally:
    streamlit run streamlit_app.py

Access from any device on the same network (or server):
    http://<server-ip>:8501
"""

import time
import sys
import os
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
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="ASML Trading Monitor",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Engine singleton — lives in session_state so it survives Streamlit reruns
# ---------------------------------------------------------------------------

def _get_engine() -> TradingEngine:
    if "engine" not in st.session_state:
        st.session_state["engine"] = TradingEngine()
    return st.session_state["engine"]


engine = _get_engine()

# ---------------------------------------------------------------------------
# Sidebar — configuration & controls
# ---------------------------------------------------------------------------

def _sync_turbo_to_calc():
    """Copy sidebar turbo entry price to calculator key."""
    st.session_state["chart_turbo_price"] = st.session_state["sidebar_turbo_entry"]


with st.sidebar:
    st.title("Instellingen")

    SETUP_OPTIONS = {
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

    prev_close = st.number_input(
        "Vorige slotkoers ASML (EUR)",
        min_value=100.0,
        max_value=9000.0,
        value=float(engine.prev_close),
        step=0.5,
        format="%.2f",
    )

    leverage = st.number_input(
        "Leverage",
        min_value=1.0,
        max_value=20.0,
        value=float(engine.leverage),
        step=0.05,
        format="%.2f",
    )

    ratio = st.selectbox(
        "Ratio",
        options=[1, 10, 100],
        index=[1, 10, 100].index(int(engine.ratio)) if int(engine.ratio) in [1, 10, 100] else 1,
        help="Turbo product ratio (1, 10 of 100)",
    )

    st.divider()
    st.markdown("**Turbo product**")
    st.text_input(
        "Naam Turbo",
        key="turbo_name",
        placeholder="bijv. TURBO LONG ASML",
    )
    st.text_input(
        "ISIN",
        key="turbo_isin",
        placeholder="bijv. NL0000000000",
    )
    st.number_input(
        "Turbo entry prijs (EUR)",
        min_value=0.01,
        max_value=999.0,
        value=5.00,
        step=0.01,
        format="%.2f",
        key="sidebar_turbo_entry",
        on_change=_sync_turbo_to_calc,
        help="Wordt direct overgenomen in de Turbo Calculator",
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
        for _k in ("chart_sl", "chart_tp"):
            st.session_state.pop(_k, None)
        engine.start(
            setup_name=setup_choice,
            prev_close=float(prev_close),
            leverage=float(leverage),
            ratio=float(ratio),
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
hdr_title, hdr_price = st.columns([3, 1], gap="large")

with hdr_title:
    st.title("ASML Trading Monitor")
    status_icons = {"running": "🟢", "stopped": "⚫", "starting": "🟡", "error": "🔴"}
    icon = status_icons.get(state["status"], "⚫")
    st.markdown(
        f"**Status:** {icon} `{state['status'].upper()}`  &nbsp;|&nbsp;  "
        f"**Candles:** {state['candle_count']}  &nbsp;|&nbsp;  "
        f"**Setup:** `{state['setup_name']}`"
    )

with hdr_price:
    if state["current_price"] is not None:
        price = state["current_price"]
        pc    = state["prev_close"]
        diff  = price - pc
        diff_pct = (diff / pc) * 100 if pc else 0.0
        sign = "+" if diff >= 0 else ""
        st.metric(
            label="ASML Live Koers",
            value=f"€ {price:,.2f}",
            delta=f"{sign}{diff:.2f} ({sign}{diff_pct:.2f}%)",
        )
        if state["current_candle"]:
            c = state["current_candle"]
            st.caption(
                f"O: {c['open']:.2f}  H: {c['high']:.2f}  "
                f"L: {c['low']:.2f}  Vol: {c['volume']}"
            )
    else:
        st.info("Wachten op data…  \nDruk **Start** in de zijbalk.")

if state["error_msg"]:
    st.error(f"Fout in trading engine: {state['error_msg']}")

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
        _sl_dist = default_entry - chart_sl
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
        _tp_dist = chart_tp - default_entry
        st.caption(f"Afstand entry: {_tp_dist:+.2f} EUR")

# --- Right: Turbo Calculator — all values from sidebar settings (display-only) ---
# Lees waarden rechtstreeks uit instellingen (sidebar)
_calc_side        = default_side
_calc_turbo_price = st.session_state.get("sidebar_turbo_entry", 5.00)
_calc_ratio       = float(ratio)

with turbo_col:
    with st.container(border=True):
        _tname = st.session_state.get("turbo_name", "")
        _tisin = st.session_state.get("turbo_isin", "")
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

        # Display-only input rows (values from sidebar)
        _drow("Side",         _calc_side)
        _drow("Turbo entry",  f"€ {_calc_turbo_price:.2f}")
        _drow("Ratio",        f"{_calc_ratio:.0f}")

        # Compute turbo translation
        _dummy = {
            "side":  _calc_side,
            "entry": default_entry,
            "sl":    chart_sl,
            "tp":    chart_tp,
        }
        result = TurboTranslator({"leverage": state["leverage"]}).translate(
            _dummy,
            asml_price=default_entry,
            turbo_price=_calc_turbo_price,
            ratio=_calc_ratio,
        )
        turbo_sl_price = result.get("turbo_sl_price")
        turbo_tp_price = result.get("turbo_tp_price")

        st.divider()

        # Result rows — styled like SL/TP table (🔴/🟢)
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
                ("Financiering", f"€ {result.get('financing', 0):.2f}"),
            ]:
                lc, rc = st.columns([1, 2])
                lc.markdown(f"**{_lbl}**")
                rc.markdown(_val)
        else:
            st.info("Vul een turbo entry prijs in via de instellingen.")

# ---------------------------------------------------------------------------
# Candlestick chart — full width, uses session_state turbo price for annotations
# ---------------------------------------------------------------------------
_prev_turbo_price = _calc_turbo_price
_prev_ratio       = _calc_ratio
_prev_side        = _calc_side

_dummy_chart = {"side": _prev_side, "entry": default_entry, "sl": chart_sl, "tp": chart_tp}
_result_chart = TurboTranslator({"leverage": state["leverage"]}).translate(
    _dummy_chart,
    asml_price=default_entry,
    turbo_price=_prev_turbo_price,
    ratio=_prev_ratio,
)

fig = _build_chart(
    candles=candles,
    entry_val=default_entry,
    sl_val=chart_sl,
    tp_val=chart_tp,
    signals=state["signals"],
    turbo_sl=_result_chart.get("turbo_sl_price"),
    turbo_tp=_result_chart.get("turbo_tp_price"),
    turbo_entry=_prev_turbo_price,
)
if fig:
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Nog geen candle data. Druk **Start** in de zijbalk.")

st.divider()

# ---------------------------------------------------------------------------
# Signals — prominent bordered table
# ---------------------------------------------------------------------------
n_sig = len(state["signals"])

with st.container(border=True):
    st.subheader(f"Signalen  ({n_sig})")

    if state["signals"]:
        rows = []
        for s in reversed(state["signals"][-20:]):
            turbo_data = s.get("turbo", {})
            rows.append({
                "Tijd":      str(s.get("time", ""))[:19].replace("T", " "),
                "Setup":     s.get("meta", {}).get("setup_name", ""),
                "Side":      s.get("side", ""),
                "Entry":     round(float(s["entry"]), 2),
                "SL":        round(float(s["sl"]), 2),
                "TP":        round(float(s["tp"]), 2),
                "Turbo SL":  round(float(turbo_data["turbo_sl_price"]), 2)
                             if "turbo_sl_price" in turbo_data else None,
                "Turbo TP":  round(float(turbo_data["turbo_tp_price"]), 2)
                             if "turbo_tp_price" in turbo_data else None,
            })

        df_signals = pd.DataFrame(rows)
        st.dataframe(
            df_signals,
            use_container_width=True,
            hide_index=True,
            height=min(38 + len(rows) * 35, 420),
            column_config={
                "Tijd":      st.column_config.TextColumn("Tijd",     width="medium"),
                "Setup":     st.column_config.TextColumn("Setup",    width="medium"),
                "Side":      st.column_config.TextColumn("Side",     width="small"),
                "Entry":     st.column_config.NumberColumn("Entry",    format="€ %.2f"),
                "SL":        st.column_config.NumberColumn("SL",       format="€ %.2f"),
                "TP":        st.column_config.NumberColumn("TP",       format="€ %.2f"),
                "Turbo SL":  st.column_config.NumberColumn("Turbo SL", format="€ %.2f"),
                "Turbo TP":  st.column_config.NumberColumn("Turbo TP", format="€ %.2f"),
            },
        )
    else:
        st.info("Nog geen signalen gedetecteerd. Start de engine om signalen te ontvangen.")

# ---------------------------------------------------------------------------
# Auto-refresh when engine is running
# ---------------------------------------------------------------------------
if engine.is_running():
    time.sleep(3)
    st.rerun()
