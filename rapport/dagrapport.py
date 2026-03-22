"""ASML Dagrapport — Streamlit tabs (PC en mobiel).

Data wordt opgehaald via yfinance en gecached in data/dagrapport_cache.json.
Cache wordt ververst na elk gepland tijdstip: 05:00, 06:00 en 08:30 Amsterdam.
"""

import datetime
import json
import os

import pandas as pd
import pytz
import streamlit as st
import yfinance as yf

# ---------------------------------------------------------------------------
# Constanten (geport vanuit homeassistant/asml_rapport.py)
# ---------------------------------------------------------------------------

HL_STATS = {
    "prev_day_high":  {"touch": 0.62, "bounce": 0.60, "avg_move": 12.00},
    "prev_day_low":   {"touch": 0.52, "bounce": 0.58, "avg_move": 12.98},
    "prev_week_high": {"touch": 0.24, "bounce": 0.76, "avg_move": 18.68},
    "prev_week_low":  {"touch": 0.17, "bounce": 0.62, "avg_move": 11.20},
}

DOW_MOD_LONG = {
    "Maandag":   +19,
    "Dinsdag":    -4,
    "Woensdag":  -13,
    "Donderdag":  -2,
    "Vrijdag":    -2,
}

DOW_MOD_SHORT = {
    "Maandag":    -2,
    "Dinsdag":   +13,
    "Woensdag":   +1,
    "Donderdag":   0,
    "Vrijdag":   -15,
}

_DAG_NAMEN = ["Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag", "Zondag"]

NASDAQ_PREMIUM = 0.93
SCHEDULE_TIMES = [datetime.time(5, 0), datetime.time(6, 0), datetime.time(8, 30)]

_CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "dagrapport_cache.json")
_AMS_TZ     = pytz.timezone("Europe/Amsterdam")


# ---------------------------------------------------------------------------
# Scheduling & cache
# ---------------------------------------------------------------------------

def _last_due_schedule_time(now: datetime.datetime) -> datetime.datetime | None:
    """Meest recente schema-tijdstip (AMS) dat gepasseerd is vandaag. None als nog geen."""
    today = now.date()
    last  = None
    for t in SCHEDULE_TIMES:
        slot = _AMS_TZ.localize(datetime.datetime.combine(today, t))
        if now >= slot:
            last = slot
    return last


