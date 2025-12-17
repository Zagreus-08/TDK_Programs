# -----------------------------------------------------------
# FINAL SCRIPT: NO Z, NO DAQ, NO DOORS, NO SERIAL
# XY HOMING + SIMPLE SNAKE SCAN WITH GUI CONTROL
# Added: Adjustable row_step, X speed, Y speed; Limit switch status on main screen
# UPDATED: Homing sequence - LIMIT_RIGHT first, then LIMIT_DOWN (with backoff)
# -----------------------------------------------------------

from time import sleep
import pigpio
import threading
import tkinter as tk
import tkinter.font as TkFont
from RpiMotorLib import RpiMotorLib

pi = pigpio.pi()

# -----------------------------------------------------------
# Port Mapping
# -----------------------------------------------------------
class PortDefineClass:
    DIR1 = 24
    STEP1 = 25

    DIR2 = 18
    STEP2 = 23

    X_pos_limit = 14     # X+
    Y_pos_limit = 17     # Y+
    X_neg_limit = 15    # X-
    Y_neg_limit = 19    # Y-

    SWITCH = 5         # Emergency switch


# -----------------------------------------------------------
# Global Status
# -----------------------------------------------------------
class StatusDataClass:
    x_offset = 0
    y_offset = 0
    fn = "result"


# -----------------------------------------------------------
# System Functions
# -----------------------------------------------------------
class SystemFuncClass:
    stop_flag = False

    def GPIO_Init(self):
        pins = (
            PortDefineClass.X_pos_limit,
            PortDefineClass.Y_pos_limit,
            PortDefineClass.X_neg_limit,
            PortDefineClass.Y_neg_limit,
            PortDefineClass.SWITCH
        )
        for p in pins:
            pi.set_mode(p, pigpio.INPUT)
            pi.set_pull_up_down(p, pigpio.PUD_UP)  # pull-up: not pressed = 1, pressed = 0

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


# -----------------------------------------------------------
# Motor Class Wrappers
# -----------------------------------------------------------
class MotorClass:
    motor_x1 = RpiMotorLib.A4988Nema(
        PortDefineClass.DIR1, PortDefineClass.STEP1,
        (-1, -1, -1), "DRV8825"
    )
    motor_x2 = RpiMotorLib.A4988Nema(
        PortDefineClass.DIR2, PortDefineClass.STEP2,
        (-1, -1, -1), "DRV8825"
    )


