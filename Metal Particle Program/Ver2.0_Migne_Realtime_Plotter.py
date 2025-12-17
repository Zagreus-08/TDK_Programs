from time import sleep
import sys
import pigpio
import threading
from RpiMotorLib import RpiMotorLib
import timeit
from daqhats import mcc128, OptionFlags, HatIDs, AnalogInputMode, AnalogInputRange, hat_list, HatError

# try to import helper; if not available, provide a simple implementation
try:
    from daqhats_utils import chan_list_to_mask
except Exception:
    def chan_list_to_mask(chan_list):
        """Convert a list of channel numbers to a channel mask (fallback)."""
        mask = 0
        for chan in chan_list:
            mask |= (1 << chan)
        return mask

import csv
from tkinter import *
import tkinter as tk
from tkinter import messagebox
import tkinter.font as TkFont
import os
import serial

pi = pigpio.pi()

def main():
    
    #GUI
    gui        = GUIClass()
    port       = PortDefineClass()
    system     = SystemFuncClass()
    scan_data  = StatusDataClass()
    motor_init = MotorClass()
    xy_move    = XYMoveClass()
    z_move     = ZMoveClass()
    serial     = SerialDataComClass()

    system.GPIO_Init()
    gui.init_offset_data()

    # --- Door Interlock Monitoring Thread ---
    threading.Thread(target=gui.monitor_doors, daemon=True).start()

    gui.gui_start()

class PortDefineClass:
    DIR1    = 24
    STEP1   = 25
    DIR2    = 18
    STEP2   = 23
    DIRZ  = 5
    STEPZ = 6

    Xlimit  = 15
    Ylimit  = 14
    Zlimit  = 17
    SWITCH  = 19
    ZHtCal  = 7
    
    LDoor = 21
    RDoor = 22

class StatusDataClass:
    x_point = 0
    y_point = 0
    v_data  = 0
    v_data1  = 0    
    v_data2  = 0    
    
    x_offset = 0
    y_offset = 0
    z_offset = 0
    xcal_offset = 0
    ycal_offset = 0
    zcal_offset = 0
    ScanHt = 0
    ZOffset = 0
    
    # Scan parameters - grid dimensions
    xdensity = 100  # Number of lines (X direction)
    ydensity = 100  # Points per line (Y direction)
    roughness = 20  # Scanning area size (mm) - default 20mm
    resolution = 10000  # Total data points (100x100=10,000, 150x150=22,500, or 200x200=40,000)

class SerialDataComClass:
    def __init__(self):
        try:
            self.ser = serial.Serial('/dev/ttyUSB0', 115200) #serial init
        except Exception as e:
            print("Serial init failed:", e)
            self.ser = None

    def TrSerialData(self, dat):
        print(str(dat))
        if self.ser:
            self.ser.write(str(dat).encode())
            self.ser.write(str("\n").encode())
        
    def TrStartData(self):
        print("START!!!!!!!!!!!!!!!!")
        if self.ser:
            self.ser.write(str("s\n").encode())
    
    def TrEndData(self):
        #dat= dat.replace('""', '')
        print("END!!!!!!!!!!!!!!!!")
        if self.ser:
            self.ser.write(str("e\n").encode())

    def TrScanData(self, c, fn):
        self.TrSerialData(f'{StatusDataClass.x_point},{StatusDataClass.y_point},{StatusDataClass.v_data:.9f},{fn}')
        data = StatusDataClass.x_point, StatusDataClass.y_point, StatusDataClass.v_data
        c.writerow(data)

    def TrScanData2(self, c, fn):
        self.TrSerialData(f'{StatusDataClass.x_point},{StatusDataClass.y_point},{StatusDataClass.v_data1:.9f},{fn}')
        data = StatusDataClass.x_point, StatusDataClass.y_point, StatusDataClass.v_data1, StatusDataClass.v_data2
        c.writerow(data)
        
    def SerialEnd(self):
        if self.ser:
            self.ser.close()
        
