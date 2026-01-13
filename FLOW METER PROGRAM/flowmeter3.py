# MF5708 dashboard — no left panel, all controls on bottom, monthly plot at left, live view at right
import os
import sys
import csv
import time
import math
import json
import threading
import collections
import datetime
import platform
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import customtkinter as ctk
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Try to import serial library (pyserial)
try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False
    print("Warning: pyserial not installed. Run: pip install pyserial")

# Platform detection
IS_RASPBERRY_PI = platform.system() == "Linux" and os.path.exists("/proc/device-tree/model")
IS_WINDOWS = platform.system() == "Windows"
PLATFORM_NAME = "Raspberry Pi" if IS_RASPBERRY_PI else ("Windows" if IS_WINDOWS else platform.system())

DEBUG_MODE = False

# Paths / config
LOGS_DIR = "logs"
BASELINE_FILE = os.path.join(LOGS_DIR, "monthly_baseline.json")
os.makedirs(LOGS_DIR, exist_ok=True)

DEFAULT_SETTINGS = {
    "com_port": "",
    "baud_rate": 9600,
    "update_interval_ms": 1000,
    "graph_window_sec": 60,
}

MAX_BUFFER_POINTS = 3600

# Helpers
def get_available_ports():
    if not SERIAL_AVAILABLE:
        return []
    ports = [p.device for p in serial.tools.list_ports.comports()]
    if IS_RASPBERRY_PI:
        for p in ["/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyAMA0", "/dev/serial0"]:
            if p not in ports and os.path.exists(p):
                ports.append(p)
    return sorted(ports)