# -----------------------------------------------------------
# XY Movement Engine
# -----------------------------------------------------------
class XYMoveClass(MotorClass, PortDefineClass, SystemFuncClass):

    # Emergency switch
    def EMGSwitch(self):
        return pi.read(PortDefineClass.SWITCH)

    # ---------------------- X Axis Step Movement ----------------------
    # Maps to Wall_scanning_V2.py motor_go() functions
    def XrightCorrect(self, step):
        """Move X+ (RIGHT) - step-based - motor_go(True, True)"""
        if SystemFuncClass.stop_flag: return
        chunk = 200
        while step > 0:
            if SystemFuncClass.stop_flag: return
            s = min(chunk, step)

            def m1(): MotorClass.motor_x1.motor_go(True, "Full", s, .0003, False, .0001)
            def m2(): MotorClass.motor_x2.motor_go(True, "Full", s, .0003, False, .0001)

            t1 = threading.Thread(target=m1); t2 = threading.Thread(target=m2)
            t1.start(); t2.start(); t1.join(); t2.join()

            step -= s

    def XleftCorrect(self, step):
        """Move X- (LEFT) - step-based - motor_go(False, False)"""
        if SystemFuncClass.stop_flag: return
        chunk = 200
        while step > 0:
            if SystemFuncClass.stop_flag: return
            s = min(chunk, step)

            def m1(): MotorClass.motor_x1.motor_go(False, "Full", s, .0003, False, .0001)
            def m2(): MotorClass.motor_x2.motor_go(False, "Full", s, .0003, False, .0001)

            t1 = threading.Thread(target=m1); t2 = threading.Thread(target=m2)
            t1.start(); t2.start(); t1.join(); t2.join()

            step -= s

    # ---------------------- X Continuous PWM Motion (from Wall_scanning_V2) ----------------------
    # Wall_scanning_V2: set_motor_direction(dir1, dir2) + start_motors()
    def Xdir(self, d):  # d=1 -> X+ (RIGHT), d=0 -> X- (LEFT)
        """Set direction for X axis: 1=RIGHT(X+), 0=LEFT(X-)"""
        pi.write(PortDefineClass.DIR1, d)
        pi.write(PortDefineClass.DIR2, d)

    def XmotorSpeed(self, sp):
        """Set PWM frequency (speed) for X axis"""
        pi.set_PWM_frequency(PortDefineClass.STEP1, sp)
        pi.set_PWM_frequency(PortDefineClass.STEP2, sp)

    def XmotorSet(self, d, sp):
        """Set both direction and speed for X axis"""
        self.Xdir(d)
        self.XmotorSpeed(sp)

    def Xstart(self):
        """Start X motors (PWM 50% dutycycle) - maps to start_motors()"""
        pi.set_PWM_dutycycle(PortDefineClass.STEP1, 50)
        pi.set_PWM_dutycycle(PortDefineClass.STEP2, 50)

    def Xstop(self):
        """Stop X motors - maps to stop_motors()"""
        pi.set_PWM_dutycycle(PortDefineClass.STEP1, 0)
        pi.set_PWM_dutycycle(PortDefineClass.STEP2, 0)

    # ---------------------- X Limits ----------------------
    # Wall_scanning_V2: check_limit_switch()
    def CheckXlimit_pos(self): 
        """Check X+ limit (GPIO 14)"""
        return pi.read(PortDefineClass.X_pos_limit) == 0
    
    def CheckXlimit_neg(self): 
        """Check X- limit (GPIO 15) - LIMIT_RIGHT"""
        return pi.read(PortDefineClass.X_neg_limit) == 0

    # ---------------------- Y Axis Step Movement ----------------------
    # Maps to Wall_scanning_V2.py motor_go() functions
    def YfrontCorrect(self, step):
        """Move Y- (DOWN/FRONT) - step-based - motor_go(True, False)"""
        chunk = 200
        while step > 0:
            if SystemFuncClass.stop_flag: return
            s = min(chunk, step)

            def m1(): MotorClass.motor_x1.motor_go(True, "Full", s, .00008, False, .0001)
            def m2(): MotorClass.motor_x2.motor_go(False, "Full", s, .00008, False, .0001)

            t1 = threading.Thread(target=m1); t2 = threading.Thread(target=m2)
            t1.start(); t2.start(); t1.join(); t2.join()

            step -= s

    def YbackCorrect(self, step):
        """Move Y+ (UP/BACK) - step-based - motor_go(False, True)"""
        chunk = 200
        while step > 0:
            if SystemFuncClass.stop_flag: return
            s = min(chunk, step)

            def m1(): MotorClass.motor_x1.motor_go(False, "Full", s, .00008, False, .0001)
            def m2(): MotorClass.motor_x2.motor_go(True, "Full", s, .00008, False, .0001)

            t1 = threading.Thread(target=m1); t2 = threading.Thread(target=m2)
            t1.start(); t2.start(); t1.join(); t2.join()

            step -= s

    def YmoveCorrect(self, step):
        if step < 0:
            self.YfrontCorrect(abs(step))   # negative -> Y-
        else:
            self.YbackCorrect(step)         # positive -> Y+

    # ---------------------- Y Continuous PWM Movement (from Wall_scanning_V2) ----------------------
    # Wall_scanning_V2: set_motor_direction(dir1, dir2) + start_motors()
    def Ydir(self, d):
        """Set direction for Y axis: 1=UP(Y+), 0=DOWN(Y-)"""
        if d == 1:  # Y+ (UP/BACK)
            pi.write(PortDefineClass.DIR1, 0)
            pi.write(PortDefineClass.DIR2, 1)
        else:       # Y- (DOWN/FRONT)
            pi.write(PortDefineClass.DIR1, 1)
            pi.write(PortDefineClass.DIR2, 0)

    def YmotorSpeed(self, sp):
        """Set PWM frequency (speed) for Y axis"""
        pi.set_PWM_frequency(PortDefineClass.STEP1, sp)
        pi.set_PWM_frequency(PortDefineClass.STEP2, sp)

    def YmotorSet(self, d, sp):
        """Set both direction and speed for Y axis"""
        self.Ydir(d)
        self.YmotorSpeed(sp)

    def Ystart(self):
        """Start Y motors (PWM 50% dutycycle) - maps to start_motors()"""
        pi.set_PWM_dutycycle(PortDefineClass.STEP1, 50)
        pi.set_PWM_dutycycle(PortDefineClass.STEP2, 50)

    def Ystop(self):
        """Stop Y motors - maps to stop_motors()"""
        pi.set_PWM_dutycycle(PortDefineClass.STEP1, 0)
        pi.set_PWM_dutycycle(PortDefineClass.STEP2, 0)

    # ---------------------- Y Limits ----------------------
    # Wall_scanning_V2: check_limit_switch()
    def CheckYlimit_pos(self): 
        """Check Y+ limit (GPIO 17)"""
        return pi.read(PortDefineClass.Y_pos_limit) == 0
    
    def CheckYlimit_neg(self): 
        """Check Y- limit (GPIO 19) - LIMIT_DOWN"""
        return pi.read(PortDefineClass.Y_neg_limit) == 0


