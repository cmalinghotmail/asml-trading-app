"""ASML Evaluatie Tool — historisch dagrapport met instelbare entry/TP drempels.

Standalone Streamlit app, alleen voor localhost gebruik:
    backend\\venv\\Scripts\\streamlit run tools\\evaluatie.py --server.port 8502

Raakt de hoofdapp (streamlit_app.py) niet aan.
"""

import datetime
import os
import sys

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
        "open":         act_open,
        "high":         act_high,
        "low":          act_low,
        "close":        act_close,
        "pdh_geraakt":  act_high  >= setup["entry_short"],  # prijs bereikte PDH-zone
        "pdl_geraakt":  act_low   <= setup["entry_long"],   # prijs bereikte PDL-zone
        "entry_long_ok":  act_low  <= setup["entry_long"],
        "tp_long_ok":     act_high >= setup["tp_long"],
        "entry_short_ok": act_high >= setup["entry_short"],
        "tp_short_ok":    act_low  <= setup["tp_short"],
    }


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
    st.session_state["nav_idx"] = dag_idx  # slider en knoppen in sync houden

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
    if st.button("🔄 Data opnieuw laden", key="reload_btn"):
        st.cache_data.clear()
        st.rerun()

# ---------------------------------------------------------------------------
# Geselecteerde dag
# ---------------------------------------------------------------------------

T = handelsdagen[dag_idx - 1]
dag_naam = _DAG_NAMEN[T.weekday()]

data = _bouw_data(df_ams, df_nas, df_fx, T)
if data is None:
    st.error(f"Onvoldoende data beschikbaar voor {T}.")
    st.stop()

a = _analyseer(data)

# ---------------------------------------------------------------------------
# Sectie 1 — Header
# ---------------------------------------------------------------------------

pdh    = data["pd_high"]
pdl    = data["pd_low"]
spread = round(pdh - pdl, 2)

st.markdown(f"## 📅 {dag_naam} {T.strftime('%d %B %Y')}  —  dag -{dag_idx}")
st.caption(
    f"Prev Day: H **€ {pdh:,.2f}**  /  L **€ {pdl:,.2f}**  /  C **€ {data['pd_close']:,.2f}**"
    f"  ·  Spread: **€ {spread:,.2f}**"
)
st.divider()

# ---------------------------------------------------------------------------
# Sectie 2 — Dagrapport advies (tab 4 mobiel layout)
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Sectie 3 — Aangepaste entry & TP
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Sectie 4 — Werkelijke uitkomst
# ---------------------------------------------------------------------------

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
