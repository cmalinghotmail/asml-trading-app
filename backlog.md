# ASML Trading App — Backlog

> Bijgehouden per sessie. Prioriteit: 🔴 hoog · 🟡 midden · 🟢 laag · 💡 idee

---

## Huidige staat (28-02-2026)

App is volledig functioneel als Streamlit-web UI:
- Live yfinance feed (1-min, 15 min vertraagd voor Euronext)
- Demo mock feed (random walk, 100 ms/candle)
- 4 ASML-specifieke setups + generieke breakout
- Turbo calculator (financing-aware SL/TP, R/R)
- Candle-cache: persistent over browser-refresh (datum + ticker validatie)
- Candlestick chart met SL/TP annotaties

---

## Bugs / Issues

| Prio | Item | Bestand |
|------|------|---------|
| 🔴 | **signal_fired reset** — MorningMomentum, OpeningRangeBreak en ClosingReversion zetten `signal_fired = True` en vuren daarna nooit meer. Engine.start() reset de state, maar als de engine al draait en het tijdvenster opnieuw begint (nieuwe dag), vuurt de setup niet meer. | [strategies/asml_setups.py](strategies/asml_setups.py) |
| 🔴 | **Mock volume te laag** — MockSaxoFeed genereert volume 100-2000, maar `vol_min` voor MorningMomentum / ClosingReversion is 3000-5000. In demo-modus vuren deze setups daardoor nooit. | [data/mock_saxo.py](data/mock_saxo.py) |
| 🟡 | **Prev close niet automatisch opgehaald** — `demo_prev_close` staat hardcoded in config.yaml. Bij live feed klopt dit de volgende dag niet meer automatisch. | [backend/engine.py](backend/engine.py):107 |
| 🟡 | **candle_history slechts 100 candles** — `CHART_CANDLES = 100` in engine. Sommige setups (ClosingReversion met `maxlen=5000`) bouwen hun eigen history, maar de chart toont maar 100 candles. | [backend/engine.py](backend/engine.py):117 |
| 🟡 | **Streepcandles bij live feed** — yfinance geeft voor lopende minuutcandles open=close (alleen close beschikbaar). Dit geeft "streep" candles op de chart. | [data/yfinance_feed.py](data/yfinance_feed.py) |
| 🟢 | **Annotatie buiten viewport** — `x=1.01` voor SL/TP labels in de chart kan op smalle schermen buiten het zichtbare gebied vallen. | [streamlit_app.py](streamlit_app.py):79 |
| 🟢 | **Ticker-validatie ontbreekt** — Geen feedback bij ongeldige ticker; engine crasht en toont generic error. | [streamlit_app.py](streamlit_app.py):187 |

---

## UI / UX verbeteringen

| Prio | Item |
|------|------|
| 🔴 | **Prev close invoerveld in UI** — Nu alleen via config.yaml; elke dag handmatig aanpassen is onpraktisch. Toevoegen als number_input in sidebar, met optie "Auto ophalen via yfinance". |
| 🟡 | **Setup-parameters aanpasbaar in UI** — tp_ratio, vol_min, sl_buffer etc. nu alleen via config.yaml. Expandable sectie per setup in sidebar. |
| 🟡 | **Notificatie bij nieuw signaal** — Geen geluid of browser-alert bij setup-signaal. `st.toast()` of `st.balloons()` als quick win; later echte browser-notificatie. |
| 🟡 | **Signalen exporteerbaar** — CSV-download knop voor de signalenlijst (entry, SL, TP, R/R, turbo-waarden). |
| 🟡 | **Turbo-calculator R/R op de chart** — R/R ratio wordt al berekend in het calculator-blok maar niet als annotatie op de chart getoond. |
| 🟡 | **Kleurcodering R/R** — R/R < 1.5 rood tonen, 1.5-2.0 geel, > 2.0 groen in de turbo-calculator. |
| 🟢 | **Setup-selectie tonen in chart-titel** — Nu alleen in de status-caption; ook in de chart-titel of als watermark. |
| 🟢 | **Zoom-knoppen verbeteren** — "Alles" toont alle 100 candles; 15m/30m/1u zijn relatief. Bij live data is "vandaag" nuttiger dan een vaste range. |
| 🟢 | **Sidebar inklapbaar per sectie** — Turbo-product (naam/ISIN) in een `st.expander` zodat sidebar compacter is. |

