#!/usr/bin/env python3
"""
FINAL SCRIPT: NO Z, NO DAQ, NO DOORS, NO SERIAL
XY HOMING + SIMPLE SNAKE SCAN WITH GUI CONTROL
- Direction mapping and switch polarity handling applied
- Y move stops if Y- limit is reached mid-step
- No default scan params: loaded/saved from scan_config.json in script folder
- Config is saved automatically when a scan is started

Notes:
- Per-pin polarity mapping is used: PER_PIN_ACTIVE_HIGH maps a pin to True if
  the pin reads '1' when the switch is pressed (active-high). If False the pin
  is active-low (reads 0 when pressed).
- By default the 4 limit pins are inverted relative to SWITCH_ACTIVE_HIGH so
  they will display 0 when unpressed and 1 when pressed (typical pull-up wiring).
"""

from time import sleep
import time
import pigpio
import threading
import tkinter as tk
import tkinter.font as TkFont
from tkinter import messagebox
import os
import json
import traceback
from RpiMotorLib import RpiMotorLib

# New imports for keyboard launching
import subprocess
import shutil

# Serial communication for sending data to plotter
import serial

# Try to import MCC 128 DAQ HAT (like mignev6.py uses)
try:
    from daqhats import mcc128, OptionFlags, HatIDs, AnalogInputMode, AnalogInputRange, hat_list, HatError
    try:
        from daqhats_utils import chan_list_to_mask
    except Exception:
        def chan_list_to_mask(chan_list):
            """Convert a list of channel numbers to a channel mask (fallback)."""
            mask = 0
            for chan in chan_list:
                mask |= (1 << chan)
            return mask
    MCC128_AVAILABLE = True
except ImportError:
    MCC128_AVAILABLE = False
    print("Warning: daqhats not installed. Install with: pip install daqhats")

# -----------------------
# Globals / Config file
# -----------------------
pi = pigpio.pi()

# Serial port for sending data to plotter
serial_port = None
try:
    # Try common serial ports for USB-to-TTL adapter
    possible_ports = ["/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyACM0", "/dev/ttyACM1"]
    for port in possible_ports:
        try:
            serial_port = serial.Serial(port, 115200, timeout=1)
            print(f" Serial port opened: {port} for data transmission")
            break
        except (serial.SerialException, FileNotFoundError):
            continue
    if serial_port is None:
        print("  Warning: No serial port found for data transmission. Running without serial output.")
except Exception as e:
    print(f"Serial port error: {e}")
    serial_port = None

# ===========================================================
# MCC128 Dual HAT Configuration
# ===========================================================

daq_device = None
daq_channel = None
DAQ_TYPE = None

hat0 = None
hat1 = None

if MCC128_AVAILABLE:
    try:
        hats = hat_list(filter_by_id=HatIDs.MCC_128)

        if len(hats) < 2:
            raise Exception(f"Found only {len(hats)} MCC128 HAT(s). Two are required.")

        # Open both HATs
        hat0 = mcc128(hats[0].address)
        hat1 = mcc128(hats[1].address)

        # Configure both
        for h in (hat0, hat1):
            h.a_in_mode_write(AnalogInputMode.SE)
            h.a_in_range_write(AnalogInputRange.BIP_10V)

        # Keep these variables so the rest of the program still works
        daq_device = hat0
        daq_channel = [0]
        DAQ_TYPE = "MCC128"

        print(f"✓ MCC128 #0 initialized (Address {hats[0].address})")
        print(f"✓ MCC128 #1 initialized (Address {hats[1].address})")

    except Exception as e:
        print(f"Could not initialize MCC128 HATs: {e}")
        daq_device = None

def read_dual_channels():
    """
    Read CH0 from both MCC128 HATs.
    Returns:
        daq1, daq2
    """

    daq1 = 0.0
    daq2 = 0.0

    try:
        if hat0 is not None:
            daq1 = hat0.a_in_read(0)

        if hat1 is not None:
            daq2 = hat1.a_in_read(0)

    except Exception as e:
        print(f"DAQ Read Error: {e}")

    return daq1, daq2

# Try to initialize I2C ADC (ADS1115) if MCC128 not available
if daq_device is None and I2C_ADC_AVAILABLE:
    try:
        i2c = busio.I2C(board.SCL, board.SDA)
        ads = ADS.ADS1115(i2c)
        # Use channel A0 (you can change this to A1, A2, A3 as needed)
        daq_channel = AnalogIn(ads, ADS.P0)
        daq_device = ads
        DAQ_TYPE = 'ADS1115'
        print(f" ADS1115 ADC initialized on I2C")
        print(f"  Reading from channel A0")
        print(f"  Voltage range: 0-5V (adjustable with gain)")
    except Exception as e:
        print(f"Could not initialize ADS1115: {e}")
        I2C_ADC_AVAILABLE = False

# If I2C ADC failed, try SPI ADC (MCP3008)
if daq_device is None and SPI_AVAILABLE:
    try:
        spi = spidev.SpiDev()
        spi.open(0, 0)  # Bus 0, Device 0
        spi.max_speed_hz = 1350000
        daq_device = spi
        daq_channel = 0  # Channel 0 (you can change to 0-7 for MCP3008)
        DAQ_TYPE = 'MCP3008'
        print(f" MCP3008 ADC initialized on SPI")
        print(f"  Reading from channel {daq_channel}")
        print(f"  Voltage range: 0-3.3V")
    except Exception as e:
        print(f"Could not initialize MCP3008: {e}")
        SPI_AVAILABLE = False

if daq_device is None:
    print("=" * 60)
    print("ERROR: No DAQ/ADC device found!")
    print("=" * 60)
    print("Supported devices:")
    print("  - MCC 128 DAQ HAT: pip install daqhats")
    print("  - ADS1115 (I2C): pip install adafruit-circuitpython-ads1x15")
    print("  - MCP3008 (SPI): pip install spidev")
    print("")
    print("Please connect a DAQ device and restart the program.")
    print("Scanning will not work without a sensor!")
    print("=" * 60)

# Configure switch polarity:
# Set to True if switches read '1' when pressed (active-high).
# Set to False if switches read '0' when pressed (active-low).
# This is the "base" polarity used for the EMG switch; limit pins are set
# relative to this in PER_PIN_ACTIVE_HIGH (below).
SWITCH_ACTIVE_HIGH = False
SWITCH_ACTIVE_LOW = False

# Direction tuples are (motor_x1_dir, motor_x2_dir)
DIR_MAP = {
    "DOWN":  (1, 0),
    "UP":    (0, 1),
    "LEFT":  (0, 0),
    "RIGHT": (1, 1),
}

# Try to determine script directory for config file
try:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except Exception:
    SCRIPT_DIR = os.getcwd()
CONFIG_FILE = os.path.join(SCRIPT_DIR, "scan_config.json")

def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            if not isinstance(cfg, dict):
                return {}
            return cfg
    except FileNotFoundError:
        return {}
    except Exception as e:
        print("load_config: failed to read config:", e)
        return {}

def save_config(cfg):
    try:
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        try:
            os.replace(tmp, CONFIG_FILE)
        except Exception:
            if os.path.exists(CONFIG_FILE):
                os.remove(CONFIG_FILE)
            os.rename(tmp, CONFIG_FILE)
    except Exception as e:
        print("save_config: failed to write config:", e)

# -----------------------
# Linear Motion (GT2 Belt 2mm pitch + 20T Pulley)
# -----------------------
MICROSTEPS = 4               # MKS Servo57c set mstep = 4 (hardware)
MOTOR_FULL_STEPS = 200        # typical 1.8  stepper

BELT_PITCH_MM = 2.0
PULLEY_TEETH = 20
DISTANCE_PER_REV_MM = BELT_PITCH_MM * PULLEY_TEETH   # 40.0 mm

PULSES_PER_REV = MOTOR_FULL_STEPS * MICROSTEPS      # 200 * 4 = 800
PULSES_PER_MM = PULSES_PER_REV / DISTANCE_PER_REV_MM # 800 / 40 = 20.0

def mm_to_pulses(mm: float) -> int:
    return int(round(mm * PULSES_PER_MM))

def pulses_to_mm(pulses: int) -> float:
    return pulses / PULSES_PER_MM

# -----------------------
# Serial Data Transmission (X,Y only - Z readings done by plotter)
# -----------------------
def send_serial_data(x, y, daq1, daq2, filename):
    """
    Send X, Y, DAQ1, DAQ2 and Filename over serial.
    """
    global serial_port
    # Format: x,y,daq1,daq2,filename
    data = f"{x:.3f},{y:.3f},{daq1:.6f},{daq2:.6f},{filename}\n"

    print(data.strip())

    if serial_port and serial_port.is_open:
        try:
            serial_port.write(data.encode("ascii"))
            serial_port.flush()
        except Exception as e:
            print(f"Serial send error: {e}")

# -----------------------
# DAQ/ADC Reading (REMOVED - Now done by plotter)
# -----------------------
# The V10 scanner no longer reads sensor data directly.
# Z and Z2 readings are now performed by the V1_Nivio_S_Realtime_Plotter
# which has its own MCC 128 DAQ HAT connection.
# The scanner only sends X,Y position data via serial.


# -----------------------
# Motion Conversion (RPM <-> Hz)
# -----------------------
def rpm_to_hz(rpm: float) -> int:
    # Convert motor RPM to step pulse frequency (Hz)
    # pulses_per_rev * rpm / 60 = pulses per second (Hz)
    return int((rpm * PULSES_PER_REV) / 60.0)

def hz_to_rpm(hz: float) -> float:
    return (hz * 60.0) / PULSES_PER_REV

# -----------------------
# Port Mapping
# -----------------------
class PortDefineClass:
    DIR1 = 24
    STEP1 = 25

    DIR2 = 18
    STEP2 = 23

    # NOTE: keep these consistent with your hardware wiring
    X_pos_limit = 14     # X+
    Y_pos_limit = 17     # Y+
    X_neg_limit = 15     # X-
    Y_neg_limit = 19     # Y-

    SWITCH = 5         # Emergency switch (EMG)

# -----------------------
# Per-pin polarity mapping
# -----------------------
# Build map: by default, set limit pins opposite of SWITCH_ACTIVE_HIGH so that
# unpressed = 0, pressed = 1 (typical pull-up wiring).
PER_PIN_ACTIVE_HIGH = {
    PortDefineClass.X_pos_limit: not SWITCH_ACTIVE_HIGH,
    PortDefineClass.X_neg_limit: not SWITCH_ACTIVE_HIGH,
    PortDefineClass.Y_pos_limit: not SWITCH_ACTIVE_HIGH,
    PortDefineClass.Y_neg_limit: not SWITCH_ACTIVE_HIGH,
    PortDefineClass.SWITCH:not SWITCH_ACTIVE_HIGH,
}

def gpio_active(pin):
    """Return True if the logical 'pressed' state is active for given pin,
    consulting PER_PIN_ACTIVE_HIGH for per-pin polarity (falls back to SWITCH_ACTIVE_HIGH)."""
    try:
        raw = pi.read(pin)
    except Exception:
        raw = 0
    active_high = PER_PIN_ACTIVE_HIGH.get(pin, SWITCH_ACTIVE_HIGH)
    return bool(raw) if active_high else not bool(raw)

# -----------------------
# Global Status
# -----------------------
class StatusDataClass:
    x_offset = 0
    y_offset = 0
    fn = "result"

# -----------------------
# System Functions
# -----------------------
class SystemFuncClass:
    stop_flag = False

    def GPIO_Init(self):
        """
        Initialize GPIO pins and pull-ups/pull-downs.
        Emergency SWITCH is configured as pull-up by default.
        """
        try:
            if hasattr(pi, "connected") and not pi.connected:
                print("WARNING: pigpio not connected (pi.connected == False). Ensure pigpiod is running.")
        except Exception:
            print("WARNING: Could not determine pigpio connection status. Continuing.")

        limit_pins = (
            PortDefineClass.X_pos_limit,
            PortDefineClass.Y_pos_limit,
            PortDefineClass.X_neg_limit,
            PortDefineClass.Y_neg_limit,
        )
        for p in limit_pins:
            try:
                pi.set_mode(p, pigpio.INPUT)
                # Use pull-up as your wiring expects (typical)
                pi.set_pull_up_down(p, pigpio.PUD_UP)
            except Exception as e:
                print(f"GPIO_Init: Failed to setup pin {p}: {e}")

        try:
            pi.set_mode(PortDefineClass.SWITCH, pigpio.INPUT)
            pi.set_pull_up_down(PortDefineClass.SWITCH, pigpio.PUD_UP)
        except Exception as e:
            print(f"GPIO_Init: Failed to setup emergency SWITCH pin {PortDefineClass.SWITCH}: {e}")

    def AllStop(self):
        SystemFuncClass.stop_flag = True
        try:
            pi.set_PWM_dutycycle(PortDefineClass.STEP1, 0)
            pi.set_PWM_dutycycle(PortDefineClass.STEP2, 0)
        except Exception:
            pass
        print("!!! EMERGENCY STOP !!!")

    def exitProgram(self):
        self.AllStop()
        # Close serial port if open
        global serial_port
        if serial_port and serial_port.is_open:
            try:
                serial_port.close()
                print("Serial port closed")
            except Exception:
                pass
        print("Program exit cleanup complete.")

    def reboot(self):
        result = messagebox.askyesno("Reboot Confirmation", "Are you sure you want to reboot?")
        if result:
            os.system("reboot")
        else:
            messagebox.showinfo("Reboot Canceled", "Reboot aborted.")

    def shutdown(self):
        result = messagebox.askyesno("Shutdown Confirmation", "Are you sure you want to shutdown?")
        if result:
            os.system("shutdown -h now")
        else:
            messagebox.showinfo("Shutdown Canceled", "Shutdown aborted.")

