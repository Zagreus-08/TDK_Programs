"""
MF5708 Flow Meter Dashboard - Cross-Platform (Windows/Raspberry Pi)
RS485 Modbus RTU Communication with Simulation Mode
"""

import os
import sys
import csv
import time
import math
import random
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
    "simulate": True,           # True = simulated data, False = real RS485
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
    
    Register Map (based on typical MF5708 specs):
    - 0x0000-0x0001: Instantaneous Flow (Float, 2 registers)
    - 0x0002-0x0003: Cumulative Flow (Float, 2 registers)  
    - 0x0004-0x0005: Temperature (Float, 2 registers)
    - Function Code: 0x03 (Read Holding Registers)
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
        """Open serial connection."""
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
                print(f"[DEBUG] Serial settings: {self.serial.get_settings()}")
            
            return True
        except Exception as e:
            self.last_error = str(e)
            self.connected = False
            if DEBUG_MODE:
                print(f"[DEBUG] Connection FAILED: {e}")
            return False
    
    def disconnect(self):
        """Close serial connection."""
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
        """Calculate Modbus CRC16."""
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
        """Build Modbus RTU read holding registers request."""
        msg = bytes([
            self.slave_addr,
            0x03,  # Function code: Read Holding Registers
            (start_reg >> 8) & 0xFF,
            start_reg & 0xFF,
            (num_regs >> 8) & 0xFF,
            num_regs & 0xFF
        ])
        crc = self._calc_crc16(msg)
        msg += bytes([crc & 0xFF, (crc >> 8) & 0xFF])
        return msg
    
    def _read_registers(self, start_reg, num_regs):
        """Read holding registers from device."""
        if not self.connected or not self.serial:
            if DEBUG_MODE:
                print(f"[DEBUG] Not connected or no serial port")
            return None
        try:
            # Clear input buffer
            self.serial.reset_input_buffer()
            # Send request
            request = self._build_read_request(start_reg, num_regs)
            
            if DEBUG_MODE:
                print(f"\n[DEBUG] ===== MODBUS REQUEST =====")
                print(f"[DEBUG] Port: {self.port}, Baud: {self.baudrate}, Slave: {self.slave_addr}")
                print(f"[DEBUG] Start Register: 0x{start_reg:04X}, Num Registers: {num_regs}")
                print(f"[DEBUG] TX (hex): {' '.join(f'{b:02X}' for b in request)}")
                print(f"[DEBUG] TX (bytes): {list(request)}")
            
            self.serial.write(request)
            
            # Add small delay for device to respond
            time.sleep(0.05)
            
            # Wait for response (3 + 2*num_regs + 2 bytes)
            expected_len = 3 + 2 * num_regs + 2
            response = self.serial.read(expected_len)
            
            if DEBUG_MODE:
                print(f"[DEBUG] ===== MODBUS RESPONSE =====")
                print(f"[DEBUG] Expected: {expected_len} bytes, Received: {len(response)} bytes")
                if response:
                    print(f"[DEBUG] RX (hex): {' '.join(f'{b:02X}' for b in response)}")
                    print(f"[DEBUG] RX (bytes): {list(response)}")
                else:
                    print(f"[DEBUG] RX: NO DATA RECEIVED!")
            
            if len(response) < expected_len:
                self.last_error = f"Incomplete response: {len(response)}/{expected_len} bytes"
                if DEBUG_MODE:
                    print(f"[DEBUG] ERROR: {self.last_error}")
                return None
            # Verify CRC
            data = response[:-2]
            recv_crc = response[-2] | (response[-1] << 8)
            calc_crc = self._calc_crc16(data)
            
            if DEBUG_MODE:
                print(f"[DEBUG] CRC Check - Received: 0x{recv_crc:04X}, Calculated: 0x{calc_crc:04X}")
            
            if recv_crc != calc_crc:
                self.last_error = "CRC mismatch"
                if DEBUG_MODE:
                    print(f"[DEBUG] ERROR: CRC MISMATCH!")
                return None
            # Extract register values
            byte_count = response[2]
            values = []
            for i in range(num_regs):
                hi = response[3 + i*2]
                lo = response[4 + i*2]
                values.append((hi << 8) | lo)
            
            if DEBUG_MODE:
                print(f"[DEBUG] Byte count: {byte_count}")
                print(f"[DEBUG] Register values (raw): {values}")
                print(f"[DEBUG] Register values (hex): {[f'0x{v:04X}' for v in values]}")
            
            return values
        except Exception as e:
            self.last_error = str(e)
            if DEBUG_MODE:
                print(f"[DEBUG] EXCEPTION: {e}")
            return None

    
    def _regs_to_float(self, regs):
        """Convert 2 Modbus registers to float (Big Endian)."""
        if len(regs) < 2:
            return 0.0
        # Pack as 2 unsigned shorts, unpack as float
        raw = struct.pack('>HH', regs[0], regs[1])
        return struct.unpack('>f', raw)[0]
    
    def _regs_to_float_swapped(self, regs):
        """Convert 2 Modbus registers to float (swapped word order)."""
        if len(regs) < 2:
            return 0.0
        raw = struct.pack('>HH', regs[1], regs[0])
        return struct.unpack('>f', raw)[0]
    
    def read_all(self):
        """
        Read all sensor values.
        Returns: (flow_slpm, total_ncm, temp_c) or None on error
        """
        if DEBUG_MODE:
            print(f"\n[DEBUG] ========== READ ALL SENSOR VALUES ==========")
        
        # Read more registers to find total flow (read 16 registers)
        regs = self._read_registers(0x0000, 16)
        if regs is None:
            if DEBUG_MODE:
                print(f"[DEBUG] Failed to read registers!")
            return None
        try:
            if DEBUG_MODE:
                print(f"[DEBUG] ===== ALL REGISTERS (0x0000 - 0x000F) =====")
                for i, val in enumerate(regs):
                    print(f"[DEBUG]   Reg[{i}] (0x{i:04X}) = {val:5d} (0x{val:04X})  /100={val/100:.2f}  /10={val/10:.1f}")
                print(f"[DEBUG]")
                # Try 32-bit combinations for total flow
                print(f"[DEBUG] ===== 32-BIT COMBINATIONS (for total flow) =====")
                for i in range(0, min(8, len(regs)-1), 2):
                    val32 = regs[i] * 65536 + regs[i+1]
                    val32_swap = regs[i+1] * 65536 + regs[i]
                    print(f"[DEBUG]   Reg[{i}:{i+1}] = {val32} (normal) | {val32_swap} (swapped)")
            
            # MF5708 Register mapping:
            # Reg[3] = Flow * 1000 = 4450 -> 4.45 SLPM (divide by 1000)
            flow = regs[3] / 1000.0
            
            # Total flow - try different register combinations
            # Show all options in debug so user can identify correct one
            total_32bit = regs[0] * 65536 + regs[1]  # Try regs 0-1 as 32-bit
            if total_32bit == 0 or total_32bit == 1:
                total_32bit = regs[4] * 65536 + regs[5]  # Try regs 4-5
            if total_32bit == 0:
                total_32bit = regs[6] * 65536 + regs[7]  # Try regs 6-7
            
            total = total_32bit / 1000.0  # Convert to NCM
            
            # No temperature sensor on this device
            temp = 0.0
            
            if DEBUG_MODE:
                print(f"[DEBUG] ===== FINAL VALUES =====")
                print(f"[DEBUG] Flow:  {flow:.2f} SLPM (from reg[3]={regs[3]} / 1000)")
                print(f"[DEBUG] Total: {total:.3f} NCM (32-bit value: {total_32bit})")
                print(f"[DEBUG] ================================\n")
            
            return (flow, total, temp)
        except Exception as e:
            self.last_error = str(e)
            if DEBUG_MODE:
                print(f"[DEBUG] Parse error: {e}")
            return None


