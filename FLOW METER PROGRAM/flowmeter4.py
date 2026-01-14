# MF5708 dashboard — compact bottom controls for Raspberry Pi 7" displays
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
        for p in ["/dev/ttyUSB0"]:
            if p not in ports and os.path.exists(p):
                ports.append(p)
    return sorted(ports)

# ---- Baseline persistence: per-month dict with metadata ----
def load_baselines():
    try:
        if os.path.exists(BASELINE_FILE):
            with open(BASELINE_FILE, "r") as f:
                data = json.load(f)
                # normalize
                if not isinstance(data, dict):
                    return {"monthly": {}, "last_auto": None}
                monthly = data.get("monthly", {})
                last_auto = data.get("last_auto", None)
                return {"monthly": monthly, "last_auto": last_auto}
    except Exception as e:
        print("Baseline load error:", e, file=sys.stderr)
    return {"monthly": {}, "last_auto": None}

def save_baselines(bdata):
    try:
        with open(BASELINE_FILE, "w") as f:
            json.dump(bdata, f)
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
        self.month_listbox = tk.Listbox(self.top, height=6, exportselection=False); self.month_listbox.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0,8))
        self.month_listbox.bind("<<ListboxSelect>>", lambda e: self.on_month_select())
        lbl_d = tk.Label(self.top, text="Day:"); lbl_d.grid(row=2, column=0, sticky="w", padx=8, pady=(4,2))
        self.day_listbox = tk.Listbox(self.top, height=8, exportselection=False); self.day_listbox.grid(row=3, column=0, sticky="nsew", padx=8, pady=(0,8))
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
        days, daily_totals = [],[]
        for filepath in files:
            try:
                tots = []
                with open(filepath,"r") as fh:
                    rdr = csv.reader(fh); next(rdr,None)
                    for r in rdr:
                        if not r: continue
                        tots.append(float(r[2]))
                if tots:
                    day_str = os.path.basename(filepath).replace(".csv","")
                    days.append(datetime.datetime.strptime(day_str,"%Y-%m-%d"))
                    daily_totals.append(max(tots))
            except Exception:
                continue
        if not days: messagebox.showinfo("Info","No valid data for month."); return

        # calculate usage relative to first day of the month (monthly usage)
        baseline_first = min(daily_totals)
        daily_usage = [max(0.0, t - baseline_first) for t in daily_totals]
        cumulative = []
        s = 0.0
        for u in daily_usage:
            s += u
            cumulative.append(s)

        parent_ax = self.parent.ax_month; parent_fig = self.parent.fig_month
        parent_ax.clear(); parent_ax.set_facecolor('#ffffff')
        parent_ax.bar(days, daily_usage, color="#00a86b", alpha=0.85, label="Daily Usage (m³)")
        parent_ax.plot(days, cumulative, color="#007acc", marker="o", linewidth=1.6, label="Cumulative (m³)")
        parent_ax.set_title(f"Monthly Usage ({month})", color='black'); parent_ax.tick_params(colors='black', labelsize=8)
        parent_ax.legend(facecolor='#ffffff', edgecolor='#cccccc', fontsize=8); parent_ax.grid(alpha=0.2, color='#e6e6e6')
        for spine in parent_ax.spines.values(): spine.set_color('#cccccc')
        parent_fig.autofmt_xdate()
        try:
            self.parent.flow_line=None; self.parent.flow_marker=None; self.parent.flow_fill=None
        except Exception: pass
        self.parent.canvas_month.draw_idle(); self.parent.mode="month"
        
        