# -----------------------
# Motor Class Wrappers
# -----------------------
class MotorClass:
    # Motor objects are created here; if this raises on import, consider lazy-init.
    motor_x1 = RpiMotorLib.A4988Nema(
        PortDefineClass.DIR1, PortDefineClass.STEP1,
        (-1, -1, -1), "DRV8825"
    )
    motor_x2 = RpiMotorLib.A4988Nema(
        PortDefineClass.DIR2, PortDefineClass.STEP2,
        (-1, -1, -1), "DRV8825"
    )

# -----------------------
# XY Movement Engine (with PWM counting)
# -----------------------
class XYMoveClass(MotorClass, PortDefineClass, SystemFuncClass):

    def __init__(self):
        # default step delays (seconds per step) matching previous hardcoded values
        self.X_stepdelay = 0.0003
        self.Y_stepdelay = 0.00008

        # pulse counting for PWM-driven motion
        self._pulse_count = 0
        self._count_lock = threading.Lock()
        self._step_cb = None
        self._count_ref = 0
        
        # NEW: Persistent position tracking
        self._position_x_mm = 0.0  # Current X position in mm
        self._position_y_mm = 0.0  # Current Y position in mm
        self._last_pulse_count = 0  # Last read pulse count
        
        # ensure STEP1 is input-capable for callback
        try:
            pi.set_mode(PortDefineClass.STEP1, pigpio.INPUT)
        except Exception:
            pass

    def _step_cb_func(self, gpio, level, tick):
        # pigpio callback: increment on rising edge
        if level == 1:
            try:
                with self._count_lock:
                    self._pulse_count += 1
            except Exception:
                pass

    def start_pwm_counting(self):
        """Attach pigpio callback to STEP1 if not already attached. Managed by refcount."""
        try:
            # increase refcount; attach callback when going from 0->1
            with self._count_lock:
                self._count_ref += 1
                ref = self._count_ref
            if ref == 1:
                # attach callback for rising edge
                try:
                    self._step_cb = pi.callback(PortDefineClass.STEP1, pigpio.RISING_EDGE, self._step_cb_func)
                except Exception as e:
                    print("start_pwm_counting: callback attach failed:", e)
        except Exception as e:
            print("start_pwm_counting error:", e)

    def stop_pwm_counting(self):
        """Decrease refcount and cancel callback when 0."""
        try:
            with self._count_lock:
                self._count_ref = max(0, self._count_ref - 1)
                ref = self._count_ref
            if ref == 0:
                try:
                    if self._step_cb is not None:
                        try:
                            self._step_cb.cancel()
                        except Exception:
                            pass
                        self._step_cb = None
                except Exception as e:
                    print("stop_pwm_counting: error cancelling callback:", e)
        except Exception as e:
            print("stop_pwm_counting error:", e)

    def get_pulse_count(self):
        with self._count_lock:
            return int(self._pulse_count)

    def clear_pulse_count(self):
        with self._count_lock:
            self._pulse_count = 0

    # --- X step movements (chunked synchronous stepping) ---
    # (Kept for compatibility but scans/jogs will use PWM)
    def XrightCorrect(self, step):
        """Step-move to the right by 'step' microsteps (chunked)."""
        if SystemFuncClass.stop_flag:
            return False
        chunk = 200
        while step > 0:
            if SystemFuncClass.stop_flag:
                return False
            s = min(chunk, step)
            # Use motor_go directly; this is blocking for s steps
            try:
                MotorClass.motor_x1.motor_go(DIR_MAP["RIGHT"][0], "Full", s, self.X_stepdelay, False, .0001)
            except Exception:
                pass
            try:
                MotorClass.motor_x2.motor_go(DIR_MAP["RIGHT"][1], "Full", s, self.X_stepdelay, False, .0001)
            except Exception:
                pass
            step -= s
        return True

    def XleftCorrect(self, step):
        """Step-move to the left by 'step' microsteps (chunked)."""
        if SystemFuncClass.stop_flag:
            return False
        chunk = 200
        while step > 0:
            if SystemFuncClass.stop_flag:
                return False
            s = min(chunk, step)
            try:
                MotorClass.motor_x1.motor_go(DIR_MAP["LEFT"][0], "Full", s, self.X_stepdelay, False, .0001)
            except Exception:
                pass
            try:
                MotorClass.motor_x2.motor_go(DIR_MAP["LEFT"][1], "Full", s, self.X_stepdelay, False, .0001)
            except Exception:
                pass
            step -= s
        return True

    def XmoveCorrect(self, step):
        """Wrapper: positive -> right, negative -> left."""
        if step < 0:
            return self.XleftCorrect(abs(step))
        else:
            return self.XrightCorrect(step)

    # --- X continuous PWM control ---
    def Xdir(self, d):
        """Set direction pins for X continuous PWM.
        d == 1 -> LEFT, else RIGHT.
        """
        if d == 1:
            dir1, dir2 = DIR_MAP["LEFT"]
        else:
            dir1, dir2 = DIR_MAP["RIGHT"]
        try:
            pi.write(PortDefineClass.DIR1, dir1)
            pi.write(PortDefineClass.DIR2, dir2)
        except Exception:
            pass

    def XmotorSpeed(self, sp):
        """Set PWM frequency for both X step pins (Hz)."""
        try:
            pi.set_PWM_frequency(PortDefineClass.STEP1, sp)
            pi.set_PWM_frequency(PortDefineClass.STEP2, sp)
        except Exception:
            pass

    def XmotorSet(self, d, sp):
        """Set X direction and speed (frequency in Hz). Also update X_stepdelay used for non-PWM chunked moves."""
        self.Xdir(d)
        self.XmotorSpeed(sp)
        # derive step delay from frequency (Hz). Protect against zero.
        try:
            hz = float(max(1, int(sp)))
            # stepdelay ~ 1/hz (seconds per step)
            self.X_stepdelay = max(0.000001, 1.0 / hz)
        except Exception:
            # fallback to previous default
            self.X_stepdelay = 0.0003

    def Xstart(self):
        """Start X PWM and begin counting pulses. Ensure Y PWM is stopped first."""
        try:
            # Stop any Y motion/PWM to avoid conflicting STEP/DIR activity
            try:
                self.Ystop()
                # small settle so drivers/DIR pins stop changing while we reconfigure X
                time.sleep(0.01)
            except Exception:
                pass

            with self._count_lock:
                self._last_pulse_count = self._pulse_count
            # ensure PWM counting callback is attached
            self.start_pwm_counting()
            # start STEP PWM (both STEP1/STEP2 used by the system)
            pi.set_PWM_dutycycle(PortDefineClass.STEP1, 50)
            pi.set_PWM_dutycycle(PortDefineClass.STEP2, 50)
        except Exception:
            pass

    def Xstop(self):
        """Stop X PWM (duty 0) and stop counting pulses."""
        try:
            pi.set_PWM_dutycycle(PortDefineClass.STEP1, 0)
            pi.set_PWM_dutycycle(PortDefineClass.STEP2, 0)
        except Exception:
            pass
        # stop counting
        try:
            self.stop_pwm_counting()
        except Exception:
            pass

    def X_hold_running(self, duration=0.1, poll_interval=0.01):
        """
        Keep the X PWM running for `duration` seconds while checking EMG/stop_flag.
        Assumes caller has already set direction & frequency and started PWM (Xstart).
        Exits early if SystemFuncClass.stop_flag or EMG pressed.
        """
        end_time = time.time() + duration
        while time.time() < end_time:
            if SystemFuncClass.stop_flag:
                break
            if self.EMGSwitch():
                SystemFuncClass().AllStop()
                break
            sleep(poll_interval)

    def CheckXlimit_pos(self):
        return gpio_active(PortDefineClass.X_pos_limit)

    def CheckXlimit_neg(self):
        return gpio_active(PortDefineClass.X_neg_limit)

    # --- Y step movements (chunked, interruptible) ---
    def YfrontCorrect(self, step):
        """Toward Y- direction (DOWN)."""
        if SystemFuncClass.stop_flag:
            return
        chunk = 200
        while step > 0:
            if SystemFuncClass.stop_flag:
                return
            s = min(chunk, step)
            try:
                MotorClass.motor_x1.motor_go(DIR_MAP["DOWN"][0], "Full", s, self.Y_stepdelay, False, .0001)
            except Exception:
                pass
            try:
                MotorClass.motor_x2.motor_go(DIR_MAP["DOWN"][1], "Full", s, self.Y_stepdelay, False, .0001)
            except Exception:
                pass
            step -= s

    def YbackCorrect(self, step):
        """Toward Y+ direction (UP)."""
        if SystemFuncClass.stop_flag:
            return
        chunk = 200
        while step > 0:
            if SystemFuncClass.stop_flag:
                return
            s = min(chunk, step)
            try:
                MotorClass.motor_x1.motor_go(DIR_MAP["UP"][0], "Full", s, self.Y_stepdelay, False, .0001)
            except Exception:
                pass
            try:
                MotorClass.motor_x2.motor_go(DIR_MAP["UP"][1], "", s, self.Y_stepdelay, False, .0001)
            except Exception:
                pass
            step -= s

    def YmoveCorrect(self, step):
        """Return True if completed (keeps same behavior as original)."""
        if step < 0:
            return self.YfrontCorrect(abs(step))
        else:
            return self.YbackCorrect(step)

    # --- Y continuous PWM control ---
    def Ydir(self, d):
        """Set direction pins for Y continuous PWM.
        d == 1 -> UP, else DOWN.
        """
        if d == 1:
            dir1, dir2 = DIR_MAP["UP"]
        else:
            dir1, dir2 = DIR_MAP["DOWN"]
        try:
            pi.write(PortDefineClass.DIR1, dir1)
            pi.write(PortDefineClass.DIR2, dir2)
        except Exception:
            pass

    def YmotorSpeed(self, sp):
        """Set PWM frequency for both Y step pins (same pins used for X in this wiring)."""
        try:
            pi.set_PWM_frequency(PortDefineClass.STEP1, sp)
            pi.set_PWM_frequency(PortDefineClass.STEP2, sp)
        except Exception:
            pass

    def YmotorSet(self, d, sp):
        """Set Y direction and speed (frequency in Hz). Also update Y_stepdelay used for chunked moves."""
        self.Ydir(d)
        self.YmotorSpeed(sp)
        try:
            hz = float(max(1, int(sp)))
            self.Y_stepdelay = max(0.000001, 1.0 / hz)
        except Exception:
            self.Y_stepdelay = 0.00008

    def Ystart(self):
        """Start Y PWM and begin counting pulses. Ensure X PWM is stopped first."""
        try:
            # Stop any X motion/PWM to avoid conflicting STEP/DIR activity
            try:
                self.Xstop()
                # small settle so drivers/DIR pins stop changing while we reconfigure Y
                time.sleep(0.01)
            except Exception:
                pass

            with self._count_lock:
                self._last_pulse_count = self._pulse_count
            # attach counting callback and start PWM
            self.start_pwm_counting()
            pi.set_PWM_dutycycle(PortDefineClass.STEP1, 50)
            pi.set_PWM_dutycycle(PortDefineClass.STEP2, 50)
        except Exception:
            pass

    def Ystop(self):
        """Stop Y PWM and stop counting pulses."""
        try:
            pi.set_PWM_dutycycle(PortDefineClass.STEP1, 0)
            pi.set_PWM_dutycycle(PortDefineClass.STEP2, 0)
        except Exception:
            pass
        try:
            self.stop_pwm_counting()
        except Exception:
            pass

    def Y_hold_running(self, duration=0.1, poll_interval=0.01):
        """
        Keep the STEP PWM running for `duration` seconds while checking EMG/stop_flag.
        Assumes caller has already set direction & frequency and started PWM (Ystart/Xstart).
        Exits early if SystemFuncClass.stop_flag or EMG pressed.
        """
        end_time = time.time() + duration
        while time.time() < end_time:
            if SystemFuncClass.stop_flag:
                break
            if self.EMGSwitch():
                SystemFuncClass().AllStop()
                break
            sleep(poll_interval)

    def reset_position_counters(self):
        """Reset persistent position counters (called after homing)."""
        with self._count_lock:
            self._position_x_mm = 0.0
            self._position_y_mm = 0.0
            self._pulse_count = 0
            self._last_pulse_count = 0

    def get_position_x_mm(self):
        """Get current X position in mm."""
        with self._count_lock:
            return self._position_x_mm

    def get_position_y_mm(self):
        """Get current Y position in mm."""
        with self._count_lock:
            return self._position_y_mm

    def update_position_x(self, direction_sign):
        """
        Update X position based on pulse count since last read.
        direction_sign: +1 for RIGHT, -1 for LEFT
        """
        with self._count_lock:
            current_pulses = self._pulse_count
            delta_pulses = current_pulses - self._last_pulse_count
            delta_mm = pulses_to_mm(delta_pulses) * direction_sign
            self._position_x_mm += delta_mm
            self._last_pulse_count = current_pulses

    def update_position_y(self, direction_sign):
        """
        Update Y position based on pulse count since last read.
        direction_sign: +1 for UP, -1 for DOWN
        """
        with self._count_lock:
            current_pulses = self._pulse_count
            delta_pulses = current_pulses - self._last_pulse_count
            delta_mm = pulses_to_mm(delta_pulses) * direction_sign
            self._position_y_mm += delta_mm
            self._last_pulse_count = current_pulses

    def CheckYlimit_pos(self):
        return gpio_active(PortDefineClass.Y_pos_limit)

    def CheckYlimit_neg(self):
        return gpio_active(PortDefineClass.Y_neg_limit)

    def EMGSwitch(self):
        return gpio_active(PortDefineClass.SWITCH)

