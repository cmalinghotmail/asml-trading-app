"""ASML Evaluatie Tool — historisch dagrapport met instelbare entry/TP drempels.

Standalone Streamlit app, alleen voor localhost gebruik:
    backend\\venv\\Scripts\\streamlit run tools\\evaluatie.py --server.port 8502

Raakt de hoofdapp (streamlit_app.py) niet aan.
"""

import datetime
import os
import sys

import pandas as pd
import streamlit as st

# Zorg dat de app-root op sys.path staat zodat imports werken
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.fetcher import fetch_daily, extract_prev_week_hl
from rapport.dagrapport import _analyseer, _niveautabel, _prijsladder_tekst

# ---------------------------------------------------------------------------
# Constanten
# ---------------------------------------------------------------------------

NASDAQ_PREMIUM = 0.93
_DAG_NAMEN = ["Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag", "Zondag"]
PCT_OPTIES  = [0, 5, 10, 15, 20]

# ---------------------------------------------------------------------------
# Data laden (één keer per sessie)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Marktdata ophalen (60 dagen)...")
def _laad_alle_data():
    df_ams = fetch_daily("ASML.AS",  period="60d", exclude_today=False)
    df_nas = fetch_daily("ASML",     period="60d", exclude_today=False)
    df_fx  = fetch_daily("EURUSD=X", period="60d", exclude_today=False)
    return df_ams, df_nas, df_fx


def _handelsdagen(df_ams) -> list[datetime.date]:
    """Laatste 20 volledige handelsdagen (exclusief vandaag)."""
    today = datetime.date.today()
    dagen = sorted(
        {d for d in df_ams.index.date if d < today},
        reverse=True
    )
    return dagen[:20]


def _bouw_data(df_ams, df_nas, df_fx, T: datetime.date) -> dict | None:
    """Bouw het data-dict op zoals _fetch_data() dat zou doen, maar voor datum T."""
    slice_ams = df_ams[df_ams.index.date < T]
    slice_nas = df_nas[df_nas.index.date < T]
    slice_fx  = df_fx[df_fx.index.date <= T]

    if slice_ams.empty or slice_nas.empty or slice_fx.empty:
        return None

    row_ams = slice_ams.iloc[-1]
    row_nas = slice_nas.iloc[-1]
    usd_eur = 1.0 / float(slice_fx.iloc[-1]["Close"])

    pw = extract_prev_week_hl(slice_ams)

    nas_close_eur = round(float(row_nas["Close"]) * usd_eur, 2)

    return {
        "gegenereerd":   T.strftime("%d-%m-%Y"),
        "pd_datum":      str(slice_ams.index[-1].date()),
        "pd_high":       round(float(row_ams["High"]),  2),
        "pd_low":        round(float(row_ams["Low"]),   2),
        "pd_close":      round(float(row_ams["Close"]), 2),
        "pw_high":       pw.get("prev_week_high", round(float(slice_ams["High"].max()), 2)),
        "pw_low":        pw.get("prev_week_low",  round(float(slice_ams["Low"].min()),  2)),
        "nas_datum":     str(slice_nas.index[-1].date()),
        "nas_close_usd": round(float(row_nas["Close"]), 2),
        "nas_close_eur": nas_close_eur,
        "nas_high_eur":  round(float(row_nas["High"]) * usd_eur, 2),
        "nas_low_eur":   round(float(row_nas["Low"])  * usd_eur, 2),
        "usd_eur":       round(usd_eur, 4),
        "ams_open_exp":  round(nas_close_eur + NASDAQ_PREMIUM, 2),
        "volgende_dag":  str(T),
    }


# ---------------------------------------------------------------------------
# Setup berekening
# ---------------------------------------------------------------------------

def _bereken_setup(pdh: float, pdl: float, entry_pct: int, tp_pct: int) -> dict:
    spread = round(pdh - pdl, 2)

    entry_long  = round(pdl + (entry_pct / 100) * spread, 2)
    tp_long     = round(pdh - (tp_pct    / 100) * spread, 2)
    sl_long     = round(entry_long - 12, 2)
    rr_long     = round((tp_long - entry_long) / (entry_long - sl_long), 2) \
                  if entry_long > sl_long else 0.0

    entry_short = round(pdh - (entry_pct / 100) * spread, 2)
    tp_short    = round(pdl + (tp_pct    / 100) * spread, 2)
    sl_short    = round(entry_short + 12, 2)
    rr_short    = round((entry_short - tp_short) / (sl_short - entry_short), 2) \
                  if sl_short > entry_short else 0.0

    return {
        "spread":       spread,
        "entry_long":   entry_long,
        "tp_long":      tp_long,
        "sl_long":      sl_long,
        "rr_long":      rr_long,
        "entry_short":  entry_short,
        "tp_short":     tp_short,
        "sl_short":     sl_short,
        "rr_short":     rr_short,
    }