def _load_cache() -> dict | None:
    try:
        with open(_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _save_cache(data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
        payload = {
            "cached_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "date":      str(datetime.date.today()),
            "data":      data,
        }
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, default=str)
    except OSError:
        pass


def _get_fresh_data() -> tuple[dict | None, bool]:
    """
    Geeft (data, was_ververst).
    Vervangt de cache als deze ouder is dan het meest recente schema-tijdstip.
    """
    # Vernieuwen-knop forceert refresh
    force = st.session_state.pop("dagrapport_force_refresh", False)

    now_ams   = datetime.datetime.now(_AMS_TZ)
    last_due  = _last_due_schedule_time(now_ams)
    cache     = _load_cache()

    # Fast path: cache is geldig
    if not force and cache:
        cache_date = cache.get("date")
        cached_at_str = cache.get("cached_at")
        if cache_date == str(datetime.date.today()) and cached_at_str and last_due:
            cached_at = _AMS_TZ.localize(
                datetime.datetime.fromisoformat(cached_at_str)
            ) if datetime.datetime.fromisoformat(cached_at_str).tzinfo is None else \
                datetime.datetime.fromisoformat(cached_at_str).astimezone(_AMS_TZ)
            if cached_at >= last_due:
                return cache["data"], False

        # Nog vóór 05:00: toon vandaagse cache als die er is
        if last_due is None and cache_date == str(datetime.date.today()):
            return cache["data"], False

    # Fetch
    try:
        data = _fetch_data()
    except Exception as exc:
        if cache:
            return cache["data"], False
        raise exc

    _save_cache(data)
    return data, True


# ---------------------------------------------------------------------------
# Data ophalen (geport vanuit homeassistant/asml_rapport.py)
# ---------------------------------------------------------------------------

def _fetch_data() -> dict:
    today  = datetime.date.today()
    result = {"gegenereerd": datetime.datetime.now().strftime("%d-%m-%Y %H:%M")}

    # ASML Amsterdam — prev day + prev week
    df = yf.download("ASML.AS", period="30d", interval="1d",
                     auto_adjust=True, progress=False)
    if df.empty:
        raise ValueError("Geen ASML.AS data van yfinance")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.index[-1].date() >= today:
        df = df.iloc[:-1]

    row = df.iloc[-1]
    result["pd_datum"] = str(df.index[-1].date())
    result["pd_high"]  = round(float(row["High"]),  2)
    result["pd_low"]   = round(float(row["Low"]),   2)
    result["pd_close"] = round(float(row["Close"]), 2)

    # Prev week H/L
    df["iso_week"] = [d.isocalendar()[1] for d in df.index.date]
    df["iso_year"] = [d.year             for d in df.index.date]
    cur_week = today.isocalendar()[1]
    cur_year = today.year
    past = df[
        (df["iso_year"] < cur_year) |
        ((df["iso_year"] == cur_year) & (df["iso_week"] < cur_week))
    ]
    lw = past["iso_week"].iloc[-1]
    ly = past["iso_year"].iloc[-1]
    wd = past[(past["iso_week"] == lw) & (past["iso_year"] == ly)]
    result["pw_week"] = int(lw)
    result["pw_high"] = round(float(wd["High"].max()), 2)
    result["pw_low"]  = round(float(wd["Low"].min()),  2)

    # Nasdaq + USD/EUR
    df_nas = yf.download("ASML", period="5d", interval="1d",
                         auto_adjust=True, progress=False)
    df_fx  = yf.download("EURUSD=X", period="5d", interval="1d",
                         auto_adjust=True, progress=False)
    if isinstance(df_nas.columns, pd.MultiIndex):
        df_nas.columns = df_nas.columns.get_level_values(0)
    if isinstance(df_fx.columns, pd.MultiIndex):
        df_fx.columns = df_fx.columns.get_level_values(0)
    if df_nas.index[-1].date() >= today:
        df_nas = df_nas.iloc[:-1]

    nas_row = df_nas.iloc[-1]
    usd_eur = 1.0 / float(df_fx.iloc[-1]["Close"])
    result["nas_datum"]     = str(df_nas.index[-1].date())
    result["nas_close_usd"] = round(float(nas_row["Close"]), 2)
    result["nas_close_eur"] = round(float(nas_row["Close"]) * usd_eur, 2)
    result["nas_high_eur"]  = round(float(nas_row["High"])  * usd_eur, 2)
    result["nas_low_eur"]   = round(float(nas_row["Low"])   * usd_eur, 2)
    result["usd_eur"]       = round(usd_eur, 4)
    result["ams_open_exp"]  = round(result["nas_close_eur"] + NASDAQ_PREMIUM, 2)

    result["volgende_dag"] = str(_volgende_handelsdag(today))
    return result


def _volgende_handelsdag(vandaag: datetime.date) -> datetime.date:
    dag = vandaag + datetime.timedelta(days=1)
    while dag.weekday() >= 5:
        dag += datetime.timedelta(days=1)
    return dag


# ---------------------------------------------------------------------------
# Analyse (geport vanuit homeassistant/asml_rapport.py)
# ---------------------------------------------------------------------------

def _analyseer(data: dict) -> dict:
    vd  = datetime.date.fromisoformat(data["volgende_dag"])
    dag = _DAG_NAMEN[vd.weekday()]

    mod_long  = DOW_MOD_LONG.get(dag, 0)
    mod_short = DOW_MOD_SHORT.get(dag, 0)

    pdh = data["pd_high"]
    pdl = data["pd_low"]
    pwh = data["pw_high"]
    pwl = data["pw_low"]
    ams = data["ams_open_exp"]

    pdh_bounce = min(100, max(0, HL_STATS["prev_day_high"]["bounce"]  * 100 + mod_long))
    pdl_bounce = min(100, max(0, HL_STATS["prev_day_low"]["bounce"]   * 100 + mod_short))
    pwh_bounce = HL_STATS["prev_week_high"]["bounce"] * 100
    pwl_bounce = HL_STATS["prev_week_low"]["bounce"]  * 100

    dist_pdh = round(pdh - ams, 2)
    dist_pdl = round(ams - pdl, 2)
    dist_pwh = round(pwh - ams, 2)
    dist_pwl = round(ams - pwl, 2)

    nas_close = data["nas_close_eur"]

    if nas_close >= pwh:
        pwh_signaal = ("🔴 break waarschijnlijk", "#ef5350",
                       f"Nasdaq sloot boven PWH → Amsterdam break (~64% kans)")
    else:
        pwh_signaal = ("🟢 bounce waarschijnlijk", "#26a69a",
                       f"Nasdaq sloot onder PWH → Amsterdam bounce (~76% kans)")

    if nas_close <= pwl:
        pwl_signaal = ("🟢 bounce waarschijnlijk", "#26a69a",
                       f"Nasdaq sloot onder PWL → Amsterdam bounce (~62% kans)")
    else:
        pwl_signaal = ("⚪ neutraal", "#888888",
                       f"Nasdaq sloot boven PWL → Nasdaq bounce ~77%, Amsterdam neutraal")

    pdl_dichtbij     = dist_pdl <= 15
    pdh_afstand_pct  = dist_pdh / ams * 100 if ams else 0

    if pdl_dichtbij:
        primaire_setup = "LONG bij PDL retrace"
        setup_kleur    = "#26a69a"
        setup_tekst    = (
            f"Open verwacht ~€{ams:.2f}. PDL (€{pdl:.2f}) ligt slechts "
            f"€{dist_pdl:.2f} onder de open. Bij terugtest naar PDL en "
            f"bevestigde bounce: LONG instappen. Target T1 = PDH €{pdh:.2f} "
            f"({pdh_bounce:.0f}% bounce kans op {dag})."
        )
        sl_niveau = round(pdl - 12, 2)
        tp_niveau = pdh
    else:
        primaire_setup = "Wacht op richting bij open"
        setup_kleur    = "#ffa726"
        setup_tekst    = (
            f"PDL (€{pdl:.2f}) ligt €{dist_pdl:.2f} onder de verwachte open. "
            f"Wacht de eerste 15–30 min af. Bij sterke open richting PDH: "
            f"LONG met PDH €{pdh:.2f} als target ({pdh_bounce:.0f}% bounce kans)."
        )
        sl_niveau = round(data["nas_low_eur"] - 5, 2)
        tp_niveau = pdh

    gesloten_op_low = abs(data["pd_close"] - pdl) < 1.0

    return {
        "dag_naam":        dag,
        "mod_long":        mod_long,
        "mod_short":       mod_short,
        "pdh_bounce":      pdh_bounce,
        "pdl_bounce":      pdl_bounce,
        "pwh_bounce":      pwh_bounce,
        "pwl_bounce":      pwl_bounce,
        "dist_pdh":        dist_pdh,
        "dist_pdl":        dist_pdl,
        "dist_pwh":        dist_pwh,
        "dist_pwl":        dist_pwl,
        "pwh_signaal":     pwh_signaal,
        "pwl_signaal":     pwl_signaal,
        "primaire_setup":  primaire_setup,
        "setup_kleur":     setup_kleur,
        "setup_tekst":     setup_tekst,
        "sl_niveau":       sl_niveau,
        "tp_niveau":       tp_niveau,
        "gesloten_op_low": gesloten_op_low,
    }


def _bounce_label(pct: float) -> str:
    if pct >= 70:
        return "Sterk"
    if pct >= 50:
        return "Matig"
    return "Zwak"


def _niveautabel(data: dict, a: dict) -> pd.DataFrame:
    dag = a["dag_naam"][:2]
    rijen = [
        ("Prev Week High", data["pw_high"], "Weerstand",
         f"{a['pwh_bounce']:.0f}% {_bounce_label(a['pwh_bounce'])}", "—",
         f"+€{a['dist_pwh']:.2f}"),
        ("Prev Day High",  data["pd_high"], "Weerstand",
         f"{a['pdh_bounce']:.0f}% {_bounce_label(a['pdh_bounce'])}",
         f"{a['mod_long']:+d}%", f"+€{a['dist_pdh']:.2f}"),
        ("Verwachte open", data["ams_open_exp"], "Referentie", "—", "—", "—"),
        ("Prev Day Low",   data["pd_low"],  "Steun",
         f"{a['pdl_bounce']:.0f}% {_bounce_label(a['pdl_bounce'])}",
         f"{a['mod_short']:+d}%", f"-€{a['dist_pdl']:.2f}"),
        ("Prev Week Low",  data["pw_low"],  "Steun",
         f"{a['pwl_bounce']:.0f}% {_bounce_label(a['pwl_bounce'])}", "—",
         f"-€{a['dist_pwl']:.2f}"),
    ]
    return pd.DataFrame(rijen, columns=["Niveau", "Koers (€)", "Rol", "Bounce", f"{dag}-mod", "Afstand"])


def _prijsladder_tekst(data: dict, a: dict) -> str:
    dag = a["dag_naam"][:2]
    return (
        f"  {data['pw_high']:>8.2f}  ── Prev Week High    (bounce {a['pwh_bounce']:.0f}%)\n"
        f"  {data['pd_high']:>8.2f}  ── Prev Day High     (bounce {a['pdh_bounce']:.0f}% op {dag})\n"
        f"  {'─'*42}\n"
        f"  {data['ams_open_exp']:>8.2f}  ── Verwachte open   (Nasdaq + {NASDAQ_PREMIUM:.2f})\n"
        f"  {'─'*42}\n"
        f"  {data['pd_low']:>8.2f}  ── Prev Day Low      (bounce {a['pdl_bounce']:.0f}% op {dag})\n"
        f"  {data['pw_low']:>8.2f}  ── Prev Week Low     (bounce {a['pwl_bounce']:.0f}%)"
    )


# ---------------------------------------------------------------------------
# Gedeelde header + data laden
# ---------------------------------------------------------------------------

def _laad_data_met_header(key_suffix: str = "") -> tuple[dict | None, dict | None]:
    """Laadt data + toont foutmelding/spinner. Geeft (data, analyse) of (None, None)."""
    col_titel, col_btn = st.columns([8, 1])
    with col_btn:
        if st.button("↺", help="Rapport vernieuwen", key=f"dagrapport_refresh_btn{key_suffix}"):
            st.session_state["dagrapport_force_refresh"] = True
            st.rerun()

    try:
        with st.spinner("Data ophalen..."):
            data, was_ververst = _get_fresh_data()
    except Exception as exc:
        st.error(f"Kon geen data ophalen: {exc}")
        return None, None

    if data is None:
        st.info("Nog geen data. Klik ↺ om op te halen.")
        return None, None

    if was_ververst:
        st.toast("Rapport bijgewerkt")

    a = _analyseer(data)

    vd  = datetime.date.fromisoformat(data["volgende_dag"])
    dag = a["dag_naam"]
    with col_titel:
        st.caption(
            f"Gegenereerd: {data['gegenereerd']}  |  "
            f"Volgende handelsdag: **{dag} {vd.strftime('%d %B %Y')}**"
        )

    today = datetime.date.today()
    if today.weekday() >= 5:
        st.warning(
            "⚠️ Weekendrapport — geen nieuw Nasdaq-signaal tot maandagnacht. "
            "Wacht de eerste 15–30 min van de sessie af."
        )
    if a["gesloten_op_low"]:
        st.warning(
            f"⚠️ Vorige handelsdag sloot op de daglow (€{data['pd_close']:.2f}) "
            "— bearish slotpatroon."
        )

    return data, a


# ---------------------------------------------------------------------------
# Tab 3 — PC layout
# ---------------------------------------------------------------------------

def render_dagrapport_tab_pc() -> None:
    data, a = _laad_data_met_header("_pc")
    if data is None:
        return

    dag = a["dag_naam"]

    # Drie metrics bovenaan
    c1, c2, c3 = st.columns(3)
    c1.metric("Verwachte open", f"€ {data['ams_open_exp']:.2f}")
    c2.metric("Prev Day Close", f"€ {data['pd_close']:.2f}")
    c3.metric("Prev Week High", f"€ {data['pw_high']:.2f}")

    # Niveautabel + bounce metrics
    col_tabel, col_bounce = st.columns([3, 2])

    with col_tabel:
        st.markdown("**Niveaus & Bounce Kansen**")
        df = _niveautabel(data, a)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Koers (€)": st.column_config.NumberColumn(format="€ %.2f"),
            },
        )

    with col_bounce:
        st.markdown("**Bounce kansen**")
        bc1, bc2 = st.columns(2)
        bc1.metric(f"PDH ({dag[:2]})", f"{a['pdh_bounce']:.0f}%",
                   delta=f"{a['mod_long']:+d}%")
        bc2.metric(f"PDL ({dag[:2]})", f"{a['pdl_bounce']:.0f}%",
                   delta=f"{a['mod_short']:+d}%")
        bc3, bc4 = st.columns(2)
        bc3.metric("PWH", f"{a['pwh_bounce']:.0f}%")
        bc4.metric("PWL", f"{a['pwl_bounce']:.0f}%")

    # Nasdaq signalen + Setup advies
    col_nas, col_setup = st.columns(2)

    with col_nas:
        pwh_label, _, pwh_txt = a["pwh_signaal"]
        pwl_label, _, pwl_txt = a["pwl_signaal"]
        with st.container(border=True):
            st.markdown("**🇺🇸 Nasdaq Signalen**")
            st.caption(
                f"Slot: € {data['nas_close_eur']:.2f}  "
                f"($ {data['nas_close_usd']:.2f} · USD/EUR {data['usd_eur']:.4f})"
            )
            st.markdown(f"**PWH € {data['pw_high']:.2f}** — {pwh_label}")
            st.caption(pwh_txt)
            st.markdown(f"**PWL € {data['pw_low']:.2f}** — {pwl_label}")
            st.caption(pwl_txt)

    with col_setup:
        with st.container(border=True):
            st.markdown("**Setup Advies**")
            st.markdown(f"**{a['primaire_setup']}**")
            st.caption(a["setup_tekst"])
            s1, s2, s3 = st.columns(3)
            s1.metric("Stop", f"€ {a['sl_niveau']:.2f}", delta_color="inverse",
                      delta=f"{a['sl_niveau'] - data['pd_close']:+.2f}")
            s2.metric("Target T1", f"€ {a['tp_niveau']:.2f}",
                      delta=f"{a['tp_niveau'] - data['pd_close']:+.2f}")
            s3.metric("Prev Close", f"€ {data['pd_close']:.2f}")

    # Prijsladder
    with st.expander("Prijsladder"):
        st.code(_prijsladder_tekst(data, a), language=None)