# -----------------------------------------------------------
# HOMING CLASS (LIMIT_RIGHT first, then LIMIT_DOWN with backoff)
# -----------------------------------------------------------
class GoHomePosClass:
    sysfunc = SystemFuncClass()
    xymove  = XYMoveClass()

    def Home(self):
        """Simple homing: Move to LIMIT_RIGHT, step back, then move to LIMIT_DOWN, step back"""
        self.sysfunc.GPIO_Init()
        print("=== START HOMING SEQUENCE ===")

        # PHASE 1: Move to LIMIT_RIGHT
        print(" Phase 1: Moving to LIMIT_RIGHT...")
        self.xymove.XmotorSet(0, 1200)  # Move X- toward LIMIT_RIGHT (DIR1=0, DIR2=0)
        self.xymove.Xstart()
        
        # Wait until LIMIT_RIGHT is triggered
        while not self.xymove.CheckXlimit_neg():
            if SystemFuncClass.stop_flag: 
                self.xymove.Xstop()
                return
            sleep(0.001)
        
        # IMMEDIATELY stop the motor - Force PWM off
        self.xymove.Xstop()
        pi.set_PWM_dutycycle(PortDefineClass.STEP1, 0)
        pi.set_PWM_dutycycle(PortDefineClass.STEP2, 0)
        sleep(0.5)  # Ensure motor stops completely
        print(" LIMIT_RIGHT reached. Motor stopped. Stepping back...")
        
        # Step back to release the limit (move X+)
        self.xymove.XrightCorrect(150)
        sleep(3.0)  # Wait LONGER after stepping back to ensure limit releases
        print(" Stepped back from LIMIT_RIGHT")

        # Reset direction pins after Phase 1 - give time to settle
        pi.write(PortDefineClass.DIR1, 0)
        pi.write(PortDefineClass.DIR2, 0)
        sleep(3.0)  # EXTRA TIME before direction change

        # WAIT BETWEEN PHASES - let motors fully stop and settle
        sleep(3.0)

        # PHASE 2: Move to LIMIT_DOWN
        print(" Phase 2: Moving to LIMIT_DOWN...")
        self.xymove.YmotorSet(0, 1200)  # Move Y- toward LIMIT_DOWN (DIR1=1, DIR2=0)
        self.xymove.Ystart()
        
        # Wait until LIMIT_DOWN is triggered
        while not self.xymove.CheckYlimit_neg():
            if SystemFuncClass.stop_flag: 
                self.xymove.Ystop()
                return
            sleep(0.001)
        
        # IMMEDIATELY stop the motor - Force PWM off
        self.xymove.Ystop()
        pi.set_PWM_dutycycle(PortDefineClass.STEP1, 0)
        pi.set_PWM_dutycycle(PortDefineClass.STEP2, 0)
        sleep(0.5)  # Ensure motor stops completely
        print(" LIMIT_DOWN reached. Motor stopped. Stepping back...")
        
        # Step back to release the limit (move Y+)
        self.xymove.YbackCorrect(150)
        sleep(3.0)  # Wait LONGER after stepping back to ensure limit releases
        print(" Stepped back from LIMIT_DOWN")

        # Reset direction pins after Phase 2 - give time to settle
        pi.write(PortDefineClass.DIR1, 0)
        pi.write(PortDefineClass.DIR2, 0)
        sleep(3.0)  # Final settling time

        print("=== HOME POSITION SET ===")


