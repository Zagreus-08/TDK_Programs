"""
MF5708 Flow Meter Dashboard - Cross-Platform (Windows/Raspberry Pi)
RS485 Modbus RTU Communication with Simulation Mode

Updated: logs moved to a popup window; main UI sized for Raspberry Pi 7" display
"""

import os
import sys
import csv
import time
import math
import random
import threading
import struct
import collections
import datetime
import platform
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

# ---------------- PLATFORM DETECTION ----------------
IS_RASPBERRY_PI = platform.system() == "Linux" and os.path.exists("/proc/device-tree/model")
IS_WINDOWS = platform.system() == "Windows"
PLATFORM_NAME = "Raspberry Pi" if IS_RASPBERRY_PI else ("Windows" if IS_WINDOWS else platform.system())

# ---------------- DEBUG MODE ----------------
DEBUG_MODE = True  # Set to False to disable debug output

# ---------------- CONFIG ----------------
LOGS_DIR = "logs"
HOUR_SUM_DIR = os.path.join(LOGS_DIR, "hourly_summary")

# Default settings (can be changed via UI)
DEFAULT_SETTINGS = {
    "com_port": "",             # Auto-detect or manual (e.g., "COM3" or "/dev/ttyUSB0")
    "baud_rate": 9600,          # MF5708 default baud rate
    "slave_address": 1,         # Modbus slave address (1-247)
    "update_interval_ms": 1000, # Sampling interval
    "graph_window_sec": 60,     # Live graph window (seconds)
}

MAX_BUFFER_POINTS = 3600       # Memory buffer for live (1 hour)
RECENT_TABLE_SIZE = 200        # Number of recent rows in live table
# ----------------------------------------

os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(HOUR_SUM_DIR, exist_ok=True)


def get_available_ports():
    """Get list of available serial ports."""
    if not SERIAL_AVAILABLE:
        return []
    ports = []
    for port in serial.tools.list_ports.comports():
        ports.append(port.device)
    # Add common Raspberry Pi ports if on Linux
    if IS_RASPBERRY_PI:
        for p in ["/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyAMA0", "/dev/serial0"]:
            if p not in ports and os.path.exists(p):
                ports.append(p)
    return sorted(ports)


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
            w.writerow(["Timestamp", "Flow (SLPM)", "Total (NCM)"])
    return fp


def append_log(flow, total):
    fp = get_log_file_path()
    with open(fp, "a", newline="") as f:
        w = csv.writer(f)
        w.writerow([datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    f"{flow:.2f}", f"{total:.3f}"])