def load_monthly_baseline():
    try:
        if os.path.exists(BASELINE_FILE):
            with open(BASELINE_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        print("Baseline load error:", e, file=sys.stderr)
    return {"baseline": 0.0, "baseline_month": None, "timestamp": None}

def save_monthly_baseline(baseline_val, baseline_month):
    try:
        with open(BASELINE_FILE, "w") as f:
            json.dump({"baseline": baseline_val, "baseline_month": baseline_month, "timestamp": datetime.datetime.now().isoformat()}, f)
    except Exception as e:
        print("Baseline save error:", e, file=sys.stderr)

def get_log_file_path(dt=None):
    if dt is None:
        dt = datetime.datetime.now()
    month_folder = dt.strftime("%Y-%m")
    folder = os.path.join(LOGS_DIR, month_folder)
    os.makedirs(folder, exist_ok=True)
    fp = os.path.join(folder, dt.strftime("%Y-%m-%d") + ".csv")
    if not os.path.exists(fp):
        with open(fp, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Timestamp", "Flow (SLPM)", "Total (NCM)"])
    return fp

def append_log(flow, total):
    fp = get_log_file_path()
    try:
        with open(fp, "a", newline="") as f:
            w = csv.writer(f)
            w.writerow([datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), f"{flow:.2f}", f"{total:.3f}"])
    except Exception as e:
        print("Append log error:", e, file=sys.stderr)

# Sensor class (unchanged)
class MF5708Sensor:
    def __init__(self, port=None, baudrate=9600, slave_addr=1, timeout=1.0):
        self.port = port
        self.baudrate = baudrate
        self.slave_addr = slave_addr
        self.timeout = timeout
        self.serial = None
        self.connected = False
        self.last_error = ""
        self.last_total = None
        self.last_total_time = None

    def connect(self):
        if not SERIAL_AVAILABLE:
            self.last_error = "pyserial not installed"
            return False
        if not self.port:
            self.last_error = "No port specified"
            return False
        try:
            if DEBUG_MODE:
                print(f"[DEBUG] Connecting {self.port} @ {self.baudrate}")
            self.serial = serial.Serial(port=self.port, baudrate=self.baudrate, bytesize=serial.EIGHTBITS,
                                        parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                                        timeout=self.timeout)
            self.connected = True
            self.last_error = ""
            return True
        except Exception as e:
            self.last_error = str(e)
            self.connected = False
            if DEBUG_MODE:
                print("[DEBUG] Connect failed:", e)
            return False

    def disconnect(self):
        try:
            if self.serial and self.serial.is_open:
                self.serial.close()
            self.serial = None
            self.connected = False
            if DEBUG_MODE:
                print("[DEBUG] Disconnected")
        except Exception as e:
            if DEBUG_MODE:
                print("[DEBUG] Disconnect error:", e)
            self.connected = False

    def _calc_crc16(self, data):
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc

    def _build_read_request(self, start_reg, num_regs):
        msg = bytes([
            self.slave_addr,
            0x03,
            (start_reg >> 8) & 0xFF,
            start_reg & 0xFF,
            (num_regs >> 8) & 0xFF,
            num_regs & 0xFF
        ])
        crc = self._calc_crc16(msg)
        msg += bytes([crc & 0xFF, (crc >> 8) & 0xFF])
        return msg

    def _read_registers(self, start_reg, num_regs):
        if not self.connected or not self.serial:
            self.last_error = "Not connected"
            return None
        try:
            self.serial.reset_input_buffer()
            time.sleep(0.01)
            request = self._build_read_request(start_reg, num_regs)
            if DEBUG_MODE:
                print(f"[DEBUG] TX (hex): {' '.join(f'{b:02X}' for b in request)}")
            self.serial.write(request)
            self.serial.flush()
            expected_len = 3 + 2 * num_regs + 2
            response = bytearray()
            max_attempts = 12
            attempt = 0
            while len(response) < expected_len and attempt < max_attempts:
                time.sleep(0.04)
                available = self.serial.in_waiting
                if available > 0:
                    chunk = self.serial.read(available)
                    response.extend(chunk)
                    if DEBUG_MODE and len(chunk) > 0:
                        print(f"[DEBUG] Read {len(chunk)} bytes (total: {len(response)}/{expected_len})")
                attempt += 1
            if DEBUG_MODE:
                print(f"[DEBUG] Final received: {len(response)} bytes")
            if len(response) < expected_len:
                self.last_error = f"Incomplete response: {len(response)}/{expected_len}"
                return None
            data = response[:-2]
            recv_crc = response[-2] | (response[-1] << 8)
            calc_crc = self._calc_crc16(data)
            if recv_crc != calc_crc:
                self.last_error = "CRC mismatch"
                if DEBUG_MODE:
                    print(f"[DEBUG] CRC mismatch: expected {calc_crc:04X}, got {recv_crc:04X}")
                return None
            values = []
            for i in range(num_regs):
                hi = response[3 + i*2]
                lo = response[4 + i*2]
                values.append((hi << 8) | lo)
            return values
        except Exception as e:
            self.last_error = str(e)
            if DEBUG_MODE:
                print("[DEBUG] _read_registers exception:", e)
            return None

    def read_all(self):
        if DEBUG_MODE:
            print("\n[DEBUG] ========== READ ALL SENSOR VALUES ==========")
        regs = self._read_registers(0x0000, 16)
        if regs is None:
            return None
        try:
            flow = regs[3] / 1000.0
            primary_total = None
            try:
                primary_32 = (regs[5] << 16) | regs[6]
                primary_total = primary_32 / 1000.0
            except Exception:
                primary_total = None

            def plausible_val(v):
                return v is not None and v >= 0.0 and v <= 1e6 and not math.isclose(v, 0.0, abs_tol=1e-12)

            if DEBUG_MODE:
                print(f"[DEBUG] flow raw regs[3]={regs[3]}, flow={flow:.3f}")
                if primary_total is not None:
                    print(f"[DEBUG] primary candidate (regs[5]/6 BE): {primary_total:.6f}")

            selected = None
            now = time.time()

            if plausible_val(primary_total):
                if self.last_total is None:
                    selected = primary_total
                else:
                    dt = max(0.1, now - (self.last_total_time or now))
                    expected_inc = (flow * dt) / 60000.0
                    allowed_inc = max(0.01, expected_inc * 20.0 + 0.001)
                    if primary_total >= self.last_total - 0.0005 and primary_total <= self.last_total + allowed_inc:
                        selected = primary_total
                    else:
                        if primary_total <= 0.05:
                            selected = primary_total
                        else:
                            if DEBUG_MODE:
                                print(f"[DEBUG] primary candidate {primary_total:.6f} outside allowed range; fallback to scanning")
                            selected = None

            if selected is None:
                candidates = []
                n = len(regs)
                for i in range(n - 1):
                    hi = regs[i]; lo = regs[i+1]
                    candidates.append(((hi << 16) | lo) / 1000.0)
                    candidates.append(((lo << 16) | hi) / 1000.0)
                plausible = [v for v in candidates if plausible_val(v)]
                if DEBUG_MODE:
                    print(f"[DEBUG] total candidates (m3): {['{:.6f}'.format(c) for c in candidates]}")
                    print(f"[DEBUG] plausible totals: {['{:.6f}'.format(p) for p in plausible]}")
                if plausible:
                    if self.last_total is not None:
                        plausible_sorted = sorted(set(plausible))
                        eps = 0.0005
                        up_candidates = [p for p in plausible_sorted if p > self.last_total + eps]
                        if up_candidates:
                            selected = min(up_candidates)
                        else:
                            selected = min(plausible, key=lambda x: abs(x - self.last_total))
                    else:
                        selected = min(plausible)
                else:
                    total_32bit = (regs[0] << 16) | regs[1]
                    if total_32bit in (0,1):
                        total_32bit = (regs[4] << 16) | regs[5]
                    if total_32bit == 0:
                        total_32bit = (regs[6] << 16) | regs[7]
                    selected = total_32bit / 1000.0
                    if DEBUG_MODE:
                        print(f"[DEBUG] fallback total_32bit={total_32bit}, total={selected:.6f}")

            if selected is not None:
                if self.last_total is not None and selected < self.last_total - 0.5:
                    if DEBUG_MODE:
                        print(f"[DEBUG] Candidate decreased sharply ({selected:.6f} < {self.last_total:.6f}), keeping last_total.")
                    total = self.last_total
                else:
                    total = selected
                self.last_total = total
                self.last_total_time = now
            else:
                total = 0.0
                self.last_total = total
                self.last_total_time = now

            if DEBUG_MODE:
                print(f"[DEBUG] Selected Flow: {flow:.3f}, Total: {total:.6f}")
            return (flow, total, 0.0)
        except Exception as e:
            self.last_error = str(e)
            if DEBUG_MODE:
                print("[DEBUG] read_all parse error:", e)
            return None

# Logs window (unchanged)
class LogsWindow:
    def __init__(self, parent_dashboard):
        self.parent = parent_dashboard
        self.top = tk.Toplevel(self.parent.root)
        try:
            title = f"Data Logs - {PLATFORM_NAME}"
            self.top.title(title)
            if IS_RASPBERRY_PI:
                self.top.geometry("780x420"); self.top.minsize(480,320)
            else:
                self.top.geometry("900x600"); self.top.minsize(600,420)
            self.top.transient(self.parent.root)
            self._build_ui()
            self.load_months()
            self.parent.logs_win = self
            self.top.update_idletasks(); self.top.lift(); self.top.focus_force()
        except Exception as e:
            try: self.top.destroy()
            except Exception: pass
            self.parent.logs_win = None
            raise

    def _build_ui(self):
        self.top.grid_rowconfigure(3, weight=1)
        self.top.grid_columnconfigure(1, weight=1)
        lbl_m = tk.Label(self.top, text="Month:"); lbl_m.grid(row=0, column=0, sticky="w", padx=8, pady=(8,2))
        self.month_listbox = tk.Listbox(self.top, height=6, exportselection=False, bg="#ffffff"); self.month_listbox.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0,8))
        self.month_listbox.bind("<<ListboxSelect>>", lambda e: self.on_month_select())
        lbl_d = tk.Label(self.top, text="Day:"); lbl_d.grid(row=2, column=0, sticky="w", padx=8, pady=(4,2))
        self.day_listbox = tk.Listbox(self.top, height=8, exportselection=False, bg="#ffffff"); self.day_listbox.grid(row=3, column=0, sticky="nsew", padx=8, pady=(0,8))
        btn_frame = tk.Frame(self.top); btn_frame.grid(row=4, column=0, sticky="ew", padx=8, pady=6); btn_frame.grid_columnconfigure((0,1,2), weight=1)
        tk.Button(btn_frame, text="Load Day", command=self.load_selected_day).grid(row=0, column=0, padx=4)
        tk.Button(btn_frame, text="Load Month", command=self.load_selected_month).grid(row=0, column=1, padx=4)
        tk.Button(btn_frame, text="Refresh", command=self.load_months).grid(row=0, column=2, padx=4)
        table_frame = tk.Frame(self.top); table_frame.grid(row=0, column=1, rowspan=5, sticky="nsew", padx=8, pady=8)
        table_frame.grid_rowconfigure(0, weight=1); table_frame.grid_columnconfigure(0, weight=1)
        style = ttk.Style(); style.theme_use("clam")
        style.configure("Treeview", background="#ffffff", foreground="black", fieldbackground="#ffffff")
        style.configure("Treeview.Heading", background="#f0f0f0", foreground="black")
        self.tree = ttk.Treeview(table_frame, columns=("Time","Flow","Total"), show="headings", height=18)
        for c,w in [("Time",160),("Flow",100),("Total",110)]: self.tree.heading(c, text=c); self.tree.column(c, width=w, anchor="center")
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview); self.tree.configure(yscroll=sb.set); sb.grid(row=0, column=1, sticky="ns")

    def load_months(self):
        self.month_listbox.delete(0, tk.END)
        try:
            months = sorted([d for d in os.listdir(LOGS_DIR) if os.path.isdir(os.path.join(LOGS_DIR,d))])
            for m in months:
                self.month_listbox.insert(tk.END, m)
        except Exception:
            pass

    def on_month_select(self):
        sel = self.month_listbox.curselection(); self.day_listbox.delete(0, tk.END)
        if not sel: return
        month = self.month_listbox.get(sel[0]); folder = os.path.join(LOGS_DIR, month)
        try:
            files = sorted([f for f in os.listdir(folder) if f.endswith(".csv")])
            for f in files: self.day_listbox.insert(tk.END, f)
        except Exception:
            pass

    def load_selected_day(self):
        sel_m = self.month_listbox.curselection(); sel_d = self.day_listbox.curselection()
        if not sel_m: messagebox.showinfo("Info", "Please select a month first."); return
        if not sel_d: messagebox.showinfo("Info", "Please select a day."); return
        month = self.month_listbox.get(sel_m[0]); dayfile = self.day_listbox.get(sel_d[0])
        path = os.path.join(LOGS_DIR, month, dayfile)
        if not os.path.exists(path): messagebox.showerror("Error", f"File not found:\n{path}"); return
        self._display_csv_in_table(path); self.parent._display_day_file(path, f"Day: {dayfile}"); self.parent.mode = "day"; self.parent.current_dayfile = path

    def _display_csv_in_table(self, path):
        for r in self.tree.get_children(): self.tree.delete(r)
        try:
            with open(path, "r") as f:
                rdr = csv.reader(f); next(rdr,None)
                for row in rdr:
                    if not row: continue
                    if len(row)>=3: self.tree.insert("", tk.END, values=(row[0], row[1], row[2]))
                    else: self.tree.insert("", tk.END, values=row+[""]*(3-len(row)))
        except Exception as e:
            print("Error loading CSV to table:", e, file=sys.stderr)

    def load_selected_month(self):
        sel = self.month_listbox.curselection()
        if not sel: messagebox.showinfo("Info", "Please select a month."); return
        month = self.month_listbox.get(sel[0]); folder = os.path.join(LOGS_DIR,month)
        files = sorted([os.path.join(folder,f) for f in os.listdir(folder) if f.endswith(".csv")])
        if not files: messagebox.showinfo("Info","No CSV files for this month."); return
        days, avg_flows, totals = [],[],[]
        for filepath in files:
            try:
                flows,tots = [],[]
                with open(filepath,"r") as fh:
                    rdr = csv.reader(fh); next(rdr,None)
                    for r in rdr:
                        if not r: continue
                        flows.append(float(r[1])); tots.append(float(r[2]))
                if flows:
                    day_str = os.path.basename(filepath).replace(".csv","")
                    days.append(datetime.datetime.strptime(day_str,"%Y-%m-%d"))
                    avg_flows.append(sum(flows)/len(flows))
                    totals.append(max(tots))
            except Exception:
                continue
        if not days: messagebox.showinfo("Info","No valid data for month."); return
        parent_ax = self.parent.ax_month; parent_fig = self.parent.fig_month
        parent_ax.clear(); parent_ax.set_facecolor('#ffffff')
        parent_ax.bar(days, totals, color="#00a86b", alpha=0.8, label="Total Flow (m³)")
        parent_ax.plot(days, avg_flows, color="#007acc", marker="o", linewidth=1.6, label="Avg Flow (L/min)")
        parent_ax.set_title(f"Monthly Summary ({month})", color='black'); parent_ax.tick_params(colors='black', labelsize=8)
        parent_ax.legend(facecolor='#ffffff', edgecolor='#cccccc', fontsize=8); parent_ax.grid(alpha=0.2, color='#e6e6e6')
        for spine in parent_ax.spines.values(): spine.set_color('#cccccc')
        parent_fig.autofmt_xdate()
        try:
            self.parent.flow_line=None; self.parent.flow_marker=None; self.parent.flow_fill=None
        except Exception: pass
        self.parent.canvas_month.draw_idle(); self.parent.mode="month"