# -----------------------
# HOMING CLASS (X then Y)
# -----------------------
class GoHomePosClass:
    sysfunc = SystemFuncClass()
    xymove  = XYMoveClass()

    def Xhome(self):
        print("Homing X (toward X-)")
        # 1. Seek X- Limit
        self.xymove.XmotorSet(1, 500) 
        self.xymove.Xstart()
        while not self.xymove.CheckXlimit_neg():
            if SystemFuncClass.stop_flag: 
                self.xymove.Xstop()
                return # Exit Homing immediately
            if self.xymove.EMGSwitch():
                SystemFuncClass().AllStop(); return
            sleep(0.001)
        self.xymove.Xstop()
        sleep(0.5)

        # 2. Calculate Centering Offset
        area_target = 270.0
        measured_x = 270.0  # Initialize with default to prevent UnboundLocalError
        offset_mm = 5.0    # Initialize default offset

        try:
            # Check if GUI and config exist
            if hasattr(self, 'gui') and self.gui and self.gui.saved_config:
                val = self.gui.saved_config.get('area_x_mm', 270.0)
                measured_x = float(val)
                offset_mm = (measured_x - area_target) / 2.0
                if offset_mm < 2.0: offset_mm = 2.0
        except Exception as e:
            print(f"X Offset Calculation Error: {e}")
            offset_mm = 5.0
            measured_x = 270.0 # Reset to default on error

        # 3. Move to the Start of the 270mm box
        print(f"Centering X: Measured {measured_x:.3f}mm. Moving RIGHT {offset_mm:.3f}mm offset.")
        offset_pulses = mm_to_pulses(offset_mm)
        self.xymove.XmotorSet(0, 100) 
        self.xymove.Xstart()
        
        with self.xymove._count_lock:
            start_count = self.xymove._pulse_count
        while (self.xymove._pulse_count - start_count) < offset_pulses:
            if SystemFuncClass.stop_flag: break
            sleep(0.001)
        self.xymove.Xstop()
        
        self.xymove.reset_position_counters()
        print("X Home established at center-start.")

    def Yhome(self):
        print("Homing Y (toward Y-)")
        # 1. Seek Y- Limit
        self.xymove.YmotorSet(0, 500) 
        self.xymove.Ystart()
        while not self.xymove.CheckYlimit_neg():
            if SystemFuncClass.stop_flag: 
                self.xymove.Ystop()
                return # Exit Homing immediately
            if self.xymove.EMGSwitch():
                SystemFuncClass().AllStop(); return
            sleep(0.001)
        self.xymove.Ystop()
        sleep(0.5)

        # 2. Calculate Centering Offset
        area_target = 270.0
        measured_y = 270.0  # Initialize with default
        offset_mm = 5.0    # Initialize default offset

        try:
            if hasattr(self, 'gui') and self.gui and self.gui.saved_config:
                val = self.gui.saved_config.get('area_y_mm', 270.0)
                measured_y = float(val)
                offset_mm = (measured_y - area_target) / 2.0
                if offset_mm < 2.0: offset_mm = 2.0
        except Exception as e:
            print(f"Y Offset Calculation Error: {e}")
            offset_mm = 5.0
            measured_y = 270.0

        # 3. Move to the Start of the 270mm box
        print(f"Centering Y: Measured {measured_y:.3f}mm. Moving UP {offset_mm:.3f}mm offset.")
        offset_pulses = mm_to_pulses(offset_mm)
        self.xymove.YmotorSet(1, 100) 
        self.xymove.Ystart()
        
        with self.xymove._count_lock:
            start_count = self.xymove._pulse_count
        while (self.xymove._pulse_count - start_count) < offset_pulses:
            if SystemFuncClass.stop_flag: break
            sleep(0.001)
        self.xymove.Ystop()
        
        self.xymove.reset_position_counters()
        print("Y Home established at center-start.")

    def Home(self):
        self.sysfunc.GPIO_Init()
        print("=== START HOMING ===")
        self.Xhome()
        if SystemFuncClass.stop_flag: return
        self.Yhome()
        if SystemFuncClass.stop_flag: return
        print("=== HOMING COMPLETE ===")

# -----------------------
# SIMPLE SCAN CLASS (Updated with missing helpers)
# -----------------------
class SimpleScanClass:
    def __init__(self, xymove=None, row_step=None, x_speed=None, y_speed=None, gui=None, x_count=None, y_count=None):
        if row_step is None or x_speed is None or y_speed is None:
            raise ValueError("SimpleScanClass requires row_step, x_speed and y_speed explicitly")
        self.xy = xymove if xymove else XYMoveClass()
        self.row_step = int(row_step)
        self.x_speed = int(x_speed)
        self.y_speed = int(y_speed)
        self.gui = gui 
    
        self.y_count = int(y_count) if y_count is not None else 1
    
        # Get filename from GUI
        base_name = self.gui.fname.get().strip() if self.gui else "scan_data"
        if not base_name: base_name = "scan_data"
        self.horiz_filename = f"{base_name}_horizontal"
        self.vert_filename = f"{base_name}_vertical"

        # Force the scan area to exactly 270mm
        self.x_total_mm = 270.0
        self.y_total_mm = 270.0
        
        # Calculate steps
        self.y_step_mm = 270.0 / float(self.y_count)
        self.row_step = mm_to_pulses(self.y_step_mm)
        self.column_step = self.row_step # Square grid
        
        print(f"[SCAN INIT] Origin: (0,0). Step Size: {self.y_step_mm:.3f} mm")

    def _snap_to_pitch(self, value_mm: float) -> float:
        """
        Snap any realtime coordinate to the nearest Step/Pitch grid point:
        0, pitch, 2*pitch, ... , 270
        """
        try:
            pitch = float(self.y_step_mm)  # your Step/Pitch in mm
            if pitch <= 0:
                return max(0.0, min(270.0, float(value_mm)))
        except Exception:
            return max(0.0, min(270.0, float(value_mm)))
    
        idx = int(round(float(value_mm) / pitch))
        snapped = idx * pitch
        # clamp to scan area
        if snapped < 0.0:
            snapped = 0.0
        if snapped > 270.0:
            snapped = 270.0
        return float(snapped)

    # --- MISSING HELPER FUNCTIONS RE-ADDED ---
    def move_y_up(self):
        """Helper to step UP one row during Phase 1"""
        if SystemFuncClass.stop_flag: return False
        try:
            current_y = abs(self.xy.get_position_y_mm())
        except: current_y = 0.0
        target = current_y + self.y_step_mm
        print(f"Stepping Y UP to: {target:.3f}")
        return self.scan_y_to_position_mm_corrected(target, collect_data=False)

    def move_x_right(self, pulses=0):
        """Helper to step RIGHT one column during Phase 2"""
        if SystemFuncClass.stop_flag: return False
        try:
            current_x = abs(self.xy.get_position_x_mm())
        except: current_x = 0.0
        target = current_x + self.y_step_mm # Uses same step size for square grid
        print(f"Stepping X RIGHT to: {target:.3f}")
        return self.scan_x_to_position_mm_corrected(target, collect_data=False)

    def scan_x_to_position_mm_corrected(
        self,
        target_mm,
        collect_data=False,
        current_y_mm=0.0,
        use_threshold=True,
        speed_multiplier=1.0,
        allow_correction=True
    ):
        try:
            cur_mm = self.xy.get_position_x_mm()
        except Exception:
            cur_mm = 0.0
    
        delta_mm = target_mm - cur_mm
        if abs(delta_mm) < 0.005:
            return True
    
        direction = "RIGHT" if delta_mm > 0 else "LEFT"
        direction_sign = 1 if delta_mm > 0 else -1
        base_speed_hz = int(self.x_speed * speed_multiplier)
    
        # Creep ONLY when returning to zero (no data)
        creep_enabled = (not collect_data) and (abs(target_mm) <= 0.001)
    
        # Creep tuning (only used if creep_enabled)
        CREEP_WINDOW_MM = 2.0
        FINE_WINDOW_MM  = 0.4
        CREEP_SPEED_HZ  = 400
        FINE_SPEED_HZ   = 120
    
        # Correction only for return-to-zero
        CORRECTION_DEADBAND_MM = 0.02
        CORRECTION_SPEED_MULT  = 0.25
    
        data_step_mm = 270.0 / float(self.y_count) if self.y_count else 270.0
        next_point_idx = 0
        creep_stage = 0
    
        def _send_point(idx):
            """Send an exact-grid point idx * step."""
            target_point = idx * data_step_mm
            d1, d2 = read_dual_channels()
            x_out = self._snap_to_pitch(target_point)          # already grid, but keep consistent
            y_out = self._snap_to_pitch(abs(current_y_mm))     # SNAP realtime Y to pitch-grid
            send_serial_data(x_out, y_out, d1, d2, self.horiz_filename)
    
        started = False
        try:
            self.xy.XmotorSet(0 if direction == "RIGHT" else 1, base_speed_hz)
            self.xy.Xstart()
            started = True
        except Exception:
            started = False
    
        try:
            while True:
                if SystemFuncClass.stop_flag:
                    return False
                if self.xy.EMGSwitch():
                    return False
    
                self.xy.update_position_x(direction_sign)
                pos = self.xy.get_position_x_mm()
                dist_to_go = abs(target_mm - pos)
    
                # Creep ONLY for return-to-zero
                if creep_enabled:
                    if creep_stage < 1 and dist_to_go <= CREEP_WINDOW_MM:
                        try: self.xy.XmotorSpeed(CREEP_SPEED_HZ)
                        except Exception: pass
                        creep_stage = 1
                    if creep_stage < 2 and dist_to_go <= FINE_WINDOW_MM:
                        try: self.xy.XmotorSpeed(FINE_SPEED_HZ)
                        except Exception: pass
                        creep_stage = 2
    
                # --- DATA COLLECTION (do this BEFORE break) ---
                if collect_data and next_point_idx <= self.y_count:
                    # Use abs(pos) in your coordinate system
                    while next_point_idx <= self.y_count and abs(pos) >= ((next_point_idx * data_step_mm) - 0.05):
                        _send_point(next_point_idx)
                        next_point_idx += 1
    
                # Completion check AFTER data block
                if (direction == "RIGHT" and pos >= target_mm) or (direction == "LEFT" and pos <= target_mm):
                    break
    
                # Safety limits
                if direction == "RIGHT" and self.xy.CheckXlimit_pos():
                    break
                if direction == "LEFT" and self.xy.CheckXlimit_neg():
                    break
    
                if self.gui:
                    self.gui.win.after(
                        0,
                        lambda p=abs(pos): self.gui.jog_x_count_label.config(text=f"X (mm): {p:.3f}")
                    )
                time.sleep(0.0005)
    
        finally:
            if started:
                try: self.xy.Xstop()
                except Exception: pass
                try: self.xy.update_position_x(direction_sign)
                except Exception: pass
    
        # --- FINAL FLUSH (guarantee last points, including 270.000) ---
        if collect_data and not SystemFuncClass.stop_flag:
            # If we missed any points (common: the last 270.000), send them now
            while next_point_idx <= self.y_count:
                _send_point(next_point_idx)
                next_point_idx += 1
    
        # Optional correction only for return-to-zero
        if creep_enabled and allow_correction and not SystemFuncClass.stop_flag:
            try:
                final_pos = self.xy.get_position_x_mm()
            except Exception:
                final_pos = target_mm
    
            err = target_mm - final_pos
            if abs(err) > CORRECTION_DEADBAND_MM:
                return self.scan_x_to_position_mm_corrected(
                    target_mm,
                    collect_data=False,
                    current_y_mm=current_y_mm,
                    use_threshold=False,
                    speed_multiplier=max(0.05, float(speed_multiplier) * CORRECTION_SPEED_MULT),
                    allow_correction=False
                )
    
        return True

    def scan_y_to_position_mm_corrected(
        self,
        target_mm,
        collect_data=False,
        current_x_mm=0.0,
        use_threshold=True,
        speed_multiplier=1.0,
        allow_correction=True
    ):
        try:
            cur_mm = self.xy.get_position_y_mm()
        except Exception:
            cur_mm = 0.0
    
        delta_mm = target_mm - cur_mm
        if abs(delta_mm) < 0.005:
            return True
    
        direction = "UP" if delta_mm > 0 else "DOWN"
        direction_sign = 1 if delta_mm > 0 else -1
        base_speed_hz = int(self.y_speed * speed_multiplier)
    
        creep_enabled = (not collect_data) and (abs(target_mm) <= 0.001)
    
        CREEP_WINDOW_MM = 2.0
        FINE_WINDOW_MM  = 0.4
        CREEP_SPEED_HZ  = 400
        FINE_SPEED_HZ   = 120
    
        CORRECTION_DEADBAND_MM = 0.02
        CORRECTION_SPEED_MULT  = 0.25
    
        data_step_mm = 270.0 / float(self.y_count) if self.y_count else 270.0
        next_point_idx = 0
        creep_stage = 0
    
        def _send_point(idx):
            target_point = idx * data_step_mm
            d1, d2 = read_dual_channels()
            x_out = self._snap_to_pitch(abs(current_x_mm))     # SNAP realtime X to pitch-grid
            y_out = self._snap_to_pitch(target_point)          # already grid, but keep consistent
            send_serial_data(x_out, y_out, d1, d2, self.vert_filename)
    
        started = False
        try:
            self.xy.YmotorSet(1 if direction == "UP" else 0, base_speed_hz)
            self.xy.Ystart()
            started = True
        except Exception:
            started = False
    
        try:
            while True:
                if SystemFuncClass.stop_flag:
                    return False
                if self.xy.EMGSwitch():
                    return False
    
                self.xy.update_position_y(direction_sign)
                pos = self.xy.get_position_y_mm()
                dist_to_go = abs(target_mm - pos)
    
                if creep_enabled:
                    if creep_stage < 1 and dist_to_go <= CREEP_WINDOW_MM:
                        try: self.xy.YmotorSpeed(CREEP_SPEED_HZ)
                        except Exception: pass
                        creep_stage = 1
                    if creep_stage < 2 and dist_to_go <= FINE_WINDOW_MM:
                        try: self.xy.YmotorSpeed(FINE_SPEED_HZ)
                        except Exception: pass
                        creep_stage = 2
    
                # DATA COLLECTION BEFORE break
                if collect_data and next_point_idx <= self.y_count:
                    while next_point_idx <= self.y_count and abs(pos) >= ((next_point_idx * data_step_mm) - 0.05):
                        _send_point(next_point_idx)
                        next_point_idx += 1
    
                if (direction == "UP" and pos >= target_mm) or (direction == "DOWN" and pos <= target_mm):
                    break
    
                if direction == "UP" and self.xy.CheckYlimit_pos():
                    break
                if direction == "DOWN" and self.xy.CheckYlimit_neg():
                    break
    
                if self.gui:
                    self.gui.win.after(
                        0,
                        lambda p=abs(pos): self.gui.jog_y_count_label.config(text=f"Y (mm): {p:.3f}")
                    )
                time.sleep(0.0005)
    
        finally:
            if started:
                try: self.xy.Ystop()
                except Exception: pass
                try: self.xy.update_position_y(direction_sign)
                except Exception: pass
    
        # FINAL FLUSH to guarantee last point
        if collect_data and not SystemFuncClass.stop_flag:
            while next_point_idx <= self.y_count:
                _send_point(next_point_idx)
                next_point_idx += 1
    
        if creep_enabled and allow_correction and not SystemFuncClass.stop_flag:
            try:
                final_pos = self.xy.get_position_y_mm()
            except Exception:
                final_pos = target_mm
    
            err = target_mm - final_pos
            if abs(err) > CORRECTION_DEADBAND_MM:
                return self.scan_y_to_position_mm_corrected(
                    target_mm,
                    collect_data=False,
                    current_x_mm=current_x_mm,
                    use_threshold=False,
                    speed_multiplier=max(0.05, float(speed_multiplier) * CORRECTION_SPEED_MULT),
                    allow_correction=False
                )
    
        return True

    def simple_scan(self):
        """TWO-PHASE, ONE-PHASE, or DEMO Scanning Routine."""
        SystemFuncClass.stop_flag = False
        RETURN_SPEED_MULTIPLIER = 3.0 
        
        # Get Mode from GUI
        mode = self.gui.scan_mode.get() if self.gui else 1
        
        while True: # Loop used for Demo Mode
            # ========== PHASE 1: HORIZONTAL SCANNING ==========
            print(f"\n=== START PHASE 1: {self.horiz_filename} ===")
            current_y = 0.0
            
            for count in range(self.y_count + 1):
                if SystemFuncClass.stop_flag: return 
                if not self.scan_x_to_position_mm_corrected(270.0, collect_data=True, current_y_mm=current_y): break
                if SystemFuncClass.stop_flag: return
                if not self.scan_x_to_position_mm_corrected(0.0, collect_data=False, use_threshold=False, speed_multiplier=RETURN_SPEED_MULTIPLIER): break
                
                if count < self.y_count:
                    if SystemFuncClass.stop_flag: return
                    if not self.move_y_up(): break
                    current_y = abs(self.xy.get_position_y_mm())

            # Return to Origin (0,0)
            print("Phase 1 Complete. Resetting to Origin...")
            self.scan_y_to_position_mm_corrected(0.0, collect_data=False, use_threshold=False, speed_multiplier=RETURN_SPEED_MULTIPLIER)
            self.xy.reset_position_counters()

            # --- MODE BRANCHING ---
            if mode == 1: # Two Phase
                if SystemFuncClass.stop_flag: return
                if self.gui:
                    self.gui._waiting_for_rotation = True
                    self.gui.win.after(0, lambda: self.gui.show_continue_button())
                    while self.gui._waiting_for_rotation:
                        if SystemFuncClass.stop_flag: return
                        time.sleep(0.1)

                # PHASE 2: VERTICAL
                print(f"\n=== START PHASE 2: {self.vert_filename} ===")
                current_x = 0.0
                for count in range(self.y_count + 1):
                    if SystemFuncClass.stop_flag: return
                    if not self.scan_y_to_position_mm_corrected(270.0, collect_data=True, current_x_mm=current_x): break
                    if SystemFuncClass.stop_flag: return
                    if not self.scan_y_to_position_mm_corrected(0.0, collect_data=False, use_threshold=False, speed_multiplier=RETURN_SPEED_MULTIPLIER): break
                    
                    if count < self.y_count:
                        if SystemFuncClass.stop_flag: return
                        if not self.move_x_right(): break
                        current_x = abs(self.xy.get_position_x_mm())

                # Final Return to Zero
                self.scan_x_to_position_mm_corrected(0.0, collect_data=False, use_threshold=False, speed_multiplier=RETURN_SPEED_MULTIPLIER)
                break # End sequence

            elif mode == 2: # One Phase
                # One Phase is now done. Return X to zero.
                self.scan_x_to_position_mm_corrected(0.0, collect_data=False, use_threshold=False, speed_multiplier=RETURN_SPEED_MULTIPLIER)
                break # End sequence

            elif mode == 3: # Demo Mode
                # One Phase is done. Return X to zero.
                self.scan_x_to_position_mm_corrected(0.0, collect_data=False, use_threshold=False, speed_multiplier=RETURN_SPEED_MULTIPLIER)
                print("Demo cycle complete. Waiting 10 seconds to repeat...")
                # Wait 10 seconds, but check stop_flag every second
                for _ in range(10):
                    if SystemFuncClass.stop_flag: return
                    time.sleep(1)
                # Continue loop back to Phase 1

        print("=== SCAN COMPLETE ===")
        # Signal GUI to clear filename if not in Demo mode
        if self.gui and mode != 3:
            self.gui.win.after(0, lambda: self.gui.fname.delete(0, tk.END))