# -----------------------------------------------------------
# SIMPLE SCAN SYSTEM
# -----------------------------------------------------------
class SimpleScanClass:
    def __init__(self, xymove=None, row_step=None, x_speed=None, y_speed=None):
        self.xy = xymove if xymove else XYMoveClass()
        self.row_step = row_step if row_step is not None else 50
        self.x_speed = x_speed if x_speed is not None else 1500
        self.y_speed = y_speed if y_speed is not None else 1500

    def go_to_xy_plus_corners(self):
        print(" Moving to X+ & Y+")
        self.xy.XmotorSet(1, self.x_speed)
        self.xy.YmotorSet(1, self.y_speed)
        self.xy.Xstart(); self.xy.Ystart()

        while True:
            if SystemFuncClass.stop_flag:
                self.xy.Xstop(); self.xy.Ystop()
                return False
            if self.xy.CheckXlimit_pos() and self.xy.CheckYlimit_pos():
                break
            sleep(0.001)

        self.xy.Xstop(); self.xy.Ystop()
        print(" At X+ & Y+")
        return True

    def scan_left_until_xminus(self):
        print(" Scanning LEFT to X-")
        self.xy.XmotorSet(0, self.x_speed)
        self.xy.Xstart()
        while not self.xy.CheckXlimit_neg():
            if SystemFuncClass.stop_flag:
                self.xy.Xstop()
                return False
            sleep(0.001)
        self.xy.Xstop()
        return True

    def scan_right_until_xplus(self):
        print(" Scanning RIGHT to X+")
        self.xy.XmotorSet(1, self.x_speed)
        self.xy.Xstart()
        while not self.xy.CheckXlimit_pos():
            if SystemFuncClass.stop_flag:
                self.xy.Xstop()
                return False
            sleep(0.001)
        self.xy.Xstop()
        return True

    def move_y_down(self):
        print(f" Moving Y down {self.row_step}")
        self.xy.YmoveCorrect(-abs(self.row_step))
        return True

    def simple_scan(self):
        print("=== START SIMPLE SCAN ===")

        if not self.go_to_xy_plus_corners():
            return

        direction = "LEFT"

        while True:
            if SystemFuncClass.stop_flag:
                return

            if direction == "LEFT":
                if not self.scan_left_until_xminus(): return
                direction = "RIGHT"
            else:
                if not self.scan_right_until_xplus(): return
                direction = "LEFT"

            self.move_y_down()

            if self.xy.CheckYlimit_neg():
                print(" Y- Limit Reached. Scan Complete.")
                break

        print("=== SIMPLE SCAN FINISHED ===")


# -----------------------------------------------------------
# ScanRoutine Controller (NO DAQ, NO CSV)
# -----------------------------------------------------------
class DataScanClass:
    def __init__(self, gui=None):
        self.gui = gui
        self.xymove = XYMoveClass()
        self.home = GoHomePosClass()

    def ScanPos(self):
        print(" Moving to scan offsets...")
        self.xymove.XmoveCorrect(StatusDataClass.x_offset)
        self.xymove.YmoveCorrect(StatusDataClass.y_offset)

    def UnloadPos(self):
        print(" Returning to unload position...")
        self.xymove.YmoveCorrect(-StatusDataClass.y_offset)
        self.xymove.XmoveCorrect(-StatusDataClass.x_offset)

    def ScanRoutine(self):
        print("=== START SCAN ROUTINE ===")
        self.ScanPos()
        sleep(1.0)

        # read values from GUI (if provided)
        row_step = 50
        x_speed = 1500
        y_speed = 1500
        if self.gui:
            try:
                row_step = self.gui.get_row_step()
            except Exception:
                row_step = 50
            try:
                x_speed = self.gui.get_x_speed()
            except Exception:
                x_speed = 1500
            try:
                y_speed = self.gui.get_y_speed()
            except Exception:
                y_speed = 1500

        simple = SimpleScanClass(self.xymove, row_step=row_step, x_speed=x_speed, y_speed=y_speed)
        simple.simple_scan()

        if not SystemFuncClass.stop_flag:
            self.UnloadPos()

        print("=== SCAN ROUTINE COMPLETE ===")