# ============== MF5708 MODBUS RTU COMMUNICATION ==============
class MF5708Sensor:
    """
    MF5708 Flow Meter RS485 Modbus RTU Communication
    (unchanged)
    """
    def __init__(self, port=None, baudrate=9600, slave_addr=1, timeout=1.0):
        self.port = port
        self.baudrate = baudrate
        self.slave_addr = slave_addr
        self.timeout = timeout
        self.serial = None
        self.connected = False
        self.last_error = ""

    def connect(self):
        if not SERIAL_AVAILABLE:
            self.last_error = "pyserial not installed"
            return False
        if not self.port:
            self.last_error = "No port specified"
            return False
        try:
            if DEBUG_MODE:
                print(f"\n[DEBUG] ===== CONNECTING =====")
                print(f"[DEBUG] Port: {self.port}")
                print(f"[DEBUG] Baud: {self.baudrate}")
                print(f"[DEBUG] Slave Address: {self.slave_addr}")
                print(f"[DEBUG] Timeout: {self.timeout}s")
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout
            )
            self.connected = True
            self.last_error = ""
            if DEBUG_MODE:
                print(f"[DEBUG] Connection SUCCESS!")
            return True
        except Exception as e:
            self.last_error = str(e)
            self.connected = False
            if DEBUG_MODE:
                print(f"[DEBUG] Connection FAILED: {e}")
            return False

    def disconnect(self):
        try:
            if self.serial:
                if self.serial.is_open:
                    self.serial.close()
                self.serial = None
            if DEBUG_MODE:
                print(f"[DEBUG] Disconnected from port")
        except Exception as e:
            if DEBUG_MODE:
                print(f"[DEBUG] Disconnect error: {e}")
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
            if DEBUG_MODE:
                print(f"[DEBUG] Not connected or no serial port")
            return None
        try:
            self.serial.reset_input_buffer()
            request = self._build_read_request(start_reg, num_regs)
            if DEBUG_MODE:
                print(f"[DEBUG] TX (hex): {' '.join(f'{b:02X}' for b in request)}")
            self.serial.write(request)
            time.sleep(0.05)
            expected_len = 3 + 2 * num_regs + 2
            response = self.serial.read(expected_len)
            if DEBUG_MODE:
                print(f"[DEBUG] Received {len(response)} bytes")
            if len(response) < expected_len:
                self.last_error = f"Incomplete response: {len(response)}/{expected_len} bytes"
                return None
            data = response[:-2]
            recv_crc = response[-2] | (response[-1] << 8)
            calc_crc = self._calc_crc16(data)
            if recv_crc != calc_crc:
                self.last_error = "CRC mismatch"
                return None
            byte_count = response[2]
            values = []
            for i in range(num_regs):
                hi = response[3 + i*2]
                lo = response[4 + i*2]
                values.append((hi << 8) | lo)
            return values
        except Exception as e:
            self.last_error = str(e)
            if DEBUG_MODE:
                print(f"[DEBUG] EXCEPTION: {e}")
            return None

    def _regs_to_float(self, regs):
        if len(regs) < 2:
            return 0.0
        raw = struct.pack('>HH', regs[0], regs[1])
        return struct.unpack('>f', raw)[0]

    def _regs_to_float_swapped(self, regs):
        if len(regs) < 2:
            return 0.0
        raw = struct.pack('>HH', regs[1], regs[0])
        return struct.unpack('>f', raw)[0]

    def read_all(self):
        if DEBUG_MODE:
            print(f"\n[DEBUG] ========== READ ALL SENSOR VALUES ==========")
        regs = self._read_registers(0x0000, 16)
        if regs is None:
            return None
        try:
            flow = regs[3] / 1000.0
            total_32bit = regs[0] * 65536 + regs[1]
            if total_32bit == 0 or total_32bit == 1:
                total_32bit = regs[4] * 65536 + regs[5]
            if total_32bit == 0:
                total_32bit = regs[6] * 65536 + regs[7]
            total = total_32bit / 1000.0
            temp = 0.0
            if DEBUG_MODE:
                print(f"[DEBUG] Flow: {flow}, Total: {total}")
            return (flow, total, temp)
        except Exception as e:
            self.last_error = str(e)
            if DEBUG_MODE:
                print(f"[DEBUG] Parse error: {e}")
            return None