# ============== SIMULATOR ==============
class FlowSimulator:
    """Simulates MF5708 sensor data for testing without hardware."""
    
    def __init__(self):
        self.total_flow = 0.0
        self.battery = 100.0
        self.temp = 25.0
        self.last_temp_update = 0
        self.start_time = time.time()
        
    def read_all(self):
        """Generate simulated sensor values."""
        t = time.time()
        # Simulate realistic flow pattern with some variation
        base_flow = 5.0 + 3.0 * math.sin((t - self.start_time) / 30.0)
        noise = random.uniform(-0.6, 0.6)
        flow = max(0.0, base_flow + noise)
        
        # Accumulate total flow (convert SLPM to NCM: 1 SLPM = 0.001 NCM/sec)
        self.total_flow += flow * 0.001
        
        # Slowly drain battery
        self.battery = max(0.0, self.battery - random.uniform(0.0005, 0.0025))
        
        # Update temperature occasionally
        if t - self.last_temp_update > 5:
            self.temp = 24.0 + random.uniform(-1.2, 1.2)
            self.last_temp_update = t
            
        return (round(flow, 2), round(self.total_flow, 3), round(self.temp, 1))
    
    def get_battery_text(self):
        """Get battery status text."""
        if self.battery > 50:
            return f"{self.battery:.0f}% (Good)"
        elif self.battery > 20:
            return f"{self.battery:.0f}% (Low)"
        else:
            return f"{self.battery:.0f}% (Replace)"


