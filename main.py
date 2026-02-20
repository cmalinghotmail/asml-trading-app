import time
import yaml
import argparse
import os
from data.mock_saxo import MockSaxoFeed
from strategy.breakout import BreakoutStrategy
from strategies.asml_setups import MorningGapFill
from turbo.translate import TurboTranslator
from ui.notifier import Notifier
from ui.gui import ConfigUI, StatusWindow


def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_cli_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="ASML Trading App")
    parser.add_argument("--leverage", type=float, help="Turbo leverage (3.00-4.00)")
    parser.add_argument("--turbo-entry", type=float, help="Turbo entry price (two decimals)")
    parser.add_argument("--ratio", type=float, help="Turbo ratio (1, 10, 100)")
    parser.add_argument("--setup", choices=["morning_gap", "breakout"], help="Trading setup to use")
    parser.add_argument("--no-gui", action="store_true", help="Disable GUI and use prompts instead")
    return parser.parse_args()


def get_leverage_from_env_or_cli():
    """Try to get leverage from env var or CLI, return None if not set."""
    # Check CLI first
    args = parse_cli_args()
    if args.leverage is not None:
        return round(args.leverage, 2)
    # Check env var
    env_val = os.getenv("ASML_LEVERAGE")
    if env_val:
        try:
            return round(float(env_val), 2)
        except ValueError:
            pass
    return None


def get_turbo_entry_from_env_or_cli():
    """Try to get turbo entry price from env var or CLI, return None if not set."""
    # Check CLI first
    args = parse_cli_args()
    if args.turbo_entry is not None:
        return round(args.turbo_entry, 2)
    # Check env var
    env_val = os.getenv("ASML_TURBO_ENTRY")
    if env_val:
        try:
            return round(float(env_val), 2)
        except ValueError:
            pass
    return None


def get_setup_from_env_or_cli():
    """Try to get setup from env var or CLI, return None if not set."""
    args = parse_cli_args()
    if args.setup:
        return args.setup
    env_val = os.getenv("ASML_SETUP")
    if env_val:
        return env_val
    return None


def get_ratio_from_env_or_cli():
    """Try to get turbo ratio from env var or CLI, return None if not set."""
    args = parse_cli_args()
    if args.ratio is not None:
        return float(args.ratio)
    env_val = os.getenv("ASML_RATIO")
    if env_val:
        try:
            return float(env_val)
        except ValueError:
            pass
    return None


def run_trading_loop(strategy, feed, turbo, notifier, manual_turbo_price, manual_ratio, demo_limit, status_window=None):
    """Run the main trading loop. Can be called from main thread or background thread."""
    try:
        for candle in feed.stream_candles(limit=demo_limit):
            # Check if we should stop (e.g., user clicked Stop button)
            if status_window and not status_window.is_running():
                break
                
            signal = strategy.on_candle(candle)
            if signal:
                # asml_price: use signal entry as trigger price
                asml_price = float(signal.get("entry"))
                turbo_vals = turbo.translate(signal, asml_price=asml_price, turbo_price=manual_turbo_price, ratio=manual_ratio)
                notifier.print_signal(signal, turbo_vals)
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("Stopped by user")
    finally:
        if status_window:
            status_window.on_stop()


