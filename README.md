# ASML Trading App

Een Streamlit-webapplicatie als **rekenhulp naast ProRealTime en DeGiro** voor het handmatig handelen in ASML-turboproducten.

De app haalt automatisch de vorige handelsdag High/Low/Mid op en berekent de bijbehorende turbo-instapkoersen, SL- en TP-niveaus. Orders worden handmatig ingevoerd in DeGiro; de app geeft alleen berekeningen en signaalindicaties.

---

## Functionaliteiten

- **Box Strategie** — Vorige handelsdag H/L/M automatisch ophalen (yfinance, weekendbestendig). Twee zones naast elkaar: LONG (onderkant box) en SHORT (bovenkant box), elk met eigen ASML entry/SL/TP en bijbehorende turbo-berekeningen.
- **Turbo Calculator** — Financing-aware vertaling van ASML SL/TP naar turbo-prijzen, R/R-ratio en financieringsniveau. Aparte instellingen voor Turbo LONG en Turbo SHORT (naam, ISIN, leverage, ratio).
- **Candlestick Chart** — Plotly-chart met SL/TP/Entry-lijnen en signaalmarkers.
- **Trading Setups** — Automatische signaaldetectie: Previous Day Box, Morning Gap Fill, Morning Momentum, Opening Range Break, Closing Reversion, generieke Breakout.
- **Twee feeds** — Demo (random-walk mock data) en Live (yfinance, 1-min candles, 15 min vertraagd).
- **Candle-cache** — Persistente cache over browser-refresh (datum + ticker validatie).

---

## Installatie

```bash
cd c:\DEV\Prive\asml-trading-app
python -m venv backend\venv
backend\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

## Starten

```bash
backend\venv\Scripts\streamlit run streamlit_app.py
```

Open daarna [http://localhost:8501](http://localhost:8501).

---

## Configuratie

Maak `config.yaml` aan op basis van `config.example.yaml`:

```yaml
# Onderliggende waarde
underlying_symbol: ASML.AS

# Turbo LONG product
turbo_long:
  name: "ASML Long 949"
  isin: "NLBNPNL3EX12"
  leverage: 3.55
  ratio: 100

# Turbo SHORT product
turbo_short:
  name: "ASML Short 1,453.1"
  isin: "NLBNPNL3FE71"
  leverage: 3.55
  ratio: 100

# Legacy leverage/ratio (fallback als turbo_long/short ontbreekt)
turbo:
  leverage: 3.55
  ratio: 100

# Default setup bij opstarten
demo_setup: prev_day_box

# Demo-opties
demo_prev_close: 1210.0
demo_limit: 500
demo_force_window: true   # tijdvensters negeren in demo-modus
```

> `config.yaml` staat in `.gitignore`. Gebruik `config.example.yaml` als startpunt.

---

## Turbo-berekening

```
Intrinsic  = turbo_price × ratio
Financing  = asml_price − intrinsic        (LONG)
           = asml_price + intrinsic        (SHORT)

Turbo SL   = (sl − financing) / ratio     (LONG)
Turbo TP   = (tp − financing) / ratio

Turbo SL   = (financing − sl) / ratio     (SHORT)
Turbo TP   = (financing − tp) / ratio
```

Turbo entry wordt berekend als `asml_entry / (leverage × ratio)`.

---

## UI-layout

```
Sidebar: setup, ticker, feed_mode, 🔄 Box vernieuwen,
         🟢 Turbo LONG (naam/ISIN/leverage/ratio),
         🔴 Turbo SHORT (naam/ISIN/leverage/ratio),
         Start / Stop

Hoofdscherm:
  Header: status + actuele koers
  📦 Box Strategie (border):
    Low | Mid | High + corresponderende turbo-prijzen
    🟢 LONG zone | 🔴 SHORT zone
      ASML Entry / SL / TP → Turbo entry / SL / TP / R/R / Financiering
  Niveau-blok | Turbo Calculator
  Candlestick chart
```

---

## Projectstructuur

```
asml-trading-app/
├── streamlit_app.py           # Hoofd UI (Streamlit)
├── config.yaml                # Lokale configuratie (GITIGNORED)
├── config.example.yaml        # Template voor config.yaml
├── requirements.txt
├── backend/
│   └── engine.py              # TradingEngine daemon thread + candle-cache
├── data/
│   ├── mock_saxo.py           # Demo random-walk feed
│   ├── yfinance_feed.py       # Live yfinance feed (1-min)
│   └── candle_cache.json      # Runtime cache (GITIGNORED)
├── strategies/
│   └── asml_setups.py         # 4 ASML-specifieke setups
├── strategy/
│   └── breakout.py            # Generieke breakout
├── turbo/
│   └── translate.py           # Turbo SL/TP calculator (financing-aware)
├── .streamlit/
│   └── config.toml            # Streamlit server + dark theme
└── ui/                        # Legacy CLI-interface (niet actief)
    ├── notifier.py
    └── gui.py
```

---

## Bekende beperkingen

- yfinance: 15 min vertraagd op Euronext; lopende minuutcandles hebben open=close (streepcandles).
- Volume van yfinance is onbetrouwbaar → volume-gebaseerde signalen werken alleen betrouwbaar met mock data.
- Candle-cache is niet persistent op Streamlit Community Cloud (ephemeral filesystem).

---

## Legacy CLI

`main.py` bevat een oude CLI/tkinter-interface (niet meer actief gebruikt). Bewaard voor compatibiliteit.