# ============== MAIN DASHBOARD ==============
class FlowDashboard:
    def __init__(self, root):
        self.root = root
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # Window setup
        self.root.title(f"MF5708 Flow Meter Dashboard - {PLATFORM_NAME}")
        self.root.geometry("1400x900")
        self.root.minsize(1200, 700)
        
        # State
        self.running = True
        self.update_after_id = None
        self.graph_after_id = None
        self.mode = "live"  # "live", "day", "month"
        self.current_month = None
        self.current_dayfile = None
        
        # Settings
        self.settings = DEFAULT_SETTINGS.copy()
        self.settings["com_port"] = self._auto_detect_port()
        
        # Sensor/Simulator
        self.simulator = FlowSimulator()
        self.sensor = MF5708Sensor()
        self.connection_status = "Disconnected"
        
        # Live data buffers
        self.times = collections.deque(maxlen=MAX_BUFFER_POINTS)
        self.flows = collections.deque(maxlen=MAX_BUFFER_POINTS)
        self.totals = collections.deque(maxlen=MAX_BUFFER_POINTS)
        
        # Build UI
        self._build_ui()
        
        # Start loops
        self._load_months()
        self._schedule_update()
        self._schedule_graph()
    
    def _auto_detect_port(self):
        """Auto-detect the most likely serial port."""
        ports = get_available_ports()
        if not ports:
            return ""
        # Prefer USB serial adapters
        for p in ports:
            if "USB" in p.upper() or "ttyUSB" in p:
                return p
        return ports[0]

    
    # ==================== UI BUILDING ====================
    def _build_ui(self):
        # Main layout: 3 columns
        self.root.grid_columnconfigure(0, weight=0)  # Settings panel
        self.root.grid_columnconfigure(1, weight=2)  # Main display
        self.root.grid_columnconfigure(2, weight=1)  # Logs panel
        self.root.grid_rowconfigure(0, weight=1)
        
        # Left: Settings Panel
        self._build_settings_panel()
        
        # Center: Metrics + Graph
        self._build_main_panel()
        
        # Right: Logs Browser
        self._build_logs_panel()
    
    def _build_settings_panel(self):
        """Build the settings/connection panel."""
        panel = ctk.CTkFrame(self.root, width=280, corner_radius=8)
        panel.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)
        panel.grid_propagate(False)
        
        # Title
        ctk.CTkLabel(panel, text="⚙️ Settings", font=ctk.CTkFont(size=18, weight="bold")
                    ).pack(anchor="w", padx=12, pady=(12, 8))
        
        # Platform info
        info_frame = ctk.CTkFrame(panel, fg_color="#1a2332")
        info_frame.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(info_frame, text=f"Platform: {PLATFORM_NAME}", 
                    font=ctk.CTkFont(size=11)).pack(anchor="w", padx=8, pady=4)
        
        # Connection Status
        self.status_label = ctk.CTkLabel(panel, text="● Simulation Mode", 
                                         text_color="#00ff88", font=ctk.CTkFont(size=12, weight="bold"))
        self.status_label.pack(anchor="w", padx=12, pady=(12, 6))
        
        # Mode Toggle
        ctk.CTkLabel(panel, text="Data Source:", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=12, pady=(8, 2))
        self.mode_var = tk.StringVar(value="simulate")
        mode_frame = ctk.CTkFrame(panel, fg_color="transparent")
        mode_frame.pack(fill="x", padx=12)
        ctk.CTkRadioButton(mode_frame, text="Simulation", variable=self.mode_var, 
                          value="simulate", command=self._on_mode_change).pack(anchor="w", pady=2)
        ctk.CTkRadioButton(mode_frame, text="RS485 Hardware", variable=self.mode_var,
                          value="hardware", command=self._on_mode_change).pack(anchor="w", pady=2)

        
        # Serial Port Selection
        ctk.CTkLabel(panel, text="Serial Port:", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=12, pady=(12, 2))
        port_frame = ctk.CTkFrame(panel, fg_color="transparent")
        port_frame.pack(fill="x", padx=12)
        
        self.port_combo = ctk.CTkComboBox(port_frame, values=get_available_ports() or ["No ports found"],
                                          width=180, state="readonly")
        if self.settings["com_port"]:
            self.port_combo.set(self.settings["com_port"])
        self.port_combo.pack(side="left", pady=4)
        
        ctk.CTkButton(port_frame, text="🔄", width=40, command=self._refresh_ports).pack(side="left", padx=4)
        
        # Baud Rate
        ctk.CTkLabel(panel, text="Baud Rate:", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=12, pady=(8, 2))
        self.baud_combo = ctk.CTkComboBox(panel, values=["9600", "19200", "38400", "57600", "115200"],
                                          width=180, state="readonly")
        self.baud_combo.set(str(self.settings["baud_rate"]))
        self.baud_combo.pack(anchor="w", padx=12, pady=4)
        
        # Slave Address
        ctk.CTkLabel(panel, text="Slave Address (1-247):", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=12, pady=(8, 2))
        self.addr_entry = ctk.CTkEntry(panel, width=180)
        self.addr_entry.insert(0, str(self.settings["slave_address"]))
        self.addr_entry.pack(anchor="w", padx=12, pady=4)
        
        # Connect/Disconnect Button
        self.connect_btn = ctk.CTkButton(panel, text="Connect", fg_color="#28a745",
                                         command=self._toggle_connection)
        self.connect_btn.pack(fill="x", padx=12, pady=(16, 8))
        
        # Update Interval
        ctk.CTkLabel(panel, text="Update Interval (ms):", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=12, pady=(16, 2))
        self.interval_slider = ctk.CTkSlider(panel, from_=200, to=5000, number_of_steps=48,
                                             command=self._on_interval_change)
        self.interval_slider.set(self.settings["update_interval_ms"])
        self.interval_slider.pack(fill="x", padx=12, pady=4)
        self.interval_label = ctk.CTkLabel(panel, text=f"{self.settings['update_interval_ms']} ms")
        self.interval_label.pack(anchor="w", padx=12)
        
        # Graph Window
        ctk.CTkLabel(panel, text="Graph Window (sec):", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=12, pady=(12, 2))
        self.window_slider = ctk.CTkSlider(panel, from_=30, to=300, number_of_steps=27,
                                           command=self._on_window_change)
        self.window_slider.set(self.settings["graph_window_sec"])
        self.window_slider.pack(fill="x", padx=12, pady=4)
        self.window_label = ctk.CTkLabel(panel, text=f"{self.settings['graph_window_sec']} sec")
        self.window_label.pack(anchor="w", padx=12)

        
        # Error display
        self.error_label = ctk.CTkLabel(panel, text="", text_color="#ff6b6b", 
                                        font=ctk.CTkFont(size=10), wraplength=250)
        self.error_label.pack(anchor="w", padx=12, pady=(12, 4))
    
    def _build_main_panel(self):
        """Build the main metrics and graph panel."""
        panel = ctk.CTkFrame(self.root, corner_radius=8)
        panel.grid(row=0, column=1, sticky="nsew", padx=6, pady=12)
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_columnconfigure(0, weight=1)
        
        # Metrics Cards Row (only Flow Rate and Total Flow - no temp/battery on this device)
        card_row = ctk.CTkFrame(panel, fg_color="#1f2a44", corner_radius=6)
        card_row.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 6))
        card_row.grid_columnconfigure((0, 1), weight=1)
        
        self.var_flow = tk.StringVar(self.root, "0.00")
        self.var_total = tk.StringVar(self.root, "0.000")
        
        def make_card(parent, var, title, unit="", color="#223153"):
            f = ctk.CTkFrame(parent, fg_color=color, corner_radius=8)
            ctk.CTkLabel(f, text=title, font=ctk.CTkFont(size=11)).pack(anchor="w", padx=10, pady=(8, 0))
            val_frame = ctk.CTkFrame(f, fg_color="transparent")
            val_frame.pack(anchor="w", padx=10, pady=(2, 8))
            ctk.CTkLabel(val_frame, textvariable=var, font=ctk.CTkFont(size=28, weight="bold"),
                        text_color="#00d4ff").pack(side="left")
            if unit:
                ctk.CTkLabel(val_frame, text=unit, font=ctk.CTkFont(size=12),
                            text_color="#888").pack(side="left", padx=(4, 0))
            return f
        
        make_card(card_row, self.var_flow, "Flow Rate", "SLPM").grid(row=0, column=0, padx=6, pady=8, sticky="nsew")
        make_card(card_row, self.var_total, "Total Flow", "NCM").grid(row=0, column=1, padx=6, pady=8, sticky="nsew")

        
        # Graph Panel
        graph_panel = ctk.CTkFrame(panel, fg_color="#0f1724", corner_radius=6)
        graph_panel.grid(row=1, column=0, sticky="nsew", padx=8, pady=(6, 8))
        graph_panel.grid_rowconfigure(0, weight=1)
        graph_panel.grid_columnconfigure(0, weight=1)
        
        # Matplotlib figure
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
        self.ax.grid(alpha=0.2, color='#444')
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=graph_panel)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        
        # Control Buttons Row
        ctrl = ctk.CTkFrame(panel, fg_color="#101827", corner_radius=6)
        ctrl.grid(row=2, column=0, sticky="ew", padx=8, pady=(6, 8))
        ctrl.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)
        
        ctk.CTkButton(ctrl, text=" Export PNG", command=self._export_graph).grid(row=0, column=0, padx=6, pady=8)
        ctk.CTkButton(ctrl, text=" Export CSV", command=self._export_csv).grid(row=0, column=1, padx=6, pady=8)
        ctk.CTkButton(ctrl, text=" Live View", command=self._switch_to_live).grid(row=0, column=2, padx=6, pady=8)
        ctk.CTkButton(ctrl, text=" Fullscreen", command=self._toggle_fullscreen).grid(row=0, column=3, padx=6, pady=8)
        ctk.CTkButton(ctrl, text=" Exit", fg_color="#dc3545", command=self._exit_now).grid(row=0, column=4, padx=6, pady=8)

    
    def _build_logs_panel(self):
        """Build the logs browser panel."""
        panel = ctk.CTkFrame(self.root, corner_radius=8)
        panel.grid(row=0, column=2, sticky="nsew", padx=(6, 12), pady=12)
        panel.grid_rowconfigure(4, weight=1)
        panel.grid_columnconfigure(0, weight=1)
        
        ctk.CTkLabel(panel, text="📁 Data Logs", font=ctk.CTkFont(size=16, weight="bold")
                    ).grid(row=0, column=0, sticky="w", padx=12, pady=(12, 8))
        
        # Month listbox
        ctk.CTkLabel(panel, text="Month:", font=ctk.CTkFont(size=11)).grid(row=1, column=0, sticky="w", padx=12)
        self.month_listbox = tk.Listbox(panel, height=4, exportselection=False, bg="#1a1a2e", fg="white",
                                        selectbackground="#3b82f6", font=("Consolas", 10))
        self.month_listbox.grid(row=2, column=0, sticky="ew", padx=12, pady=(2, 8))
        self.month_listbox.bind("<<ListboxSelect>>", lambda e: self._on_month_select())
        
        # Day listbox
        ctk.CTkLabel(panel, text="Day:", font=ctk.CTkFont(size=11)).grid(row=3, column=0, sticky="w", padx=12)
        self.day_listbox = tk.Listbox(panel, height=5, exportselection=False, bg="#1a1a2e", fg="white",
                                      selectbackground="#3b82f6", font=("Consolas", 10))
        self.day_listbox.grid(row=4, column=0, sticky="nsew", padx=12, pady=(2, 8))
        
        # Load buttons
        btn_frame = ctk.CTkFrame(panel, fg_color="transparent")
        btn_frame.grid(row=5, column=0, sticky="ew", padx=12, pady=8)
        btn_frame.grid_columnconfigure((0, 1, 2), weight=1)
        
        ctk.CTkButton(btn_frame, text="Load Day", width=80, command=self._load_selected_day).grid(row=0, column=0, padx=2)
        ctk.CTkButton(btn_frame, text="Load Month", width=80, command=self._load_selected_month).grid(row=0, column=1, padx=2)
        ctk.CTkButton(btn_frame, text="Refresh", width=80, command=self._load_months).grid(row=0, column=2, padx=2)
        
        # Data table
        table_frame = ctk.CTkFrame(panel, fg_color="#0f1724")
        table_frame.grid(row=6, column=0, sticky="nsew", padx=12, pady=(8, 12))
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)
        
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#1a1a2e", foreground="white", fieldbackground="#1a1a2e",
                       font=("Consolas", 9))
        style.configure("Treeview.Heading", background="#2d3748", foreground="white", font=("Arial", 9, "bold"))
        
        self.tree = ttk.Treeview(table_frame, columns=("Time", "Flow", "Total"), 
                                 show="headings", height=12)
        for c, w in [("Time", 140), ("Flow", 100), ("Total", 110)]:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="center")
        self.tree.grid(row=0, column=0, sticky="nsew")
        
        sb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=sb.set)
        sb.grid(row=0, column=1, sticky="ns")

    
    # ==================== SETTINGS CALLBACKS ====================
    def _on_mode_change(self):
        """Handle simulation/hardware mode change."""
        if self.mode_var.get() == "simulate":
            self.settings["simulate"] = True
            self.status_label.configure(text="● Simulation Mode", text_color="#00ff88")
            self.error_label.configure(text="")
        else:
            self.settings["simulate"] = False
            if not self.sensor.connected:
                self.status_label.configure(text="● Disconnected", text_color="#ff6b6b")
    
    def _refresh_ports(self):
        """Refresh available serial ports."""
        ports = get_available_ports()
        self.port_combo.configure(values=ports if ports else ["No ports found"])
        if ports:
            self.port_combo.set(ports[0])
    
    def _on_interval_change(self, value):
        """Handle update interval slider change."""
        val = int(value)
        self.settings["update_interval_ms"] = val
        self.interval_label.configure(text=f"{val} ms")
    
    def _on_window_change(self, value):
        """Handle graph window slider change."""
        val = int(value)
        self.settings["graph_window_sec"] = val
        self.window_label.configure(text=f"{val} sec")
    
    def _toggle_connection(self):
        """Connect or disconnect from the sensor."""
        if self.sensor.connected:
            self.sensor.disconnect()
            self.connect_btn.configure(text="Connect", fg_color="#28a745")
            self.status_label.configure(text="● Disconnected", text_color="#ff6b6b")
            self.error_label.configure(text="")
        else:
            # Get settings from UI
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
            
            # Configure and connect
            self.sensor.port = port
            self.sensor.baudrate = baud
            self.sensor.slave_addr = addr
            
            if self.sensor.connect():
                self.connect_btn.configure(text="Disconnect", fg_color="#dc3545")
                self.status_label.configure(text=f"● Connected: {port}", text_color="#00ff88")
                self.error_label.configure(text="")
                self.mode_var.set("hardware")
                self.settings["simulate"] = False
            else:
                self.error_label.configure(text=f"Error: {self.sensor.last_error}")

    
    # ==================== SENSOR READING ====================
    def _read_sensor(self):
        """Read sensor data (simulation or hardware)."""
        if self.settings["simulate"]:
            flow, total, _ = self.simulator.read_all()
            return flow, total
        else:
            if not self.sensor.connected:
                return 0.0, 0.0
            result = self.sensor.read_all()
            if result is None:
                self.error_label.configure(text=f"Read error: {self.sensor.last_error}")
                return 0.0, 0.0
            flow, total, _ = result
            return round(flow, 2), round(total, 3)
    
    # ==================== UPDATE LOOPS ====================
    def _schedule_update(self):
        if not self.running:
            return
        self._do_update()
        self.update_after_id = self.root.after(self.settings["update_interval_ms"], self._schedule_update)
    
    def _schedule_graph(self):
        if not self.running:
            return
        self._do_graph_update()
        self.graph_after_id = self.root.after(1000, self._schedule_graph)
    
    def _do_update(self):
        """Main update: read sensor, update buffers, update UI, log data."""
        flow, total = self._read_sensor()
        now = datetime.datetime.now()
        
        # Append to live buffers
        self.times.append(now)
        self.flows.append(flow)
        self.totals.append(total)
        
        # Update UI if in live mode
        if self.mode == "live":
            self.var_flow.set(f"{flow:.2f}")
            self.var_total.set(f"{total:.3f}")
            
            # Log to CSV
            try:
                append_log(flow, total)
            except Exception:
                pass
            
            # Update live table
            self._update_live_table()
    
    def _update_live_table(self):
        """Update the live data table with recent readings."""
        try:
            for r in self.tree.get_children():
                self.tree.delete(r)
            items = list(zip(self.times, self.flows, self.totals))
            tail = items[-RECENT_TABLE_SIZE:]
            for t, f, tot in reversed(tail):  # Most recent first
                self.tree.insert("", tk.END, values=(
                    t.strftime("%Y-%m-%d %H:%M:%S"), f"{f:.2f}", f"{tot:.3f}"
                ))
        except Exception as e:
            print(f"Live table error: {e}", file=sys.stderr)

    
    def _do_graph_update(self):
        """Update the live graph with scrolling window."""
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
            
            self.ax.clear()
            self.ax.set_facecolor('#0f1724')
            
            # Plot lines with better colors
            self.ax.plot(xs, ys_flow, color="#00d4ff", linewidth=2, label="Flow (SLPM)")
            self.ax.plot(xs, ys_total, color="#00ff88", linewidth=1.5, label="Total (NCM)")
            
            # Scrolling window
            self.ax.set_xlim(cutoff, now)
            max_val = max(max(ys_flow) if ys_flow else 1, max(ys_total) if ys_total else 1)
            self.ax.set_ylim(0, max_val * 1.3)
            
            # Styling
            self.ax.set_title("Live Flow / Total", color='white', fontsize=12)
            self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
            self.ax.tick_params(colors='white')
            self.ax.legend(loc="upper left", facecolor='#1a1a2e', edgecolor='#333', labelcolor='white')
            self.ax.grid(alpha=0.2, color='#444')
            for spine in self.ax.spines.values():
                spine.set_color('#333')
            
            self.fig.autofmt_xdate()
            self.canvas.draw_idle()
            
        except Exception as e:
            print(f"Graph update error: {e}", file=sys.stderr)

    
    # ==================== LOGS BROWSER ====================
    def _load_months(self):
        """Load available months from logs directory."""
        self.month_listbox.delete(0, tk.END)
        try:
            months = sorted([d for d in os.listdir(LOGS_DIR)
                           if os.path.isdir(os.path.join(LOGS_DIR, d)) and d != "hourly_summary"])
            for m in months:
                self.month_listbox.insert(tk.END, m)
        except Exception:
            pass
    
    def _on_month_select(self):
        """Handle month selection."""
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
        except Exception:
            pass
    
    def _load_selected_day(self):
        """Load and display selected day's data."""
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
        
        self.mode = "day"
        self.current_dayfile = path
        self._display_day_file(path, f"Day: {dayfile}")
    
    def _display_day_file(self, path, label):
        """Display day file data in table and graph."""
        try:
            for r in self.tree.get_children():
                self.tree.delete(r)
            
            times, flows = [], []
            with open(path, "r") as f:
                rdr = csv.reader(f)
                next(rdr, None)
                for row in rdr:
                    if not row:
                        continue
                    self.tree.insert("", tk.END, values=row)
                    try:
                        t = datetime.datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
                        times.append(t)
                        flows.append(float(row[1]))
                    except Exception:
                        pass
            
            # Hourly aggregation for graph
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

    
    def _load_selected_month(self):
        """Load and display monthly summary."""
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
        
        # Update table
        for r in self.tree.get_children():
            self.tree.delete(r)
        for d, af, tf in zip(days, avg_flows, totals):
            self.tree.insert("", tk.END, values=(d.strftime("%Y-%m-%d"), f"{af:.2f}", f"{tf:.3f}", "-", "-"))
        
        # Plot monthly summary
        self.ax.clear()
        self.ax.set_facecolor('#0f1724')
        self.ax.bar(days, totals, color="#00ff88", alpha=0.7, label="Total Flow (NCM)")
        self.ax.plot(days, avg_flows, color="#00d4ff", marker="o", linewidth=2, label="Avg Flow (SLPM)")
        self.ax.set_title(f"Monthly Summary ({month})", color='white')
        self.ax.tick_params(colors='white')
        self.ax.legend(facecolor='#1a1a2e', edgecolor='#333', labelcolor='white')
        self.ax.grid(alpha=0.2, color='#444')
        self.fig.autofmt_xdate()
        self.canvas.draw_idle()
        self.mode = "month"
    
    def _switch_to_live(self):
        """Switch back to live view mode."""
        self.mode = "live"
        self.current_dayfile = None
        self._update_live_table()
    
    # ==================== EXPORT FUNCTIONS ====================
    def _export_graph(self):
        """Export current graph as PNG."""
        fn = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG", "*.png")])
        if not fn:
            return
        try:
            self.fig.savefig(fn, dpi=150, facecolor='#0f1724')
            messagebox.showinfo("Saved", f"Graph saved to:\n{fn}")
        except Exception as e:
            messagebox.showerror("Error", str(e))
    
    def _export_csv(self):
        """Export current table data as CSV."""
        fn = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not fn:
            return
        try:
            with open(fn, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["Time", "Flow", "Total"])
                for item in self.tree.get_children():
                    w.writerow(self.tree.item(item)["values"])
            messagebox.showinfo("Saved", f"Data exported to:\n{fn}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    
    def _toggle_fullscreen(self):
        """Toggle fullscreen mode."""
        current = self.root.attributes("-fullscreen")
        self.root.attributes("-fullscreen", not current)
    
    # ==================== CLEANUP ====================
    def _cleanup(self):
        """Clean up resources."""
        self.running = False
        try:
            if self.update_after_id:
                self.root.after_cancel(self.update_after_id)
            if self.graph_after_id:
                self.root.after_cancel(self.graph_after_id)
        except Exception:
            pass
        
        # Disconnect sensor
        if self.sensor.connected:
            self.sensor.disconnect()
    
    def _exit_now(self):
        """Exit the application."""
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
    
    # Bind escape key to exit fullscreen
    root.bind("<Escape>", lambda e: root.attributes("-fullscreen", False))
    root.protocol("WM_DELETE_WINDOW", app._exit_now)
    
    try:
        root.mainloop()
    except KeyboardInterrupt:
        app._exit_now()