class SystemFuncClass:
    stop_flag = False  # Stop flag for stopping movement
    serial = SerialDataComClass()
    def GPIO_Init(self):
        pi.set_mode(PortDefineClass.Xlimit, pigpio.INPUT)
        pi.set_mode(PortDefineClass.Ylimit, pigpio.INPUT)
        pi.set_mode(PortDefineClass.Zlimit, pigpio.INPUT)
        pi.set_mode(PortDefineClass.SWITCH, pigpio.INPUT)
        pi.set_mode(PortDefineClass.ZHtCal, pigpio.INPUT)
        pi.set_mode(PortDefineClass.RDoor, pigpio.INPUT)     
        pi.set_mode(PortDefineClass.LDoor, pigpio.INPUT)
        pi.set_pull_up_down(PortDefineClass.Xlimit, pigpio.PUD_UP)
        pi.set_pull_up_down(PortDefineClass.Ylimit, pigpio.PUD_UP)
        pi.set_pull_up_down(PortDefineClass.Zlimit, pigpio.PUD_UP)
        pi.set_pull_up_down(PortDefineClass.SWITCH, pigpio.PUD_UP)
        pi.set_pull_up_down(PortDefineClass.ZHtCal, pigpio.PUD_UP)
        pi.set_pull_up_down(PortDefineClass.RDoor, pigpio.PUD_UP)  
        pi.set_pull_up_down(PortDefineClass.LDoor, pigpio.PUD_UP)  
            
        print("GPIO INIT OK")
    
    def AllStop(self):
        SystemFuncClass.stop_flag = True  # Set the flag to stop movement
        pi.write(PortDefineClass.DIRZ, 1)
        pi.set_PWM_dutycycle(PortDefineClass.STEPZ, 0)
    
        pi.write(PortDefineClass.DIR1, 0)
        pi.write(PortDefineClass.DIR2, 0)
        pi.set_PWM_dutycycle(PortDefineClass.STEP1, 0)
        pi.set_PWM_dutycycle(PortDefineClass.STEP2, 0)
        print("STOPPED ALL MOTION!")
        
    def callback(self, event):
        import subprocess
        try:
            subprocess.Popen(["onboard"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except:
            pass
        
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
        
    def exitProgram(self):
        #GPIO.cleanup()
        self.AllStop()
        self.serial.SerialEnd()

class MotorClass:
    motor1   = RpiMotorLib.A4988Nema(PortDefineClass.DIR1, PortDefineClass.STEP1, (-1,-1,-1), "DRV8825")
    motor2   = RpiMotorLib.A4988Nema(PortDefineClass.DIR2, PortDefineClass.STEP2, (-1,-1,-1), "DRV8825")
    motorZ = RpiMotorLib.A4988Nema(PortDefineClass.DIRZ, PortDefineClass.STEPZ, (-1,-1,-1), "DRV8825")


class XYMoveClass(MotorClass, PortDefineClass, SystemFuncClass):

    x_pos    = 0
    y_pos    = 0

    x_cont   = 0
    y_cont   = 0
    

    def EMGSwitch(self):
        return pi.read(PortDefineClass.SWITCH)

    def XrightCorrect(self, step):
        if SystemFuncClass.stop_flag:
            print("STOP detected in XrightCorrect - Exiting before start!")
            return
    
        chunk = 200
        remaining = step
    
        while remaining > 0:
            if SystemFuncClass.stop_flag:
                print("STOP detected during XrightCorrect - Exiting mid-move!")
                return
    
            this_chunk = min(chunk, remaining)
    
            def m1():
                MotorClass.motor1.motor_go(True, "Full", this_chunk, .0003, False, .0001)
            def m2():
                MotorClass.motor2.motor_go(True, "Full", this_chunk, .0003, False, .0001)
    
            t1 = threading.Thread(target=m1)
            t2 = threading.Thread(target=m2)
            t1.start(); t2.start()
            t1.join(); t2.join()
    
            remaining -= this_chunk
            
    def XleftCorrect(self, step):
        if SystemFuncClass.stop_flag:
            print("STOP detected in XleftCorrect - Exiting before start!")
            return
    
        chunk = 200
        remaining = step
    
        while remaining > 0:
            if SystemFuncClass.stop_flag:
                print("STOP detected during XleftCorrect - Exiting mid-move!")
                return
    
            this_chunk = min(chunk, remaining)
    
            def m1():
                MotorClass.motor1.motor_go(False, "Full", this_chunk, .0003, False, .0001)
            def m2():
                MotorClass.motor2.motor_go(False, "Full", this_chunk, .0003, False, .0001)
    
            t1 = threading.Thread(target=m1)
            t2 = threading.Thread(target=m2)
            t1.start(); t2.start()
            t1.join(); t2.join()
    
            remaining -= this_chunk
    
    def XmoveCorrect(self, step):
        if SystemFuncClass.stop_flag:
            print("STOP detected in XmoveCorrect - Exiting!")
            return
        xdiff = int(step)
        if xdiff < 0:
            if SystemFuncClass.stop_flag:
                print("STOP detected before XleftCorrect - Exiting!")
                return
            self.XleftCorrect(abs(xdiff))
        else:
            if SystemFuncClass.stop_flag:
                print("STOP detected before XrightCorrect - Exiting!")
                return
            self.XrightCorrect(xdiff)

    #X axis
    def InitXmotor(self, speed):
        pi.set_PWM_frequency(PortDefineClass.STEP1, speed)
        pi.set_PWM_frequency(PortDefineClass.STEP2, speed)
        
    def XmotorSpeed(self, speed):
        pi.set_PWM_frequency(PortDefineClass.STEP1, speed)
        pi.set_PWM_frequency(PortDefineClass.STEP2, speed)
        
    def CheckXlimit(self):
        return pi.read(PortDefineClass.Xlimit)
        
    #dir : 0 = right , 1 = left
    def Xdir(self, dir):
        pi.write(PortDefineClass.DIR1, dir)
        pi.write(PortDefineClass.DIR2, dir)
        
    def Xstart(self):
        pi.set_PWM_dutycycle(PortDefineClass.STEP1, 50)
        pi.set_PWM_dutycycle(PortDefineClass.STEP2, 50)
    
    def Xstop(self):
        pi.set_PWM_dutycycle(PortDefineClass.STEP1, 0)
        pi.set_PWM_dutycycle(PortDefineClass.STEP2, 0)
    
    def XmotorSet(self, dir, speed):
        self.Xdir(dir)
        self.XmotorSpeed(speed)
        
        
    def Xright(self, rtime, speed):
        if SystemFuncClass.stop_flag:
            self.Xstop()
            return
        
        self.XmotorSet(1, speed)
        self.Xstart()

        for _ in range(int(rtime * 100)):
            if SystemFuncClass.stop_flag:
                self.Xstop()
                return
            sleep(0.01)

        self.Xstop()
    
    
    def Xleft(self, ltime, speed):
        if SystemFuncClass.stop_flag:
            self.Xstop()
            return
        
        self.XmotorSet(0, speed)
        self.Xstart()

        for _ in range(int(ltime * 100)):
            if SystemFuncClass.stop_flag:
                self.Xstop()
                return
            sleep(0.01)

        self.Xstop()
    
        sleep(0.5)
    
    #dir : 0 = right , 1 = left
    def Ydir(self, dir):
        if dir == 1:
            pi.write(PortDefineClass.DIR1, 1)
            pi.write(PortDefineClass.DIR2, 0)
        elif dir == 0:
            pi.write(PortDefineClass.DIR1, 0)
            pi.write(PortDefineClass.DIR2, 1)
            
    def Ymovef(self):
        pi.set_PWM_dutycycle(PortDefineClass.STEP1, 50)
        pi.set_PWM_dutycycle(PortDefineClass.STEP2, 50)
    
    def Ystart(self):
        pi.set_PWM_dutycycle(PortDefineClass.STEP1, 50)
        pi.set_PWM_dutycycle(PortDefineClass.STEP2, 50)
    
    def Ystop(self):
        pi.set_PWM_dutycycle(PortDefineClass.STEP1, 0)
        pi.set_PWM_dutycycle(PortDefineClass.STEP2, 0)
    
    def CheckYlimit(self):
        return pi.read(PortDefineClass.Ylimit)
    
    def InitYmotor(self, speed):
        pi.set_PWM_frequency(PortDefineClass.STEP1, speed)
        pi.set_PWM_frequency(PortDefineClass.STEP2, speed)
    
    def YmotorSpeed(self, speed):
        pi.set_PWM_frequency(PortDefineClass.STEP1, speed)
        pi.set_PWM_frequency(PortDefineClass.STEP2, speed)
    
    def YmotorSet(self, dir, speed):
        self.Ydir(dir)
        self.YmotorSpeed(speed)
    
    def YbackCorrect(self, step):
        if SystemFuncClass.stop_flag:
            print("STOP detected in YbackCorrect - Exiting before start!")
            return
    
        chunk = 200
        remaining = step
    
        while remaining > 0:
            if SystemFuncClass.stop_flag:
                print("STOP detected during YbackCorrect - Exiting mid-move!")
                return
    
            this_chunk = min(chunk, remaining)
    
            def m1():
                MotorClass.motor1.motor_go(False, "Full", this_chunk, .00008, False, .0001)
            def m2():
                MotorClass.motor2.motor_go(True, "Full", this_chunk, .00008, False, .0001)
    
            t1 = threading.Thread(target=m1)
            t2 = threading.Thread(target=m2)
            t1.start(); t2.start()
            t1.join(); t2.join()
    
            remaining -= this_chunk
    
    def YfrontCorrect(self, step):
        if SystemFuncClass.stop_flag:
            print("STOP detected in YfrontCorrect - Exiting before start!")
            return
    
        chunk = 200
        remaining = step
    
        while remaining > 0:
            if SystemFuncClass.stop_flag:
                print("STOP detected during YfrontCorrect - Exiting mid-move!")
                return
    
            this_chunk = min(chunk, remaining)
    
            def m1():
                MotorClass.motor1.motor_go(True, "Full", this_chunk, .00008, False, .0001)
            def m2():
                MotorClass.motor2.motor_go(False, "Full", this_chunk, .00008, False, .0001)
    
            t1 = threading.Thread(target=m1)
            t2 = threading.Thread(target=m2)
            t1.start(); t2.start()
            t1.join(); t2.join()
    
            remaining -= this_chunk
        
    def YmoveCorrect(self, step):
        if SystemFuncClass.stop_flag:
            print("STOP detected in YmoveCorrect - Exiting!")
            return
        ydiff = int(step)
        if ydiff < 0 :
            self.YfrontCorrect(abs(ydiff))
        else :
            self.YbackCorrect(ydiff)
            
            
    def YbackCorrect2(self, step):
        if SystemFuncClass.stop_flag:
            print("STOP detected in YbackCorrect2 - Exiting before start!")
            return
    
        chunk = 200  # number of steps per chunk
        remaining = step
    
        while remaining > 0:
            if SystemFuncClass.stop_flag:
                print("STOP detected during YbackCorrect2 - Exiting mid-move!")
                return
    
            this_chunk = min(chunk, remaining)
    
            def m1():
                MotorClass.motor1.motor_go(False, "Full", this_chunk, .0005, False, .0001)
    
            def m2():
                MotorClass.motor2.motor_go(True, "Full", this_chunk, .0005, False, .0001)
    
            t1 = threading.Thread(target=m1)
            t2 = threading.Thread(target=m2)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
    
            remaining -= this_chunk
            
    def YfrontCorrect2(self, step):
        if SystemFuncClass.stop_flag:
            print("STOP detected in YfrontCorrect2 - Exiting before start!")
            return
    
        chunk = 200
        remaining = step
    
        while remaining > 0:
            if SystemFuncClass.stop_flag:
                print("STOP detected during YfrontCorrect2 - Exiting mid-move!")
                return
    
            this_chunk = min(chunk, remaining)
    
            def m1():
                MotorClass.motor1.motor_go(True, "Full", this_chunk, .0005, False, .0001)
            def m2():
                MotorClass.motor2.motor_go(False, "Full", this_chunk, .0005, False, .0001)
    
            t1 = threading.Thread(target=m1)
            t2 = threading.Thread(target=m2)
            t1.start(); t2.start()
            t1.join(); t2.join()
    
            remaining -= this_chunk
        
    def YmoveCorrect2(self, step):
        if SystemFuncClass.stop_flag:
            print("STOP detected in YmoveCorrect2 - Exiting!")
            return
        ydiff = int(step)
        if ydiff < 0:
            self.YfrontCorrect2(abs(ydiff))
        else:
            self.YbackCorrect2(ydiff)
    
    def Yback(self, btime, speed):
        if SystemFuncClass.stop_flag:
            self.Ystop()
            return

        self.InitYmotor(speed)
        pi.write(PortDefineClass.DIR1, 0)
        pi.write(PortDefineClass.DIR2, 1)
        pi.set_PWM_dutycycle(PortDefineClass.STEP1, 50)
        pi.set_PWM_dutycycle(PortDefineClass.STEP2, 50)

        for _ in range(int(btime * 100)):
            if SystemFuncClass.stop_flag:
                self.Ystop()
                return
            sleep(0.01)

        self.Ystop()
    
    def Yfront(self, ftime, speed):
        if SystemFuncClass.stop_flag:
            self.Ystop()
            return

        self.InitYmotor(speed)
        pi.write(PortDefineClass.DIR1, 1)
        pi.write(PortDefineClass.DIR2, 0)
        pi.set_PWM_dutycycle(PortDefineClass.STEP1, 50)
        pi.set_PWM_dutycycle(PortDefineClass.STEP2, 50)

        for _ in range(int(ftime * 100)):
            if SystemFuncClass.stop_flag:
                self.Ystop()
                return
            sleep(0.01)

        self.Ystop()

class ZMoveClass(PortDefineClass):
    
    sys_func = SystemFuncClass()
    
    def __init__(self):
        self.z_pos = 0
        self.z_cnt = 0

    #Z axis
    def CheckZLimit(self):
        return pi.read(PortDefineClass.Zlimit)
    
    def CheckZHtCal(self):
        return pi.read(PortDefineClass.ZHtCal)
    
    def Zspeed(self, speed):
        pi.set_PWM_frequency(PortDefineClass.STEPZ, speed)
    
    def Zdir(self, dir):
        if dir == 0:
            pi.write(PortDefineClass.DIRZ, 1)
        elif dir == 1:
            pi.write(PortDefineClass.DIRZ, 0)
    
    def ZmotorSet(self, dir, speed):
        self.Zdir(dir)
        self.Zspeed(speed)
    
    def Zstart(self):
        pi.set_PWM_dutycycle(PortDefineClass.STEPZ, 50)
    
    def Zstop(self):
        pi.set_PWM_dutycycle(PortDefineClass.STEPZ, 0)

    #moving down time is dtime * 0.01 sec
    def Zdown(self, dtime, speed):
    
        self.ZmotorSet(0, speed)
        self.Zstart()
    
        sleep(dtime)
    
        self.Zstop()
    
        sleep(0.5)
        
    #moving up time is sec
    def Zup(self, utime, speed):
    
        if self.CheckZLimit():
            if self.xymove.EMGSwitch():
                self.sys_func.AllStop()
                sys.tracebacklimit = 0
                raise ValueError()
            return
    
        self.ZmotorSet(1, speed)
        self.Zstart()
        
        zcnt = 0
        while zcnt != utime * 100 :
            if self.CheckZLimit():
                if self.xymove.EMGSwitch():
                    self.sys_func.AllStop()
                    sys.tracebacklimit = 0
                    raise ValueError()
                break
            sleep(0.01)
            zcnt += 1
        
        self.Zstop()
    
        sleep(0.5)
    
    def Zmove(self, step):
        self.sys_func.GPIO_Init()
        if step < 0 :
            self.Zdown(abs(step), 2500)
        else :
            self.Zup(step, 2500)
            
    def ZupCorrect(self, step):
        if SystemFuncClass.stop_flag:
            print("STOP detected in ZupCorrect - Exiting before start!")
            return
    
        chunk = 200
        remaining = step
    
        while remaining > 0:
            if SystemFuncClass.stop_flag:
                print("STOP detected during ZupCorrect - Exiting mid-move!")
                return
    
            this_chunk = min(chunk, remaining)
    
            def z():
                MotorClass.motorZ.motor_go(True, "Full", this_chunk, .00001, False, .0001)
    
            t = threading.Thread(target=z)
            t.start()
            t.join()
    
            remaining -= this_chunk
    
    
    def ZdnCorrect(self, step):
        if SystemFuncClass.stop_flag:
            print("STOP detected in ZdnCorrect - Exiting before start!")
            return
    
        chunk = 200
        remaining = step
    
        while remaining > 0:
            if SystemFuncClass.stop_flag:
                print("STOP detected during ZdnCorrect - Exiting mid-move!")
                return
    
            this_chunk = min(chunk, remaining)
    
            def z():
                MotorClass.motorZ.motor_go(False, "Full", this_chunk, .00001, False, .0001)
    
            t = threading.Thread(target=z)
            t.start()
            t.join()
    
            remaining -= this_chunk
    
    def ZmoveCorrect(self, step):
        if SystemFuncClass.stop_flag:
            print("STOP detected in ZmoveCorrect - Exiting!")
            return
        zdiff = int(step)
        if zdiff > 0 :
            self.ZupCorrect(zdiff)
        else :
            self.ZdnCorrect(abs(zdiff))


class GoHomePosClass:
    
    sysfunc = SystemFuncClass()
    zmove   = ZMoveClass()
    xymove = XYMoveClass()
    
    Y_start_pos = 0.40000 #Time sec 
    X_start_pos = 0.70000 #Time sec 
    
    def Home(self):
        try:
            
            self.sysfunc.GPIO_Init()
        
            self.Yhome()

            #douziidou
            self.xh = threading.Thread(target=self.Xhome)
            self.zh = threading.Thread(target=self.Zhome)
            
            self.xh.start()
            self.zh.start()
        
            self.xh.join()
            self.zh.join()
            
            sleep(1)
            
            self.xymove.Xright(self.X_start_pos,1500)
        
            self.xymove.Yback(self.Y_start_pos, 500)
            
            print (StatusDataClass.z_offset)
            
            self.begin = timeit.default_timer()
            self.zmove.ZmoveCorrect(int(StatusDataClass.z_offset) * 3)
            print (timeit.default_timer() - self.begin)

        except Exception as e:
            self.sysfunc.AllStop()
            print(e)

    def Zhome(self):
        if self.zmove.CheckZLimit == True:
            if self.xymove.EMGSwitch():
                self.sysfunc.AllStop()
                sys.tracebacklimit = 0
                raise ValueError()
            return
    
        self.zmove.ZmotorSet(1,8000)
        self.zmove.Zstart()
        
        
        while not self.zmove.CheckZLimit():
            if self.xymove.EMGSwitch():
                self.sysfunc.AllStop()
                sys.tracebacklimit = 0
                raise ValueError()
            pass

        
        
        self.zmove.Zstop()
        sleep(0.5)
        while self.zmove.CheckZLimit():
            self.zmove.Zdown(0.1, 1500)
            if self.xymove.EMGSwitch():
                self.sysfunc.AllStop()
                sys.tracebacklimit = 0
                raise ValueError()
            pass
        
        self.zmove.ZmotorSet(1,100)
        self.zmove.Zstart()
        while not self.zmove.CheckZLimit():
            if self.xymove.EMGSwitch():
                self.sysfunc.AllStop()
                sys.tracebacklimit = 0
                raise ValueError()
            pass
        self.zmove.Zstop()

    def Xhome(self):
    
        self.xymove.XmotorSet(0, 1000)
        self.xymove.Xstart()
    
        while not self.xymove.CheckXlimit():
            if self.xymove.EMGSwitch():
                self.sysfunc.AllStop()
                sys.tracebacklimit = 0
                raise ValueError()
            pass
    
        self.xymove.Xstop()
        sleep(0.5)
        
        while self.xymove.CheckXlimit() :
            self.xymove.Xright(0.05, 600)
            if self.xymove.EMGSwitch():
                self.sysfunc.AllStop()
                sys.tracebacklimit = 0
                raise ValueError()
            pass
    
        
        self.xymove.XmotorSet(0, 50)
        self.xymove.Xstart()
    
        print("seaking X limit...")
        while not self.xymove.CheckXlimit():
            if self.xymove.EMGSwitch():
                self.sysfunc.AllStop()
                sys.tracebacklimit = 0
                raise ValueError()
            pass
        print("X is home position")
    
        self.xymove.Xstop()
        

    def Yhome(self):
    
        self.xymove.InitYmotor(1500)
    
        self.xymove.Ydir(1)
        self.xymove.Ymovef()
    
        print("seaking Y limit...")
        
        while not self.xymove.CheckYlimit():
            if self.xymove.EMGSwitch():
                self.sysfunc.AllStop()
                sys.tracebacklimit = 0
                raise ValueError()
            pass
        
        print("Y is home position")
    
        self.xymove.Ystop()
        sleep(0.5)
        while self.xymove.CheckYlimit():
            self.xymove.Yback(0.1, 500)
            if self.xymove.EMGSwitch():
                self.sysfunc.AllStop()
                sys.tracebacklimit = 0
                raise ValueError()
            pass
       
        #back to home tooooo Slowly 
        self.xymove.YmotorSpeed(50)
        self.xymove.Ydir(1)
        self.xymove.Ymovef()
    
        print("seaking Y limit...")
        while not self.xymove.CheckYlimit():
            if self.xymove.EMGSwitch():
                self.sysfunc.AllStop()
                sys.tracebacklimit = 0
                raise ValueError()
            pass
        print("Y is home position")
    
        self.xymove.Ystop()


class DataScanClass:
    def __init__(self, gui):
        self.gui    = gui
        self.xymove = XYMoveClass()
        self.zmove  = ZMoveClass()
        self.home   = GoHomePosClass()
        self.serial = SerialDataComClass()
        self.sysfunc= SystemFuncClass()
        self.channels = [0]
        self.channel_mask = chan_list_to_mask(self.channels)
        self.samples_per_channel = 100
        #self.options = OptionFlags.CONTINUOUS
        self.options = OptionFlags.DEFAULT
        self.scan_rate = 8000.0
        
        # Find available HAT devices
        hats = hat_list(filter_by_id=HatIDs.MCC_128)
        if not hats:
            raise HatError("No MCC 128 HAT devices found.")
        
        # Use the first HAT device
        self.address_1 = hats[0].address
        
        self.hat_1 = mcc128(self.address_1)
        self.hat_1.a_in_mode_write(AnalogInputMode.SE)
        self.hat_1.a_in_range_write(AnalogInputRange.BIP_10V)

        self.timeout = 100

    def ScanPos(self):
        try:
            # Disable STOP button using GUI reference
            self.gui.StopButton.config(state='disabled')
            print("STOP button disabled during ScanPos")

            # Move to scanning position - this is just for manual particle centering
            # NO adjustment here - adjustment happens during ScanRoutine
            self.zmove.ZmoveCorrect(-1 * int(StatusDataClass.ScanHt) + StatusDataClass.ZOffset)
            self.xymove.XmoveCorrect(int(StatusDataClass.x_offset))
            self.xymove.YmoveCorrect(100)
            self.xymove.YmoveCorrect(int(StatusDataClass.y_offset))
            
            print("[INFO] At scanning position - manually center the particle now")

        except Exception as e:
            print(f"Error during ScanPos: {e}")

        finally:
            # Ensure STOP button is always re-enabled
            self.gui.StopButton.config(state='normal')
            print("STOP button re-enabled after ScanPos")

    def UnloadPos(self):
        # Simple unload - just return to home position
        self.xymove.YmoveCorrect(int(-StatusDataClass.y_offset))
        self.xymove.YmoveCorrect(-100)
        self.xymove.XmoveCorrect(int(-StatusDataClass.x_offset))
        self.zmove.ZmoveCorrect(int(StatusDataClass.ScanHt) - StatusDataClass.ZOffset)
    
    def UnloadPosAfterScan(self):
        # Unload after scan - includes reversing the centering adjustment
        scan_area_mm = StatusDataClass.roughness
        half_area_steps = int((scan_area_mm / 2) * 20)  # Convert mm to steps (20 steps per mm)
        
        # Move X and Y axes back SLOWLY and SMOOTHLY by half the scan area
        # Move 1 step at a time with small delays for smooth continuous motion
        remaining_steps = half_area_steps

        for step in range(remaining_steps):
            if SystemFuncClass.stop_flag:
                return
            
            # Move X back by 1 step
            self.xymove.XmoveCorrect(-1)
            sleep(0.005)  # 10ms delay = smooth motion at 100 steps/sec
            
            if SystemFuncClass.stop_flag:
                return
            
            # Move Y back by 1 step (same speed for synchronized movement)
            self.xymove.YmoveCorrect(-1)
            sleep(0.005)  # 10ms delay = smooth motion at 100 steps/sec
        
        print("[INFO] Returning to center position complete")
        
        # Then return to home position
        self.UnloadPos()

    def UnloadPos_stopped(self):
        self.home.Yhome()
        self.xymove.Yback(0.4, 500)
        self.home.Xhome()
        self.xymove.Xright(0.7,1500)
        self.zmove.ZmoveCorrect(int(StatusDataClass.ScanHt) - StatusDataClass.ZOffset)

    def ZHtCalibPos(self):
        while not self.zmove.CheckZLimit():
            if SystemFuncClass.stop_flag:
                return
            self.zmove.ZmoveCorrect(-15)
            if self.xymove.EMGSwitch():
                self.sysfunc.AllStop()
                sys.tracebacklimit = 0
                raise ValueError()
            pass
        
        self.xymove.XmoveCorrect(int(StatusDataClass.xcal_offset))
        self.xymove.YmoveCorrect2(int(StatusDataClass.ycal_offset))

    def GoCalib(self):
        cal_pos = 0
    
        # Step 1: Go to Z calibration position
        self.ZHtCalibPos()
        if SystemFuncClass.stop_flag:   #  stop if door opened during Z move
            return
    
        # Step 2: Calibrate Z height
        while not self.zmove.CheckZHtCal():
            if SystemFuncClass.stop_flag:
                return
            self.zmove.ZmoveCorrect(3)
            if self.xymove.EMGSwitch():
                self.sysfunc.AllStop()
                sys.tracebacklimit = 0
                raise ValueError()
            cal_pos += 1
    
        if not SystemFuncClass.stop_flag:
            StatusDataClass.zcal_offset = cal_pos
            # update GUI calibrate button text to show new cal value
            self.gui.calib_btn_var.set(f"Calibrate Z-Height\nZ-Ht: {StatusDataClass.zcal_offset}")
            print(StatusDataClass.zcal_offset)
    
        # Step 3: Home Z
        if SystemFuncClass.stop_flag:
            return
        self.home.Zhome()
    
        # Step 4: Move Y back
        if SystemFuncClass.stop_flag:
            return
        self.xymove.YmoveCorrect2(int(StatusDataClass.ycal_offset) * -1)
    
        # Step 5: Move X back
        if SystemFuncClass.stop_flag:
            return
        self.xymove.XmoveCorrect(int(StatusDataClass.xcal_offset) * -1)
    
        # Step 6: Move Z back
        if SystemFuncClass.stop_flag:
            return
        self.zmove.ZmoveCorrect(cal_pos * 3)
    
        # Step 7: Show popup
        if SystemFuncClass.stop_flag:
            return
        popup = tk.Toplevel(self.gui.win)  
        popup.title("Calibration Complete")
        popup.protocol("WM_DELETE_WINDOW", lambda: None)
        bg_color = "#97F06A"  # Bright yellow for visibility
        popup.configure(bg=bg_color)
        
        popup_label = tk.Label(
            popup,
            text="Z-Height Calibration Finished.\nPlease remove all of the Calibration Jig \nbefore Scanning.",
            font=("Helvetica", 16, "bold"),  # Bigger, bold font for better visibility
            fg="black",  # Text color
            bg=bg_color,  # Match the background color
            justify="center"
            )
        popup_label.pack(pady=15, padx=20)
        
        popup.update_idletasks()

        popup_width = popup.winfo_width()
        popup_height = popup.winfo_height()
        position_x = (800 // 2) - (popup_width // 2)
        position_y = (480 // 2) - (popup_height // 2)
        
        popup.geometry(f"{popup_width}x{popup_height}+{position_x}+{position_y}")
        
        def blink_background():
            current_color = popup["bg"]
            new_color = "#FF0000" if current_color == "#97F06A" else "#97F06A"  # Switch between green and red
            popup.configure(bg=new_color)
            popup_label.configure(bg=new_color)  # Update label background to match
            popup.after(500, blink_background)  # Repeat every 500ms

        blink_background()
        
        def close_popup_when_ready():
            while not self.zmove.CheckZHtCal():  # Wait until CheckZHtCal() is True
                sleep(0.5)  # Check every 0.5 seconds

            popup.destroy()  #  Close the popup automatically
            print("Popup closed automatically.")

        threading.Thread(target=close_popup_when_ready, daemon=True).start()
        
    def Yreturn(self):
        self.home.Yhome()
    
    #roughdness : how long one line
    #xdensity  scan point per one lineXhome
    #? : roud = 50 = 1mm  50 de 1mm r 20 d 100
    def CorrectScan(self, roughdness, xdensity, ydensity, c, fn):
        xrough = roughdness / xdensity
        yrough = roughdness / ydensity
        
        # Calculate step sizes with rounding to prevent precision loss
        # Ensure minimum step size of 1 to maintain scanning area
        y_step = max(1, round(yrough * 20))
        x_step = max(1, round(xrough * 20))
        
        x_pos = 0
        dir_num = [-1, 1]
        dir_flag = True
        
        while True :
            if SystemFuncClass.stop_flag:
                print("STOP detected in CorrectScan - Exiting!")
                return  # Immediately exit scan
            
            StatusDataClass.x_point = x_pos
            self.LineScan(ydensity, 0, -y_step, c, fn)
            if SystemFuncClass.stop_flag:
                print("STOP detected in CorrectScan - Exiting!")
                return  # Immediately exit scan
                
            self.xymove.YmoveCorrect2(y_step * ydensity)
            if SystemFuncClass.stop_flag:
                print("STOP detected in CorrectScan - Exiting!")
                return  # Immediately exit scan
            
            #dassyutujouken
            if x_pos == xdensity :
                self.xymove.XmoveCorrect(x_step * xdensity)
                if SystemFuncClass.stop_flag:
                    print("STOP detected in CorrectScan - Exiting!")
                    return  # Immediately exit scan
                break
            x_pos += 1

            #tsuginoscannojunbi
            self.xymove.XmoveCorrect(-x_step)
            if SystemFuncClass.stop_flag:
                print("STOP detected in CorrectScan - Exiting!")
                return  # Immediately exit scan
            dir_flag = not dir_flag

            print(x_pos)
        return 
    
    def LineScan(self, scan_num, x_move_count, y_move_count, c, fn):
    
        scan_pos = 0
        cnt = 1
        
        if (x_move_count > 0) or (y_move_count > 0):
            scan_pos = scan_num
            scan_num = 0
            cnt = -1
    
        while True :
            StatusDataClass.y_point = scan_pos
            if SystemFuncClass.stop_flag:
                print("STOP detected in CorrectScan - Exiting!")
                return  # Immediately exit scan
            self.PointScan(c, fn)
            #sdata.append(self.PointScan())
            
            #1 a 
            if (scan_pos == scan_num):
                if SystemFuncClass.stop_flag:
                    print("STOP detected in CorrectScan - Exiting!")
                    return  # Immediately exit scan
                break

            scan_pos += cnt
            
            if SystemFuncClass.stop_flag:
                return
            self.xymove.YmoveCorrect(y_move_count)
            if SystemFuncClass.stop_flag:
                return
            self.xymove.XmoveCorrect(x_move_count)
            
        #sleep(1)
            
    
    def PointScan(self, c, fn):
        self.hat_1.a_in_scan_start(self.channel_mask, self.samples_per_channel, self.scan_rate, self.options)        
        read_result_1 = self.hat_1.a_in_scan_read(self.samples_per_channel, self.timeout)
        self.hat_1.a_in_scan_stop()
        self.hat_1.a_in_scan_cleanup()
            
        voltage_1 = sum(read_result_1.data) / len(read_result_1.data)

        StatusDataClass.v_data = voltage_1  # You can modify the way you handle the voltage data based on your needs
        if SystemFuncClass.stop_flag:
                print("STOP detected in CorrectScan !")
                return  # Immediately exit scan
        self.serial.TrScanData(c, fn)

        return voltage_1
            
    def ScanRoutine(self, c, fn):

        self.ScanPos()
        if SystemFuncClass.stop_flag:
                return
        sleep (1.5)
        if SystemFuncClass.stop_flag:
                return
        
        # Apply centering adjustment based on scan area
        # Move both X and Y by half the scan area to center the particle
        scan_area_mm = StatusDataClass.roughness
        half_area_steps = int((scan_area_mm / 2) * 20)  # Convert mm to steps (20 steps per mm)
        
        print(f"[INFO] Centering scan: Moving X and Y axes by {scan_area_mm/2}mm ({half_area_steps} steps) to start position")
        print(f"[INFO] Scan will proceed, centering particle in {scan_area_mm}mm scan area")
        
        # Move X and Y by half the scan area SLOWLY and SMOOTHLY to prevent system damage
        # Move 1 step at a time with small delays for smooth continuous motion
        remaining_steps = half_area_steps
        
        for step in range(remaining_steps):
            if SystemFuncClass.stop_flag:
                return
            
            # Move X by 1 step
            self.xymove.XmoveCorrect(1)
            sleep(0.005)  # 10ms delay = smooth motion at 100 steps/sec
            
            if SystemFuncClass.stop_flag:
                return
            
            # Move Y by 1 step (same speed for synchronized movement)
            self.xymove.YmoveCorrect(1)
            sleep(0.005)  # 10ms delay = smooth motion at 100 steps/sec
        
        print("[INFO] Centering adjustment complete")
        
        if SystemFuncClass.stop_flag:
                return
        
        self.CorrectScan(StatusDataClass.roughness, StatusDataClass.xdensity, StatusDataClass.ydensity, c, fn)
        if SystemFuncClass.stop_flag:
            print("Scan stopped after CorrectScan.")
            return  # Exit immediately
        self.UnloadPosAfterScan()
        
class GUIClass(PortDefineClass):
    
    xy_move     = XYMoveClass()
    z_move      = ZMoveClass()
    home        = GoHomePosClass()
    system_func = SystemFuncClass()
    port        = PortDefineClass
    
    def __init__(self):
        self.data_scan   = DataScanClass(self)
        self.win = Tk()
        self.win.title("Type C Scanning System")
        self.win.geometry('800x480')
        self.win.configure(bg='#0046ad')

        # --- pigpio reference ---
        self.pi = pi  
        self.door_open = False
        self.running = True  # for clean shutdown

        # --- fonts ---
        self.buttonFont = TkFont.Font(family='Helvetica', size=25, weight='bold')
        self.buttonFont = TkFont.Font(family='Helvetica', size=20, weight='bold')
        self.buttonFont2 = TkFont.Font(family='Helvetica', size=25, weight='bold')
        self.buttonFont3 = TkFont.Font(family='Helvetica', size=11, weight='bold')
        self.buttonFont4 = TkFont.Font(family='Helvetica', size=12, weight='bold')
        self.buttonFont5 = TkFont.Font(family='Helvetica', size=15, weight='bold')
        self.labelFont = TkFont.Font(family='Helvetica', size=15, weight='bold')
        self.labelFont2 = TkFont.Font(family='Helvetica', size=10, weight='bold')
        self.labelFont3 = TkFont.Font(family='Helvetica', size=12, weight='bold')
        self.inputFont = TkFont.Font(family='Helvetica', size=15, weight='bold')
        self.logoFont = TkFont.Font(family='BiomeW04-Bold', size=60, weight='bold')
        self.win.attributes('-fullscreen',True)
        self.win.config(cursor="none")
        self.mode = IntVar()
        self.mode.set("1")
        self.condition = 1
        self.ch = IntVar()
        self.ch.set("1")
        self.chan = 1
        self.mv = IntVar()
        self.mv.set("1")
        self.mov = 1
        self.xy_mv = IntVar()  # Separate variable for X/Y calibration speed
        self.xy_mv.set("1")
        self.xy_mov = 1  # Separate speed setting for X/Y calibration
        self.res = IntVar()  # Resolution selection
        self.res.set("1")  # Default to 100x100
        self.validator = self.win.register(self.validate_input)
        self.value = 2.0
        self.prev_axis_text = "---"
        self.prev_axis_bg = self.win.cget("bg")
        self.was_scanning = False
        
        # Continuous move variables
        self.continuous_move_active = False
        self.continuous_move_axis = None
        self.continuous_move_direction = 0
        self.continuous_move_pos = None

        self.HomeButton = Button(self.win, text = 'HOME', font = self.buttonFont2, command = self.started_homing, height = 2, width = 6, bg='lightgreen', activebackground='lightgreen')
        self.HomeButton.place(x = 10, y = 160)
        
        self.logo = Label(self.win, text = 'Migne', font = self.logoFont, height = 0, width = 5, bg='#0046ad', fg='white')
        self.logo.place(x = 0, y = -10)

        self.sublogo = Label(self.win, text = 'Particle Scanning System', font = self.labelFont, height = 0, width = 22, bg='#0046ad', fg='white')
        self.sublogo.place(x = 170, y = 80)
        
        self.scan = Button(self.win, text = 'Start\nScanning', font = self.buttonFont2, command = self.scan_started, height = 2, width = 7, bg='lightgreen', activebackground='lightgreen')
        self.scan.place(x = 156, y = 160)

        self.StopButton = Button(self.win, text='STOP', font=self.buttonFont2, command=self.stop_all_motion, height=2, width=6, bg='red', activebackground='red')
        self.StopButton.place(x=320, y=160)
        
        self.ExitButton = Button(self.win, text = 'Exit', font = self.buttonFont, command = self.gui_exit, height = 1, width = 6)
        self.ExitButton.place(x = 390, y = 5)
        
        self.RebootButton = Button(self.win, text = 'Reboot', font = self.buttonFont, command = self.system_func.reboot, height = 1, width = 6)
        self.RebootButton.place(x = 520, y = 5)

        self.ShutdownButton = Button(self.win, text = 'Shutdown', font = self.buttonFont, command = self.system_func.shutdown, height = 1, width = 7)
        self.ShutdownButton.place(x = 650, y = 5)
        
        # --- NEW: split Move to Scanning Pos into two adjacent buttons ---
        self.MoveScanButton = Button(self.win, text = 'Move to\nScanning Pos', font = self.buttonFont3, command = self.goingto_scanpos, height = 2, width = 16)
        self.MoveScanButton.place(x = 470, y = 100)
        self.MoveCalibButton = Button(self.win, text = 'Goto Z-Ht\nCalibration Pos', font = self.buttonFont3, command = self.goingto_calpos, height = 2, width = 16)
        self.MoveCalibButton.place(x = 640, y = 100)
        
        self.UnloadButton = Button(self.win, text = 'Unload', font = self.buttonFont5, command = self.goingto_unloadpos, height = 2, width = 17)
        self.UnloadButton.place(x = 240, y = 250)
        
        # X/Y offset adjustment buttons (hold to continuously move)
        self.XPlusButton = Button(self.win, text = '→', font = self.buttonFont, height = 1, width = 2)
        self.XPlusButton.place(x = 600, y = 245)
        self.XPlusButton.bind('<ButtonPress-1>', lambda e: self.start_continuous_move('X', 1))
        self.XPlusButton.bind('<ButtonRelease-1>', lambda e: self.stop_continuous_move())
        
        self.XMinusButton = Button(self.win, text = '←', font = self.buttonFont, height = 1, width = 2)
        self.XMinusButton.place(x = 470, y = 245)
        self.XMinusButton.bind('<ButtonPress-1>', lambda e: self.start_continuous_move('X', -1))
        self.XMinusButton.bind('<ButtonRelease-1>', lambda e: self.stop_continuous_move())
        
        self.YPlusButton = Button(self.win, text = '↑', font = self.buttonFont, height = 1, width = 2)
        self.YPlusButton.place(x = 535, y = 210)
        self.YPlusButton.bind('<ButtonPress-1>', lambda e: self.start_continuous_move('Y', 1))
        self.YPlusButton.bind('<ButtonRelease-1>', lambda e: self.stop_continuous_move())
        
        self.YMinusButton = Button(self.win, text = '↓', font = self.buttonFont, height = 1, width = 2)
        self.YMinusButton.place(x = 535, y = 275)
        self.YMinusButton.bind('<ButtonPress-1>', lambda e: self.start_continuous_move('Y', -1))
        self.YMinusButton.bind('<ButtonRelease-1>', lambda e: self.stop_continuous_move())
        
        self.ClearOffsetButton = Button(self.win, text = 'Clear Offset', font = self.buttonFont4, command = self.ClearOffset, height = 2, width = 10)
        self.ClearOffsetButton.place(x = 678, y = 155)
        
        # X/Y Calibration Speed Radio Buttons (Low and Medium only)
        self.xy_low = Radiobutton(self.win, text = "Low", font = self.labelFont2, command = lambda: self.xy_movement(self.xy_mv.get()), 
                                  variable = self.xy_mv, value = 1, bg='#0046ad', fg='white', activebackground='#0046ad', activeforeground='white', 
                                  selectcolor='#0046ad', highlightthickness=0)
        self.xy_low.place(x = 700, y = 250)
        
        self.xy_med = Radiobutton(self.win, text = "Medium", font = self.labelFont2, command = lambda: self.xy_movement(self.xy_mv.get()), 
                                variable = self.xy_mv, value = 2, bg='#0046ad', fg='white', activebackground='#0046ad', activeforeground='white', 
                                selectcolor='#0046ad', highlightthickness=0)
        self.xy_med.place(x = 700, y = 270)
        
        # NOTE: removed the left-side calibration buttons (and left X/Y position display)
        # The calibration function remains accessible via the MoveCalibButton and the same X/Y offset inputs.

        # Calibrate button now includes Z-Ht display inside button (prevents overlap)
        self.calib_btn_var = tk.StringVar()
        self.calib_btn_var.set(f"Calibrate Z-Height\nZ-Ht: {0}")  # updated in init_offset_data

        self.CalibrateButton = Button(
            self.win,
            textvariable=self.calib_btn_var,
            font=self.buttonFont5,
            command=self.starting_calib,
            height=2,
            width=18,
            bg='yellow',
            activebackground='yellow',
            wraplength=200,
            justify='center'
        )
        self.CalibrateButton.place(x = 10, y = 250)
        
        # Arrow buttons for scanning distance (²/¼) and z-height offset (²/¼)
        self.up_button = Button(self.win, text='↑', font=("Helvetica", 20), command=self.increase_value)
        self.up_button.place(x = 590, y = 330)

        self.down_button = Button(self.win, text='↓', font=("Helvetica", 20), command=self.decrease_value)
        self.down_button.place(x = 715, y = 330)
        
        self.inc_button = Button(self.win, text='↑', font=("Helvetica", 20), command=self.ZHtUpPosOffset)
        self.inc_button.place(x = 590, y = 400)

        self.dec_button = Button(self.win, text='↓', font=("Helvetica", 20), command=self.ZHtDownPosOffset)
        self.dec_button.place(x = 675, y = 400)

        self.label1 = Label(self.win, text = 'X Offset:', font = self.labelFont, width = 7, bg='#0046ad', fg='white')
        self.label1.place(x = 480, y = 150)
        
        self.label2 = Label(self.win, text = 'Y Offset:', font = self.labelFont, width = 7, bg='#0046ad', fg='white')
        self.label2.place(x = 480, y = 180)
        
        self.label3 = Label(self.win, text = 'Scanning\nDistance:', font = self.labelFont, width = 9, bg='#0046ad', fg='white')
        self.label3.place(x = 480, y = 330)
        
        # Contextual offset display (these show scan offsets or calibration offsets depending on current position)
        self.label4 = Label(self.win, text = '---', font = self.labelFont, height = 1, width = 5, bg='#0046ad', fg='white')
        self.label4.place(x = 580, y = 150)
        
        self.label5 = Label(self.win, text = '---', font = self.labelFont, height = 1, width = 5, bg='#0046ad', fg='white')
        self.label5.place(x = 580, y = 180)
        
        # NOTE: X/Y editable entries moved to the left-side area (replacing the old X/Y status indicator)
        # left-side z display moved into button; show small ZOffset label
        self.label6 = None  # no separate label for z-height, using self.calib_btn_var instead

        self.label7 = Label(self.win, text = 'Input Filename:', font = self.labelFont, height = 1, width = 14, bg='#0046ad', fg='white')
        self.label7.place(x = 0, y = 125)
        
        self.label8 = Label(self.win, text = 'Homing Status:', font = self.labelFont, height = 1, width = 14, bg='#0046ad', fg='white')
        self.label8.place(x = 0, y = 453)
        
        self.label9 = Label(self.win, text = 'OK', font = self.labelFont, height = 1, width = 10, bg='#0046ad', fg='white')
        self.label9.place(x = 155, y = 450)
        
        self.label10 = Label(self.win, text = 'Axis Status:', font = self.labelFont, height = 1, width = 10, bg='#0046ad', fg='white')
        self.label10.place(x = 300, y = 453)
        
        self.label11 = Label(self.win, text = "---", font = self.labelFont, height = 1, width = 16, bg='#0046ad', fg='white')
        self.label11.place(x = 415, y = 450)
        
        self.label12 = Label(self.win, text = 'Scan Time:', font = self.labelFont, height = 1, width = 10, bg='#0046ad', fg='white')
        self.label12.place(x = 610, y = 453)
        
        self.label13 = Label(self.win, text = '00:00', font = self.labelFont, height = 1, width = 5, bg='#0046ad', fg='white')
        self.label13.place(x = 720, y = 453)
        
        self.label14 = Label(self.win, text = 'S/N: 202307-PSS-02', font = self.labelFont, height = 1, width = 18, bg='#0046ad', fg='white')
        self.label14.place(x = 0, y = 100)
        
        # Scan parameters section - positioned below Calibrate and Unload buttons
        self.label_scan_params = Label(self.win, text = 'Scan Settings:', font = self.labelFont, bg='#0046ad', fg='white')
        self.label_scan_params.place(x = 10, y = 310)
        
        # Scanning Area controls
        self.label_scan_area = Label(self.win, text = 'Area (mm):', font = self.labelFont3, bg='#0046ad', fg='white')
        self.label_scan_area.place(x = 10, y = 335)
        
        self.scan_area_value = Label(self.win, text = str(StatusDataClass.roughness), font = self.labelFont3, width = 5, bg='#0046ad', fg='white')
        self.scan_area_value.place(x = 110, y = 335)
        
        self.scan_area_minus = Button(self.win, text = '↓', font=("Helvetica", 20), command = self.decrease_scan_area)
        self.scan_area_minus.place(x = 20, y = 365)
        
        self.scan_area_plus = Button(self.win, text = '↑', font=("Helvetica", 20), command = self.increase_scan_area)
        self.scan_area_plus.place(x = 80, y = 365)
        
        # Resolution controls
        self.label_resolution = Label(self.win, text = 'Datapoints:', font = self.labelFont3, bg='#0046ad', fg='white')
        self.label_resolution.place(x = 150, y = 335)
        
        self.res_100 = Radiobutton(self.win, text = "100", font = self.labelFont2, command = lambda: self.set_resolution(self.res.get()), 
                                  variable = self.res, value = 1, bg='#0046ad', fg='white', activebackground='#0046ad', activeforeground='white', 
                                  selectcolor='#0046ad', highlightthickness=0)
        self.res_100.place(x = 150, y = 355)
        
        self.res_150 = Radiobutton(self.win, text = "150", font = self.labelFont2, command = lambda: self.set_resolution(self.res.get()), 
                                  variable = self.res, value = 2, bg='#0046ad', fg='white', activebackground='#0046ad', activeforeground='white', 
                                  selectcolor='#0046ad', highlightthickness=0)
        self.res_150.place(x = 150, y = 375)
        
        self.res_200 = Radiobutton(self.win, text = "200", font = self.labelFont2, command = lambda: self.set_resolution(self.res.get()), 
                                  variable = self.res, value = 3, bg='#0046ad', fg='white', activebackground='#0046ad', activeforeground='white', 
                                  selectcolor='#0046ad', highlightthickness=0)
        self.res_200.place(x = 150, y = 395)
        
        # Grid size display
        self.label_grid_info = Label(self.win, text = f'{StatusDataClass.roughness}mm | {StatusDataClass.xdensity}x{StatusDataClass.ydensity} ({StatusDataClass.resolution:,} pts)', font = self.labelFont3, bg='#0046ad', fg='yellow')
        self.label_grid_info.place(x = 170, y = 313)

        # --- X/Y offset display (left side): show both Scan and Calibration offsets ---
        # Scan offsets (left column)
        self.label_scan_x = Label(self.win, text = 'Scan X Offset:', font = self.labelFont2, bg='#0046ad', fg='white', width = 12)
        self.label_scan_x.place(x = 150, y = 350)
        self.label_x_val = Label(self.win, text = '---', font = self.labelFont, bg='#0046ad', fg='white', width = 12)
        self.label_x_val.place(x = 260, y = 350)

        self.label_scan_y = Label(self.win, text = 'Scan Y Offset:', font = self.labelFont2, bg='#0046ad', fg='white', width = 12)
        self.label_scan_y.place(x = 150, y = 380)
        self.label_y_val = Label(self.win, text = '---', font = self.labelFont, bg='#0046ad', fg='white', width = 12)
        self.label_y_val.place(x = 260, y = 380)

        # Calibration offsets (right column)
        self.label_cal_x = Label(self.win, text = 'Cal X Offset:', font = self.labelFont2, bg='#0046ad', fg='white', width = 12)
        self.label_cal_x.place(x = 360, y = 350)
        self.label_cal_x_val = Label(self.win, text = '---', font = self.labelFont, bg='#0046ad', fg='white', width = 12)
        self.label_cal_x_val.place(x = 470, y = 350)

        self.label_cal_y = Label(self.win, text = 'Cal Y Offset:', font = self.labelFont2, bg='#0046ad', fg='white', width = 12)
        self.label_cal_y.place(x = 360, y = 380)
        self.label_cal_y_val = Label(self.win, text = '---', font = self.labelFont, bg='#0046ad', fg='white', width = 12)
        self.label_cal_y_val.place(x = 470, y = 380)

        self.label15 = Label(self.win, text = 'Run Mode:', font = self.labelFont3, height = 1, width = 10, bg='#0046ad', fg='white')
        self.label15.place(x = 450, y = 70)
        
        # left X/Y position display removed to free space for future functions (label17..20 removed)

        self.label21 = Label(self.win, text = 'Z-Ht Calibration Status:', font = self.labelFont, width = 21, bg='#0046ad', fg='white')
        self.label21.place(x = 0, y = 423)
        
        self.label22 = Label(self.win, text = 'Calibrated', font = self.labelFont, width = 13, bg='#0046ad', fg='white')
        self.label22.place(x = 240, y = 423)
    
        self.label24 = Label(self.win, text = 'mm', font = self.labelFont, width = 4, bg='#0046ad', fg='white')
        self.label24.place(x = 665, y = 340)
        
        self.label25 = Label(self.win, text = f"{self.value:.1f}", font = self.labelFont, width = 3, bg='#0046ad', fg='white')
        self.label25.place(x = 635, y = 340)
        
        self.label26 = Label(self.win, text = "Min Height = 0.5 / Max Height = 8.0", font = self.labelFont2, width = 35, bg='#0046ad', fg='yellow')
        self.label26.place(x = 490, y = 375)        

        self.label27 = Label(self.win, text = "Z-Height\nOffset:", font = self.labelFont, width = 7, bg='#0046ad', fg='white')
        self.label27.place(x = 495, y = 400) 

        self.label28 = Label(self.win, text = '0', font = self.labelFont3, height = 1, width = 3, bg='#0046ad', fg='white')
        self.label28.place(x = 635, y = 410)
        
        self.label29 = Label(self.win, text = "Adjust Speed", font = self.labelFont2, width = 13, bg='#0046ad', fg='yellow')
        self.label29.place(x = 685, y = 220)

        # X/Y textboxes removed - using hold buttons instead
        
        # removed XCal/YCal entries (left side) as requested

        self.fname = Entry(self.win, font = self.inputFont, width = 27, borderwidth=0)
        self.fname.place(x = 160, y = 122)
        
        # Trigger keyboard every time the entry is clicked
        def show_keyboard(event):
            self.fname.focus_set()
            self.fname.select_range(0, tk.END)
            try:
                os.system("onboard &")
            except:
                pass
        
        self.fname.bind("<Button-1>", show_keyboard)
        
        self.single = Radiobutton(self.win, text = "Single Test", font = self.labelFont3, command = lambda: self.run_mode(self.mode.get()), 
                                  variable = self.mode, value = 1, bg='#0046ad', fg='white', activebackground='#0046ad', activeforeground='white', 
                                  selectcolor='#0046ad', highlightthickness=0)
        self.single.place(x = 550, y = 70)
        
        self.demo = Radiobutton(self.win, text = "Demo Mode", font = self.labelFont3, command = lambda: self.run_mode(self.mode.get()), 
                                variable = self.mode, value = 2, bg='#0046ad', fg='white', activebackground='#0046ad', activeforeground='white', 
                                selectcolor='#0046ad', highlightthickness=0)
        self.demo.place(x = 670, y = 70)
        

        self.low = Radiobutton(self.win, text = "Low", font = self.labelFont2, command = lambda: self.movement(self.mv.get()), 
                                  variable = self.mv, value = 1, bg='#0046ad', fg='white', activebackground='#0046ad', activeforeground='white', 
                                  selectcolor='#0046ad', highlightthickness=0)
        self.low.place(x = 720, y = 390)
        
        self.med = Radiobutton(self.win, text = "Medium", font = self.labelFont2, command = lambda: self.movement(self.mv.get()), 
                                variable = self.mv, value = 2, bg='#0046ad', fg='white', activebackground='#0046ad', activeforeground='white', 
                                selectcolor='#0046ad', highlightthickness=0)
        self.med.place(x = 720, y = 410)
        
        self.high = Radiobutton(self.win, text = "High", font = self.labelFont2, command = lambda: self.movement(self.mv.get()), 
                                variable = self.mv, value = 3, bg='#0046ad', fg='white', activebackground='#0046ad', activeforeground='white', 
                                selectcolor='#0046ad', highlightthickness=0)
        self.high.place(x = 720, y = 430)
        
        self.cb = self.pi.callback(PortDefineClass.SWITCH, pigpio.RISING_EDGE, self.emg_stop)
        
        # --- flashing setup ---
        self._flash_color = "red"
        self._flash_interval = 500
        self._stop = False
        self.seconds = 0
        self.timer_running = False

        # --- start monitoring doors ---
        threading.Thread(target=self.monitor_doors, daemon=True).start()

    # ---------------- Door Interlock ----------------
    def is_door_open(self):
        return (self.pi.read(self.LDoor) == 0 or 
                self.pi.read(self.RDoor) == 0)

    def monitor_doors(self):
        """Background monitor for doors. Stop motion if opened."""
        while self.running:
            if self.is_door_open():
                if not self.door_open:  # door just opened
                    self.door_open = True
                    SystemFuncClass.stop_flag = True
                    self.system_func.AllStop()
    
                    def update_on_open():
                        if not self.win.winfo_exists():
                            return
    
                        current_status = self.label11.cget("text")
    
                        if current_status in ["Home", "Scan Pos"]:
                            # Case 1: At Home or Scan Pos  show Door Open (dont touch Homing)
                            self.was_scanning = False
                            self.prev_axis_status = current_status  # remember if it was Home or Scan Pos
                            self.label11.config(text="Door Open", bg="red", fg="white")
                            self._stop = False
                            self._flash_label()
    
                        elif current_status == "Scanning":
                            # Case 2: Scanning  force Not_Home + Door Open
                            self.was_scanning = True
                            self.label9.config(text="Not_Home", bg="red")
                            self.prev_axis_status = "Scanning"
                            self.label11.config(text="Door Open", bg="red", fg="white")
                            self._stop = False
                            self._flash_label()
    
                        else:
                            # Case 3: Any other state  Not_Home + Axis = ---
                            self.was_scanning = False
                            self.prev_axis_status = "---"
                            self.label9.config(text="Not_Home", bg="red")
                            self.label11.config(text="---", bg="red", fg="white")
                            self._stop = False
                            self._flash_label()
    
                        # Disable critical buttons
                        self.HomeButton.config(state='disabled')
                        self.scan.config(state='disabled')
                        self.MoveCalibButton.config(state='disabled')
                        self.UnloadButton.config(state='disabled')
                        self.CalibrateButton.config(state='disabled')
                        self.MoveScanButton.config(state='disabled')
    
                    if self.win.winfo_exists():
                        self.win.after(0, update_on_open)
    
            else:
                if self.door_open:  # door just closed
                    self.door_open = False
                    threading.Thread(target=self.reset_stop_flag_after_delay, daemon=True).start()
    
                    def update_on_close():
                        if not self.win.winfo_exists():
                            return
                        # Stop flashing
                        self._stop = True
    
                        if self.was_scanning:
                            # If door was opened during scanning  STOPPED
                            self.label11.config(bg="red", text="STOPPED")
                            self.was_scanning = False
                        else:
                            # Restore based on what it was before Door Open
                            if getattr(self, "prev_axis_status", None) == "Scan Pos":
                                self.label11.config(bg=self.win.cget("bg"), text="Scan Pos", fg="white")
                            elif getattr(self, "prev_axis_status", None) == "Home":
                                self.label11.config(bg=self.win.cget("bg"), text="Home", fg="white")
                            else:
                                self.label11.config(bg=self.win.cget("bg"), text="---", fg="white")
    
                        # Re-enable buttons
                        self.HomeButton.config(state='normal')
                        self.scan.config(state='normal')
                        self.MoveCalibButton.config(state='normal')
                        self.UnloadButton.config(state='normal')
                        self.CalibrateButton.config(state='normal')
                        self.MoveScanButton.config(state='normal')
    
                    if self.win.winfo_exists():
                        self.win.after(0, update_on_close)
    
            sleep(0.1)


    def check_door_before_action(self, action_name):
        if self.is_door_open():
            messagebox.showerror("Error", f"Cannot perform {action_name} - Door is open")
            return False
        return True
    
    def increase_value(self):
        if self.value < 8.0:
            self.value += 0.1
            self.update_distance()

    def decrease_value(self):
        if self.value > 0.5:
            self.value -= 0.1
            self.update_distance()

    def update_distance(self):
        self.label25.config(text=f"{self.value:.1f}")

    def validate_input(self, P):
        # Allow empty string (clearing), a single '-' (partial), or an integer with optional leading '-'
        if P == "":
            return True
        if P == "-":
            return True
        if P.lstrip('-').isdigit():
            return True
        return False

    def started_flashing(self):
        threading.Thread(target=self.start_flashing).start()
        
    def stopped_flashing(self):
        threading.Thread(target=self.stop_flashing).start()
            
    def start_flashing(self):
        self._stop = False
        self._flash_label()

    def stop_flashing(self):
        self._stop = True
        self.label11.config(bg=self.win.cget("bg"))
     
    def _flash_label(self):
        if not self._stop:
            if self.label11.cget("bg") == self._flash_color:
                self.label11.config(bg=self.win.cget("bg"))
            else:
                self.label11.config(bg=self._flash_color)
            self.win.after(self._flash_interval, self._flash_label)
        
    def stop_all_motion(self):
        if self.label11.cget("text") != "Scanning":
            messagebox.showerror("Error", "Stop function is applicable only during Scanning, use Emergency Stop Instead")
            return
            
        print("STOP button pressed - Halting all motion!")

        SystemFuncClass.stop_flag = True  # Set stop flag
        self.system_func.AllStop()  # Stop all motors
        self.stop_timer()  # Stop the timer if running
        self.stopped_flashing()  # Stop UI flashing alerts

        self.label11["text"] = "STOPPED"

        # **Ensure all running motor threads exit**
        for thread in threading.enumerate():
            if thread != threading.current_thread():
                print(f"Stopping thread: {thread.name}")
                thread.join(timeout=0.1)  # Try to exit the thread safely

        # Re-enable scan setting buttons after stop
        self.scan_area_minus.config(state='normal')
        self.scan_area_plus.config(state='normal')
        self.res_100.config(state='normal')
        self.res_150.config(state='normal')
        self.res_200.config(state='normal')
        # Start a thread to reset stop_flag after 3 seconds
        threading.Thread(target=self.reset_stop_flag_after_delay, daemon=True).start()
    
    def reset_stop_flag_after_delay(self):
        self.UnloadButton.config(state='disabled')
        sleep(1)  # Wait for 1 seconds
        SystemFuncClass.stop_flag = False  # Reset stop flag
        self.scan.config(state='normal')
        self.UnloadButton.config(state='normal')
        print("STOP flag reset - Ready for next operation.")
        #self.label11["text"] = "Ready"    
    
    def emg_stop(self, gpio, level, tick):
        if level == 1:
            SystemFuncClass.stop_flag = True  # Set the stop flag immediately
            self.label9["text"] = "Not_Home"
            self.label9["bg"] = "red"
            self.label22["text"] = "Not Calibrated"
            self.label22["bg"] = "red"   
            self.label11["text"] = "EMG Stop Pressed"
            self.scan.config(state='normal')
            self.HomeButton.config(state='normal')
            self.MoveScanButton.config(state='normal')
            self.CalibrateButton.config(state='normal')
            self.stop_timer()
            self.stop_flashing()
            self.system_func.AllStop()
            threading.Thread(target=self.reset_stop_flag_after_delay, daemon=True).start()
        
    def run_mode(self, value):
        self.condition = value
        if self.condition == 2:
            self.fname.delete(0, "end") 
            self.fname.insert(0,'Demo')
        if self.condition == 1:
            self.fname.delete(0, "end") 
            
    def channel(self, value):
        self.chan = value
        
    def movement(self, value):
        self.mov = value
    
    def xy_movement(self, value):
        self.xy_mov = value
    
    def gui_start(self):
        self.win.protocol("WM_DELETE_WINDOW", self.system_func.exitProgram)
        self.win.mainloop()
        
    def gui_exit(self):
        self.system_func.AllStop()
        self.system_func.exitProgram()
        self.win.destroy()
        
    def get_filename_val(self):
        return self.fname.get()
    
    def start_timer(self):
        self.timer_running = True
        threading.Thread(target=self.update_timer).start()
        
    def stop_timer(self):
        self.timer_running = False
        self.seconds = 0
        
    def update_timer(self):
        if self.timer_running:
            self.seconds +=1
            minutes, seconds = divmod(self.seconds, 60)
            self.label13.config(text=f'{minutes:02d}:{seconds:02d}')
            self.win.after(1000, self.update_timer)
    
    def scan_started(self):
        if self.label9.cget("text") == str("Not_Home"):
            messagebox.showerror("Error", "Home Pos not yet Completed")
            return
        
        if self.label22.cget("text") == str("Not Calibrated"):
            messagebox.showerror("Error", "Calibration not yet Completed")
            return
        
        # Check if X/Y offsets are zero - prevent scanning
        if StatusDataClass.x_offset == 0 and StatusDataClass.y_offset == 0:
            messagebox.showerror("Error", "X/Y Offsets Not Set!\n\nPlease:\n1. Click 'Move to Scanning Pos'\n2. Use arrow buttons to center particle\n3. Try scanning again")
            return
        
        if self.label11.cget("text") != str("Home"):
            return
        
        self.scan.config(state='disabled')
        threading.Thread(target=self.scan_start).start()
    
    def scan_start(self):

        fn = self.fname.get()

        if fn == "":
            messagebox.showerror("Error", "No filename")
            self.scan.config(state='normal')
            return

        StatusDataClass.fn = self.get_filename_val()
        StatusDataClass.ScanHt = int(float(self.label25.cget("text")) * 10) * 39
        
        file_name = '/home/pi/scanning_results/' + StatusDataClass.fn + '.csv'
        f = open(file_name, 'w', newline='')
        c = csv.writer(f)

        Header = ('Scan_area', 'Scan_Pitch', 'Voltage')
        c.writerow(Header)
        
        self.label11["text"] = "Scanning"
        self.started_flashing()
        
        # Disable scan setting buttons during scanning
        self.scan_area_minus.config(state='disabled')
        self.scan_area_plus.config(state='disabled')
        self.res_100.config(state='disabled')
        self.res_150.config(state='disabled')
        self.res_200.config(state='disabled')        
        if self.condition == 1:
            self.start_timer()
            self.data_scan.ScanRoutine(c, fn)
            if self.xy_move.EMGSwitch():
                self.system_func.AllStop()
                self.scan.config(state='normal')
                self.label9["text"] = "Not_Home"
                self.label9["bg"] = "red"
                sys.tracebacklimit = 0
                raise ValueError()
        
        if self.condition == 2:
            while not SystemFuncClass.stop_flag:  # Stop when STOP button is pressed
                StatusDataClass.ScanHt = int(float(self.label25.cget("text")) * 10) * 39
                self.start_timer()
                self.data_scan.ScanRoutine(c, fn)                  
        
                if self.xy_move.EMGSwitch():
                    self.system_func.AllStop()
                    self.scan.config(state='normal')
                    self.label9["text"] = "Not_Home"
                    self.label9["bg"] = "red"
                    f.close()
                    sys.tracebacklimit = 0
                    raise ValueError()

                self.stop_timer()
                self.wait = timeit.default_timer()
                self.wt = 0

                while self.wt < 10 and not SystemFuncClass.stop_flag:
                    self.wt = timeit.default_timer() - self.wait
                    if self.xy_move.EMGSwitch():
                        self.system_func.AllStop()
                        self.scan.config(state='normal')
                        self.label9["text"] = "Not_Home"
                        self.label9["bg"] = "red"
                        sys.tracebacklimit = 0
                        raise ValueError()
        
        f.close()
        self.stop_timer()
        if self.fname.get() != "Demo":
            self.fname.delete(0, "end")
        if not SystemFuncClass.stop_flag:
            if self.label11.cget("text") != "STOPPED":
                self.label11["text"] = "Home"
        self.scan.config(state='normal')
        self.stopped_flashing()
        
        # Re-enable scan setting buttons after scanning
        self.scan_area_minus.config(state='normal')
        self.scan_area_plus.config(state='normal')
        self.res_100.config(state='normal')
        self.res_150.config(state='normal')
        self.res_200.config(state='normal')        
        # Re-enable scanning distance buttons after scanning
        self.up_button.config(state='normal')
        self.down_button.config(state='normal')
    
    def init_offset_data(self):
        # Read offsets from file and populate StatusDataClass
        try:
            f = open('/home/pi/Desktop/migne/offset.txt', 'r')
            offset_data  = f.readlines()
            offset_data  = offset_data[0].split(',')
            f.close()
        except Exception as e:
            offset_data = ['0','0','0','0','0','0']
            print("offset.txt read failed, defaulting offsets:", e)
        
        # Save into StatusDataClass
        try:
            StatusDataClass.x_offset = int(offset_data[0])
            StatusDataClass.y_offset = int(offset_data[1])
            StatusDataClass.z_offset = int(offset_data[2])
            StatusDataClass.xcal_offset = int(offset_data[3])
            StatusDataClass.ycal_offset = int(offset_data[4])
            StatusDataClass.ZOffset = int(offset_data[5])
        except Exception:
            # if parsing fails, default to zeros
            StatusDataClass.x_offset = 0
            StatusDataClass.y_offset = 0
            StatusDataClass.z_offset = 0
            StatusDataClass.xcal_offset = 0
            StatusDataClass.ycal_offset = 0
            StatusDataClass.ZOffset = 0

        # Update calibrate button text (shows z-height)
        self.calib_btn_var.set(f"Calibrate Z-Height\nZ-Ht: {StatusDataClass.z_offset}")
        # Update ZOffset label
        self.label28["text"] = StatusDataClass.ZOffset

        # Show Not_Home/Not Calibrated as initial state
        self.label9["text"] = "Not_Home"
        self.label9["bg"] = "red"
        self.label22["text"] = "Not Calibrated"
        self.label22["bg"] = "red"

        # Refresh the contextual X/Y display (defaults to scan offsets)
        self.refresh_offset_display()
        
        # Offset entries will be shown/updated by refresh_offset_display() on startup
    
    def started_homing(self):
        if not self.check_door_before_action("Home"):
            return
        if self.label11.cget("text") in ["Scanning","Going to ScanPos","Unloading"]:
            return
        self.HomeButton.config(state='disabled')
        threading.Thread(target=self.goto_home).start()

    def goto_home(self):
        
        self.label11["text"] = "Homing"
        self.started_flashing()
        # Hide offsets during homing
        self.refresh_offset_display()
        
        self.home.Home()
        self.HomeButton.config(state='normal')
        if self.xy_move.EMGSwitch():
            self.system_func.AllStop()
            self.label9["text"] = "Not_Home"
            self.label9["bg"] = "red"
            sys.tracebacklimit = 0
            raise ValueError()
        if not SystemFuncClass.stop_flag:
            self.label9["text"] = "OK"
            self.label9["bg"] = "green"
            self.label11["text"] = "Home"
        self.stopped_flashing()
        # Keep offsets hidden at Home position
        self.refresh_offset_display()

    def goingto_scanpos(self):
        if not self.check_door_before_action("Move to Scanning Position"):
            return
        if self.label9.cget("text") == "Not_Home":
            messagebox.showerror("Error", "Home Pos not yet Completed")
            self.MoveScanButton.config(state='normal')
            return
        if self.label22.cget("text") != "Calibrated":
            messagebox.showerror("Error", "Calibration not yet Completed")
            return
        if self.label11.cget("text") != "Home":
            return
        self.MoveScanButton.config(state='disabled')
        StatusDataClass.ScanHt = int(float(self.label25.cget("text")) * 10) * 39
        threading.Thread(target=self.goto_scanpos).start()

    def goto_scanpos(self):
        
        self.label11["text"] = "Going to ScanPos"
        self.started_flashing()
        # Hide offsets while moving to scan position
        self.refresh_offset_display()
        
        self.data_scan.ScanPos()
        if self.xy_move.EMGSwitch():
            self.system_func.AllStop()
            self.label9["text"] = "Not_Home"
            self.label9["bg"] = "red"
            sys.tracebacklimit = 0
            raise ValueError()
        self.stopped_flashing()
        self.MoveScanButton.config(state='normal')
        self.label11["text"] = "Scan Pos"
        # Refresh display to show scan offsets in the right-side labels
        self.refresh_offset_display()
        
    def goingto_unloadpos(self):
        if not self.check_door_before_action("Unload"):
            return
        if self.label11.cget("text") in ["Scan Pos","STOPPED"]:
            self.UnloadButton.config(state='disabled')
            threading.Thread(target=self.goto_unloadpos).start()
        else:
            messagebox.showerror("Error", "Please perform Home Position")
            self.UnloadButton.config(state='normal')

    def goto_unloadpos(self):
        # Store label value before modifying it
        previous_label = self.label11.cget("text")

        # Change the label to "Unloading"
        self.label11["text"] = "Unloading"
        self.started_flashing()
        # Hide offsets during unloading
        self.refresh_offset_display()

        # Now check the previous label value instead of the current one
        if previous_label == "Scan Pos":
            self.data_scan.UnloadPos()
        elif previous_label == "STOPPED" and self.fname.get() == "Demo":
            self.home.Home()
        else:
            self.data_scan.UnloadPos_stopped()

        # Emergency Stop Check
        if self.xy_move.EMGSwitch():
            self.system_func.AllStop()
            self.label9["text"] = "Not_Home"
            self.label9["bg"] = "red"
            sys.tracebacklimit = 0
            raise ValueError()

        # Stop UI Flashing and Enable Controls
        self.stopped_flashing()
        self.UnloadButton.config(state='normal')
        self.label11["text"] = "Home"
        # Keep offsets hidden at Home position
        self.refresh_offset_display()

    def goingto_calpos(self):
        if not self.check_door_before_action("Goto Z-Height Calibration Position"):
            return
        if self.label9.cget("text") == "Not_Home":
            messagebox.showerror("Error", "Home Pos not yet Completed")
            self.MoveScanButton.config(state='normal')
            return
        if self.label11.cget("text") != "Home":
            return
        self.MoveCalibButton.config(state='disabled')
        threading.Thread(target=self.goto_calpos).start()

    def goto_calpos(self):
        self.label11["text"] = "Going to CalPos"
        self.started_flashing()
        # Hide offsets while moving to calibration position
        self.refresh_offset_display()
        
        self.data_scan.ZHtCalibPos()
        if self.xy_move.EMGSwitch():
            self.system_func.AllStop()
            self.label9["text"] = "Not_Home"
            self.label9["bg"] = "red"
            sys.tracebacklimit = 0
            raise ValueError()
        self.stopped_flashing()
        self.MoveCalibButton.config(state='normal')
        self.label11["text"] = "Calibration Pos"
        # Refresh display to show calibration offsets in the right-side labels
        self.refresh_offset_display()
        
    def starting_calib(self):
        if not self.check_door_before_action("Calibrate Z-Height"):
            return
        if self.label9.cget("text") == "Not_Home":
            messagebox.showerror("Error", "Home Pos not yet Completed")
            return
        if self.label11.cget("text") != "Home":
            return
        self.CalibrateButton.config(state='disabled')
        threading.Thread(target=self.start_calib).start()     
        
    def start_calib(self):
        self.label11["text"] = "Calibrating"
        self.started_flashing()
        # Hide offsets during calibration
        self.refresh_offset_display()
        
        self.data_scan.GoCalib()
        StatusDataClass.z_offset = StatusDataClass.zcal_offset
        # update calibrate button text with new z_offset
        self.calib_btn_var.set(f"Calibrate Z-Height\nZ-Ht: {StatusDataClass.z_offset}")
        self.update_offset_label()
        self.update_offset_file()
        self.stopped_flashing()
        self.CalibrateButton.config(state='normal')
        if not SystemFuncClass.stop_flag:
            self.label22["text"] = "Calibrated"
            self.label11["text"] = "Home"
            self.label22["bg"] = "green"
            # Keep offsets hidden at Home position after calibration
            self.refresh_offset_display()

    def update_offset_file(self):
        # Write offsets from StatusDataClass in same order as previous file format
        try:
            f = open('/home/pi/Desktop/migne/offset.txt', 'w+')
            f.write(f'{StatusDataClass.x_offset},{StatusDataClass.y_offset},{StatusDataClass.z_offset},{StatusDataClass.xcal_offset},{StatusDataClass.ycal_offset},{StatusDataClass.ZOffset}')
            f.close()
        except Exception as e:
            print("Failed to write offset file:", e)

    def update_offset_label(self):
        # Update labels based on the StatusDataClass values. The X/Y right-side labels are context-sensitive
        # Update calibrate button text instead of a separate label
        self.calib_btn_var.set(f"Calibrate Z-Height\nZ-Ht: {StatusDataClass.z_offset}")
        self.label28["text"] = StatusDataClass.ZOffset
        # Refresh the context-sensitive X/Y display
        self.refresh_offset_display()
        # Persist offsets
        self.update_offset_file()
    


    def refresh_offset_display(self):
        # Always update left-side static labels for Scan and Calibration offsets
        try:
            self.label_x_val.config(text=str(StatusDataClass.x_offset))
            self.label_y_val.config(text=str(StatusDataClass.y_offset))
            self.label_cal_x_val.config(text=str(StatusDataClass.xcal_offset))
            self.label_cal_y_val.config(text=str(StatusDataClass.ycal_offset))
        except Exception:
            passca

        # Update right-side contextual display (Scan/Calibration or ---)
        pos = self.label11.cget("text")
        if pos == "Calibration Pos":
            self.label4["text"] = StatusDataClass.xcal_offset
            self.label5["text"] = StatusDataClass.ycal_offset
        elif pos == "Scan Pos":
            self.label4["text"] = StatusDataClass.x_offset
            self.label5["text"] = StatusDataClass.y_offset
        else:
            self.label4["text"] = "---"
            self.label5["text"] = "---"

    def ZHtDownPosOffset(self):
        
        if self.label11.cget("text") != str("Scan Pos"):
            messagebox.showerror("Error", "Go to Scan Position first")
            return
        
        if self.mov == 1:
            self.z_move.ZmoveCorrect(-1)
            StatusDataClass.ZOffset -= 1
            
        if self.mov == 2:
            self.z_move.ZmoveCorrect(-10)
            StatusDataClass.ZOffset -= 10
            
        if self.mov == 3:
            self.z_move.ZmoveCorrect(-100)
            StatusDataClass.ZOffset -= 100        
        
        self.update_offset_label()
        
    def ZHtUpPosOffset(self):
        
        if self.label11.cget("text") != str("Scan Pos"):
            messagebox.showerror("Error", "Go to Scan Position first")
            return
        
        if self.mov == 1:
            self.z_move.ZmoveCorrect(1)
            StatusDataClass.ZOffset += 1
            
        if self.mov == 2:
            self.z_move.ZmoveCorrect(10)
            StatusDataClass.ZOffset += 10

        if self.mov == 3:
            self.z_move.ZmoveCorrect(100)
            StatusDataClass.ZOffset += 100   
        
        self.update_offset_label()

    def start_continuous_move(self, axis, direction):
        """Start continuous movement when button is held down"""
        current_pos = self.label11.cget("text")
        
        if current_pos not in ["Scan Pos", "Calibration Pos"]:
            messagebox.showerror("Error", "Go to Scan Position or Calibration Position first")
            return
        
        self.continuous_move_active = True
        self.continuous_move_axis = axis
        self.continuous_move_direction = direction
        self.continuous_move_pos = current_pos
        
        # Start the continuous move loop
        self.do_continuous_move()
    
    def stop_continuous_move(self):
        """Stop continuous movement when button is released"""
        self.continuous_move_active = False
    
    def do_continuous_move(self):
        """Perform one step of continuous movement"""
        if not self.continuous_move_active:
            return
        
        try:
            # Determine step size based on X/Y calibration speed setting (separate from Z-height speed)
            if self.xy_mov == 1:  # Low
                step_size = 1
            elif self.xy_mov == 2:  # Medium
                step_size = 10
            else:  # Fallback to Low
                step_size = 1
            
            # Calculate actual movement
            move_amount = step_size * self.continuous_move_direction
            
            # Move by step_size in the specified direction
            if self.continuous_move_axis == 'X':
                self.xy_move.XmoveCorrect(move_amount)
                if self.continuous_move_pos == "Scan Pos":
                    StatusDataClass.x_offset += move_amount
                else:
                    StatusDataClass.xcal_offset += move_amount
            else:  # Y axis
                self.xy_move.YmoveCorrect2(move_amount)
                if self.continuous_move_pos == "Scan Pos":
                    StatusDataClass.y_offset += move_amount
                else:
                    StatusDataClass.ycal_offset += move_amount
            
            # Update the display
            self.update_offset_label()
            
            # Schedule next move with appropriate delay based on speed
            # Low speed: 100ms delay (10 steps/sec), Medium speed: 50ms delay (20 steps/sec)
            delay = 100 if self.xy_mov == 1 else 100
            if self.continuous_move_active:
                self.win.after(delay, self.do_continuous_move)
                
        except Exception as e:
            print(f"Error during continuous move: {e}")
            self.continuous_move_active = False
        
    # left-side calibration-specific move functions removed (not used anymore)

    def ClearOffset(self):
        
        reset = messagebox.askokcancel("Confirmation","Are you sure you want to clear all the offset?")
        if reset == True:
            StatusDataClass.x_offset = 0
            StatusDataClass.y_offset = 0
            StatusDataClass.z_offset = 0
            StatusDataClass.xcal_offset = 0
            StatusDataClass.ycal_offset = 0
            StatusDataClass.ZOffset = 0
            self.update_offset_label()
        else:
            return
    
    # Scan area control methods
    def increase_scan_area(self):
        if StatusDataClass.roughness < 50:  # Max 40mm
            StatusDataClass.roughness += 5
            self.scan_area_value.config(text=str(StatusDataClass.roughness))
            self.update_grid_display()
    
    def decrease_scan_area(self):
        if StatusDataClass.roughness > 20:  # Min 20mm
            StatusDataClass.roughness -= 5
            self.scan_area_value.config(text=str(StatusDataClass.roughness))
            self.update_grid_display()
    def set_resolution(self, value):
        if value == 1:  # 100x100 = 10,000 points
            StatusDataClass.resolution = 10000
            StatusDataClass.xdensity = 100
            StatusDataClass.ydensity = 100
        elif value == 2:  # 150x150 = 22,500 points
            StatusDataClass.resolution = 22500
            StatusDataClass.xdensity = 150
            StatusDataClass.ydensity = 150
        elif value == 3:  # 200x200 = 40,000 points
            StatusDataClass.resolution = 40000
            StatusDataClass.xdensity = 200
            StatusDataClass.ydensity = 200
        self.update_grid_display()
    
    def update_grid_display(self):
        self.label_grid_info.config(text=f'{StatusDataClass.roughness}mm | {StatusDataClass.xdensity}x{StatusDataClass.ydensity} ({StatusDataClass.resolution:,} pts)')

if __name__ == '__main__':
    main()

