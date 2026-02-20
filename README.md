# ASML Trading App

A Python application that monitors ASML 1-minute candles, detects trading setups, and translates ASML share price SL/TP to turbo product levels.

## Features

- **Phase 1 (Signals only)**: Detects trading setups and prints terminal notifications with ASML and turbo SL/TP levels.
- **Mock and Real Data**: Mock feed (1-minute candles with random walk) for testing; ready for Saxo Bank API integration.
- **Trading Setups**: Morning Gap Fill and Breakout setups (more from `ASML_Trading_Setups_Details.xlsx` convertible on demand).
- **Turbo Translation**: Converts ASML SL/TP distances to turbo product distances using configurable leverage (3.00–4.00).
- **Multiple Launch Modes**: GUI (local testing), CLI args, env vars (VPS), or interactive prompts (backward compat).
- **Clean Modular Structure**: `data/`, `strategy/`, `strategies/`, `turbo/`, `ui/` for easy extension.

---

## Installation

### 1. Create Virtual Environment

```bash
cd c:\DEV\asml_trading_app
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 2. Install Dependencies

```bash
python -m pip install -r requirements.txt
```

---

## Usage

### Mode 1: Local GUI (for Testing)

Enable the GUI in `config.yaml`:

```yaml
gui_mode: true
```

Then run:

```bash
python main.py
```

A tkinter window appears where you can:
- Select the trading setup (Morning Gap Fill / Breakout)
- Enter turbo leverage (3.00–4.00, two decimals)
- Enter turbo entry price (two decimals)
- Click **Start Monitor** to run

### Mode 2: CLI Arguments (for VPS / Non-Interactive)

Run with command-line arguments:

```bash
python main.py --leverage 3.50 --turbo-entry 12.34 --setup morning_gap
```

**Available flags:**
- `--leverage FLOAT`: Turbo leverage (3.00–4.00). Defaults to `turbo.leverage` in config if not provided.
- `--turbo-entry FLOAT`: Turbo entry price (two decimals). If provided, app computes absolute turbo SL/TP.
- `--setup {morning_gap,breakout}`: Which trading setup to run.
- `--no-gui`: Force prompts mode even if `gui_mode` is enabled.

### Mode 3: Environment Variables (for VPS / Docker)

Set environment variables before running:

**PowerShell:**
```powershell
$env:ASML_LEVERAGE = "3.50"
$env:ASML_TURBO_ENTRY = "12.34"
$env:ASML_SETUP = "morning_gap"
python main.py
```

**Bash:**
```bash
export ASML_LEVERAGE=3.50
export ASML_TURBO_ENTRY=12.34
export ASML_SETUP=morning_gap
python main.py
```

### Mode 4: Interactive Prompts (Backward Compat)

Enable prompts in `config.yaml`:

```yaml
manual_turbo: true
manual_turbo_price: true
gui_mode: false
```

Run:

```bash
python main.py
```

The terminal will prompt you to enter leverage and turbo entry price (press Enter to skip).

---

## Configuration

Edit `config.yaml` to customize behavior:

```yaml
underlying_symbol: ASML

turbo:
  leverage: 3.50              # Default turbo leverage
  long_isin: "NL0000000000"   # Turbo LONG product ISIN
  short_isin: "NL0000000001"  # Turbo SHORT product ISIN

setups:
  morning_gap:
    gap_min: 10.0             # Minimum gap in EUR to trigger
    vol_min: 100              # Minimum volume
    tp_ratio: 1.5             # TP/SL ratio
  
  breakout:
    lookback: 20              # Candles to inspect for breakout
    vol_mult: 1.5             # Volume multiplier vs MA

demo_setup: morning_gap       # Which setup to run by default
demo_prev_close: 1210.0       # Previous day close (for Morning Gap)
demo_limit: 200               # Max candles to process (test runs)
demo_force_window: true       # Always-on time window (for testing)

# UI modes
manual_turbo: false           # Prompt for leverage at startup
manual_turbo_price: false     # Prompt for turbo entry price
gui_mode: false               # Launch tkinter GUI
```

---

## Output Example

When a setup trigger is detected:

```
[Morning Gap Fill] [LONG] Entry: 1205.2, SL: 1198.5, TP: 1215.8 | Turbo Entry: 3.45, SL: 3.36, TP: 3.52 | Turbo lev: 3.50
```

**Breakdown:**
- `[Morning Gap Fill]`: Trading setup name from Excel.
- `[LONG]`: Signal direction.
- `Entry: 1205.2, SL: 1198.5, TP: 1215.8`: ASML share price levels.
- `Turbo Entry: 3.45, SL: 3.36, TP: 3.52`: Turbo product levels (if turbo entry price provided).
- `Turbo lev: 3.50`: Turbo leverage used.

---

## Turbo SL/TP Calculation

The app translates ASML underlying distances to turbo distances:

$$d^{T}_{SL} = \frac{|E_{ASML} - SL_{ASML}|}{L}$$
$$d^{T}_{TP} = \frac{|TP_{ASML} - E_{ASML}|}{L}$$

where $L$ is the turbo leverage (3.00–4.00).

If you provide a turbo entry price $E^T$:
- **LONG**: $SL^T = E^T - d^T_{SL}$, $TP^T = E^T + d^T_{TP}$
- **SHORT**: $SL^T = E^T + d^T_{SL}$, $TP^T = E^T - d^T_{TP}$

---

## Project Structure

```
asml_trading_app/
├── main.py                    # Main entry point, CLI/env var/GUI logic
├── config.yaml                # Configuration file
├── requirements.txt           # Python dependencies
├── ASML_Trading_Setups_Details.xlsx  # Trading setup definitions (from Excel)
├── data/
│   └── mock_saxo.py          # Mock 1-minute candle feed
├── strategy/
│   └── breakout.py           # Breakout strategy (generic)
├── strategies/
│   └── asml_setups.py        # Morning Gap Fill and other ASML-specific setups
├── turbo/
│   └── translate.py          # Turbo SL/TP translator
└── ui/
    ├── notifier.py           # Terminal signal printer
    └── gui.py                # Tkinter GUI for config
```

---

## Next Steps (Phase 2)

- Integrate Saxo Bank API for live data and order preparation.
- Add manual order confirmation workflow.
- Support additional setups from the Excel workbook.
- Persist trade history to CSV.

---

## Notes

- **Leverage Range**: 3.00–4.00 (two decimals), as per your requirement.
- **Time Window**: The Morning Gap Fill setup respects a time window (default 08:05–09:00) but is configured to be "always-on" in demo mode for testing.
- **Mock Feed**: Random-walk price generation for testing. Replace with Saxo API for live trading.
- **Turbo Multiplier**: The app uses a simple linear approximation (distance / leverage). For production, fetch exact turbo multipliers from your broker.

---

## Troubleshooting

### GUI does not appear (VPS/headless environment)

Set `gui_mode: false` or use `--no-gui` flag. Use CLI args or env vars instead.

### "request cancelled" during execution

This indicates the execution environment doesn't support long-running processes. Use `demo_limit` to cap candles processed, or run locally.

### Prompts don't appear

Make sure `manual_turbo` or `manual_turbo_price` is `true` in config, and neither CLI args nor env vars are set.

---

Happy trading!
