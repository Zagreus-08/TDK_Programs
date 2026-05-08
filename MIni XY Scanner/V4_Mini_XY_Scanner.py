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

# DAQ/ADC imports for actual sensor reading
try:
    import spidev  # For SPI-based ADCs like MCP3008
    SPI_AVAILABLE = True
except ImportError:
    SPI_AVAILABLE = False
    print("Warning: spidev not installed. Install with: pip install spidev")

try:
    import board
    import busio
    import adafruit_ads1x15.ads1115 as ADS
    from adafruit_ads1x15.analog_in import AnalogIn
    I2C_ADC_AVAILABLE = True
except ImportError:
    I2C_ADC_AVAILABLE = False
    print("Warning: Adafruit ADS1x15 library not installed. Install with: pip install adafruit-circuitpython-ads1x15")

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
            print(f"✓ Serial port opened: {port} for data transmission")
            break
        except (serial.SerialException, FileNotFoundError):
            continue
    if serial_port is None:
        print("⚠ Warning: No serial port found for data transmission. Running without serial output.")
except Exception as e:
    print(f"Serial port error: {e}")
    serial_port = None

# -----------------------
# DAQ/ADC Initialization
# -----------------------
daq_device = None
daq_channel = None
DAQ_TYPE = None  # Will be 'MCC128', 'ADS1115', 'MCP3008', or None

# MCC 128 DAQ HAT configuration (like mignev6.py)
mcc128_hat = None
mcc128_channels = [0]  # Default to channel 0
mcc128_samples_per_channel = 100
mcc128_scan_rate = 8000.0
mcc128_options = None
mcc128_timeout = 100

# Try to initialize MCC 128 DAQ HAT first (highest priority - same as mignev6.py)
if MCC128_AVAILABLE:
    try:
        # Find available HAT devices
        hats = hat_list(filter_by_id=HatIDs.MCC_128)
        if hats:
            # Use the first HAT device
            address = hats[0].address
            mcc128_hat = mcc128(address)
            mcc128_hat.a_in_mode_write(AnalogInputMode.SE)
            mcc128_hat.a_in_range_write(AnalogInputRange.BIP_10V)
            
            daq_device = mcc128_hat
            daq_channel = mcc128_channels
            DAQ_TYPE = 'MCC128'
            
            try:
                mcc128_options = OptionFlags.DEFAULT
            except:
                mcc128_options = OptionFlags.CONTINUOUS
            
            print(f"✓ MCC 128 DAQ HAT initialized at address {address}")
            print(f"  Reading from channel(s): {mcc128_channels}")
            print(f"  Voltage range: ±10V")
            print(f"  Sample rate: {mcc128_scan_rate} Hz")
        else:
            print("No MCC 128 HAT devices found")
    except Exception as e:
        print(f"Could not initialize MCC 128: {e}")
        MCC128_AVAILABLE = False

# Try to initialize I2C ADC (ADS1115) if MCC128 not available
if daq_device is None and I2C_ADC_AVAILABLE:
    try:
        i2c = busio.I2C(board.SCL, board.SDA)
        ads = ADS.ADS1115(i2c)
        # Use channel A0 (you can change this to A1, A2, A3 as needed)
        daq_channel = AnalogIn(ads, ADS.P0)
        daq_device = ads
        DAQ_TYPE = 'ADS1115'
        print(f"✓ ADS1115 ADC initialized on I2C")
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
        print(f"✓ MCP3008 ADC initialized on SPI")
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
MICROSTEPS = 4                # MKS Servo57c set mstep = 4 (hardware)
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
# Serial Data Transmission
# -----------------------
def send_serial_data(x_mm, y_mm, z_value):
    """Send scan data point to plotter via serial"""
    global serial_port
    if serial_port and serial_port.is_open:
        try:
            # Format: x,y,z\n (matches plotter's expected format)
            data_str = f"{x_mm:.2f},{y_mm:.2f},{z_value:.6f}\n"
            serial_port.write(data_str.encode('ascii'))
            serial_port.flush()
        except Exception as e:
            print(f"Serial send error: {e}")

def send_scan_metadata(area_x_mm, area_y_mm, x_count, y_count):
    """Send scan area and count metadata to plotter via serial"""
    global serial_port
    if serial_port and serial_port.is_open:
        try:
            # Format: META,area_x,area_y,x_count,y_count\n
            meta_str = f"META,{area_x_mm:.2f},{area_y_mm:.2f},{x_count},{y_count}\n"
            serial_port.write(meta_str.encode('ascii'))
            serial_port.flush()
            print(f"Sent metadata: Area X={area_x_mm}mm, Area Y={area_y_mm}mm, X Count={x_count}, Y Count={y_count}")
        except Exception as e:
            print(f"Metadata send error: {e}")

def read_mcp3008(spi, channel):
    """
    Read MCP3008 ADC value via SPI.
    
    Args:
        spi: SPI device object
        channel: ADC channel (0-7)
    
    Returns:
        int: 10-bit ADC value (0-1023)
    """
    if channel < 0 or channel > 7:
        return 0
    
    # MCP3008 protocol: send 3 bytes, receive 3 bytes
    # Byte 1: Start bit (0x01)
    # Byte 2: Single-ended mode (0x80) + channel select
    # Byte 3: Don't care (0x00)
    adc = spi.xfer2([1, (8 + channel) << 4, 0])
    
    # Extract 10-bit value from response
    # Response format: [?, high_bits, low_bits]
    data = ((adc[1] & 3) << 8) + adc[2]
    return data

def read_sensor_value():
    """
    Read actual sensor value from DAQ/ADC.
    Returns voltage reading from the connected sensor.
    
    Supported hardware (in priority order):
    - MCC 128 DAQ HAT: 16-bit ADC, ±10V range (same as mignev6.py)
    - ADS1115 (I2C): 16-bit ADC, 0-5V range
    - MCP3008 (SPI): 10-bit ADC, 0-3.3V range
    
    Returns:
        float: Sensor reading in volts (or 0.0 if no DAQ available)
    """
    global daq_device, daq_channel, DAQ_TYPE
    global mcc128_hat, mcc128_channels, mcc128_samples_per_channel, mcc128_scan_rate, mcc128_options, mcc128_timeout
    
    if daq_device is None:
        # No DAQ available - return 0.0 (no simulated data)
        return 0.0
    
    try:
        if DAQ_TYPE == 'MCC128':
            # Read from MCC 128 DAQ HAT (same method as mignev6.py PointScan)
            channel_mask = chan_list_to_mask(mcc128_channels)
            
            # Start scan
            mcc128_hat.a_in_scan_start(channel_mask, mcc128_samples_per_channel, mcc128_scan_rate, mcc128_options)
            
            # Read data
            read_result = mcc128_hat.a_in_scan_read(mcc128_samples_per_channel, mcc128_timeout)
            
            # Stop and cleanup
            mcc128_hat.a_in_scan_stop()
            mcc128_hat.a_in_scan_cleanup()
            
            # Calculate average voltage from samples
            if read_result.data and len(read_result.data) > 0:
                voltage = sum(read_result.data) / len(read_result.data)
                return voltage
            else:
                return 0.0
                
        elif DAQ_TYPE == 'ADS1115':
            # Read from ADS1115 (I2C)
            # Returns voltage directly
            voltage = daq_channel.voltage
            return voltage
            
        elif DAQ_TYPE == 'MCP3008':
            # Read from MCP3008 (SPI)
            # Returns 10-bit value (0-1023)
            adc_value = read_mcp3008(daq_device, daq_channel)
            # Convert to voltage (0-3.3V range)
            voltage = (adc_value / 1023.0) * 3.3
            return voltage
            
        else:
            return 0.0
            
    except Exception as e:
        print(f"Sensor read error: {e}")
        return 0.0

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

        print("GPIO Initialized (No DAQ, No Doors, No Serial)")

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
        print("Homing X (toward X+)")
        # Move toward X+ (mapped to XmotorSet(0, 1500) then Xstart)
        self.xymove.XmotorSet(0, 500)
        self.xymove.Xstart()
    
        print("seeking X limit...")
        while not self.xymove.CheckXlimit_pos():
            if SystemFuncClass.stop_flag:
                break
            if self.xymove.EMGSwitch():
                SystemFuncClass().AllStop()
                return
            sleep(0.001)
        self.xymove.Xstop()
        print("X is home position")
        sleep(0.5)
    
        # Slow re-touch to settle on the X+ limit
        self.xymove.XmotorSet(1, 60)
        self.xymove.Xstart()
    
        print("seeking X limit (slow re-touch)...")
        while self.xymove.CheckXlimit_pos():
            if SystemFuncClass.stop_flag:
                break
            if self.xymove.EMGSwitch():
                SystemFuncClass().AllStop()
                return
            sleep(0.001)
        self.xymove.Xstop()
        print("X Homed")
    
        # AFTER homing on X+, move left (toward X-) by at least 3 mm and treat that as zero.
        try:
            extra_mm = 3.0
            extra_pulses = mm_to_pulses(extra_mm)
            if extra_pulses > 0 and not SystemFuncClass.stop_flag:
                print(f"Moving left additional {extra_mm} mm ({extra_pulses} pulses) to set zero position...")
                # Configure LEFT and start counting
                try:
                    # Use a safe speed for the offset move
                    self.xymove.XmotorSet(1, 50)
                    self.xymove.Xstart()
                except Exception:
                    pass
    
                # Record starting pulse count
                with self.xymove._count_lock:
                    start_pulse_count = self.xymove._pulse_count
    
                try:
                    while True:
                        if SystemFuncClass.stop_flag:
                            print("Abort extra-left move: global stop flag set")
                            break
                        if self.xymove.EMGSwitch():
                            SystemFuncClass().AllStop()
                            print("Abort extra-left move: EMG pressed")
                            break
    
                        with self.xymove._count_lock:
                            pulses_moved = self.xymove._pulse_count - start_pulse_count
    
                        # Stop early if we unexpectedly hit the X- limit
                        if self.xymove.CheckXlimit_neg():
                            print("X- limit reached during extra-left move; stopping early")
                            try:
                                self.xymove.X_hold_running(duration=0.05)
                            except Exception:
                                pass
                            break
    
                        if pulses_moved >= extra_pulses:
                            # small hold to stabilize
                            try:
                                self.xymove.X_hold_running(duration=0.05)
                            except Exception:
                                pass
                            break
    
                        sleep(0.001)
                finally:
                    try:
                        self.xymove.Xstop()
                    except Exception:
                        pass
    
                print(f"Completed extra-left move (~{extra_mm} mm). This position will be treated as X=0 when counters are reset.")
        except Exception as e:
            print("Error during extra-left homing offset:", e)

    def Yhome(self):
        print("Homing Y (toward Y+)")
        self.xymove.YmotorSet(1, 500)
        self.xymove.Ystart()

        print("seeking Y limit...")
        while not self.xymove.CheckYlimit_pos():
            if SystemFuncClass.stop_flag:
                break
            if self.xymove.EMGSwitch():
                SystemFuncClass().AllStop()
                return
            sleep(0.001)
        self.xymove.Ystop()
        print("Y is home position")
        sleep(0.5)

        self.xymove.YmotorSet(0, 60)
        self.xymove.Ystart()
        print("seeking Y limit (slow re-touch)...")
        while self.xymove.CheckYlimit_pos():
            if SystemFuncClass.stop_flag:
                break
            if self.xymove.EMGSwitch():
                SystemFuncClass().AllStop()
                return
            sleep(0.001)
        self.xymove.Ystop()
        print("Y Homed")

    def Home(self):
        self.sysfunc.GPIO_Init()
        print("=== START HOMING ===")
        self.Xhome()
        if SystemFuncClass.stop_flag: return
        self.Yhome()
        if SystemFuncClass.stop_flag: return
        print("=== HOMING COMPLETE ===")