def main():
    cfg = load_config()
    args = parse_cli_args()

    symbol = cfg.get("underlying_symbol", "ASML")
    feed = MockSaxoFeed(symbol=symbol)

    # Try CLI/env var support first for all parameters
    manual_leverage = get_leverage_from_env_or_cli()
    manual_turbo_price = get_turbo_entry_from_env_or_cli()
    manual_ratio = get_ratio_from_env_or_cli()
    setup_choice = get_setup_from_env_or_cli()
    gui_enabled = cfg.get("gui_mode", False)

    # If neither CLI/env vars provided, try GUI (if enabled and not --no-gui)
    if manual_leverage is None and manual_turbo_price is None and not args.no_gui and gui_enabled:
        print("Launching config GUI...")
        gui = ConfigUI(cfg)
        result = gui.show()
        if result:
            manual_leverage = result.get("leverage")
            manual_turbo_price = result.get("turbo_entry")
            manual_ratio = result.get("ratio")
            setup_choice = result.get("setup", setup_choice)
        else:
            print("GUI cancelled. Exiting.")
            return

    # If still no setup choice, use config default
    if not setup_choice:
        setup_choice = cfg.get("demo_setup", "breakout")

    # If still no leverage, try interactive prompt (backward compat)
    if manual_leverage is None and cfg.get("manual_turbo", False):
        def prompt_leverage():
            prompt = "Enter turbo leverage (3.00 - 4.00, two decimals) or blank to use config: "
            while True:
                try:
                    val = input(prompt).strip()
                except EOFError:
                    return None
                if val == "":
                    return None
                val = val.replace(',', '.')
                try:
                    f = float(val)
                except ValueError:
                    print("Invalid number format — use e.g. 3.25")
                    continue
                f = round(f, 2)
                if not (3.00 <= f <= 4.00):
                    print("Value out of allowed range (3.00 - 4.00). Try again.")
                    continue
                return f

        manual_leverage = prompt_leverage()

    # If still no turbo price, try interactive prompt
    if manual_turbo_price is None and cfg.get("manual_turbo_price", False):
        def prompt_turbo_price():
            prompt = "Enter turbo entry price (two decimals) or blank to skip: "
            while True:
                try:
                    val = input(prompt).strip()
                except EOFError:
                    return None
                if val == "":
                    return None
                val = val.replace(',', '.')
                try:
                    f = float(val)
                except ValueError:
                    print("Invalid number format — use e.g. 12.34")
                    continue
                f = round(f, 2)
                if f <= 0:
                    print("Price must be positive. Try again.")
                    continue
                return f

        manual_turbo_price = prompt_turbo_price()

    # Setup the strategy
    if setup_choice == "morning_gap":
        mg_cfg = cfg.get("setups", {}).get("morning_gap", {}).copy()
        if cfg.get("demo_force_window", True):
            mg_cfg["start"] = "00:00"
            mg_cfg["end"] = "23:59"
        strategy = MorningGapFill(mg_cfg)
        prev_close = cfg.get("demo_prev_close")
        if prev_close is not None:
            strategy.set_prev_close(prev_close)
    else:
        strategy = BreakoutStrategy(cfg.get("setups", {}).get("breakout", {}))

    # Setup turbo translator with optional manual leverage
    turbo_cfg = cfg.get("turbo", {}).copy()
    if manual_leverage is not None:
        turbo_cfg["leverage"] = manual_leverage
    turbo = TurboTranslator(turbo_cfg)
    
    demo_limit = cfg.get("demo_limit")

    # Create status window if GUI was used to configure
    status_window = None
    if gui_enabled and (manual_leverage is not None or manual_turbo_price is not None or manual_ratio is not None):
        status_window = StatusWindow(cfg)
        notifier = Notifier(status_window=status_window)
        
        # Run trading loop in background thread
        import threading
        trading_thread = threading.Thread(
            target=run_trading_loop,
            args=(strategy, feed, turbo, notifier, manual_turbo_price, manual_ratio, demo_limit, status_window),
            daemon=False,
        )
        trading_thread.start()
        
        # This will block until user closes the window or clicks Stop
        status_window.mainloop()
        status_window.destroy()
        trading_thread.join(timeout=2.0)
    else:
        # Non-GUI mode: run in main thread
        notifier = Notifier(status_window=None)
        print(f"Starting monitor for {symbol} (setup: {setup_choice}). Press Ctrl+C to stop.")
        run_trading_loop(strategy, feed, turbo, notifier, manual_turbo_price, manual_ratio, demo_limit, status_window=None)


if __name__ == "__main__":
    main()
