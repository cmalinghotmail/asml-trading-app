"""ASML Dagrapport — AppDaemon app voor Home Assistant.

Draait dagelijks om 06:00. Haalt ASML marktdata op via yfinance en
schrijft een HTML-rapport naar /config/www/asml_rapport.html.

Installatie:
  1. Kopieer dit bestand naar: /config/appdaemon/apps/asml_rapport.py
  2. Voeg toe aan /config/appdaemon/apps/apps.yaml:
         asml_rapport:
           module: asml_rapport
           class: ASMLRapport
  3. Voeg toe aan AppDaemon add-on configuratie:
         python_packages:
           - yfinance
           - pandas
           - pytz
  4. Herstart AppDaemon
  5. Rapport bereikbaar op: http://homeassistant.local:8123/local/asml_rapport.html
"""

import datetime
import os

import appdaemon.plugins.hass.hassapi as hass
import pandas as pd
import yfinance as yf

# ---------------------------------------------------------------------------
# Statistieken — 6 maanden Amsterdam bounce data
# ---------------------------------------------------------------------------
HL_STATS = {
    "prev_day_high":  {"touch": 0.62, "bounce": 0.60, "avg_move": 12.00},
    "prev_day_low":   {"touch": 0.52, "bounce": 0.58, "avg_move": 12.98},
    "prev_week_high": {"touch": 0.24, "bounce": 0.76, "avg_move": 18.68},
    "prev_week_low":  {"touch": 0.17, "bounce": 0.62, "avg_move": 11.20},
}

DOW_MOD_LONG = {
    0: ("Maandag",   +19),
    1: ("Dinsdag",    -4),
    2: ("Woensdag",  -13),
    3: ("Donderdag",  -2),
    4: ("Vrijdag",    -2),
}

DOW_MOD_SHORT = {
    0: ("Maandag",    -2),
    1: ("Dinsdag",   +13),
    2: ("Woensdag",   +1),
    3: ("Donderdag",   0),
    4: ("Vrijdag",   -15),
}

NASDAQ_PREMIUM = 0.93   # EUR
RAPPORT_PATH   = "/config/www/asml_rapport.html"


# ---------------------------------------------------------------------------
# AppDaemon app
# ---------------------------------------------------------------------------

class ASMLRapport(hass.Hass):

    def initialize(self):
        self.run_daily(self.generate_rapport, datetime.time(6, 0, 0))
        # Verwijder onderstaande commentaar om direct na herstart te testen:
        # self.run_in(self.generate_rapport, 15)

    def generate_rapport(self, kwargs):
        self.log("ASML Rapport: data ophalen...")
        try:
            data = _fetch_data()
        except Exception as exc:
            self.log(f"ASML Rapport: datafout — {exc}", level="ERROR")
            _schrijf_foutpagina(str(exc))
            return

        html = _genereer_html(data)
        os.makedirs(os.path.dirname(RAPPORT_PATH), exist_ok=True)
        with open(RAPPORT_PATH, "w", encoding="utf-8") as f:
            f.write(html)
        self.log(f"ASML Rapport: geschreven naar {RAPPORT_PATH}")


# ---------------------------------------------------------------------------
# Data ophalen
# ---------------------------------------------------------------------------