# -----------------------
# ScanRoutine Controller (requires params)
# -----------------------
class DataScanClass:
    def __init__(self, gui=None):
        self.gui = gui
        self.xymove = XYMoveClass()
        self.home = GoHomePosClass()

    def ScanRoutine(self, row_step, x_speed, y_speed, x_count, y_count):
        print("=== START SCAN ROUTINE ===")
        try:
            # Check if we are already essentially at (0,0)
            cur_x = abs(self.xymove.get_position_x_mm())
            cur_y = abs(self.xymove.get_position_y_mm())
            
            # If status is READY or we just moved to origin in the worker
            # skip the slow physical homing sequence
            if cur_x < 1.0 and cur_y < 1.0:
                print("System at origin. Skipping slow Homing sequence.")
            else:
                print("Performing homing before scan...")
                self.home.Home()
            
            # Reset stop flag and run scan
            SystemFuncClass.stop_flag = False
            simple = SimpleScanClass(self.xymove, row_step=row_step, x_speed=x_speed, y_speed=y_speed, gui=self.gui,
                                     x_count=x_count, y_count=y_count)
            simple.simple_scan()
        except Exception as e:
            print("ScanRoutine Error:", e)
            traceback.print_exc()
        finally:
            print("=== SCAN ROUTINE COMPLETE ===")