# -----------------------
# SIMPLE SCAN CLASS (requires explicit params)
# -----------------------
class SimpleScanClass:
    def __init__(self, xymove=None, row_step=None, x_speed=None, y_speed=None, gui=None, x_count=None, y_count=None):
        # Require explicit parameters (no defaults)
        if row_step is None or x_speed is None or y_speed is None:
            raise ValueError("SimpleScanClass requires row_step, x_speed and y_speed explicitly")
        self.xy = xymove if xymove else XYMoveClass()
        # original row_step pulses (may be overridden below by Area Y / y_count)
        self.row_step = int(row_step)
        # x_speed and y_speed are frequencies (Hz)
        self.x_speed = int(x_speed)
        self.y_speed = int(y_speed)
        self.gui = gui  # optional reference to GUI to update labels during scan
    
        # Store counts (x_count is optional now; y_count required)
        self.x_count = int(x_count) if x_count is not None and str(x_count).strip() != "" else None
        self.y_count = int(y_count) if y_count is not None else None
    
        # Apply the speeds to the XYMoveClass so chunked moves (YmoveCorrect) use correct delays
        try:
            self.xy.XmotorSet(0, self.x_speed)
        except Exception:
            pass
        try:
            self.xy.YmotorSet(1, self.y_speed)
        except Exception:
            pass
    
        # Read area calibration values (if any) from GUI saved_config
        area_x_mm = 0.0
        area_y_mm = 0.0
        try:
            if self.gui and getattr(self.gui, 'saved_config', None):
                area_x_mm = float(self.gui.saved_config.get('area_x_mm', 0.0) or 0.0)
                area_y_mm = float(self.gui.saved_config.get('area_y_mm', 0.0) or 0.0)
        except Exception:
            area_x_mm = area_y_mm = 0.0
    
        # Horizontal usable span is (area_x_mm - 10)
        self.x_total_mm = max(area_x_mm - 10.0, 0.0)
        self.y_total_mm = max(area_y_mm - 10.0, 0.0)
    
        # Compute x_step_mm if x_count provided (optional)
        if self.x_count and self.x_count > 0:
            self.x_step_mm = self.x_total_mm / float(self.x_count)
        else:
            self.x_step_mm = 0.0
    
        # Row step (vertical) should be computed from Area Y (mm) / Y Scan Count,
        # truncated to a whole number of millimetres.
        if self.y_count and self.y_count > 0:
            raw_step_y = float(area_y_mm) / float(self.y_count) if area_y_mm > 0 else 0.0
            # truncate decimals toward zero
            self.y_step_mm = int(raw_step_y) if raw_step_y > 0 else 0
            # ensure at least 1 mm if raw_step_y > 0 but truncated to 0
            if self.y_step_mm == 0 and raw_step_y > 0:
                self.y_step_mm = 1
        else:
            self.y_step_mm = 0.0
    
        # Convert mm distances to pulses
        try:
            self.x_total_pulses = mm_to_pulses(self.x_total_mm)
            self.x_step_pulses = mm_to_pulses(self.x_step_mm)
            self.y_step_pulses = mm_to_pulses(self.y_step_mm)
        except Exception:
            self.x_total_pulses = 0
            self.x_step_pulses = 0
            self.y_step_pulses = 0
    
        # Override row_step pulses with the Area-Y-derived vertical step if available.
        # This ensures the scan uses the freshly saved/calculated row step (Area Y / Y count).
        if self.y_step_pulses and self.y_step_pulses > 0:
            self.row_step = int(self.y_step_pulses)

    # New helper: generic X-direction move by a fixed pulse target (position-based)
    def scan_x_by_pulses(self, direction, target_pulses, hold_after_limit=0.05):
        """
        Move horizontally for target_pulses using PWM counting.
        direction: 'LEFT' or 'RIGHT'
        Returns True on completion, False on abort/stop.
        """
        if target_pulses <= 0:
            # fallback to limit-based behavior if no distance configured
            if direction == "LEFT":
                return self.scan_left_until_xminus(hold_after_limit)
            else:
                return self.scan_right_until_xplus(hold_after_limit)

        # Configure direction and start PWM/counters
        try:
            if direction == "LEFT":
                self.xy.XmotorSet(1, self.x_speed)
                direction_sign = -1
            else:
                self.xy.XmotorSet(0, self.x_speed)
                direction_sign = +1
            self.xy.Xstart()
        except Exception:
            pass

        # Track pulses for this movement
        with self.xy._count_lock:
            start_pulse_count = self.xy._pulse_count

        last_ui = time.time()
        try:
            while True:
                if SystemFuncClass.stop_flag:
                    return False
                if self.xy.EMGSwitch():
                    SystemFuncClass().AllStop()
                    return False

                # Check pulses moved in THIS run
                with self.xy._count_lock:
                    pulses_moved = self.xy._pulse_count - start_pulse_count

                if pulses_moved >= target_pulses:
                    # optionally hold a tiny bit to secure trigger (keeps consistent behavior)
                    try:
                        self.xy.X_hold_running(duration=hold_after_limit)
                    except Exception:
                        pass
                    break

                # Periodic UI updates
                now = time.time()
                if self.gui and (now - last_ui >= 0.2):
                    last_ui = now
                    try:
                        self.xy.update_position_x(direction_sign)
                        pos_mm = self.xy.get_position_x_mm()
                        self.gui.win.after(0, lambda p=pos_mm:
                            self.gui.jog_x_count_label.config(text=f"X (mm): {int(p)}"))
                    except Exception:
                        pass

                # Also stop if a limit switch triggers unexpectedly (safety)
                if direction == "LEFT" and self.xy.CheckXlimit_neg():
                    try:
                        self.xy.X_hold_running(duration=hold_after_limit)
                    except Exception:
                        pass
                    break
                if direction == "RIGHT" and self.xy.CheckXlimit_pos():
                    try:
                        self.xy.X_hold_running(duration=hold_after_limit)
                    except Exception:
                        pass
                    break

                sleep(0.001)
        finally:
            try:
                self.xy.Xstop()
                # Final update
                self.xy.update_position_x(direction_sign)
            except Exception:
                pass

        # final GUI update
        if self.gui:
            try:
                pos_mm = self.xy.get_position_x_mm()
                self.gui.win.after(0, lambda p=pos_mm:
                    self.gui.jog_x_count_label.config(text=f"X (mm): {int(p)}"))
            except Exception:
                pass

        return True

    # New helper: move X to an absolute target position in mm (uses realtime position)
    def scan_x_to_position_mm(self, target_mm, hold_after_limit=0.05, collect_data=False, current_y_mm=0.0):
        """
        Move X axis until realtime X position reaches target_mm (mm).
        - target_mm: signed mm in the same frame as get_position_x_mm().
                     (Home should be 0.0 and X- negative, X+ positive)
        - collect_data: if True, read sensor and send data during movement
        - current_y_mm: current Y position for data collection
        Returns True on success (reached target), False on abort/limit/EMG.
        """
        # Read current position
        try:
            cur_mm = self.xy.get_position_x_mm()
        except Exception:
            cur_mm = 0.0

        delta_mm = target_mm - cur_mm
        if abs(delta_mm) < 0.001:
            # Already at target
            return True

        direction = "RIGHT" if delta_mm > 0 else "LEFT"
        direction_sign = 1 if delta_mm > 0 else -1
        target_pulses = mm_to_pulses(abs(delta_mm))
        if target_pulses <= 0:
            return True

        # Configure motor and start counting
        try:
            if direction == "LEFT":
                self.xy.XmotorSet(1, self.x_speed)
            else:
                self.xy.XmotorSet(0, self.x_speed)
            self.xy.Xstart()
        except Exception:
            pass

        with self.xy._count_lock:
            start_pulse_count = self.xy._pulse_count

        last_ui = time.time()
        last_data_time = time.time()
        data_interval = 0.05  # Collect data every 50ms during scan
        
        try:
            while True:
                if SystemFuncClass.stop_flag:
                    return False
                if self.xy.EMGSwitch():
                    SystemFuncClass().AllStop()
                    return False

                with self.xy._count_lock:
                    pulses_moved = self.xy._pulse_count - start_pulse_count

                if pulses_moved >= target_pulses:
                    try:
                        self.xy.X_hold_running(duration=hold_after_limit)
                    except Exception:
                        pass
                    break

                # Safety: stop if unexpected limit engages before reaching the position
                if direction == "LEFT" and self.xy.CheckXlimit_neg():
                    try:
                        self.xy.X_hold_running(duration=hold_after_limit)
                    except Exception:
                        pass
                    # update position to current
                    return False
                if direction == "RIGHT" and self.xy.CheckXlimit_pos():
                    try:
                        self.xy.X_hold_running(duration=hold_after_limit)
                    except Exception:
                        pass
                    return False

                # Data collection during scan
                now = time.time()
                if collect_data and (now - last_data_time >= data_interval):
                    last_data_time = now
                    try:
                        # Update position to get current X
                        self.xy.update_position_x(direction_sign)
                        current_x_mm = self.xy.get_position_x_mm()
                        
                        # Read sensor value
                        z_value = read_sensor_value()
                        
                        # Send data to plotter (convert to absolute coordinates)
                        # X position is negative when moving left, so convert to positive range
                        abs_x_mm = abs(current_x_mm)
                        abs_y_mm = abs(current_y_mm)
                        send_serial_data(abs_x_mm, abs_y_mm, z_value)
                        
                        print(f"Data: X={abs_x_mm:.2f}, Y={abs_y_mm:.2f}, Z={z_value:.6f}")
                    except Exception as e:
                        print(f"Data collection error: {e}")

                # Periodic GUI position update (consume pulses into position accumulator)
                if self.gui and (now - last_ui >= 0.15):
                    last_ui = now
                    try:
                        self.xy.update_position_x(direction_sign)
                        pos_mm = self.xy.get_position_x_mm()
                        self.gui.win.after(0, lambda p=pos_mm:
                            self.gui.jog_x_count_label.config(text=f"X (mm): {int(p)}"))
                    except Exception:
                        pass

                sleep(0.001)
        finally:
            try:
                self.xy.Xstop()
                # Final update to position for any remaining pulses
                self.xy.update_position_x(direction_sign)
            except Exception:
                pass

            if self.gui:
                try:
                    pos_mm = self.xy.get_position_x_mm()
                    self.gui.win.after(0, lambda p=pos_mm:
                        self.gui.jog_x_count_label.config(text=f"X (mm): {int(p)}"))
                except Exception:
                    pass

        return True

    def scan_x_to_position_mm_corrected(self, target_mm, hold_after_limit=0.05, collect_data=False, current_y_mm=0.0):
        """
        Move X axis to target position with CORRECTED coordinate system.
        
        NEW COORDINATE SYSTEM (Top-Right = 0,0):
        - After homing to X+, position is X=0 (right side, home)
        - Moving LEFT increases X coordinate (0 -> +x_total_mm)
        - Moving RIGHT decreases X coordinate (back toward 0)
        
        This means:
        - Internal position tracking uses negative values when moving LEFT
        - But we report positive values to the plotter (abs value)
        - target_mm: 0.0 = right side (home), positive = left side
        
        Returns True on success, False on abort/limit/EMG.
        """
        # Read current internal position (negative when left of home)
        try:
            cur_internal_mm = self.xy.get_position_x_mm()
        except Exception:
            cur_internal_mm = 0.0

        # Convert target from "corrected" coordinate (0=right, positive=left)
        # to internal coordinate (0=home, negative=left)
        target_internal_mm = -target_mm
        
        delta_mm = target_internal_mm - cur_internal_mm
        if abs(delta_mm) < 0.001:
            return True

        direction = "RIGHT" if delta_mm > 0 else "LEFT"
        direction_sign = 1 if delta_mm > 0 else -1
        target_pulses = mm_to_pulses(abs(delta_mm))
        if target_pulses <= 0:
            return True

        # Configure motor and start counting
        try:
            if direction == "LEFT":
                self.xy.XmotorSet(1, self.x_speed)
            else:
                self.xy.XmotorSet(0, self.x_speed)
            self.xy.Xstart()
        except Exception:
            pass

        with self.xy._count_lock:
            start_pulse_count = self.xy._pulse_count

        last_ui = time.time()
        last_data_time = time.time()
        data_interval = 0.05  # Collect data every 50ms during scan
        
        try:
            while True:
                if SystemFuncClass.stop_flag:
                    return False
                if self.xy.EMGSwitch():
                    SystemFuncClass().AllStop()
                    return False

                with self.xy._count_lock:
                    pulses_moved = self.xy._pulse_count - start_pulse_count

                if pulses_moved >= target_pulses:
                    try:
                        self.xy.X_hold_running(duration=hold_after_limit)
                    except Exception:
                        pass
                    break

                # Safety: stop if unexpected limit engages
                if direction == "LEFT" and self.xy.CheckXlimit_neg():
                    try:
                        self.xy.X_hold_running(duration=hold_after_limit)
                    except Exception:
                        pass
                    return False
                if direction == "RIGHT" and self.xy.CheckXlimit_pos():
                    try:
                        self.xy.X_hold_running(duration=hold_after_limit)
                    except Exception:
                        pass
                    return False

                # Data collection during scan
                now = time.time()
                if collect_data and (now - last_data_time >= data_interval):
                    last_data_time = now
                    try:
                        # Update internal position
                        self.xy.update_position_x(direction_sign)
                        internal_x_mm = self.xy.get_position_x_mm()
                        
                        # Convert to corrected coordinate system for plotter
                        # Internal: 0=home(right), negative=left
                        # Corrected: 0=home(right), positive=left
                        corrected_x_mm = abs(internal_x_mm)
                        corrected_y_mm = abs(current_y_mm)
                        
                        # Read sensor value
                        z_value = read_sensor_value()
                        
                        # Send data to plotter with corrected coordinates
                        send_serial_data(corrected_x_mm, corrected_y_mm, z_value)
                        
                        print(f"Data: X={corrected_x_mm:.2f}, Y={corrected_y_mm:.2f}, Z={z_value:.6f}")
                    except Exception as e:
                        print(f"Data collection error: {e}")

                # Periodic GUI position update
                if self.gui and (now - last_ui >= 0.15):
                    last_ui = now
                    try:
                        self.xy.update_position_x(direction_sign)
                        pos_mm = self.xy.get_position_x_mm()
                        # Show absolute value in GUI (corrected coordinate)
                        self.gui.win.after(0, lambda p=abs(pos_mm):
                            self.gui.jog_x_count_label.config(text=f"X (mm): {int(p)}"))
                    except Exception:
                        pass

                sleep(0.001)
        finally:
            try:
                self.xy.Xstop()
                self.xy.update_position_x(direction_sign)
            except Exception:
                pass

            if self.gui:
                try:
                    pos_mm = abs(self.xy.get_position_x_mm())
                    self.gui.win.after(0, lambda p=pos_mm:
                        self.gui.jog_x_count_label.config(text=f"X (mm): {int(p)}"))
                except Exception:
                    pass

        return True

    # Wrappers for clarity (keeps compatibility with previous names)
    def scan_left_until_xminus(self, hold_after_limit=0.1):
        # If x_total_pulses is configured, use it; else fall back to limit-based old behavior
        if getattr(self, 'x_total_pulses', 0) > 0:
            return self.scan_x_by_pulses("LEFT", self.x_total_pulses, hold_after_limit=hold_after_limit)
        # fallback
        print("Scanning LEFT to X- (PWM, limit fallback)")
        try:
            self.xy.XmotorSet(1, self.x_speed)
            self.xy.Xstart()
        except Exception:
            pass
        direction_sign = -1
        try:
            last_ui = time.time()
            while True:
                if SystemFuncClass.stop_flag:
                    return False
                if self.xy.EMGSwitch():
                    SystemFuncClass().AllStop()
                    return False
                if self.xy.CheckXlimit_neg():
                    self.xy.X_hold_running(duration=hold_after_limit)
                    break
                now = time.time()
                if self.gui and (now - last_ui >= 0.2):
                    last_ui = now
                    try:
                        self.xy.update_position_x(direction_sign)
                        pos_mm = self.xy.get_position_x_mm()
                        self.gui.win.after(0, lambda p=pos_mm:
                            self.gui.jog_x_count_label.config(text=f"X (mm): {int(p)}"))
                    except Exception:
                        pass
                sleep(0.001)
        finally:
            try:
                self.xy.Xstop()
                self.xy.update_position_x(direction_sign)
            except Exception:
                pass
        if self.gui:
            try:
                pos_mm = self.xy.get_position_x_mm()
                self.gui.win.after(0, lambda p=pos_mm:
                    self.gui.jog_x_count_label.config(text=f"X (mm): {int(p)}"))
            except Exception:
                pass
        return True

    def scan_right_until_xplus(self, hold_after_limit=0.1):
        if getattr(self, 'x_total_pulses', 0) > 0:
            return self.scan_x_by_pulses("RIGHT", self.x_total_pulses, hold_after_limit=hold_after_limit)
        # fallback to limit-based behavior (original)
        print("Scanning RIGHT to X+ (PWM, limit fallback)")
        try:
            self.xy.XmotorSet(0, self.x_speed)
            self.xy.Xstart()
        except Exception:
            pass
        direction_sign = +1
        try:
            last_ui = time.time()
            while True:
                if SystemFuncClass.stop_flag:
                    return False
                if self.xy.EMGSwitch():
                    SystemFuncClass().AllStop()
                    return False
                if self.xy.CheckXlimit_pos():
                    self.xy.X_hold_running(duration=hold_after_limit)
                    break
                now = time.time()
                if self.gui and (now - last_ui >= 0.2):
                    last_ui = now
                    try:
                        self.xy.update_position_x(direction_sign)
                        pos_mm = self.xy.get_position_x_mm()
                        self.gui.win.after(0, lambda p=pos_mm:
                            self.gui.jog_x_count_label.config(text=f"X (mm): {int(p)}"))
                    except Exception:
                        pass
                sleep(0.001)
        finally:
            try:
                self.xy.Xstop()
                self.xy.update_position_x(direction_sign)
            except Exception:
                pass
        if self.gui:
            try:
                pos_mm = self.xy.get_position_x_mm()
                self.gui.win.after(0, lambda p=pos_mm:
                    self.gui.jog_x_count_label.config(text=f"X (mm): {int(p)}"))
            except Exception:
                pass
        return True

    # move_y_down remains the same but uses self.row_step which has been overridden above
    def move_y_down(self, hold_after_limit=0.05):
        """
        Move Y down by self.row_step pulses, using PWM and counting actual STEP pulses.
        Updates persistent position counter (decrements Y).
        """
        print(f" Moving Y down (pulses) {self.row_step}")

        try:
            self.xy.YmotorSet(0, self.y_speed)  # DOWN
            self.xy.Ystart()  # This now initializes _last_pulse_count
        except Exception:
            pass

        direction_sign = -1  # DOWN decreases Y
        target = abs(self.row_step)

        # Track pulses for THIS movement only (to know when we've moved row_step)
        with self.xy._count_lock:
            start_pulse_count = self.xy._pulse_count

        last_ui = time.time()
        try:
            while True:
                if SystemFuncClass.stop_flag:
                    return False

                if self.xy.EMGSwitch():
                    SystemFuncClass().AllStop()
                    return False

                if self.xy.CheckYlimit_neg():
                    try:
                        self.xy.Y_hold_running(duration=hold_after_limit)
                    except Exception:
                        pass
                    return False

                # Check pulses moved in THIS step
                with self.xy._count_lock:
                    pulses_this_move = self.xy._pulse_count - start_pulse_count

                if pulses_this_move >= target:
                    return True

                # Update position and GUI periodically
                now = time.time()
                if self.gui and (now - last_ui >= 0.15):
                    last_ui = now
                    try:
                        self.xy.update_position_y(direction_sign)
                        pos_mm = self.xy.get_position_y_mm()
                        self.gui.win.after(0, lambda p=pos_mm:
                            self.gui.jog_y_count_label.config(text=f"Y (mm): {int(p)}"))
                    except Exception:
                        pass

                sleep(0.001)

        finally:
            try:
                self.xy.Ystop()
                # Final update
                self.xy.update_position_y(direction_sign)
            except Exception:
                pass
            if self.gui:
                try:
                    pos_mm = self.xy.get_position_y_mm()
                    self.gui.win.after(0, lambda p=pos_mm:
                        self.gui.jog_y_count_label.config(text=f"Y (mm): {int(p)}"))
                except Exception:
                    pass

    def simple_scan(self):
        """Main simple snake scan routine driven by Y scan count.
    
        COORDINATE SYSTEM:
          - After homing, X=0 is at the TOP-RIGHT corner (X+ limit)
          - Moving LEFT increases X coordinate (0 -> x_total_mm)
          - Y=0 is at the top (Y+ limit)
          - Moving DOWN increases Y coordinate (0 -> y_total_mm)
    
        Sequence:
          - Send metadata (area and scan counts) to plotter
          - Send start marker (0,0,0) to plotter (top-right corner)
          - Start with an initial LEFT scan from Home (X == 0, top-right).
          - For i in 1..Y_count:
              - Move Y down by one row_step (this is the i-th count)
              - Perform a horizontal scan that alternates direction each row;
                the first post-move scan is RIGHT.
          - Send end marker when complete
        Example Y_count=5:
          LEFT, move down (1), RIGHT, move down (2), LEFT, move down (3),
          RIGHT, move down (4), LEFT, move down (5), RIGHT
        """
        print("=== START SIMPLE SCAN (Y-count based) ===")
        print("COORDINATE SYSTEM: (0,0) = TOP-RIGHT corner")
    
        if not (self.y_count and self.y_count > 0):
            print("simple_scan: y_count not provided or invalid")
            return
    
        # In the new coordinate system:
        # - right_target_mm = 0.0 (starting position at top-right)
        # - left_target_mm = +x_total_mm (left side has positive X)
        left_target_mm = self.x_total_mm  # Positive value (left side)
        right_target_mm = 0.0              # Zero (right side, home position)
    
        try:
            y_step_mm = pulses_to_mm(self.row_step)
        except Exception:
            y_step_mm = 0.0
    
        print(f"Scan config: right_target_mm={right_target_mm} mm (home), left_target_mm={left_target_mm} mm, y_step_mm={y_step_mm} mm, y_count={self.y_count}")
    
        # Send metadata to plotter FIRST (area dimensions and scan counts)
        try:
            area_x_mm = self.x_total_mm + 10.0  # Add back the 10mm offset
            area_y_mm = self.y_total_mm + 10.0  # Add back the 10mm offset
            x_count_to_send = self.x_count if self.x_count else 0
            send_scan_metadata(area_x_mm, area_y_mm, x_count_to_send, self.y_count)
            time.sleep(0.2)  # Give plotter time to process metadata
        except Exception as e:
            print(f"Failed to send metadata: {e}")
    
        # Send start marker to plotter (0,0,0) - top-right corner
        send_serial_data(0.0, 0.0, 0.0)
        print("Sent start marker (0,0,0) to plotter - TOP-RIGHT corner")
        time.sleep(0.1)  # Small delay to ensure plotter receives marker
    
        # Track current Y position for data collection
        current_y_mm = 0.0
    
        # Start with an initial LEFT scan from home (X == 0, top-right corner)
        print("Initial horizontal pass: LEFT from top-right (0,0) (collecting data)")
        ok = self.scan_x_to_position_mm_corrected(left_target_mm, collect_data=True, current_y_mm=current_y_mm)
        if not ok:
            print("simple_scan: initial LEFT pass aborted (limit/EMG/stop).")
            return
    
        # Track last horizontal direction performed
        last_direction = "LEFT"
    
        # Now repeat for each Y-count: move down, then perform the alternating horizontal pass.
        for count in range(1, self.y_count + 1):
            if SystemFuncClass.stop_flag:
                print("simple_scan: stop_flag set, aborting")
                return
    
            # Move down by one row_step (this is the "count"-th backward movement)
            print(f"Count {count}/{self.y_count}: moving Y down by {self.row_step} pulses (~{y_step_mm} mm)")
            moved = self.move_y_down()
            if not moved:
                print("simple_scan: Y limit reached during vertical move. Ending scan and performing final sweep if appropriate.")
                # Attempt a final horizontal sweep to the opposite boundary relative to current side
                try:
                    if last_direction == "LEFT":
                        print("Final sweep after Y-limit: RIGHT (collecting data)")
                        self.scan_x_to_position_mm_corrected(right_target_mm, collect_data=True, current_y_mm=abs(self.xy.get_position_y_mm()))
                    else:
                        print("Final sweep after Y-limit: LEFT (collecting data)")
                        self.scan_x_to_position_mm_corrected(left_target_mm, collect_data=True, current_y_mm=abs(self.xy.get_position_y_mm()))
                except Exception:
                    pass
                break
    
            # Update current Y position
            try:
                current_y_mm = abs(self.xy.get_position_y_mm())
            except Exception:
                current_y_mm = count * y_step_mm
    
            # Decide next horizontal direction (alternate)
            next_direction = "RIGHT" if last_direction == "LEFT" else "LEFT"
            target_x_mm = right_target_mm if next_direction == "RIGHT" else left_target_mm
            print(f"Count {count}/{self.y_count}: horizontal pass {next_direction} to {target_x_mm} mm (collecting data)")
    
            ok = self.scan_x_to_position_mm_corrected(target_x_mm, collect_data=True, current_y_mm=current_y_mm)
            if not ok:
                print(f"simple_scan: horizontal move to {target_x_mm} mm aborted (limit/EMG/stop).")
                break
    
            # Update last direction
            last_direction = next_direction
    
        # Send end marker to plotter (max_x, max_y, 0)
        try:
            final_x = self.x_total_mm  # Left edge
            final_y = abs(self.xy.get_position_y_mm())
            send_serial_data(final_x, final_y, 0.0)
            print(f"Sent end marker ({final_x:.2f},{final_y:.2f},0) to plotter")
        except Exception as e:
            print(f"Error sending end marker: {e}")
    
        # Final GUI update of X position
        if self.gui:
            try:
                pos_mm = self.xy.get_position_x_mm()
                self.gui.win.after(0, lambda p=pos_mm:
                    self.gui.jog_x_count_label.config(text=f"X (mm): {int(p)}"))
            except Exception:
                pass
    
        print("=== SIMPLE SCAN FINISHED (Y-count based) ===")


