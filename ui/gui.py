"""Simple tkinter GUI for local testing of ASML trading app."""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import queue


class ConfigUI:
    """Tkinter GUI to configure turbo leverage and entry price before running."""

    def __init__(self, config_dict):
        """Initialize with current config values."""
        self.config_dict = config_dict
        # Defaults for the start screen per user request
        self.leverage = config_dict.get("turbo", {}).get("leverage", 3.50)
        # Show turbo price default on start screen
        self.turbo_entry = config_dict.get("turbo", {}).get("default_price", 3.50)
        # ratio default set to 100
        self.ratio = config_dict.get("turbo", {}).get("ratio", 100)
        self.setup = config_dict.get("demo_setup", "morning_gap")
        self.result = None  # will be set when user clicks "Start"

        self.window = tk.Tk()
        self.window.title("ASML Trading App - Config")
        # Make window larger so all controls fit comfortably
        self.window.geometry("780x560")
        self.build_ui()

    def build_ui(self):
        """Build the GUI layout."""
        frame = ttk.Frame(self.window, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        # Title
        title = ttk.Label(frame, text="ASML Trading Setup", font=("Arial", 14, "bold"))
        title.pack(pady=10)

        # Setup selector
        ttk.Label(frame, text="Trading Setup:").pack(anchor=tk.W, pady=(10, 5))
        self.setup_var = tk.StringVar(value=self.setup)
        setups = ["morning_gap", "breakout"]
        setup_dropdown = ttk.Combobox(frame, textvariable=self.setup_var, values=setups, state="readonly")
        setup_dropdown.pack(fill=tk.X, pady=(0, 15))

        # Ratio selector (1, 10, 100)
        ttk.Label(frame, text="Turbo Ratio (1 / 10 / 100):").pack(anchor=tk.W, pady=(10, 5))
        self.ratio_var = tk.StringVar(value=str(self.ratio))
        ratio_dropdown = ttk.Combobox(frame, textvariable=self.ratio_var, values=["1", "10", "100"], state="readonly")
        ratio_dropdown.pack(fill=tk.X, pady=(0, 15))

        # Turbo Leverage
        ttk.Label(frame, text="Turbo Leverage (3.00 - 4.00):").pack(anchor=tk.W, pady=(10, 5))
        self.leverage_var = tk.DoubleVar(value=self.leverage)
        leverage_entry = ttk.Entry(frame, textvariable=self.leverage_var, width=15)
        leverage_entry.pack(anchor=tk.W, pady=(0, 15))

        # Turbo Entry Price
        ttk.Label(frame, text="Turbo Price (two decimals):").pack(anchor=tk.W, pady=(10, 5))
        self.turbo_entry_var = tk.DoubleVar(value=self.turbo_entry)
        turbo_entry_field = ttk.Entry(frame, textvariable=self.turbo_entry_var, width=15)
        turbo_entry_field.pack(anchor=tk.W, pady=(0, 20))

        # Buttons
        # Place buttons in a bottom bar so they're always visible
        button_frame = ttk.Frame(self.window, padding=(10, 8))
        button_frame.pack(side=tk.BOTTOM, fill=tk.X)

        start_btn = ttk.Button(button_frame, text="Start Monitor", command=self.on_start)
        start_btn.pack(side=tk.LEFT, padx=8)

        # Test Signal button: open a small dialog to run a translation preview
        test_btn = ttk.Button(button_frame, text="Test Signal", command=self.on_test_signal)
        test_btn.pack(side=tk.LEFT, padx=8)

        cancel_btn = ttk.Button(button_frame, text="Cancel", command=self.on_cancel)
        cancel_btn.pack(side=tk.LEFT, padx=8)

    def on_start(self):
        """Validate and start the app."""
        try:
            lev = self.leverage_var.get()
            if not (3.00 <= lev <= 4.00):
                messagebox.showerror("Invalid Leverage", "Leverage must be between 3.00 and 4.00.")
                return

            entry = self.turbo_entry_var.get()
            if entry <= 0:
                messagebox.showerror("Invalid Price", "Entry price must be positive.")
                return

            # round to 2 decimals
            lev = round(lev, 2)
            entry = round(entry, 2)
            try:
                ratio = int(self.ratio_var.get())
            except Exception:
                messagebox.showerror("Invalid Ratio", "Ratio must be one of 1, 10, 100")
                return

            self.result = {
                "leverage": lev,
                "turbo_entry": entry,
                "ratio": ratio,
                "setup": self.setup_var.get(),
            }
            self.window.quit()
        except tk.TclError as e:
            messagebox.showerror("Input Error", f"Invalid input: {e}")

    def on_cancel(self):
        """Cancel and exit."""
        self.window.quit()

    def show(self):
        """Show the GUI and return the result (or None if canceled)."""
        self.window.mainloop()
        self.window.destroy()
        return self.result

    def on_test_signal(self):
        """Open a dialog to input ASML price/SL/TP and display translated turbo values."""
        try:
            dlg = tk.Toplevel(self.window)
            dlg.title("Test Signal")
            dlg.geometry("360x260")

            frame = ttk.Frame(dlg, padding=10)
            frame.pack(fill=tk.BOTH, expand=True)

            # Side
            ttk.Label(frame, text="Side:").grid(row=0, column=0, sticky=tk.W)
            side_var = tk.StringVar(value="LONG")
            side_box = ttk.Combobox(frame, textvariable=side_var, values=["LONG", "SHORT"], state="readonly", width=10)
            side_box.grid(row=0, column=1, sticky=tk.W)

            # ASML price
            ttk.Label(frame, text="ASML Price:").grid(row=1, column=0, sticky=tk.W)
            asml_var = tk.DoubleVar(value=self.config_dict.get("demo_prev_close", 1209.0))
            asml_entry = ttk.Entry(frame, textvariable=asml_var)
            asml_entry.grid(row=1, column=1, sticky=tk.W)

            # SL
            ttk.Label(frame, text="SL:").grid(row=2, column=0, sticky=tk.W)
            sl_var = tk.DoubleVar(value=round(asml_var.get() - 9.0, 2))
            sl_entry = ttk.Entry(frame, textvariable=sl_var)
            sl_entry.grid(row=2, column=1, sticky=tk.W)

            # TP
            ttk.Label(frame, text="TP:").grid(row=3, column=0, sticky=tk.W)
            tp_var = tk.DoubleVar(value=round(asml_var.get() + 26.0, 2))
            tp_entry = ttk.Entry(frame, textvariable=tp_var)
            tp_entry.grid(row=3, column=1, sticky=tk.W)

            # Run button
            def run_test():
                try:
                    side = side_var.get()
                    asml = float(asml_var.get())
                    sl = float(sl_var.get())
                    tp = float(tp_var.get())
                    # Gather current GUI inputs for turbo price / ratio / leverage
                    try:
                        lev = float(self.leverage_var.get())
                    except Exception:
                        lev = self.leverage
                    try:
                        turbo_price = float(self.turbo_entry_var.get())
                    except Exception:
                        turbo_price = self.turbo_entry
                    try:
                        ratio = int(self.ratio_var.get())
                    except Exception:
                        ratio = int(self.ratio)

                    # Lazy import translator to avoid circular deps
                    from turbo.translate import TurboTranslator
                    from strategies.asml_setups import MorningGapFill

                    t = TurboTranslator({"leverage": lev})
                    signal = {"side": side, "entry": asml, "sl": sl, "tp": tp}
                    res = t.translate(signal, asml_price=asml, turbo_price=turbo_price, ratio=ratio)

                    # Attempt to compute ATR from workspace Excel file if present
                    atr_value = None
                    suggested_buffer = None
                    # parameters for buffer: k and min_floor
                    k = self.config_dict.get("atr_buffer_k", 0.30)
                    min_floor = self.config_dict.get("atr_min_buffer", 0.20)
                    # look for the known filename in workspace
                    import os, pandas as _pd
                    ws_path = os.path.join(os.getcwd(), "ASML_OHLCL_2_tm_13_FEB_2026.xlsx")
                    try:
                        if os.path.exists(ws_path):
                            df = _pd.read_excel(ws_path, engine='openpyxl')
                            # find first row with datetime-like in first column
                            start_idx = None
                            for i, v in enumerate(df.iloc[:, 0].values):
                                if _pd.notna(v):
                                    s = str(v)
                                    if any(ch.isdigit() for ch in s) and ("-" in s or ":" in s):
                                        start_idx = i
                                        break
                            if start_idx is not None:
                                data = df.iloc[start_idx:].copy()
                                cols = list(data.columns)
                                # map: time, close, high, low, open, volume
                                data = data.rename(columns={
                                    cols[0]: 'time', cols[1]: 'close', cols[2]: 'high', cols[3]: 'low', cols[4]: 'open', cols[5]: 'volume'
                                })
                                data['time'] = _pd.to_datetime(data['time'], utc=True, errors='coerce')
                                for c in ['open','high','low','close']:
                                    data[c] = _pd.to_numeric(data[c], errors='coerce')
                                data = data.dropna(subset=['time','open','high','low','close'])
                                # compute TRs
                                highs = data['high'].values
                                lows = data['low'].values
                                closes = data['close'].values
                                trs = []
                                for i in range(1, len(closes)):
                                    tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
                                    trs.append(tr)
                                if len(trs) >= 14:
                                    atr = sum(trs[:14]) / 14.0
                                    for tr in trs[14:]:
                                        atr = (atr * (14 - 1) + tr) / 14.0
                                    atr_value = round(atr, 6)
                                    suggested_buffer = max(min_floor, round(k * atr_value, 4))
                    except Exception:
                        atr_value = None

                    # Format message with turbo translation and ATR/buffer if available
                    parts = []
                    if res.get("turbo_sl_price") is not None and res.get("turbo_tp_price") is not None:
                        parts.append(f"Turbo Entry: {res.get('turbo_price'):.2f}")
                        parts.append(f"Turbo SL: {res.get('turbo_sl_price'):.2f}")
                        parts.append(f"Turbo TP: {res.get('turbo_tp_price'):.2f}")
                        parts.append(f"Financing: {res.get('financing')}")
                        parts.append(f"Ratio: {res.get('ratio')}")
                    else:
                        parts.append(f"Turbo distances: SL {res.get('turbo_sl_distance')}, TP {res.get('turbo_tp_distance')}")

                    if atr_value is not None:
                        parts.append(f"ATR(14) [5-min]: {atr_value:.4f}")
                    if suggested_buffer is not None:
                        parts.append(f"Suggested SL buffer: {suggested_buffer:.4f} (k={k}, min={min_floor})")

                    messagebox.showinfo("Test Result", "\n".join(parts), parent=dlg)
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to run test: {e}", parent=dlg)

            run_btn = ttk.Button(frame, text="Run Test", command=run_test)
            run_btn.grid(row=4, column=0, pady=(10, 0))

            close_btn = ttk.Button(frame, text="Close", command=dlg.destroy)
            close_btn.grid(row=4, column=1, pady=(10, 0))

            # make grid spacing nicer
            for i in range(4):
                frame.grid_rowconfigure(i, pad=6)
            frame.grid_columnconfigure(1, weight=1)

        except Exception as e:
            messagebox.showerror("Error", f"Unable to open test dialog: {e}")


class StatusWindow:
    """Status window showing "Running..." and live signal log."""

    def __init__(self, config_dict):
        """Initialize the status window."""
        self.config_dict = config_dict
        self.running = True
        self.signal_queue = queue.Queue()

        self.window = tk.Tk()
        self.window.title("ASML Trading App - Monitor")
        self.window.geometry("700x500")
        self.window.protocol("WM_DELETE_WINDOW", self.on_close)
        self.build_ui()

    def build_ui(self):
        """Build the status window layout."""
        frame = ttk.Frame(self.window, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        # Status bar at top
        status_frame = ttk.Frame(frame)
        status_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(status_frame, text="Status:", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        self.status_label = ttk.Label(status_frame, text="🟢 Running...", foreground="green", font=("Arial", 10))
        self.status_label.pack(side=tk.LEFT, padx=5)

        # Signal log title
        ttk.Label(frame, text="Signal Log:", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(10, 5))

        # Signal table (Treeview)
        cols = (
            "time",
            "setup",
            "side",
            "asml_entry",
            "sl",
            "tp",
            "turbo_entry",
            "turbo_sl",
            "turbo_tp",
            "financing",
            "ratio",
            "lev",
        )
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", height=18)
        headings = {
            "time": "Time",
            "setup": "Setup",
            "side": "Side",
            "asml_entry": "ASML Entry",
            "sl": "SL",
            "tp": "TP",
            "turbo_entry": "Turbo Entry",
            "turbo_sl": "Turbo SL",
            "turbo_tp": "Turbo TP",
            "financing": "Financing",
            "ratio": "Ratio",
            "lev": "Lev",
        }
        for c in cols:
            self.tree.heading(c, text=headings[c])
            if c in ("time", "side", "ratio", "lev"):
                self.tree.column(c, width=70, anchor=tk.CENTER)
            elif c == "setup":
                self.tree.column(c, width=180, anchor=tk.W)
            else:
                self.tree.column(c, width=100, anchor=tk.E)

        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.LEFT, fill=tk.Y)

        # Stop button
        button_frame = ttk.Frame(frame)
        button_frame.pack(fill=tk.X, pady=10)

        self.stop_btn = ttk.Button(button_frame, text="Stop Monitor", command=self.on_stop)
        self.stop_btn.pack(side=tk.RIGHT, padx=5)

        # Start polling for signals
        self.poll_queue()

    def add_signal(self, message):
        """Add a textual signal message to the queue (backcompat).

        Prefer `add_signal_struct` for structured data.
        """
        self.signal_queue.put({"_message": str(message)})

    def add_signal_struct(self, data: dict):
        """Add structured signal data (dict) to the queue.

        Expected keys: setup, side, asml_entry, sl, tp, turbo_entry, turbo_sl, turbo_tp, financing, ratio, lev
        """
        self.signal_queue.put(data)

    def poll_queue(self):
        """Poll the signal queue and update the log."""
        try:
            while True:
                item = self.signal_queue.get_nowait()
                # If it's a dict with structured fields, insert into tree
                if isinstance(item, dict):
                    if "_message" in item:
                        import time as _time
                        ts = _time.strftime("%H:%M:%S")
                        self.tree.insert("", "end", values=(ts, item.get("_message"), "", "", "", "", "", "", "", "", "", ""))
                    else:
                        import time as _time
                        ts = _time.strftime("%H:%M:%S")
                        vals = (
                            ts,
                            item.get("setup", ""),
                            item.get("side", ""),
                            f"{item.get('asml_entry', '')}",
                            f"{item.get('sl', '')}",
                            f"{item.get('tp', '')}",
                            f"{item.get('turbo_entry', '')}",
                            f"{item.get('turbo_sl', '')}",
                            f"{item.get('turbo_tp', '')}",
                            f"{item.get('financing', '')}",
                            f"{item.get('ratio', '')}",
                            f"{item.get('lev', '')}",
                        )
                        self.tree.insert("", "end", values=vals)
                else:
                    import time as _time
                    ts = _time.strftime("%H:%M:%S")
                    self.tree.insert("", "end", values=(ts, str(item), "", "", "", "", "", "", "", "", "", ""))
        except queue.Empty:
            pass

        # Re-schedule this method
        if self.running:
            self.window.after(100, self.poll_queue)

    def on_stop(self):
        """Stop monitoring."""
        self.running = False
        self.status_label.config(text="🔴 Stopped", foreground="red")
        self.stop_btn.config(state=tk.DISABLED)

    def on_close(self):
        """Handle window close."""
        self.running = False
        self.window.quit()

    def mainloop(self):
        """Run the status window event loop."""
        try:
            self.window.mainloop()
        except Exception:
            pass

    def destroy(self):
        """Destroy the window."""
        try:
            self.window.destroy()
        except Exception:
            pass

    def is_running(self):
        """Check if the monitor should keep running."""
        return self.running
