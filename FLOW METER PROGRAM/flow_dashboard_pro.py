import os
import csv
import time
import math
import random
import collections
import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import customtkinter as ctk
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import sys

# ---------------- CONFIG ----------------
LOGS_DIR = "logs"
HOUR_SUM_DIR = os.path.join(LOGS_DIR, "hourly_summary")
SIMULATE = True                # True = simulated data. Set False to plug real sensor code.
UPDATE_INTERVAL_MS = 1000      # sampling & logging interval
GRAPH_UPDATE_MS = 1000         # graph redraw interval
MAX_BUFFER_POINTS = 3600       # memory buffer for live (1 hour)
PLOT_WINDOW_SECONDS = 3600     # live sliding window (1 hour)
RECENT_TABLE_SIZE = 200        # number of recent rows to show in live table
# ----------------------------------------

os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(HOUR_SUM_DIR, exist_ok=True)


def get_log_file_path(dt=None):
    """Return path to today's CSV (creates folder/header if missing)."""
    if dt is None:
        dt = datetime.datetime.now()
    month_folder = dt.strftime("%Y-%m")
    folder = os.path.join(LOGS_DIR, month_folder)
    os.makedirs(folder, exist_ok=True)
    fp = os.path.join(folder, dt.strftime("%Y-%m-%d") + ".csv")
    if not os.path.exists(fp):
        with open(fp, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Timestamp", "Flow (SLPM)", "Total (NCM)", "Temperature (°C)", "Battery"])
    return fp


def append_log(flow, total, temp, batt_text):
    fp = get_log_file_path()
    with open(fp, "a", newline="") as f:
        w = csv.writer(f)
        w.writerow([datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    f"{flow:.2f}", f"{total:.3f}", f"{temp:.1f}", batt_text])


class FlowDashboard:
    def __init__(self, root):
        self.root = root
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # window
        self.root.title("MF5708 Flow Dashboard")
        self.root.attributes("-fullscreen", True)
        self.root.bind("<Escape>", lambda e: self.root.attributes("-fullscreen", False))

        # state
        self.running = True
        self.update_after_id = None
        self.graph_after_id = None
        self.mode = "live"  # "live", "day", "month"
        self.current_month = None
        self.current_dayfile = None

        # simulated sensor state
        self._sim_total_flow = 0.0
        self._sim_battery = 100.0
        self._sim_temp = 25.0

        # live buffers
        self.times = collections.deque(maxlen=MAX_BUFFER_POINTS)
        self.flows = collections.deque(maxlen=MAX_BUFFER_POINTS)
        self.totals = collections.deque(maxlen=MAX_BUFFER_POINTS)
        self.temps = collections.deque(maxlen=MAX_BUFFER_POINTS)

        # build UI
        self._build_ui()

        # start background loops
        self._load_months()
        self._schedule_update()
        self._schedule_graph()

    # ---------- UI ----------
    def _build_ui(self):
        # layout
        self.root.grid_columnconfigure(0, weight=2)
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        # Left panel: metrics + graph
        left = ctk.CTkFrame(self.root, corner_radius=8)
        left.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)
        # Cards row
        card_row = ctk.CTkFrame(left, fg_color="#1f2a44", corner_radius=6)
        card_row.grid(row=0, column=0, sticky="ew", padx=8, pady=(8,6))
        card_row.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.var_flow = tk.StringVar(self.root, "0.00")
        self.var_total = tk.StringVar(self.root, "0.000")
        self.var_temp = tk.StringVar(self.root, "25.0")
        self.var_batt = tk.StringVar(self.root, "100% (Good)")

        def make_card(parent, var, title):
            f = ctk.CTkFrame(parent, fg_color="#223153", corner_radius=6)
            ctk.CTkLabel(f, text=title, font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=8, pady=(6, 0))
            ctk.CTkLabel(f, textvariable=var, font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", padx=8, pady=(0, 8))
            return f

        make_card(card_row, self.var_flow, "Flow Rate (SLPM)").grid(row=0, column=0, padx=6, pady=6, sticky="nsew")
        make_card(card_row, self.var_total, "Total Flow (NCM)").grid(row=0, column=1, padx=6, pady=6, sticky="nsew")
        make_card(card_row, self.var_temp, "Temperature (°C)").grid(row=0, column=2, padx=6, pady=6, sticky="nsew")
        make_card(card_row, self.var_batt, "Battery").grid(row=0, column=3, padx=6, pady=6, sticky="nsew")

        # Graph panel
        graph_panel = ctk.CTkFrame(left, fg_color="#0f1724", corner_radius=6)
        graph_panel.grid(row=1, column=0, sticky="nsew", padx=8, pady=(6, 8))
        graph_panel.grid_rowconfigure(0, weight=1)
        graph_panel.grid_columnconfigure(0, weight=1)

        # matplotlib figure and axes
        self.fig, self.ax = plt.subplots(figsize=(8, 4))
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        self.ax.set_title("Live Flow / Total / Temp")
        self.ax.set_ylabel("Flow (SLPM) / Temp (°C)")
        self.ax.grid(alpha=0.25)

        self.line_flow, = self.ax.plot([], [], label="Flow (SLPM)", linewidth=2)
        self.line_total, = self.ax.plot([], [], label="Total (NCM)", linewidth=1.25)
        self.line_temp, = self.ax.plot([], [], label="Temp (°C)", linestyle="--", linewidth=1)
        self.ax.legend(loc="upper left")

        self.canvas = FigureCanvasTkAgg(self.fig, master=graph_panel)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

        # controls row
        ctrl = ctk.CTkFrame(left, fg_color="#101827", corner_radius=6)
        ctrl.grid(row=2, column=0, sticky="ew", padx=8, pady=(6, 8))
        ctrl.grid_columnconfigure((0, 1, 2, 3), weight=1)

        ctk.CTkButton(ctrl, text="Export PNG", command=self._export_graph).grid(row=0, column=0, padx=6, pady=6)
        ctk.CTkButton(ctrl, text="Load Live", command=self._switch_to_live).grid(row=0, column=1, padx=6, pady=6)
        ctk.CTkButton(ctrl, text="Toggle Fullscreen", command=lambda: self.root.attributes("-fullscreen", not self.root.attributes("-fullscreen"))).grid(row=0, column=2, padx=6, pady=6)
        ctk.CTkButton(ctrl, text="Exit", command=self._exit_now).grid(row=0, column=3, padx=6, pady=6)

        # Right panel: logs browser + table
        right = ctk.CTkFrame(self.root, corner_radius=8)
        right.grid(row=0, column=1, sticky="nsew", padx=12, pady=12)
        right.grid_rowconfigure(4, weight=1)
        right.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(right, text="Data Logs", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, sticky="w", padx=8, pady=(6, 6))

        # month listbox
        self.month_listbox = tk.Listbox(right, height=5, exportselection=False)
        self.month_listbox.grid(row=1, column=0, sticky="ew", padx=8)
        self.month_listbox.bind("<<ListboxSelect>>", lambda e: self._on_month_select())

        # day listbox
        self.day_listbox = tk.Listbox(right, height=6, exportselection=False)
        self.day_listbox.grid(row=2, column=0, sticky="ew", padx=8, pady=(6, 0))

        # load buttons
        btn_frame = ctk.CTkFrame(right)
        btn_frame.grid(row=3, column=0, sticky="ew", padx=8, pady=8)
        btn_frame.grid_columnconfigure((0, 1, 2), weight=1)
        ctk.CTkButton(btn_frame, text="Load Day", command=self._load_selected_day).grid(row=0, column=0, padx=6, pady=6)
        ctk.CTkButton(btn_frame, text="Load Month", command=self._load_selected_month).grid(row=0, column=1, padx=6, pady=6)
        ctk.CTkButton(btn_frame, text="Refresh List", command=self._load_months).grid(row=0, column=2, padx=6, pady=6)

        # table for rows
        self.tree = ttk.Treeview(right, columns=("Time", "Flow", "Total", "Temp", "Battery"), show="headings", height=14)
        for c in ("Time", "Flow", "Total", "Temp", "Battery"):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=110, anchor="center")
        self.tree.grid(row=4, column=0, sticky="nsew", padx=8, pady=(6, 8))
        sb = ttk.Scrollbar(right, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=sb.set)
        sb.grid(row=4, column=1, sticky="ns", pady=(6, 8))

    # ---------- Sensor read (SIMULATE or replace) ----------
    def _read_sensor(self):
        """Return (flow_slpm, total_ncm, temp_c, battery_text). Replace for real sensor."""
        if SIMULATE:
            t = time.time()
            flow = max(0.0, 5.0 + 3.0 * math.sin(t / 30.0) + random.uniform(-0.6, 0.6))
            self._sim_total_flow += flow * 0.001
            self._sim_battery = max(0.0, self._sim_battery - random.uniform(0.0005, 0.0025))
            if time.time() - getattr(self, "_last_temp_update", 0) > 5:
                self._sim_temp = 24.0 + random.uniform(-1.2, 1.2)
                self._last_temp_update = time.time()
            if self._sim_battery > 50:
                batt = f"{self._sim_battery:.0f}% (Good)"
            elif self._sim_battery > 20:
                batt = f"{self._sim_battery:.0f}% (Low)"
            else:
                batt = f"{self._sim_battery:.0f}% (Replace)"
            return round(flow, 2), round(self._sim_total_flow, 3), round(self._sim_temp, 1), batt
        else:
            # TODO: add real Modbus/serial reading here
            return 0.0, 0.0, 25.0, "100% (Good)"

    # ---------- Scheduling ----------
    def _schedule_update(self):
        if not self.running:
            return
        self._do_update()
        self.update_after_id = self.root.after(UPDATE_INTERVAL_MS, self._schedule_update)

    def _schedule_graph(self):
        if not self.running:
            return
        self._do_graph_update()
        self.graph_after_id = self.root.after(GRAPH_UPDATE_MS, self._schedule_graph)

    # main update: read sensor, update live buffers, update labels, save log
    def _do_update(self):
        flow, total, temp, batt_text = self._read_sensor()
        now = datetime.datetime.now()
        # append live buffers
        self.times.append(now)
        self.flows.append(flow)
        self.totals.append(total)
        self.temps.append(temp)
        # update card labels (live)
        if self.mode == "live":
            self.var_flow.set(f"{flow:.2f}")
            self.var_total.set(f"{total:.3f}")
            self.var_temp.set(f"{temp:.1f}")
            self.var_batt.set(batt_text)
            # log to CSV
            try:
                append_log(flow, total, temp, batt_text)
            except Exception:
                pass

            # update live table showing most recent rows
            self._update_live_table()

    def _update_live_table(self):
        # show most recent RECENT_TABLE_SIZE rows in tree
        try:
            for r in self.tree.get_children():
                self.tree.delete(r)
            items = list(zip(self.times, self.flows, self.totals, self.temps))
            tail = items[-RECENT_TABLE_SIZE:]
            for t, f, tot, te in tail:
                self.tree.insert("", tk.END, values=(t.strftime("%Y-%m-%d %H:%M:%S"), f"{f:.2f}", f"{tot:.3f}", f"{te:.1f}", "" ))
        except Exception as e:
            print("live table update error:", e, file=sys.stderr)

    # redraw graph depending on mode
    def _do_graph_update(self):
        """Draw a smooth scrolling real-time graph like the YouTube demo."""
        if self.mode != "live":
            return  # only scroll in live mode

        try:
            if not self.times:
                return

            # Only show the most recent 60 seconds
            window_seconds = 60
            now = datetime.datetime.now()
            cutoff = now - datetime.timedelta(seconds=window_seconds)

            xs, ys_flow, ys_total, ys_temp = [], [], [], []
            for t, f, tt, te in zip(self.times, self.flows, self.totals, self.temps):
                if t >= cutoff:
                    xs.append(t)
                    ys_flow.append(f)
                    ys_total.append(tt)
                    ys_temp.append(te)

            if not xs:
                return

            # Instead of clearing every time, just update lines
            self.ax.clear()
            self.ax.plot(xs, ys_flow, color="cyan", linewidth=2, label="Flow (SLPM)")
            self.ax.plot(xs, ys_total, color="lime", linewidth=1.5, label="Total (NCM)")
            self.ax.plot(xs, ys_temp, color="orange", linestyle="--", linewidth=1, label="Temp (°C)")

            # Scrolling window effect
            self.ax.set_xlim(cutoff, now)
            self.ax.set_ylim(0, max(max(ys_flow), max(ys_temp)) * 1.2)

            self.ax.set_title("Live Flow / Total / Temp (Last 60s)")
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
            self.ax.legend(loc="upper left")
            self.ax.grid(alpha=0.3)
            self.fig.autofmt_xdate()

            self.canvas.draw_idle()

        except Exception as e:
            print("graph update error:", e, file=sys.stderr)


    # ---------- Logs browser ----------
    def _load_months(self):
        self.month_listbox.delete(0, tk.END)
        try:
            months = sorted([d for d in os.listdir(LOGS_DIR)
                             if os.path.isdir(os.path.join(LOGS_DIR, d)) and d != "hourly_summary"])
            for m in months:
                self.month_listbox.insert(tk.END, m)
        except Exception:
            pass

    def _on_month_select(self):
        sel = self.month_listbox.curselection()
        self.day_listbox.delete(0, tk.END)
        self.current_month = None
        if not sel:
            return
        month = self.month_listbox.get(sel[0])
        self.current_month = month
        folder = os.path.join(LOGS_DIR, month)
        try:
            files = sorted([f for f in os.listdir(folder) if f.endswith(".csv")])
            for f in files:
                self.day_listbox.insert(tk.END, f)
            # ensure day list is focusable/receives clicks
            self.day_listbox.focus_set()
        except Exception:
            pass

    def _load_selected_day(self):
        # User must select both month and day, then click this button
        sel_m = self.month_listbox.curselection()
        sel_d = self.day_listbox.curselection()
        if not sel_m:
            messagebox.showinfo("Info", "Please select a month first.")
            return
        if not sel_d:
            messagebox.showinfo("Info", "Please select a day.")
            return
        month = self.month_listbox.get(sel_m[0])
        dayfile = self.day_listbox.get(sel_d[0])
        path = os.path.join(LOGS_DIR, month, dayfile)
        if not os.path.exists(path):
            messagebox.showerror("Error", f"File not found:\n{path}")
            return

        # switch mode
        self.mode = "day"
        self.current_dayfile = path
        # display table and plot hourly averages
        self._display_day_file(path, f"Day {dayfile}")

    def _display_day_file(self, path, label):
        # populate table with entire day CSV (per-second rows)
        try:
            for r in self.tree.get_children():
                self.tree.delete(r)
            times = []
            flows = []
            with open(path, "r") as f:
                rdr = csv.reader(f)
                next(rdr, None)
                for row in rdr:
                    if not row:
                        continue
                    # insert raw row into table
                    self.tree.insert("", tk.END, values=row)
                    try:
                        t = datetime.datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
                        times.append(t)
                        flows.append(float(row[1]))
                    except Exception:
                        pass

            # hourly aggregation
            hourly = {}
            for t, v in zip(times, flows):
                hour = t.replace(minute=0, second=0, microsecond=0)
                hourly.setdefault(hour, []).append(v)
            if hourly:
                keys = sorted(hourly.keys())
                avg = [sum(hourly[k]) / len(hourly[k]) for k in keys]
                self.ax.clear()
                self.ax.plot(keys, avg, marker="o", linewidth=2)
                self.ax.set_title(label + " — hourly avg")
                self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
                self.fig.autofmt_xdate()
                self.canvas.draw_idle()
        except Exception as e:
            print("display day error:", e, file=sys.stderr)

    def _load_selected_month(self):
        sel = self.month_listbox.curselection()
        if not sel:
            messagebox.showinfo("Info", "Please select a month.")
            return
        month = self.month_listbox.get(sel[0])
        folder = os.path.join(LOGS_DIR, month)
        files = sorted([os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".csv")])
        if not files:
            messagebox.showinfo("Info", "No CSV files for this month.")
            return

        # summarize per day (avg flow + total)
        days = []
        avg_flows = []
        totals = []
        for filepath in files:
            try:
                flows = []
                tots = []
                with open(filepath, "r") as fh:
                    rdr = csv.reader(fh)
                    next(rdr, None)
                    for r in rdr:
                        if not r: continue
                        flows.append(float(r[1])); tots.append(float(r[2]))
                if flows:
                    day_str = os.path.basename(filepath).replace(".csv", "")
                    days.append(datetime.datetime.strptime(day_str, "%Y-%m-%d"))
                    avg_flows.append(sum(flows) / len(flows))
                    totals.append(max(tots))
            except Exception:
                continue

        if not days:
            messagebox.showinfo("Info", "No valid data for month.")
            return

        # populate table with per-day summary
        for r in self.tree.get_children():
            self.tree.delete(r)
        for d, af, tf in zip(days, avg_flows, totals):
            self.tree.insert("", tk.END, values=(d.strftime("%Y-%m-%d"), f"{af:.2f}", f"{tf:.3f}", "-", "-"))

        # plot monthly summary
        self.ax.clear()
        self.ax.bar(days, totals, color="lightgreen", label="Total Flow (NCM)")
        self.ax.plot(days, avg_flows, color="blue", marker="o", label="Avg Flow (SLPM)")
        self.ax.set_title(f"Monthly Summary ({month})")
        self.ax.legend()
        self.fig.autofmt_xdate()
        self.canvas.draw_idle()
        self.mode = "month"

    # ---------- Live / refresh ----------
    def _switch_to_live(self):
        """Switch UI back to live streaming mode and show immediate real-time data & live table."""
        self.mode = "live"
        self.current_dayfile = None
        # clear tree then populate recent live items immediately
        self._update_live_table()
        # live graph will appear automatically on next _do_graph_update call

    # ---------- Hourly summary writer (optional) ----------
    def _save_hourly_summary(self):
        """Write hourly summary CSV for today's log."""
        try:
            fp = get_log_file_path()
            if not os.path.exists(fp):
                return
            hourly = {}
            with open(fp, "r") as f:
                rdr = csv.reader(f)
                next(rdr, None)
                for r in rdr:
                    if not r: continue
                    try:
                        t = datetime.datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S")
                        key = t.replace(minute=0, second=0, microsecond=0)
                        hourly.setdefault(key, []).append(float(r[1]))
                    except Exception:
                        pass
            if not hourly:
                return
            out = []
            for k in sorted(hourly.keys()):
                out.append((k.strftime("%Y-%m-%d %H:00"), f"{(sum(hourly[k]) / len(hourly[k])):.2f}"))
            fname = os.path.join(HOUR_SUM_DIR, datetime.datetime.now().strftime("%Y-%m-%d_hourly.csv"))
            with open(fname, "w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["Hour", "Avg Flow (SLPM)"])
                for row in out:
                    w.writerow(row)
        except Exception as e:
            print("hourly save error:", e, file=sys.stderr)

    # ---------- Export graph ----------
    def _export_graph(self):
        fn = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG", "*.png")])
        if not fn:
            return
        try:
            self.fig.savefig(fn, dpi=150)
            messagebox.showinfo("Saved", f"Graph saved to: {fn}")
        except Exception as e:
            messagebox.showerror("Save error", str(e))

    # ---------- Exit / cleanup ----------
    def _cleanup(self):
        self.running = False
        try:
            if self.update_after_id:
                self.root.after_cancel(self.update_after_id)
            if self.graph_after_id:
                self.root.after_cancel(self.graph_after_id)
        except Exception:
            pass

    def _exit_now(self):
        self._cleanup()
        try:
            self.root.quit()
            self.root.destroy()
        finally:
            os._exit(0)


# ---------- Run ----------
if __name__ == "__main__":
    root = ctk.CTk()
    app = FlowDashboard(root)
    root.protocol("WM_DELETE_WINDOW", app._exit_now)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        app._exit_now()