class BaselineDialog:
    """
    Simple modal dialog to pick a date/time. Parent must implement
    _save_manual_baseline(dt: datetime.datetime, value: float)
    (this dialog will pass value=0.0).
    """
    def __init__(self, parent):
        self.parent = parent
        self.top = tk.Toplevel(parent.root)
        self.top.title("Set Baseline (date/time)")
        self.top.transient(parent.root)
        self.top.resizable(False, False)
        # slightly larger size for readability on Pi
        try:
            self.top.geometry("420x140+%d+%d" % (parent.root.winfo_rootx()+40, parent.root.winfo_rooty()+40))
        except Exception:
            pass

        frm = tk.Frame(self.top, padx=10, pady=8)
        frm.pack(fill="both", expand=True)

        lbl_font = ("TkDefaultFont", 10)
        now = datetime.datetime.now()

        # Date
        tk.Label(frm, text="Date (Y-M-D):", font=lbl_font).grid(row=0, column=0, sticky="w")
        self.year_sb = tk.Spinbox(frm, from_=2000, to=2100, width=6, font=lbl_font)
        self.month_sb = tk.Spinbox(frm, from_=1, to=12, width=4, font=lbl_font)
        self.day_sb = tk.Spinbox(frm, from_=1, to=31, width=4, font=lbl_font)
        self.year_sb.grid(row=0, column=1, sticky="w", padx=(6,0))
        self.month_sb.grid(row=0, column=2, sticky="w", padx=(4,0))
        self.day_sb.grid(row=0, column=3, sticky="w", padx=(4,0))
        self.year_sb.delete(0,"end"); self.year_sb.insert(0, now.year)
        self.month_sb.delete(0,"end"); self.month_sb.insert(0, now.month)
        self.day_sb.delete(0,"end"); self.day_sb.insert(0, now.day)

        # Time
        tk.Label(frm, text="Time (H:M:S):", font=lbl_font).grid(row=1, column=0, sticky="w", pady=(6,0))
        self.hour_sb = tk.Spinbox(frm, from_=0, to=23, width=4, font=lbl_font, format="%02.0f")
        self.min_sb = tk.Spinbox(frm, from_=0, to=59, width=4, font=lbl_font, format="%02.0f")
        self.sec_sb = tk.Spinbox(frm, from_=0, to=59, width=4, font=lbl_font, format="%02.0f")
        self.hour_sb.grid(row=1, column=1, sticky="w", padx=(6,0), pady=(6,0))
        self.min_sb.grid(row=1, column=2, sticky="w", padx=(4,0), pady=(6,0))
        self.sec_sb.grid(row=1, column=3, sticky="w", padx=(4,0), pady=(6,0))
        self.hour_sb.delete(0,"end"); self.hour_sb.insert(0, f"{now.hour:02d}")
        self.min_sb.delete(0,"end"); self.min_sb.insert(0, f"{now.minute:02d}")
        self.sec_sb.delete(0,"end"); self.sec_sb.insert(0, f"{now.second:02d}")

        # Buttons — Save (prominent), Cancel
        btn_fr = tk.Frame(frm)
        btn_fr.grid(row=2, column=0, columnspan=4, pady=(10,0), sticky="e")

        save_btn = tk.Button(btn_fr, text="Save baseline (value=0.000 m³)", width=26, height=1, font=lbl_font,
                             bg="#007acc", fg="white", command=self._on_save)
        save_btn.pack(side="left", padx=(0,8))

        cancel_btn = tk.Button(btn_fr, text="Cancel", width=10, height=1, font=lbl_font, command=self._on_cancel)
        cancel_btn.pack(side="left")

        # make modal
        self.top.grab_set()
        self.top.wait_visibility()
        self.top.focus_force()

    def _on_save(self):
        # build dt (user-chosen)
        try:
            y = int(self.year_sb.get()); m = int(self.month_sb.get()); d = int(self.day_sb.get())
            hh = int(self.hour_sb.get()); mm = int(self.min_sb.get()); ss = int(self.sec_sb.get())
            dt = datetime.datetime(y,m,d,hh,mm,ss)
        except Exception as e:
            messagebox.showerror("Invalid date/time", f"Please enter valid date/time.\n{e}")
            return

        # prefer to save the current sensor total as the baseline for the chosen date/time
        try:
            _, current_total = self.parent._read_sensor()
            baseline_value = float(current_total) if current_total is not None else 0.0
        except Exception:
            baseline_value = 0.0
        if hasattr(self.parent, "_save_manual_baseline"):
            self.parent._save_manual_baseline(dt, baseline_value)
        else:
            messagebox.showerror("Save error", "Save handler not available.")

    def _on_cancel(self):
        try:
            self.top.destroy()
        except Exception:
            pass
        