# Main dashboard
class FlowDashboard:
    def __init__(self, root):
        self.root = root
        ctk.set_appearance_mode("light"); ctk.set_default_color_theme("blue")
        self.root.configure(bg="#ffffff")
        self.root.title(f"MF5708 Flow Meter Dashboard - {PLATFORM_NAME}")
        if IS_RASPBERRY_PI:
            self.root.attributes("-fullscreen", True)
        else:
            self.root.geometry("1300x840"); self.root.minsize(1100,650)

        self.settings = DEFAULT_SETTINGS.copy()
        self.settings["com_port"] = self._auto_detect_port()

        # sensor
        self.sensor = MF5708Sensor()
        # state
        self.running = True; self.mode="live"; self.logs_win=None; self.current_dayfile=None
        self.latest_reading=(0.0,0.0,0.0); self.last_valid=(0.0,0.0)
        self.times = collections.deque(maxlen=MAX_BUFFER_POINTS); self.flows = collections.deque(maxlen=MAX_BUFFER_POINTS); self.totals = collections.deque(maxlen=MAX_BUFFER_POINTS)

        # baseline
        bl = load_monthly_baseline()
        self.monthly_baseline = float(bl.get("baseline",0.0))
        self.monthly_baseline_month = bl.get("baseline_month", None)
        ts = bl.get("timestamp"); self.baseline_ts = datetime.datetime.fromisoformat(ts) if ts else None
        self.daily_baseline = 0.0; self.daily_baseline_date = None

        # UI
        self._build_ui()

        # worker thread
        threading.Thread(target=self._sensor_worker, daemon=True).start()
        # loops
        self._schedule_update(); self._schedule_graph()

    def _auto_detect_port(self):
        ports = get_available_ports()
        if IS_RASPBERRY_PI:
            for p in ["/dev/ttyUSB0","/dev/ttyUSB1","/dev/ttyAMA0","/dev/serial0"]:
                if p in ports: return p
        return ports[0] if ports else ""

    def _build_ui(self):
        # root grid: row0 metrics, row1 main split (monthly | live), row2 bottom controls
        self.root.grid_rowconfigure(0, weight=0)
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_rowconfigure(2, weight=0)
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_columnconfigure(1, weight=1)

        # Metrics row (spans both columns)
        metrics_frame = ctk.CTkFrame(self.root, fg_color="#f8fafc", corner_radius=6)
        metrics_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=(8,6))
        metrics_frame.grid_columnconfigure((0,1,2), weight=1)
        metrics_frame.grid_columnconfigure(3, weight=0)

        metric_font = 11
        val_font = 18 if IS_RASPBERRY_PI else 20
        self.var_flow = tk.StringVar(self.root, "0.00 L/min")
        self.var_day = tk.StringVar(self.root, "0.000 m³")
        self.var_month = tk.StringVar(self.root, "0.000 m³")

        def mk_card(parent, var, title):
            f = ctk.CTkFrame(parent, fg_color="#ffffff", corner_radius=6)
            label = ctk.CTkLabel(f, text=title, font=ctk.CTkFont(size=metric_font))
            label.pack(anchor="w", padx=8, pady=(6,0))
            value = ctk.CTkLabel(f, textvariable=var, font=ctk.CTkFont(size=val_font, weight="bold"))
            value.pack(anchor="w", padx=8, pady=(2,8))
            return f

        mk_card(metrics_frame, self.var_flow, "Current").grid(row=0, column=0, padx=6, pady=8, sticky="nsew")
        mk_card(metrics_frame, self.var_day, "Total Today").grid(row=0, column=1, padx=6, pady=8, sticky="nsew")
        mk_card(metrics_frame, self.var_month, "Total This Month").grid(row=0, column=2, padx=6, pady=8, sticky="nsew")

        # Monthly plot (left column)
        month_frame = ctk.CTkFrame(self.root, fg_color="#ffffff", corner_radius=6)
        month_frame.grid(row=1, column=0, sticky="nsew", padx=(8,4), pady=(0,8))
        month_frame.grid_rowconfigure(0, weight=1)
        month_frame.grid_columnconfigure(0, weight=1)
        self.fig_month, self.ax_month = plt.subplots(figsize=(4.5,4.5), dpi=100)
        self.fig_month.patch.set_facecolor('#ffffff'); self.ax_month.set_facecolor('#ffffff')
        self.ax_month.xaxis.set_major_formatter(mdates.DateFormatter("%d"))
        self.canvas_month = FigureCanvasTkAgg(self.fig_month, master=month_frame)
        self.canvas_month.get_tk_widget().grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        # Live plot (right column)
        live_frame = ctk.CTkFrame(self.root, fg_color="#ffffff", corner_radius=6)
        live_frame.grid(row=1, column=1, sticky="nsew", padx=(4,8), pady=(0,8))
        live_frame.grid_rowconfigure(0, weight=1)
        live_frame.grid_columnconfigure(0, weight=1)
        self.fig_live, self.ax_live = plt.subplots(figsize=(8,4.5), dpi=100)
        self.fig_live.patch.set_facecolor('#ffffff'); self.ax_live.set_facecolor('#ffffff')
        self.ax_live.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        self.ax_live.set_ylabel("L/min")
        self.flow_line, = self.ax_live.plot([], [], color="#007acc", linewidth=2)
        self.flow_marker, = self.ax_live.plot([], [], 'o', color="#ff6b6b", markersize=6)
        self.flow_fill = None
        self.canvas_live = FigureCanvasTkAgg(self.fig_live, master=live_frame)
        self.canvas_live.get_tk_widget().grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        # Bottom control bar (spans both columns)
        bottom = ctk.CTkFrame(self.root, fg_color="#f0f4f8", corner_radius=6)
        bottom.grid(row=2, column=0, columnspan=2, sticky="ew", padx=8, pady=(6,12))
        bottom.grid_columnconfigure(0, weight=1)
        bottom.grid_columnconfigure(1, weight=1)
        bottom.grid_columnconfigure(2, weight=1)

        # Left: port + baseline controls
        left_controls = ctk.CTkFrame(bottom, fg_color="transparent")
        left_controls.grid(row=0, column=0, sticky="w", padx=8, pady=8)

        ports = get_available_ports()
        self.port_combo = ctk.CTkComboBox(left_controls, values=ports, width=150)
        self.port_combo.set(self.settings["com_port"] or (ports[0] if ports else "No port"))
        self.port_combo.pack(side="left", padx=(0,8))
        ctk.CTkButton(left_controls, text="⟳", width=36, height=28, command=self._refresh_ports).pack(side="left", padx=(0,8))
        self.connect_btn = ctk.CTkButton(left_controls, text="Connect", width=90, command=self._toggle_connection)
        self.connect_btn.pack(side="left")

        # Baseline small group under port controls
        baseline_group = ctk.CTkFrame(bottom, fg_color="transparent")
        baseline_group.grid(row=0, column=1, sticky="w", padx=8, pady=8)
        self.baseline_label = ctk.CTkLabel(baseline_group, text=f"{self.monthly_baseline:.3f} m³", font=ctk.CTkFont(size=11))
        self.baseline_label.pack(anchor="w", pady=(0,4))

        # create a simple tk.Frame as an inline row container (no bg param to avoid color errors)
        rowf = tk.Frame(baseline_group)
        rowf.pack(anchor="w")
        months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
        # instantiate combo/button with rowf as parent
        self.month_combo = ctk.CTkComboBox(rowf, values=months, width=120)
        self.month_combo.set(months[(datetime.datetime.now().month - 1) % 12])
        self.month_combo.pack(side="left", padx=(0,8))
        ctk.CTkButton(rowf, text="Set", width=60, command=self._set_baseline_for_selected_month).pack(side="left")

        # baseline actions
        ctk.CTkButton(baseline_group, text="Set Baseline Now", width=160, command=self._set_monthly_baseline_now).pack(anchor="w", pady=(6,2))
        ctk.CTkButton(baseline_group, text="Clear Manual Baseline", width=160, fg_color="#f59e0b", command=self._clear_manual_baseline).pack(anchor="w")

        # Middle: export / logs / exit
        mid_controls = ctk.CTkFrame(bottom, fg_color="transparent")
        mid_controls.grid(row=0, column=1, sticky="n", padx=8, pady=8)
        ctk.CTkButton(mid_controls, text="Export CSV", width=140, command=self._export_csv).pack(side="left", padx=6)
        ctk.CTkButton(mid_controls, text="Data Logs", width=140, command=self._open_logs_window).pack(side="left", padx=6)
        ctk.CTkButton(mid_controls, text="Exit", fg_color="#dc3545", width=140, command=self._exit_now).pack(side="left", padx=6)

        # Right: reboot / shutdown
        right_controls = ctk.CTkFrame(bottom, fg_color="transparent")
        right_controls.grid(row=0, column=2, sticky="e", padx=8, pady=8)
        def do_reboot():
            if messagebox.askyesno("Confirm Reboot", "Reboot the system now?"):
                try:
                    if IS_WINDOWS:
                        subprocess.Popen(["shutdown", "/r", "/t", "5"])
                    else:
                        subprocess.Popen(["sudo", "reboot"])
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to reboot:\n{e}")
        def do_shutdown():
            if messagebox.askyesno("Confirm Shutdown", "Shutdown the system now?"):
                try:
                    if IS_WINDOWS:
                        subprocess.Popen(["shutdown", "/s", "/t", "5"])
                    else:
                        subprocess.Popen(["sudo", "shutdown", "-h", "now"])
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to shutdown:\n{e}")
        ctk.CTkButton(right_controls, text="Reboot", fg_color="#f59e0b", width=110, command=do_reboot).pack(side="left", padx=(0,8))
        ctk.CTkButton(right_controls, text="Shutdown", fg_color="#dc3545", width=110, command=do_shutdown).pack(side="left")

        # status label at bottom (spans)
        self.status_label = ctk.CTkLabel(bottom, text="Disconnected", text_color="#b33434", font=ctk.CTkFont(size=10))
        self.status_label.grid(row=1, column=0, sticky="w", padx=12, pady=(4,8), columnspan=3)

        self._setup_live_plot()
        self._refresh_month_plot()

    # UI callbacks
    def _refresh_ports(self):
        ports = get_available_ports()
        self.port_combo.configure(values=ports)
        if ports:
            self.port_combo.set(ports[0])

    def _toggle_connection(self):
        if self.sensor.connected:
            self.sensor.disconnect()
            self.connect_btn.configure(text="Connect")
            self.status_label.configure(text="Disconnected", text_color="#b33434")
        else:
            port = self.port_combo.get() or self.settings.get("com_port") or self._auto_detect_port()
            if not port:
                messagebox.showerror("Error", "No serial port available")
                return
            self.sensor.port = port
            self.sensor.baudrate = DEFAULT_SETTINGS["baud_rate"]
            self.sensor.slave_addr = 1
            if self.sensor.connect():
                self.connect_btn.configure(text="Disconnect")
                self.status_label.configure(text=f"Connected: {port}", text_color="#148f4a")
            else:
                messagebox.showerror("Error", f"Connection failed:\n{self.sensor.last_error}")

    # Baseline functions
    def _set_baseline_for_selected_month(self):
        sel = self.month_combo.get()
        if not sel:
            messagebox.showinfo("Info", "Please select a month.")
            return
        _, total = self._read_sensor()
        if total is None:
            messagebox.showinfo("Info", "No total available to set baseline.")
            return
        months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
        try:
            mnum = months.index(sel) + 1
        except ValueError:
            mnum = datetime.datetime.now().month
        self.monthly_baseline = total
        self.monthly_baseline_month = mnum
        save_monthly_baseline(self.monthly_baseline, self.monthly_baseline_month)
        self.baseline_label.configure(text=f"{self.monthly_baseline:.3f} m³ ({sel})")
        messagebox.showinfo("Baseline", f"Monthly baseline set to {self.monthly_baseline:.3f} m³ for {sel}")

    def _clear_manual_baseline(self):
        self.monthly_baseline_month = None
        save_monthly_baseline(self.monthly_baseline, None)
        self.baseline_label.configure(text=f"{self.monthly_baseline:.3f} m³ (auto)")
        messagebox.showinfo("Baseline", "Manual baseline cleared; auto monthly resets will apply.")

    def _set_monthly_baseline_now(self):
        flow, total = self._read_sensor()
        if total is None:
            messagebox.showinfo("Info", "No total available to set baseline.")
            return
        try:
            self.monthly_baseline = float(total)
            self.monthly_baseline_month = datetime.datetime.now().month
            self.baseline_ts = datetime.datetime.now()
            save_monthly_baseline(self.monthly_baseline, self.monthly_baseline_month)
            months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
            mname = months[self.monthly_baseline_month - 1] if 1 <= self.monthly_baseline_month <= 12 else ""
            self.baseline_label.configure(text=f"{self.monthly_baseline:.3f} m³ ({mname})")
            messagebox.showinfo("Baseline", f"Monthly baseline set to {self.monthly_baseline:.3f} m³ for {mname}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to set baseline:\n{e}")

    # sensor worker
    def _sensor_worker(self):
        MIN_POLL = 0.5
        while self.running:
            if not self.sensor.connected:
                time.sleep(0.2); continue
            start = time.time()
            result = self.sensor.read_all()
            if result is not None:
                self.latest_reading = result; self.last_sensor_time = time.time()
            elapsed = time.time() - start
            time.sleep(max(0.0, MIN_POLL - elapsed))

    # loops
    def _schedule_update(self):
        if not self.running: return
        self._do_update()
        self.update_after_id = self.root.after(self.settings["update_interval_ms"], self._schedule_update)

    def _schedule_graph(self):
        if not self.running: return
        self._do_graph_update()
        self.graph_after_id = self.root.after(1000, self._schedule_graph)

    def _read_sensor(self):
        if not self.sensor.connected:
            return self.last_valid
        if not self.latest_reading:
            return self.last_valid
        flow, total, _ = self.latest_reading
        try: f = round(float(flow),3)
        except Exception: f = self.last_valid[0]
        try: t = round(float(total),3)
        except Exception: t = self.last_valid[1]
        self.last_valid = (f,t); return f,t

    def _do_update(self):
        flow, total = self._read_sensor()
        now = datetime.datetime.now()
        self.times.append(now); self.flows.append(flow); self.totals.append(total)

        # daily baseline reset at midnight
        try:
            today = now.date()
            if self.daily_baseline_date != today:
                self.daily_baseline = total
                self.daily_baseline_date = today
        except Exception:
            pass

        # monthly auto reset at 1st if no manual baseline month set
        try:
            if self.monthly_baseline_month is None:
                if now.day == 1:
                    bl_month = self.baseline_ts.month if getattr(self,'baseline_ts',None) else None
                    if bl_month != now.month:
                        self.monthly_baseline = total
                        self.baseline_ts = datetime.datetime.now()
                        save_monthly_baseline(self.monthly_baseline, None)
        except Exception:
            pass

        # update displays
        if self.mode == "live":
            self.var_flow.set(f"{flow:.2f} L/min")
            self.var_day.set(f"{max(0.0, total - self.daily_baseline):.3f} m³")
            month_usage = max(0.0, total - self.monthly_baseline)
            self.var_month.set(f"{month_usage:.3f} m³")
            baseline_text = f"{self.monthly_baseline:.3f} m³"
            if self.monthly_baseline_month:
                months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
                try: mname = months[self.monthly_baseline_month-1]; baseline_text += f" ({mname})"
                except Exception: pass
            else:
                baseline_text += " (auto)"
            self.baseline_label.configure(text=baseline_text)

            try:
                append_log(flow, total)
            except Exception:
                pass

        # refresh month plot occasionally
        if len(self.times) % 30 == 0:
            self._refresh_month_plot()

    # plotting helpers
    def _setup_live_plot(self):
        try:
            self.ax_live.clear()
            self.ax_live.set_facecolor('#ffffff')
            self.ax_live.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
            self.ax_live.set_ylabel("L/min")
            self.flow_line, = self.ax_live.plot([], [], color="#007acc", linewidth=1.8)
            self.flow_marker, = self.ax_live.plot([], [], 'o', color="#ff6b6b", markersize=5)
            self.flow_fill = None
            self.ax_live.grid(alpha=0.2, color='#e6e6e6')
            self.canvas_live.draw_idle()
        except Exception:
            pass

    def _do_graph_update(self):
        if self.mode != "live": return
        try:
            if not self.times: return
            window_seconds = self.settings["graph_window_sec"]
            now = datetime.datetime.now()
            cutoff = now - datetime.timedelta(seconds=window_seconds)
            xs, ys = [], []
            for t,f in zip(self.times, self.flows):
                if t >= cutoff:
                    xs.append(t); ys.append(f)
            if not xs: return
            self.flow_line.set_data(xs, ys)
            if self.flow_fill is not None:
                try: self.flow_fill.remove()
                except Exception: pass
                self.flow_fill = None
            try:
                self.flow_fill = self.ax_live.fill_between(xs, ys, color="#cfeeff", alpha=0.4)
            except Exception:
                self.flow_fill = None
            try: self.flow_marker.set_data([xs[-1]],[ys[-1]])
            except Exception: pass
            self.ax_live.set_xlim(cutoff, now)
            y_max = max(5.0, max(ys) * 1.25)
            self.ax_live.set_ylim(0.0, max(20.0, y_max))
            self.fig_live.autofmt_xdate()
            self.canvas_live.draw_idle()
        except Exception as e:
            print("Graph update error:", e, file=sys.stderr)

    def _refresh_month_plot(self):
        try:
            now = datetime.datetime.now(); folder = os.path.join(LOGS_DIR, now.strftime("%Y-%m"))
            if not os.path.isdir(folder):
                self.ax_month.clear(); self.ax_month.set_title("No month data"); self.canvas_month.draw_idle(); return
            files = sorted([os.path.join(folder,f) for f in os.listdir(folder) if f.endswith(".csv")])
            days, totals = [], []
            for fpath in files:
                try:
                    with open(fpath,"r") as fh:
                        rdr = csv.reader(fh); next(rdr,None)
                        day_tots = []
                        for r in rdr:
                            if not r: continue
                            day_tots.append(float(r[2]))
                        if day_tots:
                            day = datetime.datetime.strptime(os.path.basename(fpath).replace(".csv",""), "%Y-%m-%d")
                            days.append(day); totals.append(max(day_tots))
                except Exception:
                    continue
            self.ax_month.clear()
            if days:
                self.ax_month.bar(days, totals, color="#00a86b", alpha=0.9)
                self.ax_month.set_title("Daily totals")
                self.ax_month.xaxis.set_major_formatter(mdates.DateFormatter("%d"))
            else:
                self.ax_month.set_title("No month data")
            self.canvas_month.draw_idle()
        except Exception as e:
            print("Month plot refresh error:", e, file=sys.stderr)

    # logs
    def _open_logs_window(self):
        if self.logs_win and hasattr(self.logs_win,"top") and self.logs_win.top.winfo_exists():
            self.logs_win.top.deiconify(); self.logs_win.top.lift(); self.logs_win.top.focus_force(); return
        try: LogsWindow(self)
        except Exception as e: messagebox.showerror("Error", f"Failed to open logs window:\n{e}")

    def _display_day_file(self, path, label):
        try:
            times, flows = [], []
            with open(path,"r") as f:
                rdr = csv.reader(f); next(rdr,None)
                for r in rdr:
                    if not r: continue
                    try:
                        times.append(datetime.datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S"))
                        flows.append(float(r[1]))
                    except Exception: pass
            hourly = {}
            for t,v in zip(times,flows):
                hour = t.replace(minute=0,second=0,microsecond=0)
                hourly.setdefault(hour,[]).append(v)
            if hourly:
                keys = sorted(hourly.keys()); avg = [sum(hourly[k])/len(hourly[k]) for k in keys]
                self.ax_live.clear(); self.ax_live.set_facecolor('#ffffff')
                self.ax_live.plot(keys, avg, marker="o", linewidth=1.6, color="#007acc")
                self.ax_live.set_title(f"{label} - Hourly Avg", color='black')
                self.ax_live.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
                self.ax_live.tick_params(colors='black'); self.ax_live.grid(alpha=0.2, color='#e6e6e6')
                for spine in self.ax_live.spines.values(): spine.set_color('#cccccc')
                self.flow_line=None; self.flow_marker=None; self.flow_fill=None
                self.canvas_live.draw_idle()
        except Exception as e:
            print("Display day error:", e, file=sys.stderr)

    def _export_csv(self):
        fn = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV","*.csv")])
        if not fn: return
        try:
            with open(fn,"w", newline="") as f:
                w = csv.writer(f); w.writerow(["Time","Flow","Total"])
                for t,fval,tot in zip(self.times, self.flows, self.totals):
                    w.writerow([t.strftime("%Y-%m-%d %H:%M:%S"), f"{fval:.2f}", f"{tot:.3f}"])
            messagebox.showinfo("Saved", f"Data exported to:\n{fn}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _cleanup(self):
        self.running = False
        try:
            if getattr(self, "update_after_id", None): self.root.after_cancel(self.update_after_id)
            if getattr(self, "graph_after_id", None): self.root.after_cancel(self.graph_after_id)
        except Exception: pass
        if self.sensor.connected: self.sensor.disconnect()
        try:
            if self.logs_win and getattr(self.logs_win,"top",None): self.logs_win.top.destroy()
        except Exception: pass

    def _exit_now(self):
        self._cleanup()
        try: self.root.quit(); self.root.destroy()
        finally: os._exit(0)

# main
if __name__ == "__main__":
    print(f"Starting MF5708 Flow Meter Dashboard on {PLATFORM_NAME}")
    print(f"Serial library available: {SERIAL_AVAILABLE}")
    root = ctk.CTk()
    app = FlowDashboard(root)
    root.bind("<Escape>", lambda e: root.attributes("-fullscreen", False))
    root.protocol("WM_DELETE_WINDOW", app._exit_now)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        app._exit_now()