def _fetch_data() -> dict:
    today  = datetime.date.today()
    result = {"gegenereerd": datetime.datetime.now().strftime("%d-%m-%Y %H:%M")}

    # --- ASML Amsterdam prev day + prev week ---
    df = yf.download("ASML.AS", period="30d", interval="1d",
                     auto_adjust=True, progress=False)
    if df.empty:
        raise ValueError("Geen ASML.AS data van yfinance")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.index[-1].date() >= today:
        df = df.iloc[:-1]

    row = df.iloc[-1]
    result["pd_datum"]  = df.index[-1].date()
    result["pd_high"]   = round(float(row["High"]),  2)
    result["pd_low"]    = round(float(row["Low"]),   2)
    result["pd_close"]  = round(float(row["Close"]), 2)

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
    result["pw_week"]  = lw
    result["pw_high"]  = round(float(wd["High"].max()), 2)
    result["pw_low"]   = round(float(wd["Low"].min()),  2)

    # --- Nasdaq + USD/EUR ---
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
    result["nas_datum"]     = df_nas.index[-1].date()
    result["nas_close_usd"] = round(float(nas_row["Close"]), 2)
    result["nas_close_eur"] = round(float(nas_row["Close"]) * usd_eur, 2)
    result["nas_high_eur"]  = round(float(nas_row["High"])  * usd_eur, 2)
    result["nas_low_eur"]   = round(float(nas_row["Low"])   * usd_eur, 2)
    result["usd_eur"]       = round(usd_eur, 4)
    result["ams_open_exp"]  = round(result["nas_close_eur"] + NASDAQ_PREMIUM, 2)

    # Volgende handelsdag
    result["volgende_dag"]  = _volgende_handelsdag(today)

    return result


def _volgende_handelsdag(vandaag: datetime.date) -> datetime.date:
    dag = vandaag + datetime.timedelta(days=1)
    while dag.weekday() >= 5:  # 5=zaterdag, 6=zondag
        dag += datetime.timedelta(days=1)
    return dag


# ---------------------------------------------------------------------------
# Analysehulpers
# ---------------------------------------------------------------------------

def _bounce_kleur(pct: float) -> tuple:
    """Geeft (kleur, label) terug op basis van bounce percentage."""
    if pct >= 70:
        return "#26a69a", "Sterk"
    if pct >= 50:
        return "#ffa726", "Matig"
    return "#ef5350", "Zwak"