# Main dashboard
class FlowDashboard:
    def __init__(self, root):
        self.root = root
        ctk.set_appearance_mode("light"); ctk.set_default_color_theme("blue")
        self.root.configure(bg="#ffffff")
        self.root.title(f"MF5708 Flow Meter Dashboard - {PLATFORM_NAME}")
        if IS_RASPBERRY_PI:
            # don't force fullscreen — allow user to use 800x480 (7" official)
            try:
                self.root.geometry("800x480")
            except Exception:
                self.root.attributes("-fullscreen", True)
        else:
            self.root.geometry("1300x840"); self.root.minsize(1100,650)

        self.settings = DEFAULT_SETTINGS.copy()
        # On Raspberry Pi default to /dev/ttyUSB0 (common)
        if IS_RASPBERRY_PI and os.path.exists("/dev/ttyUSB0"):
            self.settings["com_port"] = "/dev/ttyUSB0"
        else:
            self.settings["com_port"] = self._auto_detect_port()

        # sensor
        self.sensor = MF5708Sensor(port=self.settings["com_port"])
        # state
        self.running = True; self.mode="live"; self.logs_win=None; self.current_dayfile=None
        self.latest_reading=(0.0,0.0,0.0); self.last_valid=(0.0,0.0)
        self.times = collections.deque(maxlen=MAX_BUFFER_POINTS); self.flows = collections.deque(maxlen=MAX_BUFFER_POINTS); self.totals = collections.deque(maxlen=MAX_BUFFER_POINTS)

        # baseline storage (per-month)
        bl = load_baselines()
        self.baselines_by_month = bl.get("monthly", {})  # dict: "YYYY-MM" -> {"value":..., "type":"manual"/"auto", "ts":...}
        self.last_auto_baseline_ts = bl.get("last_auto", None)
        
        # remember the month we started in so we detect month changes
        self.current_month_key = datetime.datetime.now().strftime("%Y-%m")

        self.daily_baseline = 0.0; self.daily_baseline_date = None

        # keep previous total for reset detection
        self.prev_total = None

        # UI
        self._build_ui()

        # worker thread
        threading.Thread(target=self._sensor_worker, daemon=True).start()
        # loops
        self._schedule_update(); self._schedule_graph()

    def _auto_detect_port(self):
        ports = get_available_ports()
        if IS_RASPBERRY_PI:
            for p in ["/dev/ttyUSB0"]:
                if p in ports: return p
        return ports[0] if ports else ""

    def _build_ui(self):
        # root grid: row0 metrics, row1 main split (monthly | live), row2 bottom controls
        self.root.grid_rowconfigure(0, weight=0)
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_rowconfigure(2, weight=0)
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_columnconfigure(1, weight=1)

        # Fonts / sizes tuned for Pi small display
        if IS_RASPBERRY_PI:
            metric_font = 10
            val_font = 16
            small_btn_w = 72
            tiny_btn_w = 44
            btn_h = 20
            baseline_font = 10
            bottom_pad = 6
        else:
            metric_font = 11
            val_font = 20
            small_btn_w = 120
            tiny_btn_w = 80
            btn_h = 28
            baseline_font = 11
            bottom_pad = 10

        # Metrics row (spans both columns)
        metrics_frame = ctk.CTkFrame(self.root, fg_color="#f8fafc", corner_radius=6)
        metrics_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=(8,6))
        metrics_frame.grid_columnconfigure((0,1,2), weight=1)

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

        # Bottom control bar (compact)
        bottom = ctk.CTkFrame(self.root, fg_color="#f0f4f8", corner_radius=6)
        bottom.grid(row=2, column=0, columnspan=2, sticky="ew", padx=8, pady=(6,8))
        bottom.grid_columnconfigure(0, weight=1)
        bottom.grid_columnconfigure(1, weight=1)
        bottom.grid_columnconfigure(2, weight=1)

        # Left: Connect / Disconnect only (compact)
        left_controls = tk.Frame(bottom)
        left_controls.grid(row=0, column=0, sticky="w", padx=6, pady=bottom_pad)
        self.connect_btn = ctk.CTkButton(left_controls, text="Connect", width=small_btn_w, height=btn_h, command=self._toggle_connection)
        self.connect_btn.pack(side="left")

        # Middle: baseline label + Set baseline (opens dialog)
        mid_controls = tk.Frame(bottom)
        mid_controls.grid(row=0, column=1, sticky="nsew", padx=4, pady=bottom_pad)
        mid_controls.grid_columnconfigure(0, weight=1)
        self.baseline_label = ctk.CTkLabel(mid_controls, text="", font=ctk.CTkFont(size=baseline_font))
        self.baseline_label.grid(row=0, column=0, sticky="w")
        self.set_baseline_btn = ctk.CTkButton(mid_controls, text="Set Baseline", width=small_btn_w, height=btn_h, command=self._open_baseline_dialog)
        self.set_baseline_btn.grid(row=0, column=1, sticky="e", padx=(8,0))
        # Right: actions compact
        right_controls = tk.Frame(bottom)
        right_controls.grid(row=0, column=2, sticky="e", padx=6, pady=bottom_pad)
        ctk.CTkButton(right_controls, text="Export", width=70, height=btn_h, command=self._export_csv).pack(side="left", padx=(0,6))
        ctk.CTkButton(right_controls, text="Logs", width=70, height=btn_h, command=self._open_logs_window).pack(side="left", padx=(0,6))
        ctk.CTkButton(right_controls, text="Exit", width=70, height=btn_h, fg_color="#dc3545", command=self._exit_now).pack(side="left", padx=(0,6))

        # final Plot setup and baseline label refresh
        self._setup_live_plot()
        self._refresh_month_plot()
        self._refresh_baseline_label()

    def _open_baseline_dialog(self):
        # disable to avoid re-entrance (modal dialog already prevents clicks, but this is safe)
        try:
            self.set_baseline_btn.configure(state="disabled")
        except Exception:
            pass
        try:
            BaselineDialog(self)
        finally:
            try:
                self.set_baseline_btn.configure(state="normal")
            except Exception:
                pass
            
    # ---- baseline helpers ----
    def _get_baseline_for_month(self, ym_key):
        """Return dict entry for baseline (value,type,ts) or None.
           If not explicitly stored, try to infer from logs for that month (min daily max)."""
        entry = self.baselines_by_month.get(ym_key)
        if entry:
            return entry
        # attempt to infer from logs
        folder = os.path.join(LOGS_DIR, ym_key)
        if not os.path.isdir(folder):
            return None
        files = sorted([os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".csv")])
        totals = []
        for fpath in files:
            try:
                with open(fpath, "r") as fh:
                    rdr = csv.reader(fh); next(rdr, None)
                    day_tots = [float(r[2]) for r in rdr if r and len(r) >= 3]
                if day_tots:
                    totals.append(max(day_tots))
            except Exception:
                continue
        if totals:
            val = float(min(totals))
            return {"value": val, "type": "inferred", "ts": None}
        return None

    def _refresh_baseline_label(self):
        now = datetime.datetime.now()
        key = now.strftime("%Y-%m")
        entry = self._get_baseline_for_month(key)
        if entry:
            kind = entry.get("type", "auto")
            val = entry.get("value", 0.0)
            ts = entry.get("ts")
            label = f"{val:.3f} m³ ({key}, {kind})"
        else:
            label = f"No baseline for {key}"
        try:
            self.baseline_label.configure(text=label)
        except Exception:
            pass
        
    def _save_manual_baseline(self, dt, value):
        """Save a manual baseline for the month corresponding to dt (dt is a datetime)."""
        try:
            key = dt.strftime("%Y-%m")
            new_val = float(value)
            old = self.baselines_by_month.get(key)
            # if existing manual baseline and difference is negligible, ignore to avoid tiny oscillations
            eps = 0.0005
            if old and old.get("type") == "manual":
                try:
                    old_val = float(old.get("value", 0.0))
                    if abs(old_val - new_val) <= eps:
                        # no meaningful change
                        messagebox.showinfo("Baseline", f"Baseline for {key} unchanged ({new_val:.3f} m³).")
                        return
                except Exception:
                    pass
            entry = {"value": new_val, "type": "manual", "ts": dt.isoformat()}
            self.baselines_by_month[key] = entry
            save_baselines({"monthly": self.baselines_by_month, "last_auto": self.last_auto_baseline_ts})
            self._refresh_baseline_label()
            messagebox.showinfo("Baseline saved", f"Saved baseline {new_val:.3f} m³ for {key} at {dt.isoformat()}")
        except Exception as e:
            messagebox.showerror("Save error", f"Failed to save baseline:\n{e}")

    # ---- small UI helper to flash a status message for a short time ----
    def _flash_status(self, text, color="#d97706", timeout_ms=3000):
        try:
            prev = self.status_label.cget("text")
            prev_color = self.status_label.cget("text_color")
            self.status_label.configure(text=text, text_color=color)
            def _restore():
                try:
                    # restore to connected/disconnected state
                    if self.sensor.connected:
                        port = self.sensor.port or self.settings.get("com_port","")
                        self.status_label.configure(text=f"Connected: {port}", text_color="#148f4a")
                    else:
                        self.status_label.configure(text="Disconnected", text_color="#b33434")
                except Exception:
                    pass
            self.root.after(timeout_ms, _restore)
        except Exception:
            pass

    # UI callbacks & remaining logic unchanged mostly, but with baseline & reset handling
    def _refresh_ports(self):
        return get_available_ports()

    def _toggle_connection(self):
        if self.sensor.connected:
            self.sensor.disconnect()
            self.connect_btn.configure(text="Connect")
        else:
            port = self.settings.get("com_port") or self._auto_detect_port()
            if not port:
                messagebox.showerror("Error", "No serial port available")
                return
            self.sensor.port = port
            self.sensor.baudrate = DEFAULT_SETTINGS["baud_rate"]
            self.sensor.slave_addr = 1
            if self.sensor.connect():
                self.connect_btn.configure(text="Disconnect")
            else:
                messagebox.showerror("Error", f"Connection failed:\n{self.sensor.last_error}")

    def _set_monthly_baseline_now(self):
        # open dialog (BaselineDialog will call _save_manual_baseline on Save)
        BaselineDialog(self)

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

        # daily baseline reset at midnight (or first reading after midnight)
        try:
            today = now.date()
            if self.daily_baseline_date != today:
                self.daily_baseline = total
                self.daily_baseline_date = today
        except Exception:
            pass

        # detect meter reset / rollover (sudden drop compared to previous reading)
        try:
            prev = self.prev_total
            if prev is not None and total < (prev - 0.5) and prev > 1.0:
                # meter likely reset — adjust baselines automatically
                if DEBUG_MODE:
                    print(f"[DEBUG] Meter reset detected: prev={prev}, now={total}", file=sys.stderr)
                # inform user once (modal) — avoids additional UI elements
                try:
                    messagebox.showinfo("Meter reset", "Meter total decreased: possible meter reset. Baselines adjusted.")
                except Exception:
                    pass
                # set today's baseline to current total
                self.daily_baseline = total
                self.daily_baseline_date = now.date()
                # ensure month baseline exists (auto) so month usage doesn't look weird
                key = now.strftime("%Y-%m")
                if key not in self.baselines_by_month:
                    entry = {"value": float(total), "type": "auto", "ts": datetime.datetime.now().isoformat()}
                    self.baselines_by_month[key] = entry
                    self.last_auto_baseline_ts = datetime.datetime.now().isoformat()
                    save_baselines({"monthly": self.baselines_by_month, "last_auto": self.last_auto_baseline_ts})
                    self._refresh_baseline_label()
            self.prev_total = total
        except Exception:
            pass

        # auto baseline on month change: set baseline = current total when month advances
        try:
            curr_key = now.strftime("%Y-%m")
            if getattr(self, "current_month_key", None) != curr_key:
                # month changed while app was running (or first read after start in a new month)
                # create or update an auto baseline for the new month unless a manual baseline exists
                existing = self.baselines_by_month.get(curr_key)
                if not existing or existing.get("type") != "manual":
                    entry = {"value": float(total), "type": "auto", "ts": datetime.datetime.now().isoformat()}
                    self.baselines_by_month[curr_key] = entry
                    self.last_auto_baseline_ts = datetime.datetime.now().isoformat()
                    save_baselines({"monthly": self.baselines_by_month, "last_auto": self.last_auto_baseline_ts})
                    self._refresh_baseline_label()
                # update current month tracker
                self.current_month_key = curr_key
        except Exception:
            pass

        # update displays
        if self.mode == "live":
            self.var_flow.set(f"{flow:.2f} L/min")
            self.var_day.set(f"{max(0.0, total - self.daily_baseline):.3f} m³")

            # month usage: use stored baseline if present, else try to infer; if none show raw total (raw)
            try:
                key = now.strftime("%Y-%m")
                entry = self._get_baseline_for_month(key)
                if entry:
                    baseline_val = float(entry.get("value", 0.0))
                    month_usage = max(0.0, total - baseline_val)
                    self.var_month.set(f"{month_usage:.3f} m³")
                else:
                    # no baseline yet — show raw total with note
                    self.var_month.set(f"{total:.3f} m³ (raw)")
            except Exception:
                self.var_month.set("0.000 m³")

            self._refresh_baseline_label()

            try:
                append_log(flow, total)
            except Exception:
                pass

        # refresh month plot occasionally
        if len(self.times) % 30 == 0:
            self._refresh_month_plot()

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
        """
        Build a Jan..Dec horizontal bar chart for the current year.
        For each month:
          - read daily csvs from logs/YYYY-MM
          - find month_max = max of daily maxima
          - baseline: prefer stored baseline for YYYY-MM (baselines_by_month),
            otherwise infer baseline_first = min(daily maxima) and usage = max(0, month_max - baseline_first)
          - if no data -> usage 0 (shows '-' label)
        """
        try:
            now = datetime.datetime.now()
            year = now.year
            months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
            usages = []
            display_texts = []
            for m in range(1,13):
                ym = f"{year}-{m:02d}"
                folder = os.path.join(LOGS_DIR, ym)
                month_files = sorted([os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".csv")]) if os.path.isdir(folder) else []
                day_maxes = []
                for fpath in month_files:
                    try:
                        with open(fpath, "r") as fh:
                            rdr = csv.reader(fh); next(rdr, None)
                            tots = [float(r[2]) for r in rdr if r and len(r) >= 3]
                            if tots:
                                day_maxes.append(max(tots))
                    except Exception:
                        continue
                if not day_maxes:
                    usages.append(0.0)
                    display_texts.append("-")
                    continue

                month_max = max(day_maxes)
                # baseline: prefer explicit baseline entry for this year-month
                baseline_entry = self.baselines_by_month.get(ym)
                if baseline_entry:
                    baseline_val = float(baseline_entry.get("value", 0.0))
                else:
                    # infer baseline as the minimum daily maximum in that month (first/lowest reading)
                    baseline_val = float(min(day_maxes))
                usage = max(0.0, month_max - baseline_val)
                usages.append(usage)
                display_texts.append(f"{usage:.3f} m³")

            # plot horizontal bars
            self.ax_month.clear()
            self.ax_month.set_facecolor('#ffffff')
            y_pos = list(range(len(months)))[::-1]  # reverse so Jan on top? adjust as you prefer
            # we want Jan at top -> reverse months and usages to have Jan at top (matplotlib barh draws at y positions)
            months_rev = months[::-1]
            usages_rev = usages[::-1]
            texts_rev = display_texts[::-1]

            bar_cols = ["#00a86b" if u > 0 else "#e6e6e6" for u in usages_rev]
            bars = self.ax_month.barh(range(12), usages_rev, color=bar_cols, alpha=0.95)
            self.ax_month.set_yticks(range(12))
            self.ax_month.set_yticklabels(months_rev)
            self.ax_month.set_xlabel("Monthly usage (m³)")
            self.ax_month.set_title(f"Yearly Monthly Usage ({year})")
            self.ax_month.grid(axis='x', alpha=0.2)

            # annotate values inside bars (if wide enough) or to the right
            for i, (bar, txt) in enumerate(zip(bars, texts_rev)):
                w = bar.get_width()
                if w > 0.02 * max(1.0, max(usages_rev)):  # place inside if bar sufficiently wide
                    self.ax_month.text(w * 0.5, bar.get_y() + bar.get_height()/2, txt,
                                       va='center', ha='center', color='white', fontsize=9, weight='bold')
                else:
                    # small/zero bar -> place text to the right
                    self.ax_month.text(w + 0.01, bar.get_y() + bar.get_height()/2, txt,
                                       va='center', ha='left', color='black', fontsize=9)

            # tighten layout and redraw
            for spine in self.ax_month.spines.values(): spine.set_color('#cccccc')
            self.fig_month.tight_layout()
            self.canvas_month.draw_idle()
        except Exception as e:
            print("Month plot refresh error:", e, file=sys.stderr)
  

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