class Notifier:
    def __init__(self, status_window=None):
        """Initialize notifier with optional GUI status window."""
        self.status_window = status_window

    def print_signal(self, signal, turbo_vals=None):
        side = signal.get("side")
        entry = signal.get("entry")
        sl = signal.get("sl")
        tp = signal.get("tp")
        setup_name = signal.get("meta", {}).get("setup_name", "Unknown Setup")

        turbo_sl = "-"
        turbo_tp = "-"
        lev = None
        turbo_entry_price = None
        turbo_sl_price = None
        turbo_tp_price = None
        if turbo_vals:
            # Legacy distance fields
            turbo_sl = turbo_vals.get("turbo_sl_distance")
            turbo_tp = turbo_vals.get("turbo_tp_distance")
            # Reporting leverage
            lev = turbo_vals.get("leverage")
            # Absolute turbo price fields (new translator may use either key)
            turbo_entry_price = turbo_vals.get("turbo_entry_price") or turbo_vals.get("turbo_price")
            turbo_sl_price = turbo_vals.get("turbo_sl_price")
            turbo_tp_price = turbo_vals.get("turbo_tp_price")

        # Print in requested format with setup name
        base = f"[{setup_name}] [{side}] Entry: {entry}, SL: {sl}, TP: {tp}"
        turbo_part = f"Turbo SL: {turbo_sl}, TP: {turbo_tp}"
        # If absolute turbo prices available, show them instead (accept either field name)
        if turbo_sl_price is not None and turbo_tp_price is not None:
            # turbo_entry_price may be None if translator used 'turbo_price' key
            entry_display = turbo_entry_price if turbo_entry_price is not None else turbo_vals.get("turbo_price")
            if entry_display is not None:
                turbo_part = (
                    f"Turbo Entry: {entry_display:.2f}, SL: {turbo_sl_price:.2f}, TP: {turbo_tp_price:.2f}"
                )
            else:
                turbo_part = f"Turbo SL Price: {turbo_sl_price:.2f}, TP Price: {turbo_tp_price:.2f}"
        msg = f"{base} | {turbo_part}"
        if lev:
            msg += f" | Turbo lev: {lev:.2f}"
        
        # Print to terminal
        print(msg)
        
        # Also send structured data to GUI if available
        if self.status_window:
            payload = {
                "setup": setup_name,
                "side": side,
                "asml_entry": entry,
                "sl": sl,
                "tp": tp,
                "turbo_entry": turbo_entry_price,
                "turbo_sl": turbo_sl_price,
                "turbo_tp": turbo_tp_price,
                "financing": turbo_vals.get("financing") if turbo_vals else None,
                "ratio": turbo_vals.get("ratio") if turbo_vals else None,
                "lev": turbo_vals.get("leverage") if turbo_vals else None,
            }
            try:
                self.status_window.add_signal_struct(payload)
            except Exception:
                # fallback to plain string when structured insertion fails
                self.status_window.add_signal(msg)