# ---------------------------------------------------------------------------
# Werkelijke uitkomst
# ---------------------------------------------------------------------------

def _werkelijke_uitkomst(df_ams, T: datetime.date, setup: dict) -> dict | None:
    rijen = df_ams[df_ams.index.date == T]
    if rijen.empty:
        return None
    row = rijen.iloc[0]
    act_open  = round(float(row["Open"]),  2)
    act_high  = round(float(row["High"]),  2)
    act_low   = round(float(row["Low"]),   2)
    act_close = round(float(row["Close"]), 2)
    return {
        "open":           act_open,
        "high":           act_high,
        "low":            act_low,
        "close":          act_close,
        "pdh_geraakt":    act_high  >= setup["entry_short"],
        "pdl_geraakt":    act_low   <= setup["entry_long"],
        "entry_long_ok":  act_low   <= setup["entry_long"],
        "tp_long_ok":     act_high  >= setup["tp_long"],
        "entry_short_ok": act_high  >= setup["entry_short"],
        "tp_short_ok":    act_low   <= setup["tp_short"],
    }


# ---------------------------------------------------------------------------
# Samenvatting — 20 dagen × 25 parameter-combinaties
# ---------------------------------------------------------------------------

def _bereken_samenvatting(
    handelsdagen_subset: list,
    df_ams,
    df_nas,
    df_fx,
    bounce_drempel: int,
    hefboom: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Retourneert (df_dagen, df_combo) voor de opgegeven handelsdagen."""

    dag_rijen  = []
    raw_rijen  = []  # plat: één rij per (T, entry_pct, tp_pct)

    # Setup bij 0% om PDH/PDL-aanraking te bepalen onafhankelijk van drempels
    setup_0 = {"entry_long": 0, "entry_short": float("inf"),
                "tp_long": float("inf"), "tp_short": 0}

    for T in handelsdagen_subset:
        data = _bouw_data(df_ams, df_nas, df_fx, T)
        if data is None:
            continue

        a   = _analyseer(data)
        pdh = data["pd_high"]
        pdl = data["pd_low"]
        pwh = data["pw_high"]
        pwl = data["pw_low"]

        # Werkelijke OHLC van dag T
        rijen = df_ams[df_ams.index.date == T]
        if rijen.empty:
            continue
        row       = rijen.iloc[0]
        act_high  = round(float(row["High"]),  2)
        act_low   = round(float(row["Low"]),   2)
        act_open  = round(float(row["Open"]),  2)
        act_close = round(float(row["Close"]), 2)

        sterk_long  = a["pdl_bounce"] >= bounce_drempel
        sterk_short = a["pdh_bounce"] >= bounce_drempel
        sterk       = sterk_long or sterk_short

        dag_rijen.append({
            "Datum":       T.strftime("%d %b"),
            "Dag":         a["dag_naam"][:2],
            "Spread":      round(pdh - pdl, 2),
            "PDH%":        round(a["pdh_bounce"]),
            "PDL%":        round(a["pdl_bounce"]),
            "PWH⚠":        "⚠️" if pdl < pwh < pdh else "—",
            "PWL⚠":        "⚠️" if pdl < pwl < pdh else "—",
            "Sterk":       sterk,
            "Open":        act_open,
            "High":        act_high,
            "Low":         act_low,
            "Close":       act_close,
            "PDH✓":        act_high >= pdh,
            "PDL✓":        act_low  <= pdl,
            "_T":          T,
        })

        for ep in PCT_OPTIES:
            for tp in PCT_OPTIES:
                setup = _bereken_setup(pdh, pdl, ep, tp)
                raw_rijen.append({
                    "_T":          T,
                    "_ep":         ep,
                    "_tp":         tp,
                    "_sterk":      sterk,
                    "el":          setup["entry_long"],
                    "tl":          setup["tp_long"],
                    "es":          setup["entry_short"],
                    "ts":          setup["tp_short"],
                    "el_ok":       act_low  <= setup["entry_long"],
                    "tl_ok":       act_high >= setup["tp_long"],
                    "es_ok":       act_high >= setup["entry_short"],
                    "ts_ok":       act_low  <= setup["tp_short"],
                })

    df_dagen = pd.DataFrame(dag_rijen)
    df_raw   = pd.DataFrame(raw_rijen)

    if df_raw.empty or df_dagen.empty:
        return df_dagen, pd.DataFrame()

    n_dagen = len(df_dagen)
    combo_agg = []

    for ep in PCT_OPTIES:
        for tp in PCT_OPTIES:
            sub = df_raw[(df_raw["_ep"] == ep) & (df_raw["_tp"] == tp)]
            if sub.empty:
                continue

            n_el     = int(sub["el_ok"].sum())
            n_el_win = int((sub["el_ok"] & sub["tl_ok"]).sum())
            n_es     = int(sub["es_ok"].sum())
            n_es_win = int((sub["es_ok"] & sub["ts_ok"]).sum())

            hit_l = n_el_win / n_el if n_el > 0 else 0.0
            hit_s = n_es_win / n_es if n_es > 0 else 0.0

            avg_el = sub["el"].mean()
            avg_tl = sub["tl"].mean()
            avg_es = sub["es"].mean()
            avg_ts = sub["ts"].mean()

            bereik_l  = max(avg_tl - avg_el, 0)
            bereik_s  = max(avg_es - avg_ts, 0)
            bereik    = round((bereik_l + bereik_s) / 2, 1)
            avg_entry = round((avg_el + avg_es) / 2, 1)

            turbo_pct = round(bereik    / avg_entry * hefboom * 100, 1) if avg_entry else 0.0
            sl_pct    = round(12.0      / avg_entry * hefboom * 100, 1) if avg_entry else 0.0

            ev_l = round(hit_l * turbo_pct - (1 - hit_l) * sl_pct, 1)
            ev_s = round(hit_s * turbo_pct - (1 - hit_s) * sl_pct, 1)

            n_l_dag = round(n_el / n_dagen, 1)
            n_s_dag = round(n_es / n_dagen, 1)
            ev_dag  = round(ev_l * min(n_l_dag, 2) + ev_s * min(n_s_dag, 2), 1)

            combo_agg.append({
                "entry%":    ep,
                "tp%":       tp,
                "bereik(€)": bereik,
                "turbo%":    turbo_pct,
                "SL%":       sl_pct,
                "N_L/dag":   n_l_dag,
                "hit_L%":    round(hit_l * 100),
                "N_S/dag":   n_s_dag,
                "hit_S%":    round(hit_s * 100),
                "EV_L":      ev_l,
                "EV_S":      ev_s,
                "EV/dag":    ev_dag,
            })

    return df_dagen, pd.DataFrame(combo_agg)


# ---------------------------------------------------------------------------
# Pagina-configuratie
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="ASML Evaluatie",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.block-container { padding-top: 2rem !important; }
hr { margin: 0.3rem 0 !important; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Data laden
# ---------------------------------------------------------------------------

df_ams, df_nas, df_fx = _laad_alle_data()

if df_ams is None:
    st.error("Kon ASML.AS data niet ophalen. Controleer internetverbinding.")
    st.stop()

handelsdagen = _handelsdagen(df_ams)
if not handelsdagen:
    st.error("Geen historische handelsdagen beschikbaar.")
    st.stop()

# ---------------------------------------------------------------------------
# Sidebar — navigatie + instellingen
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## 📊 ASML Evaluatie Tool")
    st.caption("Historisch dagrapport · localhost:8502")
    st.divider()

    # Dagnavigatie — index in aparte session_state, slider zonder key
    if "nav_idx" not in st.session_state:
        st.session_state["nav_idx"] = 1

    col_prev, col_next = st.columns(2)
    if col_prev.button("◄ Ouder", key="nav_prev",
                       disabled=st.session_state["nav_idx"] >= len(handelsdagen)):
        st.session_state["nav_idx"] += 1
        st.rerun()
    if col_next.button("Nieuwer ►", key="nav_next",
                       disabled=st.session_state["nav_idx"] <= 1):
        st.session_state["nav_idx"] -= 1
        st.rerun()

    dag_idx = st.slider(
        "Dag (1 = gisteren)",
        min_value=1,
        max_value=len(handelsdagen),
        value=st.session_state["nav_idx"],
    )
    st.session_state["nav_idx"] = dag_idx

    st.divider()
    st.markdown("**Entry drempel** (% van spread boven PDL / onder PDH)")
    entry_pct = st.selectbox(
        "Entry %", options=PCT_OPTIES, index=1,
        format_func=lambda x: f"{x}%",
        key="entry_pct",
    )

    st.markdown("**TP drempel** (% van spread onder PDH / boven PDL)")
    tp_pct = st.selectbox(
        "TP %", options=PCT_OPTIES, index=0,
        format_func=lambda x: f"{x}%",
        key="tp_pct",
    )

    st.divider()
    st.markdown("**Hefboom (turbo)**")
    hefboom = st.slider(
        "Hefboom", min_value=2.0, max_value=6.0, value=3.5, step=0.5,
        key="hefboom",
    )

    st.markdown("**Bounce drempel sterke dag**")
    bounce_drempel = st.slider(
        "Drempel %", min_value=50, max_value=75, value=60, step=5,
        key="bounce_drempel",
    )

    st.divider()
    if st.button("🔄 Data opnieuw laden", key="reload_btn"):
        st.cache_data.clear()
        st.rerun()

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_dag, tab_sam = st.tabs(["📅 Dag detail", "📊 Samenvatting 20 dagen"])

# ===========================================================================
# TAB 1 — Dag detail
# ===========================================================================

with tab_dag:
    T        = handelsdagen[dag_idx - 1]
    dag_naam = _DAG_NAMEN[T.weekday()]

    data = _bouw_data(df_ams, df_nas, df_fx, T)
    if data is None:
        st.error(f"Onvoldoende data beschikbaar voor {T}.")
        st.stop()

    a = _analyseer(data)

    pdh    = data["pd_high"]
    pdl    = data["pd_low"]
    spread = round(pdh - pdl, 2)

    st.markdown(f"## 📅 {dag_naam} {T.strftime('%d %B %Y')}  —  dag -{dag_idx}")
    st.caption(
        f"Prev Day: H **€ {pdh:,.2f}**  /  L **€ {pdl:,.2f}**  /  C **€ {data['pd_close']:,.2f}**"
        f"  ·  Spread: **€ {spread:,.2f}**"
    )
    st.divider()

    st.metric("Verwachte open Amsterdam", f"€ {data['ams_open_exp']:.2f}")
    st.caption(
        f"Nasdaq slot: $ {data['nas_close_usd']:.2f}  →  "
        f"€ {data['nas_close_eur']:.2f}  (USD/EUR {data['usd_eur']:.4f})"
    )

    st.divider()

    st.markdown("**Niveaus**")
    df_tabel = _niveautabel(data, a)[["Niveau", "Koers (€)", "Bounce", "Afstand"]]
    st.dataframe(
        df_tabel,
        width="stretch",
        hide_index=True,
        column_config={"Koers (€)": st.column_config.NumberColumn(format="€ %.2f")},
    )

    st.divider()

    st.markdown("**Bounce kansen**")
    dag = a["dag_naam"]
    bc1, bc2 = st.columns(2)
    bc1.metric(f"PDH ({dag[:2]})", f"{a['pdh_bounce']:.0f}%", delta=f"{a['mod_long']:+d}%")
    bc2.metric(f"PDL ({dag[:2]})", f"{a['pdl_bounce']:.0f}%", delta=f"{a['mod_short']:+d}%")
    bc3, bc4 = st.columns(2)
    bc3.metric("PWH", f"{a['pwh_bounce']:.0f}%")
    bc4.metric("PWL", f"{a['pwl_bounce']:.0f}%")

    st.divider()

    with st.container(border=True):
        st.markdown(f"**{a['primaire_setup']}**")
        st.caption(a["setup_tekst"])

    with st.expander("Prijsladder", expanded=False):
        st.code(_prijsladder_tekst(data, a), language=None)

    st.divider()
    st.markdown(f"### Setup met drempels  (entry {entry_pct}% · TP {tp_pct}%)")

    setup = _bereken_setup(pdh, pdl, entry_pct, tp_pct)

    col_long, col_short = st.columns(2)

    with col_long:
        with st.container(border=True):
            st.markdown("🟢 **LONG** — instap boven PDL")
            st.caption(
                f"Entry = PDL + {entry_pct}% × spread  =  "
                f"€ {pdl:.2f} + {entry_pct}% × € {spread:.2f}"
            )
            l1, l2 = st.columns(2)
            l1.metric("Entry",  f"€ {setup['entry_long']:.2f}")
            l2.metric("TP",     f"€ {setup['tp_long']:.2f}")
            l3, l4 = st.columns(2)
            l3.metric("SL",     f"€ {setup['sl_long']:.2f}", delta_color="inverse",
                      delta=f"{setup['sl_long'] - setup['entry_long']:+.2f}")
            l4.metric("R/R",    f"{setup['rr_long']:.2f}")

    with col_short:
        with st.container(border=True):
            st.markdown("🔴 **SHORT** — instap onder PDH")
            st.caption(
                f"Entry = PDH − {entry_pct}% × spread  =  "
                f"€ {pdh:.2f} − {entry_pct}% × € {spread:.2f}"
            )
            s1, s2 = st.columns(2)
            s1.metric("Entry",  f"€ {setup['entry_short']:.2f}")
            s2.metric("TP",     f"€ {setup['tp_short']:.2f}")
            s3, s4 = st.columns(2)
            s3.metric("SL",     f"€ {setup['sl_short']:.2f}", delta_color="inverse",
                      delta=f"{setup['sl_short'] - setup['entry_short']:+.2f}")
            s4.metric("R/R",    f"{setup['rr_short']:.2f}")

    st.divider()
    st.markdown("### Werkelijke uitkomst")

    uitkomst = _werkelijke_uitkomst(df_ams, T, setup)

    if uitkomst is None:
        st.info("Geen dagdata beschikbaar voor deze datum (mogelijk een feestdag of weekend).")
    else:
        u = uitkomst
        st.caption(
            f"Open **€ {u['open']:,.2f}**  ·  "
            f"High **€ {u['high']:,.2f}**  ·  "
            f"Low **€ {u['low']:,.2f}**  ·  "
            f"Close **€ {u['close']:,.2f}**"
        )

        def _vinkje(ok: bool, ja_tekst: str, nee_tekst: str) -> str:
            return f"✅ {ja_tekst}" if ok else f"❌ {nee_tekst}"

        col_u1, col_u2 = st.columns(2)

        with col_u1:
            with st.container(border=True):
                st.markdown("🟢 **LONG uitkomst**")
                st.markdown(_vinkje(u["entry_long_ok"],
                    f"Entry bereikt (Low ≤ € {setup['entry_long']:.2f})",
                    f"Entry niet bereikt (Low = € {u['low']:.2f})"))
                st.markdown(_vinkje(u["tp_long_ok"],
                    f"TP bereikt (High ≥ € {setup['tp_long']:.2f})",
                    f"TP niet bereikt (High = € {u['high']:.2f})"))

        with col_u2:
            with st.container(border=True):
                st.markdown("🔴 **SHORT uitkomst**")
                st.markdown(_vinkje(u["entry_short_ok"],
                    f"Entry bereikt (High ≥ € {setup['entry_short']:.2f})",
                    f"Entry niet bereikt (High = € {u['high']:.2f})"))
                st.markdown(_vinkje(u["tp_short_ok"],
                    f"TP bereikt (Low ≤ € {setup['tp_short']:.2f})",
                    f"TP niet bereikt (Low = € {u['low']:.2f})"))


# ===========================================================================
# TAB 2 — Samenvatting 20 dagen
# ===========================================================================

with tab_sam:
    st.markdown("### Samenvatting 20 handelsdagen")

    df_dagen, df_combo = _bereken_samenvatting(
        handelsdagen, df_ams, df_nas, df_fx, bounce_drempel, hefboom
    )

    # -----------------------------------------------------------------------
    # Blok A — Per-dag overzicht
    # -----------------------------------------------------------------------

    st.markdown("#### Dag overzicht")
    st.caption(
        f"Sterk = PDH-bounce ≥ {bounce_drempel}% (SHORT) of PDL-bounce ≥ {bounce_drempel}% (LONG)  ·  "
        f"⚠️ = PWH of PWL ligt binnen de spread (mogelijke obstructie)"
    )

    # Maak display-kopie met leesbare booleans
    df_display = df_dagen.drop(columns=["_T"]).copy()
    df_display["Sterk"] = df_display["Sterk"].map({True: "✅ Sterk", False: "⚪"})
    df_display["PDH✓"]  = df_display["PDH✓"].map({True: "✅", False: "❌"})
    df_display["PDL✓"]  = df_display["PDL✓"].map({True: "✅", False: "❌"})

    st.dataframe(
        df_display,
        width="stretch",
        hide_index=True,
        column_config={
            "Spread":  st.column_config.NumberColumn("Spread(€)", format="%.1f"),
            "PDH%":    st.column_config.ProgressColumn("PDH%", min_value=0, max_value=100, format="%d%%"),
            "PDL%":    st.column_config.ProgressColumn("PDL%", min_value=0, max_value=100, format="%d%%"),
            "Open":    st.column_config.NumberColumn(format="€%.0f"),
            "High":    st.column_config.NumberColumn(format="€%.0f"),
            "Low":     st.column_config.NumberColumn(format="€%.0f"),
            "Close":   st.column_config.NumberColumn(format="€%.0f"),
        },
    )

    # -----------------------------------------------------------------------
    # Blok B — Parameter-grid
    # -----------------------------------------------------------------------

    st.divider()
    st.markdown("#### Parameter-grid (entry% × TP%)")
    st.caption(
        f"Hefboom: **{hefboom}×**  ·  SL: vaste €12  ·  max 2 trades per richting per dag"
    )

    filter_sterk = st.checkbox(
        "Alleen sterke handelsdagen", value=False, key="filter_sterk"
    )

    if filter_sterk and not df_dagen.empty:
        sterke_T = set(df_dagen.loc[df_dagen["Sterk"], "_T"])
        if sterke_T:
            subset = [T for T in handelsdagen if T in sterke_T]
            _, df_combo = _bereken_samenvatting(
                subset, df_ams, df_nas, df_fx, bounce_drempel, hefboom
            )
            st.caption(f"Gefilterd op **{len(sterke_T)}** sterke dagen van de {len(handelsdagen)}.")
        else:
            st.info("Geen sterke dagen gevonden bij de huidige bounce drempel.")
            df_combo = pd.DataFrame()

    if df_combo.empty:
        st.info("Onvoldoende data voor samenvatting.")
    else:
        st.dataframe(
            df_combo,
            width="stretch",
            hide_index=True,
            column_config={
                "entry%":    st.column_config.NumberColumn("entry%",   format="%d%%"),
                "tp%":       st.column_config.NumberColumn("tp%",      format="%d%%"),
                "bereik(€)": st.column_config.NumberColumn("bereik(€)", format="%.1f"),
                "turbo%":    st.column_config.ProgressColumn(
                                 "turbo%", min_value=0, max_value=25, format="%.1f%%"),
                "SL%":       st.column_config.NumberColumn("SL%",      format="%.1f%%"),
                "N_L/dag":   st.column_config.NumberColumn("N_L/d",    format="%.1f"),
                "hit_L%":    st.column_config.ProgressColumn(
                                 "hit_L%", min_value=0, max_value=100, format="%d%%"),
                "N_S/dag":   st.column_config.NumberColumn("N_S/d",    format="%.1f"),
                "hit_S%":    st.column_config.ProgressColumn(
                                 "hit_S%", min_value=0, max_value=100, format="%d%%"),
                "EV_L":      st.column_config.NumberColumn("EV_L%",    format="%+.1f%%"),
                "EV_S":      st.column_config.NumberColumn("EV_S%",    format="%+.1f%%"),
                "EV/dag":    st.column_config.NumberColumn("EV/dag%",  format="%+.1f%%"),
            },
        )

        best = df_combo.loc[df_combo["EV/dag"].idxmax()]
        st.success(
            f"Beste combinatie: **entry {int(best['entry%'])}% · TP {int(best['tp%'])}%**"
            f"  →  EV/dag **{best['EV/dag']:+.1f}%**"
            f"  ·  turbo {best['turbo%']:.1f}%"
            f"  ·  hit L {int(best['hit_L%'])}% / S {int(best['hit_S%'])}%"
        )