# ============== LOGS WINDOW (popup) ==============
class LogsWindow:
    """Popup Toplevel for browsing logs and viewing CSV contents."""

    def __init__(self, parent_dashboard):
        self.parent = parent_dashboard

        # ✅ CREATE TOPLEVEL FIRST (CRITICAL)
        self.top = tk.Toplevel(self.parent.root)

        try:
            title = f"Data Logs - {PLATFORM_NAME}"
            self.top.title(title)

            # Size handling
            if IS_RASPBERRY_PI:
                self.top.geometry("780x420")
                self.top.minsize(480, 320)
            else:
                self.top.geometry("900x600")
                self.top.minsize(600, 420)

            # ⚠️ transient causes issues on Pi
            if not IS_RASPBERRY_PI:
                self.top.transient(self.parent.root)

            self._build_ui()
            self.load_months()

            # Register with parent ONLY after success
            self.parent.logs_win = self

            # ---- RPI WINDOW MANAGER FIX ----
            self.top.update_idletasks()
            self.top.lift()
            self.top.focus_force()

            if IS_RASPBERRY_PI:
                self.top.attributes("-topmost", True)
                self.top.after(300, lambda: self.top.attributes("-topmost", False))

        except Exception as e:
            # ✅ CLEAN FAIL — destroy partial window
            try:
                self.top.destroy()
            except Exception:
                pass

            self.parent.logs_win = None
            raise RuntimeError(str(e))


    def _build_ui(self):
        self.top.grid_rowconfigure(3, weight=1)
        self.top.grid_columnconfigure(1, weight=1)

        # Month listbox
        lbl_m = tk.Label(self.top, text="Month:")
        lbl_m.grid(row=0, column=0, sticky="w", padx=8, pady=(8, 2))
        self.month_listbox = tk.Listbox(self.top, height=6, exportselection=False, bg="#ffffff")
        self.month_listbox.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.month_listbox.bind("<<ListboxSelect>>", lambda e: self.on_month_select())

        # Day listbox
        lbl_d = tk.Label(self.top, text="Day:")
        lbl_d.grid(row=2, column=0, sticky="w", padx=8, pady=(4, 2))
        self.day_listbox = tk.Listbox(self.top, height=8, exportselection=False, bg="#ffffff")
        self.day_listbox.grid(row=3, column=0, sticky="nsew", padx=8, pady=(0, 8))

        # Buttons
        btn_frame = tk.Frame(self.top)
        btn_frame.grid(row=4, column=0, sticky="ew", padx=8, pady=6)
        btn_frame.grid_columnconfigure((0, 1, 2), weight=1)
        tk.Button(btn_frame, text="Load Day", command=self.load_selected_day).grid(row=0, column=0, padx=4)
        tk.Button(btn_frame, text="Load Month", command=self.load_selected_month).grid(row=0, column=1, padx=4)
        tk.Button(btn_frame, text="Refresh", command=self.load_months).grid(row=0, column=2, padx=4)

        # Table for CSV contents
        table_frame = tk.Frame(self.top)
        table_frame.grid(row=0, column=1, rowspan=5, sticky="nsew", padx=8, pady=8)
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview",
                        background="#ffffff",
                        foreground="black",
                        fieldbackground="#ffffff",
                        font=("Consolas", 0))
        style.configure("Treeview.Heading",
                        background="#f0f0f0",
                        foreground="black",
                        font=("Arial", 9, "bold"))
    
        self.tree = ttk.Treeview(table_frame, columns=("Time", "Flow", "Total"),
                                 show="headings", height=18)
        for c, w in [("Time", 160), ("Flow", 100), ("Total", 110)]:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="center")
        self.tree.grid(row=0, column=0, sticky="nsew")

        sb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=sb.set)
        sb.grid(row=0, column=1, sticky="ns")

    def load_months(self):
        self.month_listbox.delete(0, tk.END)
        try:
            months = sorted([d for d in os.listdir(LOGS_DIR)
                           if os.path.isdir(os.path.join(LOGS_DIR, d)) and d != "hourly_summary"])
            for m in months:
                self.month_listbox.insert(tk.END, m)
        except Exception:
            pass

    def on_month_select(self):
        sel = self.month_listbox.curselection()
        self.day_listbox.delete(0, tk.END)
        if not sel:
            return
        month = self.month_listbox.get(sel[0])
        folder = os.path.join(LOGS_DIR, month)
        try:
            files = sorted([f for f in os.listdir(folder) if f.endswith(".csv")])
            for f in files:
                self.day_listbox.insert(tk.END, f)
        except Exception:
            pass

    def load_selected_day(self):
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
        # Populate table
        self._display_csv_in_table(path)
        # Also update main graph to show this day (parent handles plotting)
        self.parent._display_day_file(path, f"Day: {dayfile}")
        self.parent.mode = "day"
        self.parent.current_dayfile = path

    def _display_csv_in_table(self, path):
        for r in self.tree.get_children():
            self.tree.delete(r)
        try:
            with open(path, "r") as f:
                rdr = csv.reader(f)
                next(rdr, None)
                for row in rdr:
                    if not row:
                        continue
                    # Ensure 3 columns
                    if len(row) >= 3:
                        self.tree.insert("", tk.END, values=(row[0], row[1], row[2]))
                    else:
                        self.tree.insert("", tk.END, values=row + [""]*(3-len(row)))
        except Exception as e:
            print(f"Error loading CSV to table: {e}", file=sys.stderr)

    def load_selected_month(self):
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
        days, avg_flows, totals = [], [], []
        for filepath in files:
            try:
                flows, tots = [], []
                with open(filepath, "r") as fh:
                    rdr = csv.reader(fh)
                    next(rdr, None)
                    for r in rdr:
                        if not r:
                            continue
                        flows.append(float(r[1]))
                        tots.append(float(r[2]))
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
        # Update main graph using parent's axes
        parent_ax = self.parent.ax
        parent_fig = self.parent.fig
        parent_ax.clear()
        parent_ax.set_facecolor('#0f1724')
        parent_ax.bar(days, totals, color="#00ff88", alpha=0.7, label="Total Flow (NCM)")
        parent_ax.plot(days, avg_flows, color="#00d4ff", marker="o", linewidth=2, label="Avg Flow (SLPM)")
        parent_ax.set_title(f"Monthly Summary ({month})", color='white')
        parent_ax.tick_params(colors='white')
        parent_ax.legend(facecolor='#1a1a2e', edgecolor='#333', labelcolor='white')
        parent_ax.grid(alpha=0.2, color='#444')
        parent_fig.autofmt_xdate()
        self.parent.canvas.draw_idle()
        self.parent.mode = "month"
    
    def update_live_table(self, items):
        """
        Update the logs window table with recent live items (list of (datetime, flow, total)).
        This is called by the parent dashboard periodically if logs window is open.
        """
        try:
            # Only keep RECENT_TABLE_SIZE most recent
            tail = items[-RECENT_TABLE_SIZE:]
            # Replace contents with most recent first
            for r in self.tree.get_children():
                self.tree.delete(r)
            for t, f, tot in reversed(tail):
                self.tree.insert("", tk.END, values=(t.strftime("%Y-%m-%d %H:%M:%S"), f"{f:.2f}", f"{tot:.3f}"))
        except Exception as e:
            print(f"LogsWindow update error: {e}", file=sys.stderr)