# -----------------------------------------------------------
# GUI
# -----------------------------------------------------------
class GUIClass(PortDefineClass):
    
    system_func = SystemFuncClass()
    
    def __init__(self):
        self.data_scan = DataScanClass(self)

        self.win = tk.Tk()
        self.win.title("XY Scanning System")
        self.win.geometry('800x480')
        self.win.configure(bg='#0046ad')
        self.win.config(cursor="none")

        self.buttonFont = TkFont.Font(family='Helvetica', size=20, weight='bold')
        self.buttonFont2 = TkFont.Font(family='Helvetica', size=25, weight='bold')
        self.labelFont = TkFont.Font(family='Helvetica', size=15, weight='bold')
        self.logoFont = TkFont.Font(family='BiomeW04-Bold', size=35, weight='bold')

        self.logo = tk.Label(self.win, text='Nivio-S', font=self.logoFont, height=0, width=6, bg='#0046ad', fg='white')
        self.logo.place(x=0, y=0)
        
        self.sublogo = tk.Label(self.win, text='Wall Scanning System', font=self.labelFont, height=0, width=22, bg='#0046ad', fg='white')
        self.sublogo.place(x=100, y=55)

        # HOME
        self.HomeButton = tk.Button(self.win, text="HOME",
                                    font=self.buttonFont2, bg='lightgreen',
                                    command=self.started_homing,
                                    width=6, height=5)
        self.HomeButton.place(x=10, y=90)

        # SCAN
        self.ScanButton = tk.Button(self.win, text="SCAN",
                                    font=self.buttonFont2, bg='lightgreen',
                                    command=self.scan_started,
                                    width=6, height=5)
        self.ScanButton.place(x=170, y=90)

        # STOP
        self.StopButton = tk.Button(self.win, text="STOP",
                                    font=self.buttonFont2, bg='red',
                                    command=self.stop_all_motion,
                                    width=6, height=5)
        self.StopButton.place(x=330, y=90)

        # EXIT
        self.ExitButton = tk.Button(self.win, text='Exit', font=self.buttonFont, command=self.gui_exit, height=1, width=6)
        self.ExitButton.place(x=390, y=5)

        # STATUS
        self.status_title = tk.Label(self.win, text='Axis Status:', font=self.labelFont, height=1, width=10, bg='#0046ad', fg='white')
        self.status_title.place(x=10, y=450)
        
        self.status_label = tk.Label(self.win, text="READY",
                                     font=self.labelFont,
                                     bg='#0046ad', fg='white', width=10)
        self.status_label.place(x=140, y=450)

        # Adjustable parameters area
        # Row Step
        self.row_label = tk.Label(self.win, text="Row Step (steps):", font=self.labelFont, bg='#0046ad', fg='white')
        self.row_label.place(x=10, y=300)
        self.row_entry = tk.Entry(self.win, font=TkFont.Font(size=14), width=10)
        self.row_entry.place(x=200, y=300)
        self.row_entry.insert(0, "50")

        # X Speed
        self.xspeed_label = tk.Label(self.win, text="X Speed (Hz):", font=self.labelFont, bg='#0046ad', fg='white')
        self.xspeed_label.place(x=10, y=340)
        self.xspeed_entry = tk.Entry(self.win, font=TkFont.Font(size=14), width=10)
        self.xspeed_entry.place(x=200, y=340)
        self.xspeed_entry.insert(0, "1500")

        # Y Speed
        self.yspeed_label = tk.Label(self.win, text="Y Speed (Hz):", font=self.labelFont, bg='#0046ad', fg='white')
        self.yspeed_label.place(x=10, y=380)
        self.yspeed_entry = tk.Entry(self.win, font=TkFont.Font(size=14), width=10)
        self.yspeed_entry.place(x=200, y=380)
        self.yspeed_entry.insert(0, "1500")

        # small help text
        self.help_label = tk.Label(self.win, text="Enter integer values. Defaults used on invalid input.",
                                   font=TkFont.Font(size=10), bg='#0046ad', fg='white')
        self.help_label.place(x=10, y=420)

        # Limit status labels on main screen
        self.l_xpos = tk.Label(self.win, text="X+ : ?", font=TkFont.Font(size=14), width=12, bg='darkred', fg='white')
        self.l_xpos.place(x=560, y=90)
        self.l_xneg = tk.Label(self.win, text="X- : ?", font=TkFont.Font(size=14), width=12, bg='darkred', fg='white')
        self.l_xneg.place(x=560, y=150)
        self.l_ypos = tk.Label(self.win, text="Y+ : ?", font=TkFont.Font(size=14), width=12, bg='darkred', fg='white')
        self.l_ypos.place(x=560, y=210)
        self.l_yneg = tk.Label(self.win, text="Y- : ?", font=TkFont.Font(size=14), width=12, bg='darkred', fg='white')
        self.l_yneg.place(x=560, y=270)
        self.l_emg = tk.Label(self.win, text="EMG: ?", font=TkFont.Font(size=14), width=12, bg='darkred', fg='white')
        self.l_emg.place(x=560, y=330)

        # after-id for periodic update
        self.limit_after_id = None

        # start periodic updates of limit status
        self.update_limit_status()

    # --------------------- HOMING ---------------------
    def started_homing(self):
        self.HomeButton.config(state='disabled')
        self.status_label["text"] = "Homing..."
        threading.Thread(target=self.goto_home, daemon=True).start()

    def goto_home(self):
        try:
            GoHomePosClass().Home()
            if not SystemFuncClass.stop_flag:
                self.status_label["text"] = "Homed"
        except Exception as e:
            print("Home Error:", e)
        finally:
            self.HomeButton.config(state='normal')

    # --------------------- SCAN ---------------------
    def scan_started(self):
        threading.Thread(target=self.scan_start, daemon=True).start()

    def scan_start(self):
        self.ScanButton.config(state='disabled')
        self.status_label["text"] = "Scanning..."

        try:
            self.data_scan.ScanRoutine()
        except Exception as e:
            print("Scan Error:", e)
        finally:
            self.ScanButton.config(state='normal')
            self.status_label["text"] = "READY"

    # --------------------- STOP ---------------------
    def stop_all_motion(self):
        SystemFuncClass.stop_flag = True
        SystemFuncClass().AllStop()
        self.status_label["text"] = "STOPPED"
        sleep(1)
        SystemFuncClass.stop_flag = False
        self.status_label["text"] = "READY"

    # --------------------- EXIT ---------------------
    def gui_exit(self):
        # cancel periodic updates
        try:
            if self.limit_after_id:
                self.win.after_cancel(self.limit_after_id)
        except Exception:
            pass
        SystemFuncClass().AllStop()
        self.win.destroy()

    def gui_start(self):
        self.win.protocol("WM_DELETE_WINDOW", self.gui_exit)
        self.win.mainloop()

    # --------------------- Getters for adjustable params ---------------------
    def get_row_step(self):
        v = self.row_entry.get().strip()
        try:
            val = int(v)
            if val <= 0:
                raise ValueError
            return val
        except Exception:
            print(f"Invalid row_step '{v}', using default 50")
            return 50

    def get_x_speed(self):
        v = self.xspeed_entry.get().strip()
        try:
            val = int(v)
            if val <= 0:
                raise ValueError
            return val
        except Exception:
            print(f"Invalid x_speed '{v}', using default 1500")
            return 1500

    def get_y_speed(self):
        v = self.yspeed_entry.get().strip()
        try:
            val = int(v)
            if val <= 0:
                raise ValueError
            return val
        except Exception:
            print(f"Invalid y_speed '{v}', using default 1500")
            return 1500

    # --------------------- Limit Status Updater ---------------------
    def update_limit_status(self):
        try:
            xp = "ON" if self.data_scan.xymove.CheckXlimit_pos() else "OFF"
            xn = "ON" if self.data_scan.xymove.CheckXlimit_neg() else "OFF"
            yp = "ON" if self.data_scan.xymove.CheckYlimit_pos() else "OFF"
            yn = "ON" if self.data_scan.xymove.CheckYlimit_neg() else "OFF"
            emg = "ON" if self.data_scan.xymove.EMGSwitch() else "OFF"

            self.l_xpos.config(text=f"X+ : {xp}", bg='green' if xp == "ON" else 'darkred')
            self.l_xneg.config(text=f"X- : {xn}", bg='green' if xn == "ON" else 'darkred')
            self.l_ypos.config(text=f"Y+ : {yp}", bg='green' if yp == "ON" else 'darkred')
            self.l_yneg.config(text=f"Y- : {yn}", bg='green' if yn == "ON" else 'darkred')
            self.l_emg.config(text=f"EMG: {emg}", bg='green' if emg == "ON" else 'darkred')
        except Exception:
            pass

        self.limit_after_id = self.win.after(100, self.update_limit_status)


if __name__ == "__main__":
    try:
        gui = GUIClass()
        gui.gui_start()
    except Exception as e:
        print(f"Fatal Error: {e}")
    finally:
        try:
            SystemFuncClass().AllStop()
        except Exception:
            pass
        print("Program terminated.")