# -----------------------
# GUI
# -----------------------
class GUIClass(PortDefineClass):
    system_func = SystemFuncClass()

    def __init__(self):
        # Load saved config first
        self.saved_config = load_config()

        # Create UI
        self.win = tk.Tk()
        self.win.title("XY Scanning System")
        self.win.geometry('800x480')
        self.win.configure(bg='#0046ad')
        self.win.attributes('-fullscreen',True)
        self.win.config(cursor="none")

        self.buttonFont = TkFont.Font(family='Helvetica', size=20, weight='bold')
        self.buttonFont2 = TkFont.Font(family='Helvetica', size=25, weight='bold')
        self.buttonFont3 = TkFont.Font(family='Helvetica', size=16, weight='bold')
        self.labelFont = TkFont.Font(family='Helvetica', size=15, weight='bold')
        self.logoFont = TkFont.Font(family='BiomeW04-Bold', size=35, weight='bold')

        self.logo = tk.Label(self.win, text='Nivio-S', font=self.logoFont, height=0, width=6, bg='#0046ad', fg='white')
        self.logo.place(x=0, y=0)
        self.sublogo = tk.Label(self.win, text='Wall Scanning System', font=self.labelFont, height=0, width=22, bg='#0046ad', fg='white')
        self.sublogo.place(x=10, y=55)

        # Buttons
        self.HomeButton = tk.Button(self.win, text="HOME", font=self.buttonFont2, bg='lightgreen',
                                    command=self.started_homing, width=6, height=2)
        self.HomeButton.place(x=10, y=90)

        self.ScanButton = tk.Button(self.win, text="SCAN", font=self.buttonFont2, bg='lightgreen',
                                    command=self.scan_started, width=6, height=2)
        self.ScanButton.place(x=170, y=90)

        self.StopButton = tk.Button(self.win, text="STOP", font=self.buttonFont2, bg='red',
                                    command=self.stop_all_motion, width=6, height=2)
        self.StopButton.place(x=330, y=90)

        # New Calibrate Area button
        self.CalibButton = tk.Button(self.win, text="Calibrate\nArea", font=self.buttonFont3, bg='orange',
                                     command=self.start_area_calibration, width=10, height=2)
        self.CalibButton.place(x=340, y=180)

        self.ExitButton = tk.Button(self.win, text='Exit', font=self.buttonFont, command=self.gui_exit, height=1, width=6)
        self.ExitButton.place(x=390, y=5)

        self.RebootButton = tk.Button(self.win, text='Reboot', font=self.buttonFont, command=self.system_func.reboot, height=1, width=6)
        self.RebootButton.place(x=520, y=5)

        self.ShutdownButton = tk.Button(self.win, text='Shutdown', font=self.buttonFont, command=self.system_func.shutdown, height=1, width=7)
        self.ShutdownButton.place(x=650, y=5)

        # Show Keyboard button (toggles the on-screen keyboard)
        # Place it near the parameter entries
        self.kb_proc = None  # subprocess.Popen object for the keyboard (if any)
        self.KBButton = tk.Button(self.win, text="Show\nKeyboard", font=self.buttonFont3, command=self.toggle_keyboard, height=2, width=10)
        self.KBButton.place(x=340, y=305)

        # Status
        self.status_title = tk.Label(self.win, text='Axis Status:', font=self.labelFont, height=1, width=10, bg='#0046ad', fg='white')
        self.status_title.place(x=10, y=450)
        # We'll manage status label background via set_status().
        self.status_label = tk.Label(self.win, text="READY", font=self.labelFont, bg='#0046ad', fg='white', width=18)
        self.status_label.place(x=140, y=450)

        # Status UI state & blink handling
        self.status_normal_bg = '#0046ad'   # window background / non-highlighted
        self.status_ready_bg = 'green'      # READY uses green steady
        self._blink_job = None              # tkinter after id for blinking, or None
        self._blink_state = False           # current toggle state
        self._blink_color = 'green'         # blink color (green)
        self._status_text = "READY"         # last status text
        self._emg_active = False            # flag to avoid repeated AllStop calls from update loop

        # Jog state variables
        self._jog_active_x = False
        self._jog_active_y = False
        self._jog_thread_x = None
        self._jog_thread_y = None

        # Pulse counters and fractional accumulators
        self.jog_pulse_x = 0
        self.jog_pulse_y = 0
        self._jog_acc_x = 0.0
        self._jog_acc_y = 0.0


        # Add this line in __init__ near other flags
        self._is_homed = False 

        # Change the initial status call at the bottom of __init__
        self.set_status("Not Homed", bg='red', blink=False)
        self._homing_active = False
        self._scanning_active = False

        self.filename_label = tk.Label(self.win, text = "Input Filename:", font = self.labelFont, height = 1, width = 14, bg='#0046ad', fg='white')
        self.filename_label.place(x = 10, y = 185)
        self.fname = tk.Entry(self.win, font=TkFont.Font(size=14), width = 26, borderwidth=0)
        self.fname.place(x = 10, y = 210)
        
        # Adjustable parameters area (no hard-coded defaults)
        self.row_label = tk.Label(self.win, text="Step/Pitch (mm):", font=self.labelFont, bg='#0046ad', fg='white')
        self.row_label.place(x=10, y=300)
        self.row_entry = tk.Entry(self.win, font=TkFont.Font(size=14), width=10)
        self.row_entry.place(x=200, y=300)

        # Populate row_entry from config (prefer "row_step_mm", fallback "row_step")
        row_val = None
        try:
            if "row_step_mm" in self.saved_config:
                row_val = self.saved_config["row_step_mm"]
            elif "row_step" in self.saved_config:
                row_val = self.saved_config["row_step"]
        except Exception:
            row_val = None

        if row_val is not None:
            try:
                rv = float(row_val)
                if rv.is_integer():
                    self.row_entry.insert(0, str(int(rv)))
                else:
                    # preserve decimal representation
                    self.row_entry.insert(0, f"{float(rv):.3f}")
            except Exception:
                try:
                    # fallback: insert raw string
                    self.row_entry.insert(0, str(row_val))
                except Exception:
                    pass

        self.xspeed_label = tk.Label(self.win, text="X Speed (RPM):", font=self.labelFont, bg='#0046ad', fg='white')
        self.xspeed_label.place(x=10, y=340)
        self.xspeed_entry = tk.Entry(self.win, font=TkFont.Font(size=14), width=10)
        self.xspeed_entry.place(x=200, y=340)

        # Populate xspeed_entry from config (prefer "x_speed_rpm", fallback "x_speed")
        x_val = None
        try:
            if "x_speed_rpm" in self.saved_config:
                x_val = self.saved_config["x_speed_rpm"]
            elif "x_speed" in self.saved_config:
                x_val = self.saved_config["x_speed"]
        except Exception:
            x_val = None

        if x_val is not None:
            try:
                self.xspeed_entry.insert(0, str(int(float(x_val))))
            except Exception:
                try:
                    self.xspeed_entry.insert(0, str(x_val))
                except Exception:
                    pass

        self.yspeed_label = tk.Label(self.win, text="Y Speed (RPM):", font=self.labelFont, bg='#0046ad', fg='white')
        self.yspeed_label.place(x=10, y=380)
        self.yspeed_entry = tk.Entry(self.win, font=TkFont.Font(size=14), width=10)
        self.yspeed_entry.place(x=200, y=380)

        # Populate yspeed_entry from config (prefer "y_speed_rpm", fallback "y_speed")
        y_val = None
        try:
            if "y_speed_rpm" in self.saved_config:
                y_val = self.saved_config["y_speed_rpm"]
            elif "y_speed" in self.saved_config:
                y_val = self.saved_config["y_speed"]
        except Exception:
            y_val = None

        if y_val is not None:
            try:
                self.yspeed_entry.insert(0, str(int(float(y_val))))
            except Exception:
                try:
                    self.yspeed_entry.insert(0, str(y_val))
                except Exception:
                    pass

        self.count_label = tk.Label(self.win, text="Scan Count:", font=self.labelFont, bg='#0046ad', fg='white')
        self.count_label.place(x=10, y=265)
        self.count_entry = tk.Entry(self.win, font=TkFont.Font(size=14), width=10)
        self.count_entry.place(x=200, y=260)
        
        self.count_entry.bind('<KeyRelease>', self.update_row_step_from_count)

        # Populate counts from config if present
        try:
            xcnt = self.saved_config.get("x_count", None)
            ycnt = self.saved_config.get("y_count", None)
        except Exception:
            xcnt = ycnt = None

        if xcnt is not None:
            try:
                self.xcount_entry.insert(0, str(int(xcnt)))
            except Exception:
                try:
                    self.xcount_entry.insert(0, str(xcnt))
                except Exception:
                    pass

        if ycnt is not None:
            try:
                self.count_entry.insert(0, str(int(ycnt)))
            except Exception:
                try:
                    self.count_entry.insert(0, str(ycnt))
                except Exception:
                    pass

        self.help_label = tk.Label(self.win, text="Enter integer values. Config saved when scanning starts.",
                                   font=TkFont.Font(size=10), bg='#0046ad', fg='white')
        self.help_label.place(x=10, y=420)

        # Directional Jog Buttons (press-and-hold to jog)
        # Positioning approximate (center cluster)
        self.jog_label = tk.Label(self.win, text="Manual Jog:",
                                   font=self.labelFont, bg='#0046ad', fg='white')
        self.jog_label.place(x=530, y=250)
        
        self.btn_up = tk.Button(self.win, text="↑", font=TkFont.Font(size=20), bg='lightgreen', width=2, height=1)
        self.btn_up.place(x=610, y=280)
        self.btn_left = tk.Button(self.win, text="←", font=TkFont.Font(size=20), bg='lightgreen', width=2, height=1)
        self.btn_left.place(x=540, y=325)
        self.btn_right = tk.Button(self.win, text="→", font=TkFont.Font(size=20), bg='lightgreen', width=2, height=1)
        self.btn_right.place(x=680, y=325)
        self.btn_down = tk.Button(self.win, text="↓", font=TkFont.Font(size=20), bg='lightgreen', width=2, height=1)
        self.btn_down.place(x=610, y=370)

        # Bind press/release for press-and-hold jog behavior (PWM-based)
        self.btn_left.bind('<ButtonPress-1>', lambda e: self.start_jog_x('LEFT'))
        self.btn_left.bind('<ButtonRelease-1>', lambda e: self.stop_jog_x())

        self.btn_right.bind('<ButtonPress-1>', lambda e: self.start_jog_x('RIGHT'))
        self.btn_right.bind('<ButtonRelease-1>', lambda e: self.stop_jog_x())

        self.btn_up.bind('<ButtonPress-1>', lambda e: self.start_jog_y('UP'))
        self.btn_up.bind('<ButtonRelease-1>', lambda e: self.stop_jog_y())

        self.btn_down.bind('<ButtonPress-1>', lambda e: self.start_jog_y('DOWN'))
        self.btn_down.bind('<ButtonRelease-1>', lambda e: self.stop_jog_y())

        # Pulse counter labels (below the jog buttons) -- now show mm
        self.real_pos = tk.Label(self.win, text="Realtime axis position:",
                                   font=TkFont.Font(size=12), bg='#0046ad', fg='white')
        self.real_pos.place(x=500, y=430)
        
        self.jog_x_count_label = tk.Label(self.win, text="X (mm): 0", font=TkFont.Font(size=12), bg='#0046ad', fg='white')
        self.jog_x_count_label.place(x=500, y=450)
        self.jog_y_count_label = tk.Label(self.win, text="Y (mm): 0", font=TkFont.Font(size=12), bg='#0046ad', fg='white')
        self.jog_y_count_label.place(x=660, y=450)

        # Continue button (always visible, but disabled until rotation pause)
        # Position it next to the Show Keyboard button to fit naturally in the UI
        self.ContinueButton = tk.Button(self.win, text="Continue", font=self.buttonFont3, bg='lightgray',
                                        command=self.on_continue_clicked, height=2, width=10)
        # Place it right below the Show Keyboard button
        self.ContinueButton.place(x=340, y=365)
        self.ContinueButton.config(state='disabled')  # Disabled initially (grayed out)
        
        # Rotation wait flags
        self._waiting_for_rotation = False
        self._rotation_confirmed = False

        # Area calibration display (new)
        self.area_x_display = tk.Label(self.win, text=f"Area X (mm): {int(self.saved_config.get('area_x_mm', 0))}", font=TkFont.Font(size=12), bg='#0046ad', fg='white')
        self.area_x_display.place(x=340, y=240)
        self.area_y_display = tk.Label(self.win, text=f"Area Y (mm): {int(self.saved_config.get('area_y_mm', 0))}", font=TkFont.Font(size=12), bg='#0046ad', fg='white')
        self.area_y_display.place(x=340, y=260)

        # Limit status labels
        self.l_xpos = tk.Label(self.win, text="X+ : ?", font=TkFont.Font(size=14), width=6, bg='darkred', fg='white')
        self.l_xpos.place(x=660, y=130)
        self.l_xneg = tk.Label(self.win, text="X- : ?", font=TkFont.Font(size=14), width=6, bg='darkred', fg='white')
        self.l_xneg.place(x=540, y=130)
        self.l_ypos = tk.Label(self.win, text="Y+ : ?", font=TkFont.Font(size=14), width=6, bg='darkred', fg='white')
        self.l_ypos.place(x=600, y=100)
        self.l_yneg = tk.Label(self.win, text="Y- : ?", font=TkFont.Font(size=14), width=6, bg='darkred', fg='white')
        self.l_yneg.place(x=600, y=160)
        self.l_emg  = tk.Label(self.win, text="EMG: ?", font=TkFont.Font(size=14), width=6, bg='darkred', fg='white')
        self.l_emg.place(x=600, y=200)

        # Scanning Mode Selection (Radio Buttons)
        self.mode_label = tk.Label(self.win, text="Scanning Mode:", font=self.labelFont, bg='#0046ad', fg='white')
        self.mode_label.place(x=270, y=55)
        
        self.scan_mode = tk.IntVar(value=1) # 1: Two Phase, 2: One Phase, 3: Demo
        
        self.rb1 = tk.Radiobutton(self.win, text="Two Phase", variable=self.scan_mode, value=1, 
                                  font=TkFont.Font(size=10, weight='bold'), bg='#0046ad', fg='white',
                                  selectcolor='black', activebackground='#0046ad', 
                                  borderwidth=0, highlightthickness=0, command=self.on_mode_changed)
        self.rb1.place(x=430, y=60)
        
        self.rb2 = tk.Radiobutton(self.win, text="One Phase", variable=self.scan_mode, value=2, 
                                  font=TkFont.Font(size=10, weight='bold'), bg='#0046ad', fg='white',
                                  selectcolor='black', activebackground='#0046ad', 
                                  borderwidth=0, highlightthickness=0, command=self.on_mode_changed)
        self.rb2.place(x=550, y=60)
        
        self.rb3 = tk.Radiobutton(self.win, text="Demo Mode", variable=self.scan_mode, value=3, 
                                  font=TkFont.Font(size=10, weight='bold'), bg='#0046ad', fg='white',
                                  selectcolor='black', activebackground='#0046ad', 
                                  borderwidth=0, highlightthickness=0, command=self.on_mode_changed)
        self.rb3.place(x=670, y=60)

        # after-id for periodic update
        self.limit_after_id = None

        # DataScan object (create after UI so GUI entries exist)
        self.data_scan = DataScanClass(self)

        # Initialize status to READY (green)
        self.set_status("READY", bg=self.status_ready_bg, blink=False)

        # Initialize System State
        self._is_homed = False
        self._homing_active = False
        self._scanning_active = False
        self._calib_active = False

        # Start with RED BLINKING "Not Homed"
        self.set_status("Not Homed", bg='red', blink=True, blink_color='red')
        
        self.update_limit_status()

    # --------------------- KEYBOARD LAUNCH / TOGGLE ---------------------
    def find_keyboard_cmd(self):
        """Return the first available keyboard command from common candidates, or None."""
        candidates = ['onboard', 'matchbox-keyboard', 'florence']
        for cmd in candidates:
            if shutil.which(cmd):
                return cmd
        return None

    def toggle_keyboard(self):
        """Toggle the on-screen keyboard. Starts or terminates the keyboard process."""
        # If we have a running proc, try to terminate it (toggle off)
        if getattr(self, 'kb_proc', None):
            proc = self.kb_proc
            # If process ended on its own, clear state
            if proc.poll() is not None:
                self.kb_proc = None
                self.KBButton.config(text="Show\nKeyboard")
                return
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            self.kb_proc = None
            self.KBButton.config(text="Show\nKeyboard")
            return

        # Otherwise, try to start a keyboard
        cmd = self.find_keyboard_cmd()
        if not cmd:
            messagebox.showwarning("Keyboard Not Found",
                                   "No on-screen keyboard found. Install 'onboard' or 'matchbox-keyboard' and try again.")
            return
        try:
            # Start detached so the GUI doesn't block; suppress output
            self.kb_proc = subprocess.Popen([cmd],
                                           stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL,
                                           start_new_session=True)
        except FileNotFoundError:
            messagebox.showerror("Start Failed", f"Keyboard binary '{cmd}' not found.")
            self.kb_proc = None
        except Exception as e:
            messagebox.showerror("Start Failed", f"Failed to start '{cmd}': {e}")
            self.kb_proc = None

    # --------------------- STATUS / BLINKING UTILITIES ---------------------
    def _do_blink_toggle(self):
        """Internal: toggle blink state and reschedule if necessary."""
        # Toggle
        self._blink_state = not self._blink_state
        bg = self._blink_color if self._blink_state else self.status_normal_bg
        fg = 'white' if bg in ('green', 'lightgreen', 'yellow') else 'white'
        try:
            self.status_label.config(bg=bg, fg=fg)
        except Exception:
            pass
        # Schedule next toggle
        try:
            self._blink_job = self.win.after(500, self._do_blink_toggle)
        except Exception:
            self._blink_job = None

    def start_blink(self, color='green'):
        """Start blinking between `color` and the normal background."""
        # If already blinking with same color, do nothing
        if self._blink_job is not None and self._blink_color == color:
            return
        # Stop any existing blink
        self.stop_blink()
        self._blink_color = color
        self._blink_state = False
        # Start toggling immediately
        try:
            self._blink_job = self.win.after(0, self._do_blink_toggle)
        except Exception:
            self._blink_job = None

    def stop_blink(self):
        """Stop blinking and restore an appropriate static background."""
        if self._blink_job is not None:
            try:
                self.win.after_cancel(self._blink_job)
            except Exception:
                pass
        self._blink_job = None
        self._blink_state = False
        # Restore background according to current status text
        if self._status_text == "READY":
            bg = self.status_ready_bg; fg = 'black'
        else:
            bg = self.status_normal_bg; fg = 'white'
        try:
            self.status_label.config(bg=bg, fg=fg)
        except Exception:
            pass

    def set_status(self, text, bg=None, blink=False, blink_color='green'):
        def _set():
            self._status_text = text
            if blink:
                try:
                    self.status_label.config(text=text)
                except Exception: pass
                self.start_blink(blink_color)
            else:
                self.stop_blink()
                if bg is None:
                    if text == "READY" or text == "Homed":
                        bg_use = self.status_ready_bg
                    elif text in ("STOPPED", "Not Homed"):
                        bg_use = 'red'
                    else:
                        bg_use = self.status_normal_bg
                else:
                    bg_use = bg
                
                # Text color logic: Black for light colors, White for dark
                fg = 'black' if bg_use in ('green', 'lightgreen', 'yellow', 'orange') else 'white'
                try:
                    self.status_label.config(text=text, bg=bg_use, fg=fg)
                except Exception: pass
        try:
            self.win.after(0, _set)
        except Exception:
            _set()

    # --------------------- HOMING ---------------------
    def started_homing(self):
        """
        Triggered by the HOME button. Resets stop flag and starts homing.
        """
        if self._homing_active or self._scanning_active or self._calib_active:
            return

        # 1. RESET STOP FLAG (Critical to allow new motion)
        SystemFuncClass.stop_flag = False
        self._homing_active = True

        # 2. Disable UI immediately
        try:
            self.HomeButton.config(state='disabled')
            self.ScanButton.config(state='disabled')
            self.CalibButton.config(state='disabled')
        except Exception: pass

        # 3. Update Status
        self.set_status("Homing...", blink=True, blink_color='green')

        # 4. Start Thread
        threading.Thread(target=self.goto_home, daemon=True).start()

    # --------------------- HOMING WORKER ---------------------
    def goto_home(self):
        """
        Background worker for homing.
        """
        try:
            # Re-verify stop flag is clear at thread start
            SystemFuncClass.stop_flag = False
            
            home_obj = GoHomePosClass()
            home_obj.gui = self 
            home_obj.Home()
            
            # Check if we finished successfully or were stopped
            if not SystemFuncClass.stop_flag and not self._emg_active:
                self.reset_pulse_counters()
                self._is_homed = True
                self.set_status("READY", bg=self.status_ready_bg, blink=False)
                print("[SYSTEM] Homing Successful.")
            else:
                # If the user pressed STOP during homing
                self._is_homed = False
                # Do not set to READY, let stop_all_motion handle the STOPPED status
                print("[SYSTEM] Homing Aborted by user.")
                
        except Exception as e:
            print(f"Homing Error: {e}")
            self._is_homed = False
            self.set_status("Not Homed", bg='red', blink=True, blink_color='red')
        finally:
            self._homing_active = False
            self.win.after(0, self._restore_ui_after_op)

    # --------------------- SCAN ---------------------
    def scan_started(self):
        """
        Modified scan trigger:
        - If NOT HOMED: require Homing.
        - If STOPPED: move to origin (0,0) then scan.
        """
        # 1. Block if brand new start and never homed
        if not self._is_homed and self._status_text == "Not Homed":
            messagebox.showwarning("Homing Required", "System must be Homed before starting.")
            return

        # 2. Prevent re-entry if thread is already running
        if self._scanning_active: 
            return

        # 3. Capture if we are starting from a red "STOPPED" state
        was_stopped = (self._status_text == "STOPPED")

        # 4. CRITICAL: RESET STOP FLAG to allow new motion
        SystemFuncClass.stop_flag = False
        self._scanning_active = True

        # 5. Validate parameters before starting the thread
        valid = self.validate_and_save_params()
        if valid is None:
            self._scanning_active = False
            return

        # Unpack params
        row_pulses, x_speed_hz, y_speed_hz, x_count, y_count = valid

        def _scan_worker():
            try:
                # Create a local scanner instance for this thread
                simple_scanner = SimpleScanClass(self.data_scan.xymove, 
                                                row_step=row_pulses, 
                                                x_speed=x_speed_hz, 
                                                y_speed=y_speed_hz, 
                                                gui=self,
                                                y_count=y_count)

                # --- MOVE TO ORIGIN IF PREVIOUSLY STOPPED ---
                if was_stopped:
                    print("[SCAN] System was Stopped. Moving to real (0,0) before starting...")
                    self.set_status("Moving to Origin", bg='orange', blink=True)
                    
                    # Use precision return (No Data, No Threshold) to hit exactly 0.000
                    # speed_multiplier=2.0 for a fast but safe return
                    ok_x = simple_scanner.scan_x_to_position_mm_corrected(0.0, collect_data=False, use_threshold=False, speed_multiplier=2.0)
                    if SystemFuncClass.stop_flag or not ok_x: return
                    
                    ok_y = simple_scanner.scan_y_to_position_mm_corrected(0.0, collect_data=False, use_threshold=False, speed_multiplier=2.0)
                    if SystemFuncClass.stop_flag or not ok_y: return
                    
                    # Synchronize software counters with hardware state
                    self.reset_pulse_counters()
                    time.sleep(0.5)

                # --- START ACTUAL SCAN ---
                self.set_status("Scanning...", blink=True, blink_color='green')
                
                # Execute the standard scan routine
                self.data_scan.ScanRoutine(row_pulses, x_speed_hz, y_speed_hz, x_count, y_count)
                
                # If we finished without being stopped, system is officially Homed/Ready
                if not SystemFuncClass.stop_flag:
                    self._is_homed = True 
                
            except Exception as e:
                print(f"Scan Worker Error: {e}")
                traceback.print_exc()
            finally:
                self._scanning_active = False
                
                # Restore UI buttons and status only if we didn't just press STOP again
                if not SystemFuncClass.stop_flag:
                    self.set_status("READY", bg=self.status_ready_bg, blink=False)
                    self.win.after(0, self._restore_ui_after_op)
                else:
                    # If we were stopped during this worker, the stop_all_motion function
                    # will have already set the status to STOPPED.
                    pass

        # Start the background scan thread
        threading.Thread(target=_scan_worker, daemon=True).start()

    def scan_start(self):
        # kept for compatibility (not used)
        self.scan_started()

    def on_mode_changed(self):
        """Called when a radio button is clicked."""
        if self.scan_mode.get() == 3:
            self.fname.delete(0, tk.END)
            self.fname.insert(0, "Demo")
        else:
            if self.fname.get() == "Demo":
                self.fname.delete(0, tk.END)

    def stop_all_motion(self):
        """Emergency stop handler."""
        SystemFuncClass.stop_flag = True
        SystemFuncClass().AllStop()
        
        self._jog_active_x = False
        self._jog_active_y = False
        self._scanning_active = False
        self._homing_active = False
        self._calib_active = False
        self._is_homed = False 

        # Clear Filename ONLY if NOT in Demo Mode
        if self.scan_mode.get() != 3:
            try:
                self.fname.delete(0, tk.END)
            except Exception: pass

        self.set_status("STOPPED", bg='red', blink=False)
        
        def _cleanup():
            self.ScanButton.config(state='normal')
            self.HomeButton.config(state='normal')
        self.win.after(300, _cleanup)
        
    # --------------------- SENSOR ROTATION PAUSE ---------------------
    def show_continue_button(self):
        """Enable the Continue button during sensor rotation wait"""
        try:
            self.ContinueButton.config(state='normal', bg='yellow')  # Enable and make it yellow
            print("[GUI] Continue button enabled")
        except Exception as e:
            print(f"[GUI] Error enabling continue button: {e}")
    
    def hide_continue_button(self):
        """Disable the Continue button after rotation confirmed"""
        try:
            self.ContinueButton.config(state='disabled', bg='lightgray')  # Disable and gray it out
            print("[GUI] Continue button disabled")
        except Exception as e:
            print(f"[GUI] Error disabling continue button: {e}")
    
    def on_continue_clicked(self):
        """Handle Continue button click - ask for confirmation"""
        print("[GUI] Continue button clicked")
        
        # Show confirmation dialog
        result = messagebox.askyesno(
            "Sensor Rotation",
            "Have you finished rotating the sensor?\n\nClick Yes to proceed to Phase 2\nClick No to continue waiting"
        )
        
        if result:  # User clicked Yes
            print("[GUI] User confirmed sensor rotation - proceeding to Phase 2")
            self._rotation_confirmed = True
            self._waiting_for_rotation = False
            
            # Hide the Continue button
            self.hide_continue_button()
            
            # Update status back to Scanning
            self.set_status("Scanning...", blink=True, blink_color='green')
        else:  # User clicked No
            print("[GUI] User not ready - continuing to wait")
            # Keep waiting - do nothing, button stays visible

    # --------------------- EXIT ---------------------
    def gui_exit(self):
        try:
            if self.limit_after_id:
                self.win.after_cancel(self.limit_after_id)
        except Exception:
            pass
    
        # Ensure keyboard is closed if user exits
        if getattr(self, 'kb_proc', None):
            try:
                proc = self.kb_proc
                if proc and proc.poll() is None:
                    proc.terminate()
            except Exception:
                # ignore errors terminating the keyboard process
                pass
            # clear state even if termination failed or process already ended
            self.kb_proc = None
    
        # Stop any counting callbacks/workers
        try:
            if getattr(self, 'data_scan', None) and getattr(self.data_scan, 'xymove', None):
                try:
                    # Force stop counting
                    self.data_scan.xymove.stop_pwm_counting()
                except Exception:
                    pass
        except Exception:
            pass
    
        SystemFuncClass().AllStop()
        
        # Close serial port if open
        global serial_port
        if serial_port and serial_port.is_open:
            try:
                serial_port.close()
                print("Serial port closed")
            except Exception:
                pass
    
        # Optional: stop pigpio cleanly
        try:
            pi.stop()
        except Exception:
            pass
    
        self.win.destroy()

    def gui_start(self):
        self.win.protocol("WM_DELETE_WINDOW", self.gui_exit)
        self.win.mainloop()

    def update_row_step_from_count(self, event=None):
        """Automatically updates the Row Step entry when Y Scan Count changes."""
        try:
            y_count_str = self.count_entry.get().strip()
            if y_count_str:
                y_count = int(y_count_str)
                if y_count > 0:
                    # Calculate based on the fixed 270mm scan area
                    row_mm = 270.0 / float(y_count)
                    
                    # Update the row_entry field immediately
                    self.row_entry.delete(0, tk.END)
                    self.row_entry.insert(0, f"{row_mm:.3f}")
        except ValueError:
            # Ignore if user is currently typing and it's not a valid number yet
            pass

    # --------------------- PARAM VALIDATION & SAVE ---------------------
    def validate_and_save_params(self):
        # NOTE: Row step (vertical) is computed automatically as Area Y (mm) / Y Scan Count,
        # truncated to a whole number of millimetres (no decimals).
        row_mm_s = self.row_entry.get().strip()    # mm (ignored; row step auto-computed)
        x_s = self.xspeed_entry.get().strip()      # RPM
        y_s = self.yspeed_entry.get().strip()      # RPM
    
        try:
            xcount_s = self.xcount_entry.get().strip()
        except Exception:
            xcount_s = ""
        try:
            ycount_s = self.count_entry.get().strip()
        except Exception:
            ycount_s = ""
    
        # X Speed
        try:
            x_rpm = int(x_s)
            if x_rpm <= 0:
                raise ValueError
        except Exception:
            messagebox.showerror(
                "Invalid Parameter",
                "X Speed must be a positive integer (RPM)."
            )
            return None
    
        # Y Speed
        try:
            y_rpm = int(y_s)
            if y_rpm <= 0:
                raise ValueError
        except Exception:
            messagebox.showerror(
                "Invalid Parameter",
                "Y Speed must be a positive integer (RPM)."
            )
            return None
    
        # X Count is optional now
        try:
            if xcount_s == "":
                x_count = None
            else:
                x_count = int(xcount_s)
                if x_count <= 0:
                    raise ValueError
        except Exception:
            messagebox.showerror(
                "Invalid Parameter",
                "X Scan Count must be a positive integer or left empty."
            )
            return None
    
        # Y Count is required
        try:
            y_count = int(ycount_s)
            if y_count <= 0:
                raise ValueError
        except Exception:
            messagebox.showerror(
                "Invalid Parameter",
                "Y Scan Count must be a positive integer."
            )
            return None
    
        # Determine area_y_mm from saved config (area calibration). If not present, assume 0.
        try:
            area_y_mm = float(self.saved_config.get('area_y_mm', 0.0) or 0.0)
        except Exception:
            area_y_mm = 0.0
    
        # Use fixed 270.0 area and keep as float for 3 decimal places
        computed_row_mm = 270.0 / float(y_count) if y_count > 0 else 0.0
    
        if computed_row_mm <= 0:
            messagebox.showerror(
                "Invalid Parameter",
                "Computed Row Step is not positive. Ensure Area Y is calibrated and Y Scan Count is positive."
            )
            return None
    
        # Convert to pulses and speeds
        row_pulses = mm_to_pulses(computed_row_mm)
        x_speed_hz = rpm_to_hz(x_rpm)
        y_speed_hz = rpm_to_hz(y_rpm)
    
        # Merge with existing saved_config so we DON'T overwrite area_x_mm/area_y_mm
        try:
            cfg = dict(self.saved_config or {})  # preserve any existing keys (including area_x_mm/area_y_mm)
        except Exception:
            cfg = {}
    
        # Update/overwrite only the scan-related keys
        cfg.update({
            "row_step_mm": float(f"{computed_row_mm:.3f}"),  # Forces exactly 3 decimal places
            "x_speed_rpm": int(x_rpm),
            "y_speed_rpm": int(y_rpm),
            "x_count": int(x_count) if x_count is not None else None,
            "y_count": int(y_count)
        })
    
        try:
            save_config(cfg)
            self.saved_config = cfg
            print("Saved scan configuration to", CONFIG_FILE)
            # update area displays if present and update row_entry with the truncated integer
            try:
                self.area_x_display.config(text=f"Area X (mm): {int(self.saved_config.get('area_x_mm', 0))}")
                self.area_y_display.config(text=f"Area Y (mm): {int(self.saved_config.get('area_y_mm', 0))}")
                self.row_entry.delete(0, tk.END)
                self.row_entry.insert(0, f"{float(computed_row_mm):.3f}")
            except Exception:
                pass
        except Exception as e:
            print("Failed to save configuration:", e)
            messagebox.showwarning(
                "Save Failed",
                "Failed to save configuration file. Scan will continue."
            )
    
        # Return INTERNAL units and counts
        return (row_pulses, x_speed_hz, y_speed_hz, x_count, y_count)

    # --------------------- Getters (kept if other code calls them) ---------------------
    def get_row_step(self):
        v = self.row_entry.get().strip()
        return int(v)

    def get_x_speed(self):
        v = self.xspeed_entry.get().strip()
        return int(v)

    def get_y_speed(self):
        v = self.yspeed_entry.get().strip()
        return int(v)

    def _get_x_speed_safe(self):
        """Safe getter for jog use: RPM -> Hz."""
        try:
            rpm = int(self.xspeed_entry.get().strip())
            if rpm <= 0:
                raise ValueError
            return rpm_to_hz(rpm)
        except Exception:
            try:
                rpm = int(self.saved_config.get("x_speed_rpm", 60))
                return rpm_to_hz(rpm)
            except Exception:
                return rpm_to_hz(60)

    def _get_y_speed_safe(self):
        """Safe getter for jog use: RPM -> Hz."""
        try:
            rpm = int(self.yspeed_entry.get().strip())
            if rpm <= 0:
                raise ValueError
            return rpm_to_hz(rpm)
        except Exception:
            try:
                rpm = int(self.saved_config.get("y_speed_rpm", 60))
                return rpm_to_hz(rpm)
            except Exception:
                return rpm_to_hz(60)

    # --------------------- Pulse counter utilities ---------------------
    def reset_pulse_counters(self):
        """Reset both pulse counters and update UI (called after Homing)."""
        # Use the new reset method
        try:
            self.data_scan.xymove.reset_position_counters()
        except Exception:
            pass
        try:
            self.jog_x_count_label.config(text="X (mm): 0")
            self.jog_y_count_label.config(text="Y (mm): 0")
        except Exception:
            pass

    # --------------------- Manual Jog Handlers (PWM-based for smooth motion) ---------------------
    def start_jog_x(self, direction, event=None):
        """Start continuous jog on X axis using PWM. direction is 'LEFT' or 'RIGHT'."""
        print(f"DEBUG start_jog_x called: direction={direction}, stop_flag={SystemFuncClass.stop_flag}, emg={self._emg_active}, homing={getattr(self,'_homing_active',False)}, scanning={getattr(self,'_scanning_active',False)}")

        # Basic guards
        if SystemFuncClass.stop_flag:
            print("DEBUG: blocked by SystemFuncClass.stop_flag")
            return
        if self._emg_active:
            print("DEBUG: blocked by _emg_active")
            return
        if getattr(self, '_homing_active', False) or getattr(self, '_scanning_active', False):
            print("DEBUG: blocked by homing/scanning active")
            return

        # Map to the actual button
        btn = self.btn_left if direction == 'LEFT' else self.btn_right
        try:
            state = btn.cget('state')
            print(f"DEBUG: button state for jog button = '{state}'")
            # Only abort if widget is explicitly disabled
            if state == 'disabled':
                print("DEBUG: jog button widget state is 'disabled' -> abort start")
                return
        except Exception as e:
            print("DEBUG: cannot read button state:", e)

        if self._jog_active_x:
            print("DEBUG: jog already active (x)")
            return
        self._jog_active_x = True

        d = 1 if direction == 'LEFT' else 0
        direction_sign = -1 if direction == 'LEFT' else 1

        speed_hz = self._get_x_speed_safe()
        print(f"DEBUG: starting X motor: dir={d}, speed_hz={speed_hz}")

        try:
            self.data_scan.xymove.XmotorSet(d, speed_hz)
            # Optional: enforce DIR pin writes for clarity
            try:
                pi.write(PortDefineClass.DIR1, DIR_MAP["LEFT" if d==1 else "RIGHT"][0])
                pi.write(PortDefineClass.DIR2, DIR_MAP["LEFT" if d==1 else "RIGHT"][1])
            except Exception:
                pass
            self.data_scan.xymove.Xstart()
        except Exception as e:
            print("DEBUG: exception during XmotorSet/Xstart:", e)

        # Read back debug info if available
        try:
            f1 = pi.get_PWM_frequency(PortDefineClass.STEP1)
            f2 = pi.get_PWM_frequency(PortDefineClass.STEP2)
            d1 = pi.get_PWM_dutycycle(PortDefineClass.STEP1)
            d2 = pi.get_PWM_dutycycle(PortDefineClass.STEP2)
            dir1 = pi.read(PortDefineClass.DIR1)
            dir2 = pi.read(PortDefineClass.DIR2)
            print(f"DEBUG: STEP1 freq={f1} duty={d1}, STEP2 freq={f2} duty={d2}, DIR1={dir1}, DIR2={dir2}")
        except Exception:
            pass

        def _worker():
            try:
                last_ui = time.time()
                while self._jog_active_x and not SystemFuncClass.stop_flag:
                    # Stop if global inhibit became active while running
                    if self._emg_active or getattr(self, '_homing_active', False) or getattr(self, '_scanning_active', False):
                        print("DEBUG: stopping jog X because emg/homing/scanning became active")
                        break

                    # Stop if button becomes disabled while running
                    try:
                        if btn.cget('state') == 'disabled':
                            print("DEBUG: stopping jog X because widget disabled")
                            break
                    except Exception:
                        pass

                    if direction == 'LEFT' and self.data_scan.xymove.CheckXlimit_neg():
                        print("DEBUG: X- limit triggered during jog, stopping")
                        break
                    if direction == 'RIGHT' and self.data_scan.xymove.CheckXlimit_pos():
                        print("DEBUG: X+ limit triggered during jog, stopping")
                        break
                    if self.data_scan.xymove.EMGSwitch():
                        print("DEBUG: EMG pressed during jog X")
                        SystemFuncClass().AllStop()
                        break

                    now = time.time()
                    if now - last_ui >= 0.15:
                        last_ui = now
                        try:
                            self.data_scan.xymove.update_position_x(direction_sign)
                            pos_mm = self.data_scan.xymove.get_position_x_mm()
                            self.win.after(0, lambda p=pos_mm:
                                self.jog_x_count_label.config(text=f"X (mm): {int(p)}"))
                        except Exception:
                            pass

                    sleep(0.005)

            except Exception as e:
                print("DEBUG: Jog X error:", e)
            finally:
                try:
                    self.data_scan.xymove.Xstop()
                    self.data_scan.xymove.update_position_x(direction_sign)
                except Exception:
                    pass
                self._jog_active_x = False
                try:
                    pos_mm = self.data_scan.xymove.get_position_x_mm()
                    self.win.after(0, lambda p=pos_mm:
                        self.jog_x_count_label.config(text=f"X (mm): {int(p)}"))
                except Exception:
                    pass
                if not self._emg_active and self._status_text not in ("Scanning...", "Homing..."):
                    self.set_status("READY", bg=self.status_ready_bg, blink=False)

        self._jog_thread_x = threading.Thread(target=_worker, daemon=True)
        self._jog_thread_x.start()


    def stop_jog_x(self, event=None):
        """Stop continuous X jog (called on button release)."""
        print("DEBUG stop_jog_x called")
        self._jog_active_x = False
        try:
            if getattr(self, 'data_scan', None) and getattr(self.data_scan, 'xymove', None):
                self.data_scan.xymove.Xstop()
                pos_mm = self.data_scan.xymove.get_position_x_mm()
                self.jog_x_count_label.config(text=f"X (mm): {int(pos_mm)}")
        except Exception as e:
            print("DEBUG stop_jog_x exception:", e)


    def start_jog_y(self, direction, event=None):
        """Start continuous jog on Y axis using PWM. direction is 'UP' or 'DOWN'."""
        print(f"DEBUG start_jog_y called: direction={direction}, stop_flag={SystemFuncClass.stop_flag}, emg={self._emg_active}, homing={getattr(self,'_homing_active',False)}, scanning={getattr(self,'_scanning_active',False)}")

        # Basic guards
        if SystemFuncClass.stop_flag:
            print("DEBUG: blocked by SystemFuncClass.stop_flag")
            return
        if self._emg_active:
            print("DEBUG: blocked by _emg_active")
            return
        if getattr(self, '_homing_active', False) or getattr(self, '_scanning_active', False):
            print("DEBUG: blocked by homing/scanning active")
            return
        # Map to the actual button
        btn = self.btn_up if direction == 'UP' else self.btn_down
        try:
            state = btn.cget('state')
            print(f"DEBUG: button state for jog button = '{state}'")
            if state == 'disabled':
                print("DEBUG: jog button widget state is 'disabled' -> abort start")
                return
        except Exception as e:
            print("DEBUG: cannot read button state:", e)

        if self._jog_active_y:
            print("DEBUG: jog already active (y)")
            return
        self._jog_active_y = True

        d = 1 if direction == 'UP' else 0
        direction_sign = 1 if direction == 'UP' else -1

        speed_hz = self._get_y_speed_safe()
        print(f"DEBUG: starting Y motor: dir={d}, speed_hz={speed_hz}")

        try:
            self.data_scan.xymove.YmotorSet(d, speed_hz)
            try:
                pi.write(PortDefineClass.DIR1, DIR_MAP["UP" if d==1 else "DOWN"][0])
                pi.write(PortDefineClass.DIR2, DIR_MAP["UP" if d==1 else "DOWN"][1])
            except Exception:
                pass
            self.data_scan.xymove.Ystart()
        except Exception as e:
            print("DEBUG: exception during YmotorSet/Ystart:", e)

        try:
            f1 = pi.get_PWM_frequency(PortDefineClass.STEP1)
            f2 = pi.get_PWM_frequency(PortDefineClass.STEP2)
            d1 = pi.get_PWM_dutycycle(PortDefineClass.STEP1)
            d2 = pi.get_PWM_dutycycle(PortDefineClass.STEP2)
            dir1 = pi.read(PortDefineClass.DIR1)
            dir2 = pi.read(PortDefineClass.DIR2)
            print(f"DEBUG: STEP1 freq={f1} duty={d1}, STEP2 freq={f2} duty={d2}, DIR1={dir1}, DIR2={dir2}")
        except Exception:
            pass

        def _worker():
            try:
                last_ui = time.time()
                while self._jog_active_y and not SystemFuncClass.stop_flag:
                    if self._emg_active or getattr(self, '_homing_active', False) or getattr(self, '_scanning_active', False):
                        print("DEBUG: stopping jog Y because emg/homing/scanning became active")
                        break

                    try:
                        if btn.cget('state') == 'disabled':
                            print("DEBUG: stopping jog Y because widget disabled")
                            break
                    except Exception:
                        pass

                    if direction == 'UP' and self.data_scan.xymove.CheckYlimit_pos():
                        print("DEBUG: Y+ limit triggered during jog, stopping")
                        break
                    if direction == 'DOWN' and self.data_scan.xymove.CheckYlimit_neg():
                        print("DEBUG: Y- limit triggered during jog, stopping")
                        break
                    if self.data_scan.xymove.EMGSwitch():
                        print("DEBUG: EMG pressed during jog Y")
                        SystemFuncClass().AllStop()
                        break

                    now = time.time()
                    if now - last_ui >= 0.15:
                        last_ui = now
                        try:
                            self.data_scan.xymove.update_position_y(direction_sign)
                            pos_mm = self.data_scan.xymove.get_position_y_mm()
                            self.win.after(0, lambda p=pos_mm:
                                self.jog_y_count_label.config(text=f"Y (mm): {int(p)}"))
                        except Exception:
                            pass

                    sleep(0.005)

            except Exception as e:
                print("DEBUG: Jog Y error:", e)
            finally:
                try:
                    self.data_scan.xymove.Ystop()
                    self.data_scan.xymove.update_position_y(direction_sign)
                except Exception:
                    pass
                self._jog_active_y = False
                try:
                    pos_mm = self.data_scan.xymove.get_position_y_mm()
                    self.win.after(0, lambda p=pos_mm:
                        self.jog_y_count_label.config(text=f"Y (mm): {int(p)}"))
                except Exception:
                    pass
                if not self._emg_active and self._status_text not in ("Scanning...", "Homing..."):
                    self.set_status("READY", bg=self.status_ready_bg, blink=False)

        self._jog_thread_y = threading.Thread(target=_worker, daemon=True)
        self._jog_thread_y.start()


    def stop_jog_y(self, event=None):
        """Stop continuous Y jog (called on button release)."""
        print("DEBUG stop_jog_y called")
        self._jog_active_y = False
        try:
            if getattr(self, 'data_scan', None) and getattr(self.data_scan, 'xymove', None):
                self.data_scan.xymove.Ystop()
                pos_mm = self.data_scan.xymove.get_position_y_mm()
                self.jog_y_count_label.config(text=f"Y (mm): {int(pos_mm)}")
        except Exception as e:
            print("DEBUG stop_jog_y exception:", e)

    # --------------------- Limit Status Updater ---------------------
    def update_limit_status(self):
        """
        Periodic readout of limit switches and EMG. 
        Enforces safety and state-based button activation.
        """
        try:
            xpos = gpio_active(PortDefineClass.X_pos_limit)
            xneg = gpio_active(PortDefineClass.X_neg_limit)
            ypos = gpio_active(PortDefineClass.Y_pos_limit)
            yneg = gpio_active(PortDefineClass.Y_neg_limit)
            emg  = gpio_active(PortDefineClass.SWITCH)
        except Exception as e:
            print("Error reading GPIO:", e)
            xpos = xneg = ypos = yneg = emg = False

        # --- 1. Update tiny status boxes ---
        def set_label(lbl, name, val):
            try:
                lbl.config(text=f"{name} : {int(bool(val))}")
                if val:
                    lbl.config(bg='green', fg='black')
                else:
                    lbl.config(bg='darkred', fg='white')
            except Exception: pass

        set_label(self.l_xpos, "X+", xpos)
        set_label(self.l_xneg, "X-", xneg)
        set_label(self.l_ypos, "Y+", ypos)
        set_label(self.l_yneg, "Y-", yneg)
        set_label(self.l_emg,  "EMG", emg)

        # --- 2. State & Status Label Logic ---
        cur_text = getattr(self, "_status_text", "")

        if emg:
            if not self._emg_active:
                self._emg_active = True
                self._is_homed = False # Loss of position on EMG
                try: SystemFuncClass().AllStop()
                except Exception: pass
            self.set_status("EMG Stopped", bg='red', blink=False)
        else:
            if self._emg_active:
                self._emg_active = False
                self.win.after(0, self.stop_all_motion)
            else:
                # Normal State Persistence
                if cur_text == "STOPPED":
                    # Keep solid red "STOPPED" state, do not auto-revert to READY
                    pass 
                elif cur_text in ("Scanning...", "Homing...", "Moving to Origin", "Calibrating..."):
                    # Let active operations manage their own blinking status
                    pass 
                elif not self._is_homed:
                    # Initial or Reset state: Force RED BLINKING "Not Homed"
                    if cur_text != "Not Homed":
                        self.set_status("Not Homed", bg='red', blink=True, blink_color='red')
                else:
                    # System is Homed and idle: Show solid green READY
                    if cur_text != "READY":
                        self.set_status("READY", bg=self.status_ready_bg, blink=False)

        # --- 3. Button Management ---
        try:
            # Determine if motors are currently busy
            is_busy = any([getattr(self, "_homing_active", False), 
                           getattr(self, "_scanning_active", False), 
                           getattr(self, "_calib_active", False)])

            if is_busy:
                # Lockdown UI while machine is in motion
                for btn in [self.ScanButton, self.HomeButton, self.CalibButton,
                            self.btn_up, self.btn_down, self.btn_left, self.btn_right]:
                    btn.config(state='disabled')
            else:
                # MACHINE IS IDLE
                self.HomeButton.config(state='normal') # Always allow Home

                # SCAN Logic: Allowed if system is Homed OR if we are in a STOPPED state
                if self._is_homed or cur_text == "STOPPED":
                    self.ScanButton.config(state='normal')
                else:
                    self.ScanButton.config(state='disabled')

                # CALIBRATE/JOG Logic: Only allowed if system is successfully Homed
                if self._is_homed:
                    self.CalibButton.config(state='normal')
                    self.btn_up.config(state='disabled' if ypos else 'normal')
                    self.btn_down.config(state='disabled' if yneg else 'normal')
                    self.btn_right.config(state='disabled' if xpos else 'normal')
                    self.btn_left.config(state='disabled' if xneg else 'normal')
                else:
                    self.CalibButton.config(state='disabled')
                    for b in [self.btn_up, self.btn_down, self.btn_left, self.btn_right]:
                        b.config(state='disabled')
        except Exception:
            pass

        # Schedule next check
        try:
            self.limit_after_id = self.win.after(200, self.update_limit_status)
        except Exception:
            self.limit_after_id = None

    # --------------------- Area Calibration ---------------------
    def start_area_calibration(self):
        """
        Trigger area calibration. Requires system to be Homed first.
        """
        # --- NEW: Mandatory Homing Guard ---
        if not getattr(self, "_is_homed", False):
            messagebox.showwarning("Homing Required", "System must be Homed before performing calibration.")
            return

        if getattr(self, "_scanning_active", False) or getattr(self, "_homing_active", False):
            messagebox.showinfo("Busy", "Cannot calibrate while homing or scanning is active.")
            return
        
        if SystemFuncClass.stop_flag:
            messagebox.showinfo("System Stop", "System is stopped. Clear stop and try again.")
            return

        # Disable UI buttons
        try:
            self._calib_active = True
            buttons = [self.CalibButton, self.HomeButton, self.ScanButton, 
                       self.btn_up, self.btn_down, self.btn_left, self.btn_right]
            for btn in buttons:
                self.win.after(0, lambda b=btn: b.config(state='disabled'))
        except Exception: pass

        self.set_status("Calibrating...", blink=True, blink_color='yellow')
        threading.Thread(target=self._area_calibration_worker, daemon=True).start()

    def _area_calibration_worker(self):
        """
        Background worker for the reversed calibration sequence.
        """
        x_extent = 0.0
        y_extent = 0.0
        aborted = False

        try:
            xy = self.data_scan.xymove
            xy.reset_position_counters()

            # --- STAGE 1: Move UP until Y+ limit (Find Height) ---
            if not aborted:
                print("Area Calib: Moving UP to find Y+ limit...")
                try:
                    speed_y = self._get_y_speed_safe()
                    # Set DIR pins for UP
                    pi.write(PortDefineClass.DIR1, DIR_MAP["UP"][0])
                    pi.write(PortDefineClass.DIR2, DIR_MAP["UP"][1])
                    xy.YmotorSet(1, speed_y) # 1 typically UP
                    xy.Ystart()
                    
                    direction_sign = 1 # Increasing Y
                    last_ui = time.time()
                    while True:
                        if SystemFuncClass.stop_flag or xy.EMGSwitch():
                            aborted = True; break
                        
                        # STOP on Y+ LIMIT (Top)
                        if xy.CheckYlimit_pos(): 
                            print("Area Calib: Y+ limit hit.")
                            xy.Ystop()
                            time.sleep(0.1)
                            break
                        
                        # UI Update
                        if time.time() - last_ui >= 0.15:
                            last_ui = time.time()
                            xy.update_position_y(direction_sign)
                            self.win.after(0, lambda p=xy.get_position_y_mm():
                                           self.jog_y_count_label.config(text=f"Y (mm): {int(p)}"))
                        time.sleep(0.002)
                finally:
                    xy.Ystop()
                    xy.update_position_y(direction_sign)
                    y_extent = abs(xy.get_position_y_mm())
                    self.win.after(0, lambda v=y_extent: self.area_y_display.config(text=f"Area Y (mm): {int(round(v))}"))

            # --- STAGE 2: Move RIGHT until X+ limit (Find Width) ---
            if not aborted:
                print("Area Calib: Moving RIGHT to find X+ limit...")
                try:
                    speed_x = self._get_x_speed_safe()
                    # Set DIR pins for RIGHT
                    pi.write(PortDefineClass.DIR1, DIR_MAP["RIGHT"][0])
                    pi.write(PortDefineClass.DIR2, DIR_MAP["RIGHT"][1])
                    xy.XmotorSet(0, speed_x) # 0 typically RIGHT
                    xy.Xstart()

                    direction_sign = 1 # Increasing X
                    last_ui = time.time()
                    while True:
                        if SystemFuncClass.stop_flag or xy.EMGSwitch():
                            aborted = True; break
                        
                        # STOP on X+ LIMIT (Right side)
                        if xy.CheckXlimit_pos():
                            print("Area Calib: X+ limit hit.")
                            xy.Xstop()
                            time.sleep(0.1)
                            break
                        
                        if time.time() - last_ui >= 0.15:
                            last_ui = time.time()
                            xy.update_position_x(direction_sign)
                            self.win.after(0, lambda p=xy.get_position_x_mm():
                                           self.jog_x_count_label.config(text=f"X (mm): {int(p)}"))
                        time.sleep(0.002)
                finally:
                    xy.Xstop()
                    xy.update_position_x(direction_sign)
                    x_extent = abs(xy.get_position_x_mm())
                    self.win.after(0, lambda v=x_extent: self.area_x_display.config(text=f"Area X (mm): {int(round(v))}"))

            # --- STAGE 3: Save and Return Home ---
            if not aborted:
                # Save config
                cfg = dict(self.saved_config or {})
                cfg["area_x_mm"] = float(round(x_extent, 3))
                cfg["area_y_mm"] = float(round(y_extent, 3))
                save_config(cfg)
                self.saved_config = cfg
                
                # Perform Homing after calibration
                print("Area Calib: Sequence complete. Returning Home...")
                self.set_status("Homing...", blink=True)
                home_obj = GoHomePosClass()
                home_obj.Home()
                
                self.win.after(0, lambda: messagebox.showinfo("Calibration Complete",
                                f"Area Measured:\nX = {int(round(x_extent))} mm\nY = {int(round(y_extent))} mm"))
            else:
                self.win.after(0, lambda: messagebox.showwarning("Aborted", "Calibration Aborted."))

        except Exception as e:
            print(f"Calibration Error: {e}")
            traceback.print_exc()
        finally:
            self._calib_active = False
            self.win.after(0, self._restore_ui_after_op) # Helper to re-enable buttons
            self.set_status("READY")

    def _restore_ui_after_op(self):
        """Helper to re-enable buttons after any thread completes"""
        btns = [self.CalibButton, self.HomeButton, self.ScanButton, 
                self.btn_up, self.btn_down, self.btn_left, self.btn_right]
        for b in btns:
            try: b.config(state='normal')
            except: pass


# -----------------------
# MAIN
# -----------------------
def main():
    # Initialize pigpio pins BEFORE creating GUI and objects that read GPIO
    try:
        SystemFuncClass().GPIO_Init()
    except Exception as e:
        print("Fatal error during GPIO initialization:", e)
        traceback.print_exc()

    # Create GUI
    try:
        gui = GUIClass()
    except Exception as e:
        print("Failed creating GUIClass:", e)
        traceback.print_exc()
        return

    # Start GUI loop
    try:
        gui.gui_start()
    except Exception as e:
        print("Fatal error in GUI mainloop:", e)
        traceback.print_exc()

if __name__ == "__main__":
    main()
