# Claude Code — Werkinstructies voor dit project

## Bij elke sessie
- Lees altijd eerst het geheugenbestand: `C:\Users\cmali\.claude\projects\c--DEV-Prive-asml-trading-app\memory\MEMORY.md`

## Backlog / openstaande taken

### 1. Gedeelde yfinance fetcher
`streamlit_app.py`, `hl_tranche.py` en `yfinance_feed.py` hebben elk eigen MultiIndex-handling.
Oplossing: `data/fetcher.py` met `fetch_daily()` en `fetch_intraday()`.

### 2. Turbo-berekening centraliseren
Formule staat op 3+ plekken. Altijd `TurboTranslator` gebruiken, `_turbo_prijs()` in `hl_tranche.py` verwijderen.

### 3. Box strategy extraheren
`_fetch_box_levels()` en `_render_box_zone()` uit `streamlit_app.py` naar `turbo/box_strategy.py`.

---

## Na goedgekeurde wijzigingen
- Maak altijd een git commit na wijzigingen die door de gebruiker zijn goedgekeurd.
- Commit messages in het Nederlands.
- Gebruik `git user`: cmalinghotmail / cmaling@hotmail.com
- Push naar GitHub (remote `origin`, branch `main`).
