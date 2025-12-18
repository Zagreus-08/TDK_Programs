#!/usr/bin/env python3
"""
FINAL SCRIPT: NO Z, NO DAQ, NO DOORS, NO SERIAL
XY HOMING + SIMPLE SNAKE SCAN WITH GUI CONTROL
- Direction mapping and switch polarity handling applied
- Y move stops if Y- limit is reached mid-step
- No default scan params: loaded/saved from scan_config.json in script folder
- Config is saved automatically when a scan is started

MODIFICATIONS:
- Status label supports:
    * READY -> steady green background
    * "Scanning..." / "Homing..." -> blinking green background
    * EMG pressed -> "EMG Stopped" red background and AllStop triggered
- Added a "Show Keyboard" button next to parameter area to launch the installed
  on-screen keyboard (tries 'onboard', falls back to 'matchbox-keyboard'/'florence').
  The button toggles (Show/Hide). The keyboard process is tracked and terminated
  when hiding or on GUI exit.
- Recommendations:
    * If your on-screen keyboard binary differs, update the candidates list in
      GUIClass.find_keyboard_cmd().
    * Consider adding debounce/filtering on the EMG input if noisy.
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

# -----------------------
# Globals / Config file
# -----------------------
pi = pigpio.pi()

# Configure switch polarity:
# Set to True if switches read '1' when pressed (active-high).
# Set to False if switches read '0' when pressed (active-low).
SWITCH_ACTIVE_HIGH = True

# Direction tuples are (motor_x1_dir, motor_x2_dir)
DIR_MAP = {
    "DOWN":  (0, 1),
    "UP":    (1, 0),
    "LEFT":  (1, 1),
    "RIGHT": (0, 0),
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
# Utility: interpret hardware active state
# -----------------------
def gpio_active(pin):
    """Return True if the logical 'pressed' state is active for given pin,
    respecting SWITCH_ACTIVE_HIGH setting."""
    try:
        raw = pi.read(pin)
    except Exception:
        raw = 0
    return bool(raw) if SWITCH_ACTIVE_HIGH else not bool(raw)

# -----------------------
# Port Mapping
# -----------------------
class PortDefineClass:
    DIR1 = 24
    STEP1 = 25

    DIR2 = 18
    STEP2 = 23

    X_pos_limit = 17     # X+
    Y_pos_limit = 15     # Y+
    X_neg_limit = 19     # X-
    Y_neg_limit = 14     # Y-

    SWITCH = 5         # Emergency switch

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
                pi.set_pull_up_down(p, pigpio.PUD_DOWN)
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
# XY Movement Engine
# -----------------------
class XYMoveClass(MotorClass, PortDefineClass, SystemFuncClass):

    def EMGSwitch(self):
        return gpio_active(PortDefineClass.SWITCH)

    # --- X step movements (chunked synchronous stepping) ---
    def XrightCorrect(self, step):
        """Step-move to the right by 'step' microsteps (chunked)."""
        if SystemFuncClass.stop_flag:
            return False
        chunk = 200
        while step > 0:
            if SystemFuncClass.stop_flag:
                return False
            s = min(chunk, step)

            def m1(): MotorClass.motor_x1.motor_go(DIR_MAP["RIGHT"][0], "Full", s, .0003, False, .0001)
            def m2(): MotorClass.motor_x2.motor_go(DIR_MAP["RIGHT"][1], "Full", s, .0003, False, .0001)

            t1 = threading.Thread(target=m1); t2 = threading.Thread(target=m2)
            t1.start(); t2.start(); t1.join(); t2.join()
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

            def m1(): MotorClass.motor_x1.motor_go(DIR_MAP["LEFT"][0], "Full", s, .0003, False, .0001)
            def m2(): MotorClass.motor_x2.motor_go(DIR_MAP["LEFT"][1], "Full", s, .0003, False, .0001)

            t1 = threading.Thread(target=m1); t2 = threading.Thread(target=m2)
            t1.start(); t2.start(); t1.join(); t2.join()
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
        """Set PWM frequency for both X step pins."""
        try:
            pi.set_PWM_frequency(PortDefineClass.STEP1, sp)
            pi.set_PWM_frequency(PortDefineClass.STEP2, sp)
        except Exception:
            pass

    def XmotorSet(self, d, sp):
        """Set X direction and speed (frequency)."""
        self.Xdir(d)
        self.XmotorSpeed(sp)

    def Xstart(self):
        """Start X PWM (50 duty) on both step pins."""
        try:
            pi.set_PWM_dutycycle(PortDefineClass.STEP1, 50)
            pi.set_PWM_dutycycle(PortDefineClass.STEP2, 50)
        except Exception:
            pass

    def Xstop(self):
        """Stop X PWM (duty 0)."""
        try:
            pi.set_PWM_dutycycle(PortDefineClass.STEP1, 0)
            pi.set_PWM_dutycycle(PortDefineClass.STEP2, 0)
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

            def m1(): MotorClass.motor_x1.motor_go(DIR_MAP["DOWN"][0], "Full", s, .00008, False, .0001)
            def m2(): MotorClass.motor_x2.motor_go(DIR_MAP["DOWN"][1], "Full", s, .00008, False, .0001)

            t1 = threading.Thread(target=m1); t2 = threading.Thread(target=m2)
            t1.start(); t2.start(); t1.join(); t2.join()
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

            def m1(): MotorClass.motor_x1.motor_go(DIR_MAP["UP"][0], "Full", s, .00008, False, .0001)
            def m2(): MotorClass.motor_x2.motor_go(DIR_MAP["UP"][1], "Full", s, .00008, False, .0001)

            t1 = threading.Thread(target=m1); t2 = threading.Thread(target=m2)
            t1.start(); t2.start(); t1.join(); t2.join()
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
        self.Ydir(d)
        self.YmotorSpeed(sp)

    def Ystart(self):
        try:
            pi.set_PWM_dutycycle(PortDefineClass.STEP1, 50)
            pi.set_PWM_dutycycle(PortDefineClass.STEP2, 50)
        except Exception:
            pass

    def Ystop(self):
        try:
            pi.set_PWM_dutycycle(PortDefineClass.STEP1, 0)
            pi.set_PWM_dutycycle(PortDefineClass.STEP2, 0)
        except Exception:
            pass

    def CheckYlimit_pos(self):
        return gpio_active(PortDefineClass.Y_pos_limit)

    def CheckYlimit_neg(self):
        return gpio_active(PortDefineClass.Y_neg_limit)

# -----------------------
# HOMING CLASS (X then Y)
# -----------------------
class GoHomePosClass:
    sysfunc = SystemFuncClass()
    xymove  = XYMoveClass()

    def Xhome(self):
        print("Homing X (toward X+)")
        # Move toward X+ (mapped to XmotorSet(0) in original script? Keep mapping consistent)
        # Using original approach: set XmotorSet(0, 1500) then Xstart
        self.xymove.XmotorSet(0, 1500)
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

        while self.xymove.CheckXlimit_pos():
            if SystemFuncClass.stop_flag:
                break
            self.xymove.XmoveCorrect(-50)
            if self.xymove.EMGSwitch():
                SystemFuncClass().AllStop()
                return
            sleep(0.001)

        self.xymove.XmotorSet(0, 60)
        self.xymove.Xstart()

        print("seeking X limit (slow re-touch)...")
        while not self.xymove.CheckXlimit_pos():
            if SystemFuncClass.stop_flag:
                break
            if self.xymove.EMGSwitch():
                SystemFuncClass().AllStop()
                return
            sleep(0.001)
        self.xymove.Xstop()
        print("X Homed")

    def Yhome(self):
        print("Homing Y (toward Y+)")
        self.xymove.YmotorSet(1, 1500)
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

        while self.xymove.CheckYlimit_pos():
            if SystemFuncClass.stop_flag:
                break
            self.xymove.YmoveCorrect(-50)
            if self.xymove.EMGSwitch():
                SystemFuncClass().AllStop()
                return
            sleep(0.001)

        self.xymove.YmotorSet(1, 60)
        self.xymove.Ystart()
        print("seeking Y limit (slow re-touch)...")
        while not self.xymove.CheckYlimit_pos():
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
        self.Yhome()
        if SystemFuncClass.stop_flag: return
        self.Xhome()
        if SystemFuncClass.stop_flag: return
        print("=== HOMING COMPLETE ===")

# -----------------------
# SIMPLE SCAN CLASS (requires explicit params)
# -----------------------
class SimpleScanClass:
    def __init__(self, xymove=None, row_step=None, x_speed=None, y_speed=None):
        # Require explicit parameters (no defaults)
        if row_step is None or x_speed is None or y_speed is None:
            raise ValueError("SimpleScanClass requires row_step, x_speed and y_speed explicitly")
        self.xy = xymove if xymove else XYMoveClass()
        self.row_step = int(row_step)
        self.x_speed = int(x_speed)
        self.y_speed = int(y_speed)

    def go_to_xy_plus_corners(self):
        """Move both axes toward their + limits until both are triggered."""
        print("Moving to X+ & Y+")
        # Keep original behavior: set X and Y as in original script
        self.xy.XmotorSet(1, self.x_speed)
        self.xy.YmotorSet(1, self.y_speed)
        self.xy.Xstart(); self.xy.Ystart()
        try:
            while True:
                if SystemFuncClass.stop_flag:
                    self.xy.Xstop(); self.xy.Ystop()
                    return False
                if self.xy.CheckXlimit_pos() and self.xy.CheckYlimit_pos():
                    break
                # EMG check
                if self.xy.EMGSwitch():
                    SystemFuncClass().AllStop()
                    return False
                sleep(0.001)
        finally:
            self.xy.Xstop(); self.xy.Ystop()
        print("At X+ & Y+")
        return True

    def scan_left_until_xminus(self, hold_after_limit=0.1):
        """Scan LEFT until X- limit is detected. Hold running for hold_after_limit seconds after detection."""
        print("Scanning LEFT to X-")
        # LEFT = d==1 per Xdir mapping
        self.xy.XmotorSet(1, self.x_speed)
        self.xy.Xstart()
        try:
            while True:
                if SystemFuncClass.stop_flag:
                    return False
                if self.xy.CheckXlimit_neg():
                    # Keep running for a short duration to ensure reliable triggering
                    self.xy.X_hold_running(duration=hold_after_limit)
                    break
                if self.xy.EMGSwitch():
                    SystemFuncClass().AllStop()
                    return False
                sleep(0.001)
        finally:
            try:
                self.xy.Xstop()
            except Exception:
                pass
        return True

    def scan_right_until_xplus(self, hold_after_limit=0.1):
        """Scan RIGHT until X+ limit is detected. Hold running for hold_after_limit seconds after detection."""
        print("Scanning RIGHT to X+")
        # RIGHT = d==0 per Xdir mapping
        self.xy.XmotorSet(0, self.x_speed)
        self.xy.Xstart()
        try:
            while True:
                if SystemFuncClass.stop_flag:
                    return False
                if self.xy.CheckXlimit_pos():
                    # Keep running a short time after detection
                    self.xy.X_hold_running(duration=hold_after_limit)
                    break
                if self.xy.EMGSwitch():
                    SystemFuncClass().AllStop()
                    return False
                sleep(0.001)
        finally:
            try:
                self.xy.Xstop()
            except Exception:
                pass
        return True

    def move_y_down(self):
        """
        Move Y down by row_step, monitoring for Y- limit during movement.
        Returns:
            True if full step completed without hitting Y- limit
            False if Y- limit was triggered during movement (partial step)
        """
        print(f" Moving Y down {self.row_step}")
        chunk = 50  # steps per small move
        remaining = abs(self.row_step)

        while remaining > 0:
            if SystemFuncClass.stop_flag:
                return False

            # If Y- already hit, abort (partial)
            if self.xy.CheckYlimit_neg():
                print("Y- limit detected during downward movement (partial row)")
                return False

            step_size = min(chunk, remaining)
            # perform the small chunk (this uses YmoveCorrect which is interruptible)
            self.xy.YmoveCorrect(-step_size)
            remaining -= step_size

            # Check again after chunk
            if self.xy.CheckYlimit_neg():
                print("Y- limit detected during downward movement (partial row)")
                return False

        # Full step completed
        return True

    def simple_scan(self):
        """Main simple snake scan routine with robust X-limit triggering behavior."""
        print("=== START SIMPLE SCAN ===")

        direction = "LEFT"

        while True:
            if SystemFuncClass.stop_flag:
                return

            # Horizontal scan in current direction
            if direction == "LEFT":
                if not self.scan_left_until_xminus():
                    return
                next_direction = "RIGHT"
            else:
                if not self.scan_right_until_xplus():
                    return
                next_direction = "LEFT"

            # Move down one row (monitor for Y- limit)
            full_step_completed = self.move_y_down()

            # If Y- limit was triggered during downward movement, perform final scan on the last (partial) row
            if not full_step_completed or self.xy.CheckYlimit_neg():
                print("Y- Limit reached. Performing final scan on partial/last row.")

                # Determine which direction to scan based on where we just came from
                if next_direction == "RIGHT":
                    # We were at X-, now scan RIGHT until X+ or stop
                    print("Final scan: RIGHT (X- → X+)")
                    target_limit = self.xy.CheckXlimit_pos
                    self.xy.XmotorSet(0, self.x_speed)  # RIGHT
                else:
                    # We were at X+, now scan LEFT until X- or stop
                    print("Final scan: LEFT (X+ → X-)")
                    target_limit = self.xy.CheckXlimit_neg
                    self.xy.XmotorSet(1, self.x_speed)  # LEFT

                try:
                    self.xy.Xstart()
                    # Run until target X limit is hit; hold briefly after first detection
                    while True:
                        if SystemFuncClass.stop_flag:
                            break
                        if target_limit():
                            # ensure we hold running slightly to secure triggering
                            self.xy.X_hold_running(duration=0.5)
                            print("Final scan complete: reached target X limit")
                            break
                        if self.xy.EMGSwitch():
                            SystemFuncClass().AllStop()
                            break
                        sleep(0.001)
                finally:
                    try:
                        self.xy.Xstop()
                    except Exception:
                        pass

                # Finished scanning
                break

            # Continue to next row (toggle direction)
            direction = next_direction

        print("=== SIMPLE SCAN FINISHED ===")

# -----------------------
# ScanRoutine Controller (requires params)
# -----------------------
class DataScanClass:
    def __init__(self, gui=None):
        self.gui = gui
        self.xymove = XYMoveClass()
        self.home = GoHomePosClass()

    def ScanPos(self):
        print("Moving to scan offsets...")
        self.xymove.XmoveCorrect(StatusDataClass.x_offset)
        self.xymove.YmoveCorrect(StatusDataClass.y_offset)

    def ScanRoutine(self, row_step, x_speed, y_speed):
        print("=== START SCAN ROUTINE ===")
        self.home.Home()
        sleep(2.0)
        simple = SimpleScanClass(self.xymove, row_step=row_step, x_speed=x_speed, y_speed=y_speed)
        simple.simple_scan()
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
                                    command=self.started_homing, width=6, height=5)
        self.HomeButton.place(x=10, y=90)

        self.ScanButton = tk.Button(self.win, text="SCAN", font=self.buttonFont2, bg='lightgreen',
                                    command=self.scan_started, width=6, height=5)
        self.ScanButton.place(x=170, y=90)

        self.StopButton = tk.Button(self.win, text="STOP", font=self.buttonFont2, bg='red',
                                    command=self.stop_all_motion, width=6, height=5)
        self.StopButton.place(x=330, y=90)

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

        # --- UI state management ---
        # Valid states: 'init' (only Home+Stop), 'ready' (Home disabled, Scan+Jog enabled),
        # 'scanning' (only Stop enabled), 'emg'(all disabled)
        self._ui_state = 'init'

    def set_ui_state(self, state):
        """Set grouped UI button states according to high-level state."""
        self._ui_state = state
        if state == 'init':
            # Only Home and Stop enabled
            try:
                self.HomeButton.config(state='normal')
                self.ScanButton.config(state='disabled')
                self.btn_up.config(state='disabled')
                self.btn_down.config(state='disabled')
                self.btn_left.config(state='disabled')
                self.btn_right.config(state='disabled')
                self.StopButton.config(state='normal')
            except Exception:
                pass
        elif state == 'ready':
            # After homing: Home disabled, Scan & jog enabled
            try:
                self.HomeButton.config(state='disabled')
                self.ScanButton.config(state='normal')
                self.btn_up.config(state='normal')
                self.btn_down.config(state='normal')
                self.btn_left.config(state='normal')
                self.btn_right.config(state='normal')
                self.StopButton.config(state='normal')
            except Exception:
                pass
        elif state == 'scanning':
            # During scanning: only Stop enabled
            try:
                self.HomeButton.config(state='disabled')
                self.ScanButton.config(state='disabled')
                self.btn_up.config(state='disabled')
                self.btn_down.config(state='disabled')
                self.btn_left.config(state='disabled')
                self.btn_right.config(state='disabled')
                self.StopButton.config(state='normal')
            except Exception:
                pass
        elif state == 'emg':
            # Emergency stop: disable everything
            try:
                self.HomeButton.config(state='disabled')
                self.ScanButton.config(state='disabled')
                self.btn_up.config(state='disabled')
                self.btn_down.config(state='disabled')
                self.btn_left.config(state='disabled')
                self.btn_right.config(state='disabled')
                self.StopButton.config(state='disabled')
            except Exception:
                pass
        else:
            # Unknown state: fallback to safe (init)
            self.set_ui_state('init')

        # Jog state variables (keep here to reset when states change)
        self._jog_active_x = False
        self._jog_active_y = False
        self._jog_thread_x = None
        self._jog_thread_y = None

        # Pulse counters and fractional accumulators
        self.jog_pulse_x = 0
        self.jog_pulse_y = 0
        self._jog_acc_x = 0.0
        self._jog_acc_y = 0.0

        return

        # DataScan object (create after UI so GUI entries exist)
        self.data_scan = DataScanClass(self)

        # Adjustable parameters area (no hard-coded defaults)
        self.row_label = tk.Label(self.win, text="Row Step (steps):", font=self.labelFont, bg='#0046ad', fg='white')
        self.row_label.place(x=10, y=300)
        self.row_entry = tk.Entry(self.win, font=TkFont.Font(size=14), width=10)
        self.row_entry.place(x=200, y=300)
        if "row_step" in self.saved_config:
            try:
                self.row_entry.insert(0, str(int(self.saved_config["row_step"])))
            except Exception:
                pass

        self.xspeed_label = tk.Label(self.win, text="X Speed (Hz):", font=self.labelFont, bg='#0046ad', fg='white')
        self.xspeed_label.place(x=10, y=340)
        self.xspeed_entry = tk.Entry(self.win, font=TkFont.Font(size=14), width=10)
        self.xspeed_entry.place(x=200, y=340)
        if "x_speed" in self.saved_config:
            try:
                self.xspeed_entry.insert(0, str(int(self.saved_config["x_speed"])))
            except Exception:
                pass

        self.yspeed_label = tk.Label(self.win, text="Y Speed (Hz):", font=self.labelFont, bg='#0046ad', fg='white')
        self.yspeed_label.place(x=10, y=380)
        self.yspeed_entry = tk.Entry(self.win, font=TkFont.Font(size=14), width=10)
        self.yspeed_entry.place(x=200, y=380)
        if "y_speed" in self.saved_config:
            try:
                self.yspeed_entry.insert(0, str(int(self.saved_config["y_speed"])))
            except Exception:
                pass

        self.help_label = tk.Label(self.win, text="Enter integer values. Config saved when scanning starts.",
                                   font=TkFont.Font(size=10), bg='#0046ad', fg='white')
        self.help_label.place(x=10, y=420)

        # Directional Jog Buttons (press-and-hold to jog)
        # Positioning approximate (center cluster)
        self.btn_up = tk.Button(self.win, text="UP", font=self.buttonFont3, bg='lightgreen', width=4, height=2)
        self.btn_up.place(x=590, y=300)
        self.btn_left = tk.Button(self.win, text="LEFT", font=self.buttonFont3, bg='lightgreen', width=4, height=2)
        self.btn_left.place(x=510, y=345)
        self.btn_right = tk.Button(self.win, text="RIGHT", font=self.buttonFont3, bg='lightgreen', width=4, height=2)
        self.btn_right.place(x=670, y=345)
        self.btn_down = tk.Button(self.win, text="DOWN", font=self.buttonFont3, bg='lightgreen', width=4, height=2)
        self.btn_down.place(x=590, y=390)

        # Bind press/release for press-and-hold jog behavior
        self.btn_left.bind('<ButtonPress-1>', lambda e: self.start_jog_x('LEFT'))
        self.btn_left.bind('<ButtonRelease-1>', lambda e: self.stop_jog_x())

        self.btn_right.bind('<ButtonPress-1>', lambda e: self.start_jog_x('RIGHT'))
        self.btn_right.bind('<ButtonRelease-1>', lambda e: self.stop_jog_x())

        self.btn_up.bind('<ButtonPress-1>', lambda e: self.start_jog_y('UP'))
        self.btn_up.bind('<ButtonRelease-1>', lambda e: self.stop_jog_y())

        self.btn_down.bind('<ButtonPress-1>', lambda e: self.start_jog_y('DOWN'))
        self.btn_down.bind('<ButtonRelease-1>', lambda e: self.stop_jog_y())

        # Pulse counter labels (below the jog buttons)
        self.jog_x_count_label = tk.Label(self.win, text="X Pulses: 0", font=TkFont.Font(size=12), bg='#0046ad', fg='white')
        self.jog_x_count_label.place(x=510, y=450)
        self.jog_y_count_label = tk.Label(self.win, text="Y Pulses: 0", font=TkFont.Font(size=12), bg='#0046ad', fg='white')
        self.jog_y_count_label.place(x=650, y=450)

        # Limit status labels
        self.l_xpos = tk.Label(self.win, text="X+ : ?", font=TkFont.Font(size=14), width=12, bg='darkred', fg='white')
        self.l_xpos.place(x=560, y=60)
        self.l_xneg = tk.Label(self.win, text="X- : ?", font=TkFont.Font(size=14), width=12, bg='darkred', fg='white')
        self.l_xneg.place(x=560, y=100)
        self.l_ypos = tk.Label(self.win, text="Y+ : ?", font=TkFont.Font(size=14), width=12, bg='darkred', fg='white')
        self.l_ypos.place(x=560, y=140)
        self.l_yneg = tk.Label(self.win, text="Y- : ?", font=TkFont.Font(size=14), width=12, bg='darkred', fg='white')
        self.l_yneg.place(x=560, y=180)
        self.l_emg  = tk.Label(self.win, text="EMG: ?", font=TkFont.Font(size=14), width=12, bg='darkred', fg='white')
        self.l_emg.place(x=560, y=220)

        # after-id for periodic update
        self.limit_after_id = None

        # Initialize status to READY (green)
        self.set_status("READY", bg=self.status_ready_bg, blink=False)

        # Initialize UI state to only Home + Stop enabled
        try:
            self.set_ui_state('init')
        except Exception:
            pass

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
        # User pressed HOME — disable HOME and go busy
        self.HomeButton.config(state='disabled')
        # Set UI to busy state (only Stop enabled)
        try:
            self.set_ui_state('scanning')
        except Exception:
            pass
        # Homing should blink green
        self.set_status("Homing...", blink=True, blink_color='green')
        threading.Thread(target=self.goto_home, daemon=True).start()

    def goto_home(self):
        try:
            GoHomePosClass().Home()
            # If homing completed without global stop_flag and not EMG active -> show Homed and enable Scan/Jog
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
                # Switch UI: Home disabled, Scan + jog enabled
                try:
                    self.win.after(0, lambda: self.set_ui_state('ready'))
                except Exception:
                    try:
                        self.set_ui_state('ready')
                    except Exception:
                        pass
            else:
                # Homing aborted or EMG active -> return to initial state
                try:
                    self.win.after(0, lambda: self.set_ui_state('init'))
                except Exception:
                    try:
                        self.set_ui_state('init')
                    except Exception:
                        pass
        except Exception as e:
            print("Home Error:", e)
            traceback.print_exc()
            self.set_status("READY", bg=self.status_ready_bg, blink=False)
            try:
                self.win.after(0, lambda: self.set_ui_state('init'))
            except Exception:
                try:
                    self.set_ui_state('init')
                except Exception:
                    pass
        finally:
            # Ensure HOME not left enabled here; state transitions are handled explicitly above
            pass

    # --------------------- SCAN ---------------------
    def scan_started(self):
        # user-facing wrapper that will validate, save config and then start scan thread
        # Run validation & save on main thread, then background the scan.
        self.ScanButton.config(state='disabled')
        # Scanning should blink green
        self.set_status("Scanning...", blink=True, blink_color='green')

        # Switch UI to scanning state (only STOP enabled)
        try:
            self.win.after(0, lambda: self.set_ui_state('scanning'))
        except Exception:
            try:
                self.set_ui_state('scanning')
            except Exception:
                pass

        valid = self.validate_and_save_params()
        if valid is None:
            # invalid: re-enable and reset status and UI
            self.ScanButton.config(state='normal')
            self.set_status("READY", bg=self.status_ready_bg, blink=False)
            try:
                self.win.after(0, lambda: self.set_ui_state('ready'))
            except Exception:
                try:
                    self.set_ui_state('ready')
                except Exception:
                    pass
            return
        row_step, x_speed, y_speed = valid

        def _scan_worker():
            try:
                self.data_scan.ScanRoutine(row_step, x_speed, y_speed)
            except Exception as e:
                print("Scan Error:", e)
                traceback.print_exc()
            finally:
                try:
                    # Return UI to READY state (stop blinking) on main thread
                    self.win.after(0, lambda: self.ScanButton.config(state='normal'))
                    self.set_status("READY", bg=self.status_ready_bg, blink=False)
                    try:
                        self.win.after(0, lambda: self.set_ui_state('ready'))
                    except Exception:
                        try:
                            self.set_ui_state('ready')
                        except Exception:
                            pass
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

        # Indicate stopped in UI (red), then after a short pause return to INITIAL
        self.set_status("STOPPED", bg='red', blink=False)
        sleep(1)
        SystemFuncClass.stop_flag = False
        # Only set back to initial READY/INIT if EMG is not active
        if not self._emg_active:
            self.set_status("READY", bg=self.status_ready_bg, blink=False)
            try:
                self.win.after(0, lambda: self.set_ui_state('init'))
            except Exception:
                try:
                    self.set_ui_state('init')
                except Exception:
                    pass

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
                pass
            self.kb_proc = None
        SystemFuncClass().AllStop()
        self.win.destroy()

    def gui_start(self):
        self.win.protocol("WM_DELETE_WINDOW", self.gui_exit)
        self.win.mainloop()

    # --------------------- PARAM VALIDATION & SAVE ---------------------
    def validate_and_save_params(self):
        row_s = self.row_entry.get().strip()
        x_s = self.xspeed_entry.get().strip()
        y_s = self.yspeed_entry.get().strip()

        try:
            row_step = int(row_s)
            if row_step <= 0:
                raise ValueError
        except Exception:
            messagebox.showerror("Invalid Parameter", "Row Step must be a positive integer. Please correct.")
            return None

        try:
            x_speed = int(x_s)
            if x_speed <= 0:
                raise ValueError
        except Exception:
            messagebox.showerror("Invalid Parameter", "X Speed must be a positive integer. Please correct.")
            return None

        try:
            y_speed = int(y_s)
            if y_speed <= 0:
                raise ValueError
        except Exception:
            messagebox.showerror("Invalid Parameter", "Y Speed must be a positive integer. Please correct.")
            return None

        cfg = {
            "row_step": row_step,
            "x_speed": x_speed,
            "y_speed": y_speed
        }
        try:
            save_config(cfg)
            self.saved_config = cfg
            print("Saved scan configuration to", CONFIG_FILE)
        except Exception as e:
            print("Failed to save configuration:", e)
            messagebox.showwarning("Save Failed", "Failed to save configuration file. Scan will continue but settings won't be persisted.")

        return (row_step, x_speed, y_speed)

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
        """Safe getter for jog use: fall back to saved_config or default if entry invalid."""
        try:
            return max(1, int(self.xspeed_entry.get().strip()))
        except Exception:
            try:
                return int(self.saved_config.get("x_speed", 500))
            except Exception:
                return 500

    def _get_y_speed_safe(self):
        """Safe getter for jog use: fall back to saved_config or default if entry invalid."""
        try:
            return max(1, int(self.yspeed_entry.get().strip()))
        except Exception:
            try:
                return int(self.saved_config.get("y_speed", 500))
            except Exception:
                return 500

    # --------------------- Pulse counter utilities ---------------------
    def reset_pulse_counters(self):
        """Reset both pulse counters and update UI (called after Homing)."""
        self.jog_pulse_x = 0
        self.jog_pulse_y = 0
        self._jog_acc_x = 0.0
        self._jog_acc_y = 0.0
        try:
            self.jog_x_count_label.config(text="X Pulses: 0")
            self.jog_y_count_label.config(text="Y Pulses: 0")
        except Exception:
            pass

    # --------------------- Manual Jog Handlers (updated to count pulses) ---------------------
    def start_jog_x(self, direction):
        """Start continuous jog on X axis. direction is 'LEFT' or 'RIGHT'."""
        # don't start if global stop is active or EMG pressed
        if SystemFuncClass.stop_flag or self._emg_active:
            return
        if self._jog_active_x:
            return
        self._jog_active_x = True

        # choose direction tuple and sign for the counter
        dir_tuple = DIR_MAP['LEFT'] if direction == 'LEFT' else DIR_MAP['RIGHT']
        m1_dir, m2_dir = dir_tuple[0], dir_tuple[1]
        sign = -1 if direction == 'LEFT' else 1

        speed = self._get_x_speed_safe()  # Hz
        # Convert Hz to step delay (s per step). Prevent zero or absurdly small delay.
        stepdelay = max(0.00005, 1.0 / float(max(1, speed)))

        # chunk size in steps per motor per iteration (small so release stops quickly)
        chunk = 20

        def _worker():
            try:
                xym = self.data_scan.xymove
                # Show status
                try:
                    self.set_status(f"Jogging X ({direction})", bg='yellow', blink=False)
                except Exception:
                    pass

                last_ui = time.time()
                while self._jog_active_x and not SystemFuncClass.stop_flag:
                    # check limits/EMG before issuing chunk
                    if direction == 'LEFT' and xym.CheckXlimit_neg():
                        break
                    if direction == 'RIGHT' and xym.CheckXlimit_pos():
                        break
                    if xym.EMGSwitch():
                        SystemFuncClass().AllStop()
                        break

                    # perform small chunk of steps concurrently on both motors
                    def m1():
                        try:
                            MotorClass.motor_x1.motor_go(m1_dir, "Full", chunk, stepdelay, False, .0001)
                        except Exception:
                            pass

                    def m2():
                        try:
                            MotorClass.motor_x2.motor_go(m2_dir, "Full", chunk, stepdelay, False, .0001)
                        except Exception:
                            pass

                    t1 = threading.Thread(target=m1)
                    t2 = threading.Thread(target=m2)
                    t1.start(); t2.start()
                    t1.join(); t2.join()

                    # increment or decrement pulse counter by chunk depending on direction
                    self.jog_pulse_x += sign * chunk

                    # update UI periodically (every 0.15-0.3s)
                    now = time.time()
                    if now - last_ui >= 0.2:
                        last_ui = now
                        try:
                            v = self.jog_pulse_x
                            self.win.after(0, lambda vv=v: self.jog_x_count_label.config(text=f"X Pulses: {vv}"))
                        except Exception:
                            pass

            except Exception as e:
                print("Jog X error:", e)
            finally:
                # ensure motor stopped and finalize UI/counter
                try:
                    self.data_scan.xymove.Xstop()
                except Exception:
                    pass
                self._jog_active_x = False
                try:
                    v = self.jog_pulse_x
                    self.win.after(0, lambda vv=v: self.jog_x_count_label.config(text=f"X Pulses: {vv}"))
                except Exception:
                    pass
                if not self._emg_active and self._status_text not in ("Scanning...", "Homing..."):
                    self.set_status("READY", bg=self.status_ready_bg, blink=False)

        self._jog_thread_x = threading.Thread(target=_worker, daemon=True)
        self._jog_thread_x.start()

    def stop_jog_x(self):
        """Stop continuous X jog (called on button release)."""
        self._jog_active_x = False
        try:
            if getattr(self, 'data_scan', None) and getattr(self.data_scan, 'xymove', None):
                self.data_scan.xymove.Xstop()
        except Exception:
            pass
        # update UI counter immediately
        try:
            v = self.jog_pulse_x
            self.jog_x_count_label.config(text=f"X Pulses: {v}")
        except Exception:
            pass

    def start_jog_y(self, direction):
        """Start continuous jog on Y axis. direction is 'UP' or 'DOWN'."""
        # don't start if global stop is active or EMG pressed
        if SystemFuncClass.stop_flag or self._emg_active:
            return
        if self._jog_active_y:
            return
        self._jog_active_y = True
    
        # choose direction tuple and sign for the counter
        dir_tuple = DIR_MAP['UP'] if direction == 'UP' else DIR_MAP['DOWN']
        m1_dir, m2_dir = dir_tuple[0], dir_tuple[1]
        sign = 1 if direction == 'UP' else -1
    
        # IMPORTANT: match the Y movement parameters used by YfrontCorrect/YbackCorrect
        # (these functions in your script use a per-step delay of 0.00008 and chunking
        # of 200). Use the same values here so a manual jog produces the same physical
        # motion per counted pulse as the scan Y movements.
        stepdelay = 0.00008
        chunk = 200
    
        def _worker():
            try:
                xym = self.data_scan.xymove
                # Show status
                try:
                    self.set_status(f"Jogging Y ({direction})", bg='yellow', blink=False)
                except Exception:
                    pass
    
                last_ui = time.time()
                while self._jog_active_y and not SystemFuncClass.stop_flag:
                    # check limits/EMG before issuing chunk
                    if direction == 'UP' and xym.CheckYlimit_pos():
                        break
                    if direction == 'DOWN' and xym.CheckYlimit_neg():
                        break
                    if xym.EMGSwitch():
                        SystemFuncClass().AllStop()
                        break
    
                    # perform chunked steps with same chunk & stepdelay as scan Y movement
                    def m1():
                        try:
                            MotorClass.motor_x1.motor_go(m1_dir, "Full", chunk, stepdelay, False, .0001)
                        except Exception:
                            pass
    
                    def m2():
                        try:
                            MotorClass.motor_x2.motor_go(m2_dir, "Full", chunk, stepdelay, False, .0001)
                        except Exception:
                            pass
    
                    t1 = threading.Thread(target=m1)
                    t2 = threading.Thread(target=m2)
                    t1.start(); t2.start()
                    t1.join(); t2.join()
    
                    # increment or decrement pulse counter by the exact number of steps issued
                    self.jog_pulse_y += sign * chunk
    
                    # update UI periodically (every ~0.2s)
                    now = time.time()
                    if now - last_ui >= 0.2:
                        last_ui = now
                        try:
                            v = self.jog_pulse_y
                            self.win.after(0, lambda vv=v: self.jog_y_count_label.config(text=f"Y Pulses: {vv}"))
                        except Exception:
                            pass
    
            except Exception as e:
                print("Jog Y error:", e)
            finally:
                try:
                    self.data_scan.xymove.Ystop()
                except Exception:
                    pass
                self._jog_active_y = False
                try:
                    v = self.jog_pulse_y
                    self.win.after(0, lambda vv=v: self.jog_y_count_label.config(text=f"Y Pulses: {vv}"))
                except Exception:
                    pass
                if not self._emg_active and self._status_text not in ("Scanning...", "Homing..."):
                    self.set_status("READY", bg=self.status_ready_bg, blink=False)
    
        self._jog_thread_y = threading.Thread(target=_worker, daemon=True)
        self._jog_thread_y.start()

    def stop_jog_y(self):
        """Stop continuous Y jog (called on button release)."""
        self._jog_active_y = False
        try:
            if getattr(self, 'data_scan', None) and getattr(self.data_scan, 'xymove', None):
                self.data_scan.xymove.Ystop()
        except Exception:
            pass
        # update UI counter immediately
        try:
            v = self.jog_pulse_y
            self.jog_y_count_label.config(text=f"Y Pulses: {v}")
        except Exception:
            pass

    # --------------------- Limit Status Updater ---------------------
    def update_limit_status(self):
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
            lbl.config(text=f"{name} : {int(bool(val))}")
            if val:
                lbl.config(bg='green', fg='black')
            else:
                lbl.config(bg='darkred', fg='white')

        set_label(self.l_xpos, "X+", xpos)
        set_label(self.l_xneg, "X-", xneg)
        set_label(self.l_ypos, "Y+", ypos)
        set_label(self.l_yneg, "Y-", yneg)
        # EMG label custom: show 1/0
        self.l_emg.config(text=f"EMG : {int(bool(emg))}")
        if emg:
            self.l_emg.config(bg='green', fg='black')
        else:
            self.l_emg.config(bg='darkred', fg='white')

        # EMG handling: if EMG pressed, show EMG Stopped in red and trigger AllStop once
        if emg:
            if not self._emg_active:
                # first detection of EMG -> take action
                self._emg_active = True
                try:
                    SystemFuncClass().AllStop()
                except Exception:
                    pass
                # Disable all UI while EMG active
                try:
                    self.win.after(0, lambda: self.set_ui_state('emg'))
                except Exception:
                    try:
                        self.set_ui_state('emg')
                    except Exception:
                        pass
            # Update status label to EMG Stopped (override any blinking)
            self.set_status("EMG Stopped", bg='red', blink=False)
        else:
            # If EMG was previously active and is now released, restore initial UI
            if self._emg_active:
                # clear EMG active flag (so a future press will be handled)
                self._emg_active = False
                # Return UI to initial state (only HOME + STOP enabled)
                try:
                    self.win.after(0, lambda: self.set_ui_state('init'))
                    self.win.after(0, lambda: self.set_status("READY", bg=self.status_ready_bg, blink=False))
                except Exception:
                    try:
                        self.set_ui_state('init')
                        self.set_status("READY", bg=self.status_ready_bg, blink=False)
                    except Exception:
                        pass
            else:
                # For non-transition case (EMG not active), ensure scanning/homing status keeps blinking (or READY stays green)
                cur_text = self._status_text
                # If currently scanning or homing, ensure blinking is active.
                if cur_text in ("Scanning...", "Homing..."):
                    # If not already blinking, start it
                    if self._blink_job is None:
                        self.set_status(cur_text, blink=True, blink_color='green')
                else:
                    # For other states, ensure background matches the state (READY green)
                    if cur_text == "READY":
                        # ensure steady green
                        self.set_status("READY", bg=self.status_ready_bg, blink=False)
                    # otherwise leave as-is (e.g., STOPPED or Homed)

        try:
            self.limit_after_id = self.win.after(200, self.update_limit_status)
        except Exception:
            self.limit_after_id = None

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