# ---------------------------------------------------------------------------
# Tab 4 — Mobiel layout
# ---------------------------------------------------------------------------

def render_dagrapport_tab_mobiel() -> None:
    data, a = _laad_data_met_header("_mob")
    if data is None:
        return

    dag = a["dag_naam"]

    # Verwachte open
    st.metric("Verwachte open Amsterdam", f"€ {data['ams_open_exp']:.2f}")
    st.caption(
        f"Nasdaq slot: $ {data['nas_close_usd']:.2f}  →  € {data['nas_close_eur']:.2f}  "
        f"(USD/EUR {data['usd_eur']:.4f})"
    )

    st.divider()

    # Compacte niveautabel
    st.markdown("**Niveaus**")
    df = _niveautabel(data, a)[["Niveau", "Koers (€)", "Bounce", "Afstand"]]
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Koers (€)": st.column_config.NumberColumn(format="€ %.2f"),
        },
    )

    st.divider()

    # Bounce grid 2×2
    st.markdown("**Bounce kansen**")
    bc1, bc2 = st.columns(2)
    bc1.metric(f"PDH ({dag[:2]})", f"{a['pdh_bounce']:.0f}%", delta=f"{a['mod_long']:+d}%")
    bc2.metric(f"PDL ({dag[:2]})", f"{a['pdl_bounce']:.0f}%", delta=f"{a['mod_short']:+d}%")
    bc3, bc4 = st.columns(2)
    bc3.metric("PWH", f"{a['pwh_bounce']:.0f}%")
    bc4.metric("PWL", f"{a['pwl_bounce']:.0f}%")

    st.divider()

    # Setup advies
    with st.container(border=True):
        st.markdown(f"**{a['primaire_setup']}**")
        st.caption(a["setup_tekst"])
        s1, s2 = st.columns(2)
        s1.metric("Stop", f"€ {a['sl_niveau']:.2f}", delta_color="inverse",
                  delta=f"{a['sl_niveau'] - data['pd_close']:+.2f}")
        s2.metric("Target T1", f"€ {a['tp_niveau']:.2f}",
                  delta=f"{a['tp_niveau'] - data['pd_close']:+.2f}")

    # Nasdaq signalen compact
    pwh_label, _, pwh_txt = a["pwh_signaal"]
    pwl_label, _, pwl_txt = a["pwl_signaal"]
    with st.expander("🇺🇸 Nasdaq Signalen"):
        st.markdown(f"**PWH € {data['pw_high']:.2f}** — {pwh_label}")
        st.caption(pwh_txt)
        st.markdown(f"**PWL € {data['pw_low']:.2f}** — {pwl_label}")
        st.caption(pwl_txt)

    # Prijsladder
    with st.expander("Prijsladder", expanded=False):
        st.code(_prijsladder_tekst(data, a), language=None)