# ============== MAIN DASHBOARD ==============
class FlowDashboard:
    def __init__(self, root):
        self.root = root
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")
        self.root.configure(bg="#ffffff")

        # Window setup - adapt size for Raspberry Pi 7" (800x480) and lock it.
        self.root.title(f"MF5708 Flow Meter Dashboard - {PLATFORM_NAME}")
        if IS_RASPBERRY_PI:
            # Fixed to Raspberry Pi official 7" resolution
            w, h = 800, 480
            self.root.geometry(f"{w}x{h}")
            self.root.minsize(w, h)
            self.root.maxsize(w, h)
            self.root.resizable(False, False)
        else:
            # Windows / testing configuration
            self.root.geometry("1400x900")
            self.root.minsize(1200, 700)

        # Live data buffers
        self.log_buffer = []
        self.last_log_flush = time.time()
        self.latest_reading = (0.0, 0.0)
        self.sensor_lock = threading.Lock()
        self.last_valid = (0.0, 0.0)
        self.last_sensor_time = time.time()
        
        # State
        self.running = True
        self.update_after_id = None
        self.graph_after_id = None
        self.mode = "live"  # "live", "day", "month"
        self.current_month = None
        self.current_dayfile = None
        self.logs_win = None  # reference to LogsWindow if opened

        # Settings
        self.settings = DEFAULT_SETTINGS.copy()
        self.settings["com_port"] = self._auto_detect_port()

        # Sensor/Simulator
        self.sensor = MF5708Sensor()
        self.connection_status = "Disconnected"

        # Live data buffers
        self.times = collections.deque(maxlen=MAX_BUFFER_POINTS)
        self.flows = collections.deque(maxlen=MAX_BUFFER_POINTS)
        self.totals = collections.deque(maxlen=MAX_BUFFER_POINTS)

        # Build UI
        self._build_ui()

        threading.Thread(target=self._sensor_worker, daemon=True).start()


        # Start loops
        self._schedule_update()
        self._schedule_graph()

    def _auto_detect_port(self):
        ports = get_available_ports()
        if not ports:
            return ""
        for p in ports:
            if "USB" in p.upper() or "ttyUSB" in p:
                return p
        return ports[0]

    # ==================== UI BUILDING ====================
    def _build_ui(self):
        # Main layout: 2 columns (settings + main display)
        self.root.grid_columnconfigure(0, weight=0)  # Settings panel
        self.root.grid_columnconfigure(1, weight=1)  # Main display
        self.root.grid_rowconfigure(0, weight=1)

        # Left: Settings Panel
        self._build_settings_panel()

        # Center: Metrics + Graph
        self._build_main_panel()

        # Note: Logs are now in a separate popup window, opened via a button.

    def _build_settings_panel(self):
        panel = ctk.CTkFrame(self.root, width=280, corner_radius=8)
        panel.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)
        panel.grid_propagate(False)

        ctk.CTkLabel(panel, text="⚙️ Settings", font=ctk.CTkFont(size=18, weight="bold")
                    ).pack(anchor="w", padx=12, pady=(12, 8))

        info_frame = ctk.CTkFrame(panel, fg_color="#f8fafc")
        info_frame.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(info_frame, text=f"Platform: {PLATFORM_NAME}",
                    font=ctk.CTkFont(size=11)).pack(anchor="w", padx=8, pady=4)

        self.status_label = ctk.CTkLabel(
            panel,
            text="● Disconnected",
            text_color="#ff6b6b",
            font=ctk.CTkFont(size=12, weight="bold")
        )

        self.status_label.pack(anchor="w", padx=12, pady=(12, 6))

        ctk.CTkLabel(panel, text="Data Source:", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=12, pady=(8, 2))
        mode_frame = ctk.CTkFrame(panel, fg_color="transparent")
        mode_frame.pack(fill="x", padx=12)

        ctk.CTkLabel(panel, text="Serial Port:", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=12, pady=(12, 2))
        port_frame = ctk.CTkFrame(panel, fg_color="transparent")
        port_frame.pack(fill="x", padx=12)

        self.port_combo = ctk.CTkComboBox(port_frame, values=get_available_ports() or ["No ports found"],
                                          width=180, state="readonly")
        if self.settings["com_port"]:
            self.port_combo.set(self.settings["com_port"])
        self.port_combo.pack(side="left", pady=4)

        ctk.CTkButton(port_frame, text="🔄", width=40, command=self._refresh_ports).pack(side="left", padx=4)

        ctk.CTkLabel(panel, text="Baud Rate:", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=12, pady=(8, 2))
        self.baud_combo = ctk.CTkComboBox(panel, values=["9600", "19200", "38400", "57600", "115200"],
                                          width=180, state="readonly")
        self.baud_combo.set(str(self.settings["baud_rate"]))
        self.baud_combo.pack(anchor="w", padx=12, pady=4)

        ctk.CTkLabel(panel, text="Slave Address (1-247):", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=12, pady=(8, 2))
        self.addr_entry = ctk.CTkEntry(panel, width=180)
        self.addr_entry.insert(0, str(self.settings["slave_address"]))
        self.addr_entry.pack(anchor="w", padx=12, pady=4)

        self.connect_btn = ctk.CTkButton(panel, text="Connect", fg_color="#28a745",
                                         command=self._toggle_connection)
        self.connect_btn.pack(fill="x", padx=12, pady=(16, 8))

        ctk.CTkLabel(panel, text="Update Interval (ms):", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=12, pady=(16, 2))
        self.interval_slider = ctk.CTkSlider(panel, from_=200, to=5000, number_of_steps=48,
                                             command=self._on_interval_change)
        self.interval_slider.set(self.settings["update_interval_ms"])
        self.interval_slider.pack(fill="x", padx=12, pady=4)
        self.interval_label = ctk.CTkLabel(panel, text=f"{self.settings['update_interval_ms']} ms")
        self.interval_label.pack(anchor="w", padx=12)

        ctk.CTkLabel(panel, text="Graph Window (sec):", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=12, pady=(12, 2))
        self.window_slider = ctk.CTkSlider(panel, from_=30, to=300, number_of_steps=27,
                                           command=self._on_window_change)
        self.window_slider.set(self.settings["graph_window_sec"])
        self.window_slider.pack(fill="x", padx=12, pady=4)
        self.window_label = ctk.CTkLabel(panel, text=f"{self.settings['graph_window_sec']} sec")
        self.window_label.pack(anchor="w", padx=12)

        self.error_label = ctk.CTkLabel(panel, text="", text_color="#ff6b6b",
                                        font=ctk.CTkFont(size=10), wraplength=250)
        self.error_label.pack(anchor="w", padx=12, pady=(12, 4))

    def _build_main_panel(self):
        panel = ctk.CTkFrame(self.root, corner_radius=8)
        panel.grid(row=0, column=1, sticky="nsew", padx=6, pady=12)
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        # Metrics Cards Row
        card_row = ctk.CTkFrame(panel, fg_color="#f8fafc", corner_radius=6)
        card_row.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 6))
        card_row.grid_columnconfigure((0, 1), weight=1)

        self.var_flow = tk.StringVar(self.root, "0.00")
        self.var_total = tk.StringVar(self.root, "0.000")

        def make_card(parent, var, title, unit="", color="#f8fafc"):
            f = ctk.CTkFrame(parent, fg_color=color, corner_radius=8)
            ctk.CTkLabel(f, text=title, font=ctk.CTkFont(size=11), text_color="#000000").pack(anchor="w", padx=10, pady=(0,0))
            val_frame = ctk.CTkFrame(f, fg_color="transparent")
            val_frame.pack(anchor="w", padx=10, pady=(2, 8))
            ctk.CTkLabel(val_frame, textvariable=var, font=ctk.CTkFont(size=28, weight="bold"),
                        text_color="#000000").pack(side="left")
            if unit:
                ctk.CTkLabel(val_frame, text=unit, font=ctk.CTkFont(size=12),
                            text_color="#555555").pack(side="left", padx=(4, 0))
            return f

        make_card(card_row, self.var_flow, "Flow Rate", "SLPM").grid(row=0, column=0, padx=6, pady=8, sticky="nsew")
        make_card(card_row, self.var_total, "Total Flow", "NCM").grid(row=0, column=1, padx=6, pady=8, sticky="nsew")

        # Graph Panel
        graph_panel = ctk.CTkFrame(panel, fg_color="#0f1724", corner_radius=6)
        graph_panel.grid(row=1, column=0, sticky="nsew", padx=8, pady=(6, 8))
        graph_panel.grid_rowconfigure(0, weight=1)
        graph_panel.grid_columnconfigure(0, weight=1)
        

        self.fig, self.ax = plt.subplots(figsize=(10, 5))
        self.fig.patch.set_facecolor('#0f1724')
        self.ax.set_facecolor('#0f1724')
        self.ax.tick_params(colors='white')
        self.ax.xaxis.label.set_color('white')
        self.ax.yaxis.label.set_color('white')
        self.ax.title.set_color('white')
        for spine in self.ax.spines.values():
            spine.set_color('#333')

        self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        self.ax.set_title("Live Flow / Total / Temp", fontsize=12)
        self.ax.set_ylabel("Value")
        self.ax.grid(alpha=0.2, color='#444')# Matplotlib figure (use smaller size on Pi)
        
        if IS_RASPBERRY_PI:
            # slightly smaller figure to better fit 800x480
            self.fig, self.ax = plt.subplots(figsize=(7, 3))
        else:
            self.fig, self.ax = plt.subplots(figsize=(10, 5))

        self.fig.patch.set_facecolor('#ffffff')
        self.ax.set_facecolor('#ffffff')
        self.ax.tick_params(colors='black')
        self.ax.xaxis.label.set_color('black')
        self.ax.yaxis.label.set_color('black')
        # reduce title size on small screen
        title_fontsize = 10 if IS_RASPBERRY_PI else 12
        self.ax.set_title("Live Flow / Total / Temp", fontsize=title_fontsize, color='black')
        self.ax.set_ylabel("Value", color='black')

        # light grid and spines
        self.ax.grid(alpha=0.2, color='#e6e6e6')
        for spine in self.ax.spines.values():
            spine.set_color('#cccccc')

        self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        
        self.flow_line, = self.ax.plot([], [], label="Flow (SLPM)")
        self.total_line, = self.ax.plot([], [], label="Total (NCM)")
        self.ax.legend()

        self.canvas = FigureCanvasTkAgg(self.fig, master=graph_panel)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        # Control Buttons Row
        ctrl = ctk.CTkFrame(panel, fg_color="#f8fafc", corner_radius=6)
        ctrl.grid(row=2, column=0, sticky="ew", padx=8, pady=(6, 8))
        ctrl.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        ctk.CTkButton(ctrl, text=" Export PNG", command=self._export_graph).grid(row=0, column=0, padx=6, pady=8)
        ctk.CTkButton(ctrl, text=" Export CSV", command=self._export_csv).grid(row=0, column=1, padx=6, pady=8)
        ctk.CTkButton(ctrl, text=" Live View", command=self._switch_to_live).grid(row=0, column=2, padx=6, pady=8)
        ctk.CTkButton(ctrl, text=" Data Logs", command=self._open_logs_window).grid(row=0, column=3, padx=6, pady=8)
        ctk.CTkButton(ctrl, text=" Exit", fg_color="#dc3545", command=self._exit_now).grid(row=0, column=4, padx=6, pady=8)

    # ==================== SETTINGS CALLBACKS ====================

    def _refresh_ports(self):
        ports = get_available_ports()
        self.port_combo.configure(values=ports if ports else ["No ports found"])
        if ports:
            self.port_combo.set(ports[0])

    def _on_interval_change(self, value):
        val = int(value)
        self.settings["update_interval_ms"] = val
        self.interval_label.configure(text=f"{val} ms")

    def _on_window_change(self, value):
        val = int(value)
        self.settings["graph_window_sec"] = val
        self.window_label.configure(text=f"{val} sec")

    def _toggle_connection(self):
        if self.sensor.connected:
            self.sensor.disconnect()
            self.connect_btn.configure(text="Connect", fg_color="#28a745")
            self.status_label.configure(text="● Disconnected", text_color="#ff6b6b")
            self.error_label.configure(text="")
        else:
            port = self.port_combo.get()
            if not port or port == "No ports found":
                self.error_label.configure(text="Error: No serial port selected")
                return
            try:
                baud = int(self.baud_combo.get())
                addr = int(self.addr_entry.get())
            except ValueError:
                self.error_label.configure(text="Error: Invalid baud rate or address")
                return
            self.sensor.port = port
            self.sensor.baudrate = baud
            self.sensor.slave_addr = addr
            if self.sensor.connect():
                self.connect_btn.configure(text="Disconnect", fg_color="#dc3545")
                self.status_label.configure(text=f"● Connected: {port}", text_color="#00ff88")
                self.error_label.configure(text="")
                self.mode_var.set("hardware")
            else:
                self.error_label.configure(text=f"Error: {self.sensor.last_error}")

    # ==================== SENSOR READING ====================
    def _read_sensor(self):
        if not self.sensor.connected:
            return self.last_valid

        result = self.sensor.read_all()
        if result is None:
            self.error_label.configure(text=f"Read error: {self.sensor.last_error}")
            return self.last_valid

        with self.sensor_lock:
            flow, total, _ = self.latest_reading
        return round(flow, 2), round(total, 3)


    def _sensor_worker(self):
        while self.running:
            if self.sensor.connected:
                result = self.sensor.read_all()
                if result:
                    with self.sensor_lock:
                        self.latest_reading = result
            time.sleep(self.settings["update_interval_ms"] / 1000)

    # ==================== UPDATE LOOPS ====================
    def _schedule_update(self):
        if not self.running:
            return
        try:
            append_log(flow, total)
        except Exception:
            pass
        
        self._do_update()
        self.update_after_id = self.root.after(self.settings["update_interval_ms"], self._schedule_update)

    def _schedule_graph(self):
        if not self.running:
            return
        self._do_graph_update()
        self.graph_after_id = self.root.after(1000, self._schedule_graph)

    def _do_update(self):
        flow, total = self._read_sensor()
        now = datetime.datetime.now()
        self.times.append(now)
        self.flows.append(flow)
        self.totals.append(total)
        if self.mode == "live":
            self.var_flow.set(f"{flow:.2f}")
            self.var_total.set(f"{total:.3f}")
            try:
                append_log(flow, total)
            except Exception:
                pass
            # Update logs popup table if open
            if self.logs_win:
                items = list(zip(self.times, self.flows, self.totals))
                self.logs_win.update_live_table(items)

    def _do_graph_update(self):
        if self.mode != "live":
            return
        try:
            if not self.times:
                return
            window_seconds = self.settings["graph_window_sec"]
            now = datetime.datetime.now()
            cutoff = now - datetime.timedelta(seconds=window_seconds)
            xs, ys_flow, ys_total = [], [], []
            for t, f, tt in zip(self.times, self.flows, self.totals):
                if t >= cutoff:
                    xs.append(t)
                    ys_flow.append(f)
                    ys_total.append(tt)
            if not xs:
                return
            self.ax.set_facecolor('#ffffff')
            self.flow_line.set_data(xs, ys_flow)
            self.total_line.set_data(xs, ys_total)
            self.ax.set_xlim(cutoff, now)
            self.ax.relim()
            self.ax.autoscale_view()
            self.canvas.draw_idle()
            max_val = max(max(ys_flow) if ys_flow else 1, max(ys_total) if ys_total else 1)
            self.ax.set_ylim(0, max_val * 1.3)
            self.ax.set_title("Live Flow / Total", color='black', fontsize=12)
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
            self.ax.tick_params(colors='black')
            self.ax.legend(loc="upper left", facecolor='#ffffff', edgecolor='#cccccc', labelcolor='black')
            self.ax.grid(alpha=0.2, color='#e6e6e6')
            for spine in self.ax.spines.values():
                spine.set_color('#cccccc')
            self.fig.autofmt_xdate()
            self.canvas.draw_idle()
        except Exception as e:
            print(f"Graph update error: {e}", file=sys.stderr)
            
    # ==================== LOGS POPUP ====================
    def _open_logs_window(self):
        # Window exists AND is valid
        if (
            self.logs_win
            and hasattr(self.logs_win, "top")
            and self.logs_win.top.winfo_exists()
        ):
            self.logs_win.top.deiconify()
            self.logs_win.top.lift()
            self.logs_win.top.focus_force()
            return

        self.logs_win = None  # reset bad reference

        try:
            LogsWindow(self)
        except Exception as e:
            messagebox.showerror(
                "Error",
                f"Failed to open logs window:\n{e}"
            )

            
    def _switch_to_live(self):
        """Switch back to live view mode and refresh graph/table immediately."""
        self.mode = "live"
        self.current_dayfile = None

        # Force an immediate graph refresh
        try:
            self._do_graph_update()
        except Exception:
            pass

        # If logs popup is open, refresh its table with the latest live buffer
        try:
            if self.logs_win:
                items = list(zip(self.times, self.flows, self.totals))
                self.logs_win.update_live_table(items)
        except Exception:
            pass
    # ==================== LOGS HANDLING (when loaded from logs popup) ====================
    def _display_day_file(self, path, label):
        """Display day file data in main graph (called from LogsWindow)."""
        try:
            times, flows = [], []
            with open(path, "r") as f:
                rdr = csv.reader(f)
                next(rdr, None)
                for row in rdr:
                    if not row:
                        continue
                    try:
                        t = datetime.datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
                        times.append(t)
                        flows.append(float(row[1]))
                    except Exception:
                        pass
            hourly = {}
            for t, v in zip(times, flows):
                hour = t.replace(minute=0, second=0, microsecond=0)
                hourly.setdefault(hour, []).append(v)
            if hourly:
                keys = sorted(hourly.keys())
                avg = [sum(hourly[k]) / len(hourly[k]) for k in keys]
                self.ax.clear()
                self.ax.set_facecolor('#0f1724')
                self.ax.plot(keys, avg, marker="o", linewidth=2, color="#00d4ff")
                self.ax.set_title(f"{label} — Hourly Average", color='white')
                self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
                self.ax.tick_params(colors='white')
                self.ax.grid(alpha=0.2, color='#444')
                self.fig.autofmt_xdate()
                self.canvas.draw_idle()
        except Exception as e:
            print(f"Display day error: {e}", file=sys.stderr)

    # ==================== EXPORT FUNCTIONS ====================
    def _export_graph(self):
        fn = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG", "*.png")])
        if not fn:
            return
        try:
            self.fig.savefig(fn, dpi=150, facecolor='#0f1724')
            messagebox.showinfo("Saved", f"Graph saved to:\n{fn}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _export_csv(self):
        fn = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not fn:
            return
        try:
            with open(fn, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["Time", "Flow", "Total"])
                # If logs popup is open, export its table; otherwise export recent buffer
                if self.logs_win and getattr(self.logs_win, "tree", None):
                    for item in self.logs_win.tree.get_children():
                        w.writerow(self.logs_win.tree.item(item)["values"])
                else:
                    for t, fval, tot in zip(self.times, self.flows, self.totals):
                        w.writerow([t.strftime("%Y-%m-%d %H:%M:%S"), f"{fval:.2f}", f"{tot:.3f}"])
            messagebox.showinfo("Saved", f"Data exported to:\n{fn}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # ==================== CLEANUP ====================
    def _cleanup(self):
        self.running = False
        try:
            if self.update_after_id:
                self.root.after_cancel(self.update_after_id)
            if self.graph_after_id:
                self.root.after_cancel(self.graph_after_id)
        except Exception:
            pass
        if self.sensor.connected:
            self.sensor.disconnect()
        # Close logs window if open
        try:
            if self.logs_win and getattr(self.logs_win, "top", None):
                self.logs_win.top.destroy()
        except Exception:
            pass

    def _exit_now(self):
        self._cleanup()
        try:
            self.root.quit()
            self.root.destroy()
        finally:
            os._exit(0)


# ==================== MAIN ====================
if __name__ == "__main__":
    print(f"Starting MF5708 Flow Meter Dashboard on {PLATFORM_NAME}")
    print(f"Serial library available: {SERIAL_AVAILABLE}")

    if not SERIAL_AVAILABLE:
        print("\nNote: Install pyserial for RS485 hardware support:")
        print("  pip install pyserial")

    root = ctk.CTk()
    app = FlowDashboard(root)

    # Bind escape key to exit fullscreen (still available if used)
    root.bind("<Escape>", lambda e: root.attributes("-fullscreen", False))
    root.protocol("WM_DELETE_WINDOW", app._exit_now)

    try:
        root.mainloop()
    except KeyboardInterrupt:
        app._exit_now()