---

## Data & Feeds

| Prio | Item |
|------|------|
| 🔴 | **Auto prev_close via yfinance** — Bij start van live feed de vorige slotkoers automatisch ophalen: `yf.download(ticker, period="5d", interval="1d")` en de voorlaatste close pakken. |
| 🟡 | **Poll-interval configureerbaar** — Nu hardcoded 60s in yfinance_feed.py. Nuttig om dit via config of UI in te stellen (bijv. 30s voor snellere respons). |
| 🟡 | **Candle-cache kwaliteit** — Cache laadt alleen als datum + ticker exact matchen. Overwegen of feed_mode ook als validatiecriterium wenselijk is (nu al gedaan) of juist niet (mock vs live door elkaar). |
| 🟢 | **Multi-ticker support** — Architectuur maakt één ticker per engine mogelijk. Meerdere tickers vereist meerdere engine-instances of refactoring. |
| 💡 | **Saxo Bank API** (Fase 2) — Real-time Euronext data zonder 15 min vertraging. OAuth flow + streaming quotes. Credentials staan al in config.example.yaml. |

---

## Strategieën

| Prio | Item |
|------|------|
| 🔴 | **Vol_min in mock-feed aanpassen of mock configureerbaar maken** — MockSaxoFeed volume (100-2000) is te laag voor vol_min-checks. Oplossing: volume schaalbaar maken via constructor parameter, of vol_min in demo-modus verlagen. |
| 🟡 | **MorningGapFill `load_history_from_excel`** — Methode is geïmplementeerd maar wordt nergens aangeroepen vanuit de engine. Bedoeld voor historische ATR-seeding; koppelen aan UI of verwijderen. |
| 🟡 | **ATR-buffer uitbreiden naar andere setups** — ATR-based SL buffer alleen in MorningGapFill. MorningMomentum en OpeningRangeBreak gebruiken vaste lookback. |
| 🟡 | **Setup: tijdvenster reset per dag** — Na midnight moeten setups (signal_fired, first_open, detected_gap, range_built) automatisch gereset worden zonder engine herstarten. |
| 🟢 | **BreakoutStrategy: pd.concat performance** — Elke candle concat-t een nieuwe DataFrame. Bij 100+ candles merkbaar; vervangen door `deque` + directe berekening. |
| 💡 | **Backtesting module** — Historische candles (Excel of yfinance download) door een setup draaien en P/L per signaal rapporteren. |
| 💡 | **VWAP visualisatie** — ClosingReversion berekent VWAP intern maar toont die niet op de chart. Als extra lijn toevoegen. |

---

## Turbo Calculator

| Prio | Item |
|------|------|
| 🟡 | **Werkelijke barrier invoer** — Financing wordt berekend als `asml_price - turbo_price * ratio`. De werkelijke barrier (knock-out niveau) van het product wijkt hier soms van af. Veld toevoegen voor handmatige barrier-invoer. |
| 🟡 | **Ratio vrij invoerbaar** — Nu beperkt tot [1, 10, 100] via selectbox. Sommige turboproducten hebben andere ratios; vrij number_input toevoegen. |
| 🟡 | **Positie-calculator** — Aantal turbo's berekenen op basis van risicobedrag (bijv. max €100 verlies bij SL). Formule: `n = max_verlies / (turbo_entry - turbo_sl)`. |
| 🟢 | **Berekeningshistorie** — Vorige berekeningen onthouden in session_state zodat je kunt vergelijken. |
| 🟢 | **Kopieer-knop voor turbo-waarden** — Eén klik om SL/TP als tekst naar klembord te kopiëren (handig voor invoer in DeGiro). |