def _analyseer(data: dict) -> dict:
    vd = data["volgende_dag"]
    dow = vd.weekday()          # 0=ma, 4=vr
    dag_naam, mod_long  = DOW_MOD_LONG.get(dow,  ("—", 0))
    _,         mod_short = DOW_MOD_SHORT.get(dow, ("—", 0))

    pdh = data["pd_high"]
    pdl = data["pd_low"]
    pwh = data["pw_high"]
    pwl = data["pw_low"]
    ams = data["ams_open_exp"]

    # Bounce kansen
    pdh_bounce = min(100, max(0, HL_STATS["prev_day_high"]["bounce"]  * 100 + mod_long))
    pdl_bounce = min(100, max(0, HL_STATS["prev_day_low"]["bounce"]   * 100 + mod_short))
    pwh_bounce = HL_STATS["prev_week_high"]["bounce"] * 100
    pwl_bounce = HL_STATS["prev_week_low"]["bounce"]  * 100

    # Afstanden vanuit verwachte open
    dist_pdh = round(pdh - ams, 2)
    dist_pdl = round(ams - pdl, 2)
    dist_pwh = round(pwh - ams, 2)
    dist_pwl = round(ams - pwl, 2)

    # Nasdaq signaal vs PWH/PWL Amsterdam
    nas_close = data["nas_close_eur"]
    nas_vs_pwh = "boven" if nas_close >= pwh else "onder"
    nas_vs_pwl = "onder" if nas_close <= pwl else "boven"

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

    # Primaire setup bepalen
    pdl_dichtbij = dist_pdl <= 15  # PDL binnen 15 EUR van open
    pdh_afstand_pct = dist_pdh / ams * 100 if ams else 0

    if pdl_dichtbij:
        primaire_setup = "LONG bij PDL retrace"
        setup_kleur = "#26a69a"
        setup_tekst = (
            f"Open verwacht ~€{ams:.2f}. PDL (€{pdl:.2f}) ligt slechts "
            f"€{dist_pdl:.2f} onder de open. Bij terugtest naar PDL en "
            f"bevestigde bounce: LONG instappen. Target T1 = PDH €{pdh:.2f} "
            f"({pdh_bounce:.0f}% bounce kans op {dag_naam})."
        )
        sl_niveau = round(pdl - 12, 2)
        tp_niveau = pdh
    else:
        primaire_setup = "Wacht op richting bij open"
        setup_kleur = "#ffa726"
        setup_tekst = (
            f"PDL (€{pdl:.2f}) ligt €{dist_pdl:.2f} onder de verwachte open. "
            f"Wacht de eerste 15–30 min af. Bij sterke open richting PDH: "
            f"LONG met PDH €{pdh:.2f} als target ({pdh_bounce:.0f}% bounce kans)."
        )
        sl_niveau = round(data["nas_low_eur"] - 5, 2)
        tp_niveau = pdh

    # Sloot vrijdag op de low?
    gesloten_op_low = abs(data["pd_close"] - pdl) < 1.0

    return {
        "dag_naam":        dag_naam,
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


# ---------------------------------------------------------------------------
# HTML generatie
# ---------------------------------------------------------------------------

def _kleur_badge(pct: float) -> str:
    kleur, label = _bounce_kleur(pct)
    return f'<span class="badge" style="background:{kleur}">{pct:.0f}% {label}</span>'


def _genereer_html(data: dict) -> str:
    a   = _analyseer(data)
    vd  = data["volgende_dag"]
    dag = a["dag_naam"]

    # Weekendwaarschuwing
    today = datetime.date.today()
    is_weekend = today.weekday() >= 5
    weekend_html = ""
    if is_weekend:
        weekend_html = f"""
        <div class="waarschuwing">
            ⚠️ Weekendrapport — gegenereerd op {today.strftime("%A %d %B")}. Geen nieuw
            Nasdaq-signaal tot maandagnacht. Wacht de eerste 15–30 min van de sessie af.
        </div>"""

    # Signaalwaarschuwing vrijdag sloot op low
    low_signaal = ""
    if a["gesloten_op_low"]:
        low_signaal = f"""
        <div class="waarschuwing" style="background:#3a1a1a; border-color:#ef5350">
            ⚠️ Vorige handelsdag sloot op de <strong>daglow</strong>
            (€{data['pd_close']:.2f}) — bearish slotpatroon.
        </div>"""

    # Niveautabel
    niveaus = [
        ("Prev Week High", data["pw_high"], "weerstand", a["pwh_bounce"],
         0, f'+€{a["dist_pwh"]:.2f}'),
        ("Prev Day High",  data["pd_high"], "weerstand", a["pdh_bounce"],
         a["mod_long"], f'+€{a["dist_pdh"]:.2f}'),
        ("Verwachte open", data["ams_open_exp"], "referentie", None,
         0, "—"),
        ("Prev Day Low",   data["pd_low"],  "steun",     a["pdl_bounce"],
         a["mod_short"], f'-€{a["dist_pdl"]:.2f}'),
        ("Prev Week Low",  data["pw_low"],  "steun",     a["pwl_bounce"],
         0, f'-€{a["dist_pwl"]:.2f}'),
    ]

    tabel_rijen = ""
    for naam, niveau, rol, bounce, mod, afstand in niveaus:
        if bounce is None:
            bounce_cel = '<td class="center">—</td>'
            mod_cel    = '<td class="center">—</td>'
        else:
            mod_str  = f"{mod:+d}%" if mod != 0 else "—"
            mod_kleur = "#26a69a" if mod > 0 else ("#ef5350" if mod < 0 else "#888")
            bounce_cel = f'<td class="center">{_kleur_badge(bounce)}</td>'
            mod_cel    = f'<td class="center" style="color:{mod_kleur}">{mod_str}</td>'

        rol_kleur = "#ef5350" if rol == "weerstand" else ("#26a69a" if rol == "steun" else "#4fa3e0")
        is_open   = naam == "Verwachte open"
        rij_stijl = 'style="background:#1e2840; font-weight:600"' if is_open else ""

        tabel_rijen += f"""
        <tr {rij_stijl}>
            <td>{naam}</td>
            <td class="prijs">€ {niveau:,.2f}</td>
            <td class="center" style="color:{rol_kleur}">{rol.title()}</td>
            {bounce_cel}
            {mod_cel}
            <td class="center">{afstand}</td>
        </tr>"""

    # Nasdaq signaalblok
    pwh_label, pwh_kleur, pwh_txt = a["pwh_signaal"]
    pwl_label, pwl_kleur, pwl_txt = a["pwl_signaal"]

    # Rapport
    return f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ASML Dagrapport</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #0e1117;
    color: #e0e0e0;
    font-size: 14px;
    padding: 12px;
  }}
  h1 {{ font-size: 1.2rem; color: #fafafa; margin-bottom: 2px; }}
  h2 {{ font-size: 0.95rem; color: #aaa; font-weight: 400; margin-bottom: 16px; }}
  h3 {{ font-size: 0.85rem; color: #4fa3e0; text-transform: uppercase;
        letter-spacing: .05em; margin: 16px 0 8px; }}
  .card {{
    background: #1a1f2e;
    border: 1px solid #2a2f3e;
    border-radius: 8px;
    padding: 12px;
    margin-bottom: 12px;
  }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{
    text-align: left; font-size: 0.75rem; color: #888;
    padding: 4px 6px; border-bottom: 1px solid #2a2f3e;
    text-transform: uppercase; letter-spacing: .04em;
  }}
  td {{ padding: 6px 6px; border-bottom: 1px solid #1e2430; }}
  .prijs {{ font-weight: 600; color: #fafafa; font-size: 0.9rem; }}
  .center {{ text-align: center; }}
  .badge {{
    display: inline-block;
    padding: 2px 7px;
    border-radius: 10px;
    font-size: 0.75rem;
    font-weight: 600;
    color: #fff;
  }}
  .setup-box {{
    border-left: 3px solid {a['setup_kleur']};
    padding: 8px 12px;
    background: #161b28;
    border-radius: 0 6px 6px 0;
    margin-bottom: 8px;
  }}
  .setup-titel {{ color: {a['setup_kleur']}; font-weight: 700; font-size: 0.9rem; margin-bottom: 4px; }}
  .signaal-rij {{ display: flex; align-items: flex-start; gap: 8px; margin-bottom: 10px; }}
  .signaal-label {{ font-weight: 700; white-space: nowrap; }}
  .meta {{ font-size: 0.75rem; color: #666; margin-top: 16px; text-align: right; }}
  .waarschuwing {{
    background: #2a2010;
    border: 1px solid #ffa726;
    border-radius: 6px;
    padding: 8px 12px;
    margin-bottom: 10px;
    font-size: 0.82rem;
    color: #ffa726;
  }}
  @media (max-width: 480px) {{
    body {{ font-size: 13px; padding: 8px; }}
    h1 {{ font-size: 1.05rem; }}
  }}
</style>
</head>
<body>

<h1>📊 ASML Dagrapport</h1>
<h2>Volgende handelsdag: <strong style="color:#fafafa">{dag} {vd.strftime("%d %B %Y")}</strong></h2>

{weekend_html}
{low_signaal}

<!-- Niveautabel -->
<div class="card">
  <h3>Niveaus &amp; Bounce Kansen</h3>
  <table>
    <thead>
      <tr>
        <th>Niveau</th>
        <th>Koers</th>
        <th class="center">Rol</th>
        <th class="center">Bounce</th>
        <th class="center">{dag[:2]}-mod</th>
        <th class="center">Afstand</th>
      </tr>
    </thead>
    <tbody>
      {tabel_rijen}
    </tbody>
  </table>
</div>

<!-- Nasdaq signalen -->
<div class="card">
  <h3>🇺🇸 Nasdaq Signaal</h3>
  <p style="margin-bottom:10px; color:#aaa; font-size:0.82rem">
    Nasdaq slot: <strong style="color:#fafafa">€ {data['nas_close_eur']:.2f}</strong>
    &nbsp;($ {data['nas_close_usd']:.2f} · USD/EUR {data['usd_eur']:.4f})
    &nbsp;→ Amsterdam open verwacht: <strong style="color:#ffd700">€ {data['ams_open_exp']:.2f}</strong>
  </p>
  <div class="signaal-rij">
    <div>
      <div class="signaal-label" style="color:{pwh_kleur}">
        Prev Week High € {data['pw_high']:,.2f} — {pwh_label}
      </div>
      <div style="color:#aaa; font-size:0.82rem">{pwh_txt}</div>
    </div>
  </div>
  <div class="signaal-rij">
    <div>
      <div class="signaal-label" style="color:{pwl_kleur}">
        Prev Week Low € {data['pw_low']:,.2f} — {pwl_label}
      </div>
      <div style="color:#aaa; font-size:0.82rem">{pwl_txt}</div>
    </div>
  </div>
</div>

<!-- Setup advies -->
<div class="card">
  <h3>Setup Advies</h3>
  <div class="setup-box">
    <div class="setup-titel">Primair: {a['primaire_setup']}</div>
    <div style="color:#ccc; line-height:1.5">{a['setup_tekst']}</div>
  </div>
  <div style="display:flex; gap:16px; flex-wrap:wrap; margin-top:8px; font-size:0.82rem; color:#aaa">
    <span>🔴 Stop: <strong style="color:#ef5350">€ {a['sl_niveau']:.2f}</strong></span>
    <span>🟢 Target T1: <strong style="color:#26a69a">€ {a['tp_niveau']:.2f}</strong></span>
    <span>Prev Day Close: <strong style="color:#fafafa">€ {data['pd_close']:.2f}</strong></span>
  </div>
</div>

<!-- Prijsladder tekst -->
<div class="card">
  <h3>Prijsladder</h3>
  <div style="font-family: monospace; font-size: 0.82rem; line-height: 2; color: #ccc">
    <div style="color:#888">€ {data['pw_high']:>8.2f}  ── Prev Week High &nbsp; (bounce {a['pwh_bounce']:.0f}%)</div>
    <div style="color:#ef5350">€ {data['pd_high']:>8.2f}  ── Prev Day High &nbsp;&nbsp; (bounce {a['pdh_bounce']:.0f}% op {dag[:2]})</div>
    <div style="height:1px; background:#2a2f3e; margin: 4px 0"></div>
    <div style="color:#ffd700">€ {data['ams_open_exp']:>8.2f}  ── Verwachte open (Nasdaq + {NASDAQ_PREMIUM:.2f})</div>
    <div style="height:1px; background:#2a2f3e; margin: 4px 0"></div>
    <div style="color:#26a69a">€ {data['pd_low']:>8.2f}  ── Prev Day Low &nbsp;&nbsp;&nbsp; (bounce {a['pdl_bounce']:.0f}% op {dag[:2]})</div>
    <div style="color:#888">€ {data['pw_low']:>8.2f}  ── Prev Week Low &nbsp;&nbsp; (bounce {a['pwl_bounce']:.0f}%)</div>
  </div>
</div>

<div class="meta">Gegenereerd: {data['gegenereerd']} &nbsp;|&nbsp; Data: yfinance (15 min vertraagd)</div>

</body>
</html>"""


def _schrijf_foutpagina(fout: str):
    os.makedirs(os.path.dirname(RAPPORT_PATH), exist_ok=True)
    with open(RAPPORT_PATH, "w", encoding="utf-8") as f:
        f.write(f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>body{{background:#0e1117;color:#ef5350;font-family:sans-serif;padding:20px}}</style>
</head><body>
<h2>ASML Rapport — Fout bij ophalen</h2>
<p>{fout}</p>
<p style="color:#888">Gegenereerd: {datetime.datetime.now().strftime("%d-%m-%Y %H:%M")}</p>
</body></html>""")