# -----------------------
# ScanRoutine Controller (requires params)
# -----------------------
class DataScanClass:
    def __init__(self, gui=None):
        self.gui = gui
        self.xymove = XYMoveClass()
        self.home = GoHomePosClass()

    def ScanRoutine(self, row_step, x_speed, y_speed, x_count, y_count):
        """
        Start a scan routine. If the GUI's Axis Status Label already indicates "Homed"
        (or "Home"), skip performing a fresh homing sequence.

        Now takes x_count and y_count to control position-based scanning grid.
        x_count is optional (movement span comes from area_x_mm + 10).
        """
        print("=== START SCAN ROUTINE ===")
        try:
            # Decide whether to run homing. If GUI was provided and reports "Homed" or "Home", skip homing.
            do_home = True
            try:
                if getattr(self, 'gui', None) is not None:
                    gui_status = ""
                    # Prefer the internal cached status text if available
                    try:
                        gui_status = getattr(self.gui, '_status_text', "") or ""
                    except Exception:
                        gui_status = ""
                    # Fallback to reading the visible label text
                    if not gui_status:
                        try:
                            if hasattr(self.gui, 'status_label'):
                                gui_status = str(self.gui.status_label.cget('text') or "")
                        except Exception:
                            gui_status = gui_status or ""
                    gs = str(gui_status).strip().lower()
                    if gs in ("homed", "home"):
                        do_home = False
            except Exception:
                # If any error reading GUI status, default to performing homing
                do_home = True

            if do_home:
                print("Performing homing before scan...")
                self.home.Home()
                sleep(2.0)
            else:
                print("Skipping homing (GUI status indicates already homed)")

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
        self.sublogo.place(x=100, y=55)

        # Buttons
        self.HomeButton = tk.Button(self.win, text="HOME", font=self.buttonFont2, bg='lightgreen',
                                    command=self.started_homing, width=6, height=3)
        self.HomeButton.place(x=10, y=90)

        self.ScanButton = tk.Button(self.win, text="SCAN", font=self.buttonFont2, bg='lightgreen',
                                    command=self.scan_started, width=6, height=3)
        self.ScanButton.place(x=170, y=90)

        self.StopButton = tk.Button(self.win, text="STOP", font=self.buttonFont2, bg='red',
                                    command=self.stop_all_motion, width=6, height=3)
        self.StopButton.place(x=330, y=90)

        # New Calibrate Area button
        self.CalibButton = tk.Button(self.win, text="Calibrate\nArea", font=self.buttonFont3, bg='orange',
                                     command=self.start_area_calibration, width=6, height=3)
        self.CalibButton.place(x=10, y=220)

        self.ExitButton = tk.Button(self.win, text='Exit', font=self.buttonFont, command=self.gui_exit, height=1, width=6)
        self.ExitButton.place(x=390, y=5)

        self.RebootButton = tk.Button(self.win, text='Reboot', font=self.buttonFont, command=self.system_func.reboot, height=1, width=6)
        self.RebootButton.place(x=520, y=5)

        self.ShutdownButton = tk.Button(self.win, text='Shutdown', font=self.buttonFont, command=self.system_func.shutdown, height=1, width=7)
        self.ShutdownButton.place(x=650, y=5)

        # Show Keyboard button (toggles the on-screen keyboard)
        # Place it near the parameter entries
        self.kb_proc = None  # subprocess.Popen object for the keyboard (if any)
        self.KBButton = tk.Button(self.win, text="Show\nKeyboard", font=self.buttonFont3, command=self.toggle_keyboard, height=4, width=8)
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

        self._homing_active = False
        self._scanning_active = False

        # Adjustable parameters area (no hard-coded defaults)
        self.row_label = tk.Label(self.win, text="Row Step (mm):", font=self.labelFont, bg='#0046ad', fg='white')
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
                    self.row_entry.insert(0, str(rv))
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

        # X/Y Scan Count entries (placed to the right of the speed entries)
        self.xcount_label = tk.Label(self.win, text="X Scan Count:", font=self.labelFont, bg='#0046ad', fg='white')
        self.xcount_label.place(x=310, y=230)
        self.xcount_entry = tk.Entry(self.win, font=TkFont.Font(size=14), width=4)
        self.xcount_entry.place(x=470, y=230)

        self.ycount_label = tk.Label(self.win, text="Y Scan Count:", font=self.labelFont, bg='#0046ad', fg='white')
        self.ycount_label.place(x=310, y=265)
        self.ycount_entry = tk.Entry(self.win, font=TkFont.Font(size=14), width=4)
        self.ycount_entry.place(x=470, y=265)

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
                self.ycount_entry.insert(0, str(int(ycnt)))
            except Exception:
                try:
                    self.ycount_entry.insert(0, str(ycnt))
                except Exception:
                    pass

        self.help_label = tk.Label(self.win, text="Enter integer values. Config saved when scanning starts.",
                                   font=TkFont.Font(size=10), bg='#0046ad', fg='white')
        self.help_label.place(x=10, y=420)

        # Directional Jog Buttons (press-and-hold to jog)
        # Positioning approximate (center cluster)
        self.jog_label = tk.Label(self.win, text="Manual Jog:",
                                   font=self.labelFont, bg='#0046ad', fg='white')
        self.jog_label.place(x=530, y=220)
        
        self.btn_up = tk.Button(self.win, text="↑", font=TkFont.Font(size=20), bg='lightgreen', width=2, height=1)
        self.btn_up.place(x=600, y=250)
        self.btn_left = tk.Button(self.win, text="←", font=TkFont.Font(size=20), bg='lightgreen', width=2, height=1)
        self.btn_left.place(x=530, y=295)
        self.btn_right = tk.Button(self.win, text="→", font=TkFont.Font(size=20), bg='lightgreen', width=2, height=1)
        self.btn_right.place(x=670, y=295)
        self.btn_down = tk.Button(self.win, text="↓", font=TkFont.Font(size=20), bg='lightgreen', width=2, height=1)
        self.btn_down.place(x=600, y=340)

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
        self.real_pos.place(x=500, y=420)
        
        self.jog_x_count_label = tk.Label(self.win, text="X (mm): 0", font=TkFont.Font(size=12), bg='#0046ad', fg='white')
        self.jog_x_count_label.place(x=500, y=440)
        self.jog_y_count_label = tk.Label(self.win, text="Y (mm): 0", font=TkFont.Font(size=12), bg='#0046ad', fg='white')
        self.jog_y_count_label.place(x=660, y=440)

        # Area calibration display (new)
        self.area_x_display = tk.Label(self.win, text=f"Area X (mm): {int(self.saved_config.get('area_x_mm', 0))}", font=TkFont.Font(size=12), bg='#0046ad', fg='white')
        self.area_x_display.place(x=135, y=240)
        self.area_y_display = tk.Label(self.win, text=f"Area Y (mm): {int(self.saved_config.get('area_y_mm', 0))}", font=TkFont.Font(size=12), bg='#0046ad', fg='white')
        self.area_y_display.place(x=135, y=260)

        # Limit status labels
        self.l_xpos = tk.Label(self.win, text="X+ : ?", font=TkFont.Font(size=14), width=6, bg='darkred', fg='white')
        self.l_xpos.place(x=640, y=90)
        self.l_xneg = tk.Label(self.win, text="X- : ?", font=TkFont.Font(size=14), width=6, bg='darkred', fg='white')
        self.l_xneg.place(x=520, y=90)
        self.l_ypos = tk.Label(self.win, text="Y+ : ?", font=TkFont.Font(size=14), width=6, bg='darkred', fg='white')
        self.l_ypos.place(x=580, y=60)
        self.l_yneg = tk.Label(self.win, text="Y- : ?", font=TkFont.Font(size=14), width=6, bg='darkred', fg='white')
        self.l_yneg.place(x=580, y=120)
        self.l_emg  = tk.Label(self.win, text="EMG: ?", font=TkFont.Font(size=14), width=6, bg='darkred', fg='white')
        self.l_emg.place(x=580, y=160)

        # after-id for periodic update
        self.limit_after_id = None

        # DataScan object (create after UI so GUI entries exist)
        self.data_scan = DataScanClass(self)

        # Initialize status to READY (green)
        self.set_status("READY", bg=self.status_ready_bg, blink=False)

        # start periodic updates of limit status
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
        """
        Centralized status update. Safe to call from any thread.
        - text: status string
        - bg: explicit background color (None = use defaults)
        - blink: True to start blinking with blink_color
        """
        # schedule on main thread to keep UI thread-safe
        def _set():
            self._status_text = text
            if blink:
                # set text and start blinking
                try:
                    self.status_label.config(text=text)
                except Exception:
                    pass
                self.start_blink(blink_color)
            else:
                # stop blinking and set static background
                self.stop_blink()
                if bg is None:
                    # default bg choices
                    if text == "READY" or text == "Homed":
                        bg_use = self.status_ready_bg
                    else:
                        bg_use = self.status_normal_bg
                else:
                    bg_use = bg
                fg = 'black' if bg_use in ('green', 'lightgreen', 'yellow') else 'white'
                try:
                    self.status_label.config(text=text, bg=bg_use, fg=fg)
                except Exception:
                    pass
        try:
            self.win.after(0, _set)
        except Exception:
            # fallback: try to call directly (best-effort)
            _set()

    # --------------------- HOMING ---------------------
    def started_homing(self):
        """
        Triggered by the HOME button. Disable Scan and all jog buttons while homing.
        Start homing in a background thread and restore UI when finished.
        """
        # Prevent re-entry
        if self._homing_active:
            return

        # Mark homing active
        self._homing_active = True

        # Disable Scan and all jog buttons immediately on the UI thread
        try:
            self.win.after(0, lambda: self.HomeButton.config(state='disabled'))
            self.win.after(0, lambda: self.ScanButton.config(state='disabled'))
            # Disable jog buttons
            self.win.after(0, lambda: self.btn_up.config(state='disabled'))
            self.win.after(0, lambda: self.btn_down.config(state='disabled'))
            self.win.after(0, lambda: self.btn_left.config(state='disabled'))
            self.win.after(0, lambda: self.btn_right.config(state='disabled'))
        except Exception:
            pass

        # Homing should blink green
        self.set_status("Homing...", blink=True, blink_color='green')

        # Start homing in background thread
        threading.Thread(target=self.goto_home, daemon=True).start()

    def goto_home(self):
        """
        Background worker for homing. Calls GoHomePosClass().Home() and restores UI
        after homing finishes (unless other operations require buttons to remain disabled).
        """
        try:
            GoHomePosClass().Home()
            # If homing completed without global stop_flag and not EMG active -> show Homed
            if not SystemFuncClass.stop_flag and not self._emg_active:
                # reset pulse counters after homing
                try:
                    self.win.after(0, self.reset_pulse_counters)
                except Exception:
                    try:
                        self.reset_pulse_counters()
                    except Exception:
                        pass
                self.set_status("Homed", bg=self.status_ready_bg, blink=False)
        except Exception as e:
            print("Home Error:", e)
            traceback.print_exc()
            self.set_status("READY", bg=self.status_ready_bg, blink=False)
        finally:
            # Homing finished or aborted - clear homing flag and restore buttons appropriately
            try:
                self._homing_active = False
                # Re-enable Scan button (only if not currently scanning)
                if not self._scanning_active:
                    try:
                        self.win.after(0, lambda: self.HomeButton.config(state='normal'))
                        self.win.after(0, lambda: self.ScanButton.config(state='normal'))
                    except Exception:
                        pass
                # Re-enable jog buttons only if not scanning (scanning keeps jogs disabled)
                if not self._scanning_active:
                    try:
                        self.win.after(0, lambda: self.btn_up.config(state='normal'))
                        self.win.after(0, lambda: self.btn_down.config(state='normal'))
                        self.win.after(0, lambda: self.btn_left.config(state='normal'))
                        self.win.after(0, lambda: self.btn_right.config(state='normal'))
                    except Exception:
                        pass
                # Always ensure HOME button is re-enabled (it was disabled only when scanning)
                if not self._scanning_active:
                    try:
                        self.win.after(0, lambda: self.HomeButton.config(state='normal'))
                    except Exception:
                        pass
            except Exception:
                pass

    # --------------------- SCAN ---------------------
    def scan_started(self):
        """
        Validate params, disable Home and jogs, then start scanning in background.
        Restore UI when scanning finishes.
        """
        # Prevent re-entry if already scanning
        if self._scanning_active:
            return

        # Mark scanning active
        self._scanning_active = True

        # Disable Home and all jog buttons immediately
        try:
            self.win.after(0, lambda: self.HomeButton.config(state='disabled'))
            self.win.after(0, lambda: self.ScanButton.config(state='disabled'))
            self.win.after(0, lambda: self.btn_up.config(state='disabled'))
            self.win.after(0, lambda: self.btn_down.config(state='disabled'))
            self.win.after(0, lambda: self.btn_left.config(state='disabled'))
            self.win.after(0, lambda: self.btn_right.config(state='disabled'))
        except Exception:
            pass

        # Disable Scan button in GUI (prevent double-start)
        try:
            self.ScanButton.config(state='disabled')
        except Exception:
            pass

        # Scanning should blink green
        self.set_status("Scanning...", blink=True, blink_color='green')

        valid = self.validate_and_save_params()
        if valid is None:
            # invalid: reset UI
            try:
                self.ScanButton.config(state='normal')
            except Exception:
                pass
            # clear scanning flag and re-enable home/jogs if appropriate
            self._scanning_active = False
            # If not homing, re-enable Home and jogs
            if not self._homing_active:
                try:
                    self.HomeButton.config(state='normal')
                    self.btn_up.config(state='normal')
                    self.btn_down.config(state='normal')
                    self.btn_left.config(state='normal')
                    self.btn_right.config(state='normal')
                except Exception:
                    pass
            self.set_status("READY", bg=self.status_ready_bg, blink=False)
            return

        # Unpack returned internal units and counts
        row_pulses, x_speed_hz, y_speed_hz, x_count, y_count = valid

        def _scan_worker():
            try:
                self.reset_pulse_counters()
                # run scan routine (this will call homing internally as needed)
                self.data_scan.ScanRoutine(row_pulses, x_speed_hz, y_speed_hz, x_count, y_count)
            except Exception as e:
                print("Scan Error:", e)
                traceback.print_exc()
            finally:
                # Scanning finished. Clear scanning flag and restore UI appropriately
                try:
                    self._scanning_active = False
                    # Re-enable Scan button
                    try:
                        self.win.after(0, lambda: self.ScanButton.config(state='normal'))
                    except Exception:
                        pass
                    # Re-enable Home button if not homing
                    if not self._homing_active:
                        try:
                            self.win.after(0, lambda: self.HomeButton.config(state='normal'))
                            self.win.after(0, lambda: self.ScanButton.config(state='normal'))
                        except Exception:
                            pass
                    # Re-enable jog buttons if not homing
                    if not self._homing_active:
                        try:
                            self.win.after(0, lambda: self.btn_up.config(state='normal'))
                            self.win.after(0, lambda: self.btn_down.config(state='normal'))
                            self.win.after(0, lambda: self.btn_left.config(state='normal'))
                            self.win.after(0, lambda: self.btn_right.config(state='normal'))
                        except Exception:
                            pass
                    # Return UI to READY state (stop blinking)
                    self.set_status("READY", bg=self.status_ready_bg, blink=False)
                except Exception:
                    pass

        threading.Thread(target=_scan_worker, daemon=True).start()

    def scan_start(self):
        # kept for compatibility (not used)
        self.scan_started()

    # --------------------- STOP ---------------------
    def stop_all_motion(self):
        SystemFuncClass.stop_flag = True
        SystemFuncClass().AllStop()
        # also ensure any jog threads stop
        try:
            self._jog_active_x = False
            self._jog_active_y = False
            if self.data_scan and getattr(self.data_scan, 'xymove', None):
                try:
                    self.data_scan.xymove.Xstop()
                    self.data_scan.xymove.Ystop()
                except Exception:
                    pass
        except Exception:
            pass

        # Indicate stopped in UI (red), then after a short pause return to READY
        self.set_status("STOPPED", bg='red', blink=False)
        sleep(1)
        SystemFuncClass.stop_flag = False
        # Only set back to READY if EMG is not active
        if not self._emg_active:
            self.set_status("READY", bg=self.status_ready_bg, blink=False)

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
            ycount_s = self.ycount_entry.get().strip()
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
    
        # Compute row step automatically per request: Area Y (mm) / Y Scan Count, truncated to whole mm
        raw_row = float(area_y_mm) / float(y_count) if y_count > 0 else 0.0
        # Truncate decimal part to get whole number mm (e.g. 50.23 -> 50)
        computed_row_mm = int(raw_row) if raw_row > 0 else 0
    
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
            "row_step_mm": float(round(computed_row_mm, 3)),
            "x_speed_rpm": x_rpm,
            "y_speed_rpm": y_rpm,
            "x_count": int(x_count) if x_count is not None else None,
            "y_count": y_count
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
                self.row_entry.insert(0, str(computed_row_mm))
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
        Periodic readout of limit switches and EMG; updates labels and disables/enables
        the appropriate jog buttons based on limit state, and respects homing/scanning.
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

        def set_label(lbl, name, val):
            try:
                lbl.config(text=f"{name} : {int(bool(val))}")
                if val:
                    lbl.config(bg='green', fg='black')
                else:
                    lbl.config(bg='darkred', fg='white')
            except Exception:
                pass

        set_label(self.l_xpos, "X+", xpos)
        set_label(self.l_xneg, "X-", xneg)
        set_label(self.l_ypos, "Y+", ypos)
        set_label(self.l_yneg, "Y-", yneg)
        # EMG label custom: show 1/0
        try:
            self.l_emg.config(text=f"EMG : {int(bool(emg))}")
            if emg:
                self.l_emg.config(bg='green', fg='black')
            else:
                self.l_emg.config(bg='darkred', fg='white')
        except Exception:
            pass

        # EMG handling: if EMG pressed, show EMG Stopped in red and trigger AllStop once
        if emg:
            if not self._emg_active:
                # first detection of EMG -> take action
                self._emg_active = True
                try:
                    SystemFuncClass().AllStop()
                except Exception:
                    pass
            # Update status label to EMG Stopped (override any blinking)
            self.set_status("EMG Stopped", bg='red', blink=False)
            # Disable all controls while EMG active
            try:
                self.ScanButton.config(state='disabled')
                self.HomeButton.config(state='disabled')
                self.btn_up.config(state='disabled')
                self.btn_down.config(state='disabled')
                self.btn_left.config(state='disabled')
                self.btn_right.config(state='disabled')
            except Exception:
                pass
        else:
            # If EMG was previously active and is now released, call STOP handler
            if self._emg_active:
                # clear EMG active flag (so a future press will be handled)
                self._emg_active = False
                # Schedule stop_all_motion on the GUI thread to mimic pressing STOP
                try:
                    self.win.after(0, self.stop_all_motion)
                except Exception:
                    try:
                        self.stop_all_motion()
                    except Exception:
                        pass
            else:
                # For non-transition case (EMG not active), ensure scanning/homing status keeps blinking (or READY stays green)
                cur_text = self._status_text
                if cur_text in ("Scanning...", "Homing..."):
                    if self._blink_job is None:
                        self.set_status(cur_text, blink=True, blink_color='green')
                else:
                    if cur_text == "READY":
                        self.set_status("READY", bg=self.status_ready_bg, blink=False)

            # Manage button states based on homing/scanning and limit switches
            try:
                # Homing active: ensure Scan disabled and all jogs disabled
                if getattr(self, "_homing_active", False):
                    try:
                        self.ScanButton.config(state='disabled')
                        self.btn_up.config(state='disabled')
                        self.btn_down.config(state='disabled')
                        self.btn_left.config(state='disabled')
                        self.btn_right.config(state='disabled')
                    except Exception:
                        pass
                # Scanning active: ensure Home disabled and all jogs disabled
                elif getattr(self, "_scanning_active", False):
                    try:
                        self.HomeButton.config(state='disabled')
                        self.btn_up.config(state='disabled')
                        self.btn_down.config(state='disabled')
                        self.btn_left.config(state='disabled')
                        self.btn_right.config(state='disabled')
                    except Exception:
                        pass
                else:
                    # Normal mode (neither homing nor scanning)  enable Scan & Home by default
                    try:
                        self.ScanButton.config(state='normal')
                        self.HomeButton.config(state='normal')
                    except Exception:
                        pass

                    # Enable/disable individual jog buttons based on limit switches:
                    try:
                        # Y+ -> disable btn_up
                        if ypos:
                            self.btn_up.config(state='disabled')
                        else:
                            self.btn_up.config(state='normal')

                        # Y- -> disable btn_down
                        if yneg:
                            self.btn_down.config(state='disabled')
                        else:
                            self.btn_down.config(state='normal')

                        # X+ -> disable btn_right
                        if xpos:
                            self.btn_right.config(state='disabled')
                        else:
                            self.btn_right.config(state='normal')
                        # X- -> disable btn_left
                        if xneg:
                            self.btn_left.config(state='disabled')
                        else:
                            self.btn_left.config(state='normal')
                    except Exception:
                        pass
            except Exception:
                pass

        # schedule next update
        try:
            self.limit_after_id = self.win.after(200, self.update_limit_status)
        except Exception:
            self.limit_after_id = None

    # --------------------- Area Calibration (NEW) ---------------------
    def start_area_calibration(self):
        """
        Trigger area calibration. Requires axis to be 'Homed' (status label shows Homed or Home).
        This will:
          - from zero (homed) move LEFT until X- limit and record realtime X (mm)
          - then move DOWN until Y- limit and record realtime Y (mm)
        The measured extents (absolute mm) are saved to config keys: area_x_mm, area_y_mm
        """
        # Prevent re-entry while another operation is ongoing
        if getattr(self, "_scanning_active", False) or getattr(self, "_homing_active", False):
            messagebox.showinfo("Busy", "Cannot calibrate while homing or scanning is active.")
            return
        if SystemFuncClass.stop_flag:
            messagebox.showinfo("System Stop", "System is stopped. Clear stop and try again.")
            return
        # Require homed status (best-effort check)
        cur = getattr(self, "_status_text", "") or ""
        if str(cur).strip().lower() not in ("homed", "home"):
            res = messagebox.askyesno("Not Homed", "Axis status is not 'Homed'. Run homing now before calibration?")
            if res:
                self.started_homing()
                # calibration will have to be retried after homing completes
            return

        # Disable UI buttons and start calibration thread
        try:
            self._calib_active = True
            # disable relevant buttons
            self.win.after(0, lambda: self.CalibButton.config(state='disabled'))
            self.win.after(0, lambda: self.HomeButton.config(state='disabled'))
            self.win.after(0, lambda: self.ScanButton.config(state='disabled'))
            self.win.after(0, lambda: self.btn_up.config(state='disabled'))
            self.win.after(0, lambda: self.btn_down.config(state='disabled'))
            self.win.after(0, lambda: self.btn_left.config(state='disabled'))
            self.win.after(0, lambda: self.btn_right.config(state='disabled'))
        except Exception:
            pass

        # update status
        self.set_status("Calibrating...", blink=True, blink_color='yellow')

        threading.Thread(target=self._area_calibration_worker, daemon=True).start()

    def _area_calibration_worker(self):
        """
        Background worker that performs the calibration sequence:
         - from homed (0,0) move LEFT until X- limit triggers -> record X extent
         - then move DOWN until Y- limit triggers -> record Y extent
        Saves area_x_mm and area_y_mm to config and updates UI.
        """
        x_extent = 0.0
        y_extent = 0.0
        aborted = False

        try:
            xy = self.data_scan.xymove

            # Ensure counters start from zero (homed = zero)
            try:
                xy.reset_position_counters()
            except Exception:
                pass

            # --- PRECHECK: if X- already asserted, skip moving left ---
            try:
                if xy.CheckXlimit_neg():
                    print("Area Calib: X- already asserted at start; treating X extent as 0")
                    x_extent = 0.0
                    try:
                        self.win.after(0, lambda v=x_extent: self.area_x_display.config(text=f"Area X (mm): {int(round(v))}"))
                    except Exception:
                        pass
                else:
                    # Start LEFT motion
                    try:
                        speed_x = self._get_x_speed_safe()
                        # Explicitly set DIR pins for LEFT for robustness
                        try:
                            pi.write(PortDefineClass.DIR1, DIR_MAP["LEFT"][0])
                            pi.write(PortDefineClass.DIR2, DIR_MAP["LEFT"][1])
                        except Exception:
                            pass
                        xy.XmotorSet(1, speed_x)  # 1 => LEFT
                        xy.Xstart()               # initializes _last_pulse_count
                    except Exception as e:
                        print("Area Calib: failed to start X motion:", e)
                        aborted = True

                    # Poll until X- limit triggers or abort/EMG/stop
                    if not aborted:
                        direction_sign = -1
                        try:
                            last_ui = time.time()
                            while True:
                                if SystemFuncClass.stop_flag:
                                    print("Area Calib: global stop_flag detected, aborting X move")
                                    aborted = True
                                    break
                                if xy.EMGSwitch():
                                    print("Area Calib: EMG detected, aborting X move")
                                    SystemFuncClass().AllStop()
                                    aborted = True
                                    break

                                # Immediate stop on limit assertion
                                if xy.CheckXlimit_neg():
                                    print("Area Calib: X- limit detected, stopping X PWM immediately")
                                    try:
                                        xy.Xstop()
                                    except Exception:
                                        pass
                                    # do a tiny delay to let hardware settle
                                    time.sleep(0.02)
                                    break

                                # Periodically update realtime X display
                                now = time.time()
                                if now - last_ui >= 0.15:
                                    last_ui = now
                                    try:
                                        xy.update_position_x(direction_sign)
                                        pos_mm = xy.get_position_x_mm()
                                        self.win.after(0, lambda p=pos_mm:
                                                       self.jog_x_count_label.config(text=f"X (mm): {int(p)}"))
                                    except Exception:
                                        pass

                                sleep(0.002)
                        finally:
                            # Ensure PWM is stopped
                            try:
                                xy.Xstop()
                            except Exception:
                                pass
                            # Final position update
                            try:
                                xy.update_position_x(direction_sign)
                            except Exception:
                                pass

                        # read final X extent (absolute)
                        try:
                            x_extent = abs(xy.get_position_x_mm())
                        except Exception:
                            x_extent = 0.0

                        # Update UI with measured X immediately
                        try:
                            self.win.after(0, lambda v=x_extent: self.area_x_display.config(text=f"Area X (mm): {int(round(v))}"))
                        except Exception:
                            pass

            # --- Now move DOWN until Y- limit (unless aborted) ---
            except Exception:
                # If some unexpected error occurred during X stage precheck/start, mark aborted
                aborted = True

            if not aborted:
                try:
                    if xy.CheckYlimit_neg():
                        print("Area Calib: Y- already asserted at start of Y move; treating Y extent as 0")
                        y_extent = 0.0
                        try:
                            self.win.after(0, lambda v=y_extent: self.area_y_display.config(text=f"Area Y (mm): {int(round(v))}"))
                        except Exception:
                            pass
                    else:
                        try:
                            speed_y = self._get_y_speed_safe()
                            # Explicitly set DIR pins for DOWN for robustness
                            try:
                                pi.write(PortDefineClass.DIR1, DIR_MAP["DOWN"][0])
                                pi.write(PortDefineClass.DIR2, DIR_MAP["DOWN"][1])
                            except Exception:
                                pass
                            xy.YmotorSet(0, speed_y)  # 0 => DOWN
                            xy.Ystart()
                        except Exception as e:
                            print("Area Calib: failed to start Y motion:", e)
                            aborted = True

                        if not aborted:
                            direction_sign = -1
                            try:
                                last_ui = time.time()
                                while True:
                                    if SystemFuncClass.stop_flag:
                                        print("Area Calib: global stop_flag detected, aborting Y move")
                                        aborted = True
                                        break
                                    if xy.EMGSwitch():
                                        print("Area Calib: EMG detected, aborting Y move")
                                        SystemFuncClass().AllStop()
                                        aborted = True
                                        break

                                    # Immediate stop on Y- limit assertion
                                    if xy.CheckYlimit_neg():
                                        print("Area Calib: Y- limit detected, stopping Y PWM immediately")
                                        try:
                                            xy.Ystop()
                                        except Exception:
                                            pass
                                        time.sleep(0.02)
                                        break

                                    # Periodic UI updates
                                    now = time.time()
                                    if now - last_ui >= 0.15:
                                        last_ui = now
                                        try:
                                            xy.update_position_y(direction_sign)
                                            pos_mm = xy.get_position_y_mm()
                                            self.win.after(0, lambda p=pos_mm:
                                                           self.jog_y_count_label.config(text=f"Y (mm): {int(p)}"))
                                        except Exception:
                                            pass

                                    sleep(0.002)
                            finally:
                                try:
                                    xy.Ystop()
                                except Exception:
                                    pass
                                try:
                                    xy.update_position_y(direction_sign)
                                except Exception:
                                    pass

                            # read final Y extent (absolute)
                            try:
                                y_extent = abs(xy.get_position_y_mm())
                            except Exception:
                                y_extent = 0.0

                            # Update UI with measured Y
                            try:
                                self.win.after(0, lambda v=y_extent: self.area_y_display.config(text=f"Area Y (mm): {int(round(v))}"))
                            except Exception:
                                pass
                except Exception as e:
                    print("Area Calib: unexpected error during Y stage:", e)
                    aborted = True

            # Save calibration into config (save measured extents even if zeros)
            try:
                cfg = dict(self.saved_config or {})
                cfg["area_x_mm"] = float(round(x_extent, 3))
                cfg["area_y_mm"] = float(round(y_extent, 3))
                save_config(cfg)
                self.saved_config = cfg
                print(f"Area calibration saved: X={cfg['area_x_mm']} mm, Y={cfg['area_y_mm']} mm")
            except Exception as e:
                print("Area Calib: failed to save config:", e)

            # Notify user on completion or abort
            if aborted:
                try:
                    self.win.after(0, lambda: messagebox.showwarning("Calibration Aborted",
                                                                    "Area calibration was aborted (EMG/Stop)."))
                except Exception:
                    pass
            else:
                try:
                    self.win.after(0, lambda: messagebox.showinfo("Calibration Complete",
                                                                  f"Measured area extents:\nX = {int(round(x_extent))} mm\nY = {int(round(y_extent))} mm"))
                except Exception:
                    pass

        except Exception as e:
            print("Area calibration worker error:", e)
            traceback.print_exc()
            try:
                # Capture 'e' into default arg so it remains available when the lambda runs later
                self.win.after(0, lambda ex=e: messagebox.showerror("Calibration Error",
                                                                    f"Error during area calibration: {ex}"))
            except Exception:
                pass

        finally:
            # restore UI state
            try:
                self._calib_active = False
                self.win.after(0, lambda: self.CalibButton.config(state='normal'))
                if not getattr(self, "_scanning_active", False) and not getattr(self, "_homing_active", False):
                    self.win.after(0, lambda: self.HomeButton.config(state='normal'))
                    self.win.after(0, lambda: self.ScanButton.config(state='normal'))
                    self.win.after(0, lambda: self.btn_up.config(state='normal'))
                    self.win.after(0, lambda: self.btn_down.config(state='normal'))
                    self.win.after(0, lambda: self.btn_left.config(state='normal'))
                    self.win.after(0, lambda: self.btn_right.config(state='normal'))
            except Exception:
                pass

            # Reset status to READY (or Homed if appropriate)
            try:
                if not self._emg_active:
                    self.set_status("READY", bg=self.status_ready_bg, blink=False)
            except Exception:
                pass

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