---

## Architectuur / Code kwaliteit

| Prio | Item |
|------|------|
| 🟡 | **Legacy code opruimen** — `main.py`, `ui/gui.py`, `ui/notifier.py` worden niet gebruikt door de Streamlit app. Verwijderen of duidelijk markeren als "legacy CLI". |
| 🟡 | **Twee strategy-directories samenvoegen** — `strategy/breakout.py` en `strategies/asml_setups.py` in dezelfde `strategies/` map. `strategy/` directory verwijderen. |
| 🟡 | **Unit tests** — Geen tests aanwezig. Minimaal: TurboTranslator berekeningen, strategy on_candle logica, candle-cache read/write. |
| 🟢 | **config.yaml naar config.example.yaml updaten** — `underlying_symbol: ASML` in voorbeeld maar UI gebruikt `ASML.AS`; ratio default is 10 in example maar 100 in engine default. |
| 🟢 | **Engine start-validatie** — Bij `engine.start()` valideren dat leverage > 0 en ratio in (1, 10, 100) voor de thread start, zodat fout in UI verschijnt ipv engine-thread crasht. |
| 💡 | **Async feed** — `time.sleep(3)` in Streamlit auto-refresh blokkeert de main thread. Langetermijn: asyncio of `st.fragment` met eigen refresh-interval. |

---

## Toekomstige fases

| Fase | Item |
|------|------|
| **Fase 2** | Saxo Bank API — real-time streaming quotes, geen 15 min vertraging |
| **Fase 2** | Automatische orderplaatsing via Saxo API (market/limit orders) |
| **Fase 3** | Historische backtesting met rapportage (win rate, avg R/R, drawdown) |
| **Fase 3** | Multi-ticker dashboard (ASML + andere Euronext largecaps) |
| **Fase 3** | Mobiele pushnotificaties (bijv. via Telegram bot of ntfy.sh) |

---

## Gedaan (recent)

- [x] **Aparte Turbo LONG / SHORT in sidebar** — naam, ISIN, leverage en ratio per product; long-waarden in long-zone, short-waarden in short-zone
- [x] **Config-driven defaults** — turbo_long / turbo_short in config.yaml → automatisch geladen in session_state bij eerste run; ASML Long 949 en ASML Short 1,453.1 als standaard
- [x] **Previous Day Box als default setup** — demo_setup: prev_day_box, ticker default ASML.AS
- [x] **Box header: Low | Mid | High** — turbo-prijzen bij Low (Long) en High (Short); mid toont beide turbo-prijzen
- [x] **Fix: config-defaults overschreven lege session_state niet** — conditie gewijzigd van `not in session_state` naar `_v and not session_state.get(_k)`; defaults laden nu ook als sleutel leeg is vanuit vorige sessie
- [x] **Fix: Streamlit widget-conflict** — value= / index= verwijderd uit per-turbo number_input/selectbox; session_state is enige bron
- [x] Box Strategie sectie: prev-day H/L/M ophalen via yfinance, twee zones (LONG/SHORT) naast elkaar, turbo entry/SL/TP + R/R + financiering per zone
- [x] Live data via yfinance: configureerbare ticker + feed-modus (mock/live radio)
- [x] ASML entry → turbo entry via leverage × ratio (Niveau-blok)
- [x] Compactere UI: kleinere header, minder witruimte, signalen in Niveau-blok
- [x] Candle-cache: persistent over browser-refresh (datum + ticker validatie)
- [x] Turbo calculator: financing-aware SL/TP met R/R
- [x] 4 ASML-specifieke setups: Morning Gap Fill, Morning Momentum, Opening Range Break, Closing Reversion
- [x] Generieke Breakout setup
- [x] Sidebar: Turbo product naam + ISIN invoer
- [x] Fallback naar config.example.yaml als config.yaml ontbreekt (Streamlit Cloud)
- [x] Tijdzone-correctie yfinance: UTC → Europe/Amsterdam
