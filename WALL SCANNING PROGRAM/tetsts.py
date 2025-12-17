#!/usr/bin/env python3
"""
Manual Wall Scanner Control with GUI + Homing
Motor 1: DIR = BCM 24, STEP = BCM 25
Motor 2: DIR = BCM 18, STEP = BCM 23

Movement Pattern (continuous PWM-based):
- UP (Y+): DIR1=0, DIR2=1
- DOWN (Y-): DIR1=1, DIR2=0
- LEFT (X-): DIR1=0, DIR2=0
- RIGHT (X+): DIR1=1, DIR2=1

Limit Switches:
- GPIO 14: Left limit (X positive)
- GPIO 15: Right limit (X negative)
- GPIO 17: Up limit (Y positive)
- GPIO 19: Down limit (Y negative)

Homing Sequence:
- Move RIGHT until limit
- Step back
- Move DOWN until limit
- Step back → HOME position

Run with: sudo python3 manual_control.py
"""

import time
import threading
import tkinter as tk
from tkinter import ttk
import pigpio

# ----- Configuration -----
# Motor pins
DIR1 = 24
STEP1 = 25
DIR2 = 18
STEP2 = 23

# Limit switch pins
LIMIT_UP = 17   # Y positive
LIMIT_DOWN = 19 # Y negative
LIMIT_LEFT = 14 # X positive
LIMIT_RIGHT = 15 # X negative

# Motor speed (PWM frequency in Hz)
MOTOR_SPEED1 = 1000
MOTOR_SPEED2 = 1000

# Homing config
HOMING_SPEED = 600
HOMING_TIMEOUT = 30  # max seconds to home before timeout
STEP_BACK_TIME = 0.45   # seconds for stepping back
PHASE_SETTLE_TIME = 3.0 # seconds to settle between phases
# --------------------------

# Initialize pigpio
pi = pigpio.pi()


class WallScannerController:
    def __init__(self):
        self.running = False
        self.movement_thread = None
        self.current_direction = None
        
        # Setup limit switch pins with pull-up (pressed = LOW)
        for pin in (LIMIT_LEFT, LIMIT_RIGHT, LIMIT_UP, LIMIT_DOWN):
            pi.set_mode(pin, pigpio.INPUT)
            pi.set_pull_up_down(pin, pigpio.PUD_UP)
    
    def check_limit_switch(self, direction):
        """Check if limit switch is triggered for given direction"""
        if direction == "UP":
            return pi.read(LIMIT_UP) == 0
        elif direction == "DOWN":
            return pi.read(LIMIT_DOWN) == 0
        elif direction == "LEFT":
            return pi.read(LIMIT_LEFT) == 0
        elif direction == "RIGHT":
            return pi.read(LIMIT_RIGHT) == 0
        return False
    
    def set_motor_direction(self, dir1, dir2):
        """Set direction pins for both motors"""
        pi.write(DIR1, dir1)
        pi.write(DIR2, dir2)
    
    def start_motors(self, speed1=MOTOR_SPEED1, speed2=MOTOR_SPEED2):
        """Start PWM on both motor step pins"""
        pi.set_PWM_frequency(STEP1, speed1)
        pi.set_PWM_frequency(STEP2, speed2)
        pi.set_PWM_dutycycle(STEP1, 128)  # 50% duty cycle
        pi.set_PWM_dutycycle(STEP2, 128)
    
    def stop_motors(self):
        """Stop PWM on both motor step pins"""
        pi.set_PWM_dutycycle(STEP1, 0)
        pi.set_PWM_dutycycle(STEP2, 0)
        pi.write(DIR1,0)
        pi.write(DIR2,0)
    
    def start_movement(self, direction, duration=None):
        """Start continuous movement in specified direction
        Args:
            direction: "UP", "DOWN", "LEFT", "RIGHT"
            duration: time in seconds to move. If None, moves until stopped
        """
        if self.running:
            self.stop_movement()
            time.sleep(0.05)
        
        self.running = True
        self.current_direction = direction
        self.movement_thread = threading.Thread(target=self._movement_loop, args=(direction, duration))
        self.movement_thread.daemon = True
        self.movement_thread.start()
        print(f"Started moving {direction}" + (f" for {duration}s" if duration else ""))
    
    def stop_movement(self):
        """Stop continuous movement"""
        self.stop_motors()
        self.running = False
        if self.movement_thread and self.movement_thread.is_alive():
            self.movement_thread.join(timeout=0.5)
        self.current_direction = None
        print("Movement stopped")
    
    def _movement_loop(self, direction, duration=None):
        """Continuous PWM-based movement loop with optional time control
        Args:
            direction: Movement direction
            duration: Optional - time in seconds to move before stopping
        """
        if direction == "UP":
            dir1, dir2 = 0, 0
        elif direction == "DOWN":
            dir1, dir2 = 1, 1
        elif direction == "LEFT":
            dir1, dir2 = 0, 1
        elif direction == "RIGHT":
            dir1, dir2 = 1, 0
        else:
            return
        
        self.set_motor_direction(dir1, dir2)
        time.sleep(0.001)
        self.start_motors()
        
        start_time = time.time()
        
        while self.running:
            # Check time limit if duration specified
            if duration is not None:
                elapsed = time.time() - start_time
                if elapsed >= duration:
                    print(f"{direction} movement time ({duration}s) reached")
                    self.running = False
                    self.stop_motors()
                    break
            
            # Check limit switches
            if self.check_limit_switch(direction):
                print(f"{direction} limit reached!")
                self.running = False
                self.stop_motors()
                break
            time.sleep(0.01)
    
    def pulse_step(self, dir1, dir2, duration):
        """Move a short distance (step back)"""
        self.set_motor_direction(dir1, dir2)
        pi.set_PWM_frequency(STEP1, HOMING_SPEED)
        pi.set_PWM_frequency(STEP2, HOMING_SPEED)
        pi.set_PWM_dutycycle(STEP1, 128)
        pi.set_PWM_dutycycle(STEP2, 128)
        time.sleep(duration)
        self.stop_motors()

    def home_sequence(self):
        """Run homing sequence with time control: LEFT (X-) → DOWN (Y-)"""
        if self.running:
            return

        self.running = True
        print(" Starting homing sequence")

        # ---- PHASE 1: HOME X (move LEFT/X- to LIMIT_RIGHT) ----
        print(" Phase 1: Moving LEFT (X-) to LIMIT_RIGHT...")
        self.set_motor_direction(0, 0)  # LEFT (X-)
        self.start_motors(HOMING_SPEED, HOMING_SPEED)
        
        phase1_start = time.time()
        while pi.read(LIMIT_RIGHT) == 1:  # Wait for LIMIT_RIGHT (X-) to trigger
            # Timeout check
            if time.time() - phase1_start > HOMING_TIMEOUT:
                print(" ERROR: Phase 1 timeout!")
                break
            time.sleep(0.01)
        
        print(" LIMIT_RIGHT reached. Stopping motor...")
        self.stop_motors()
        pi.set_PWM_dutycycle(STEP1, 0)
        pi.set_PWM_dutycycle(STEP2, 0)
        time.sleep(0.5)  # Ensure motor stops completely
        
        # Step back RIGHT (X+) with time control
        print(f" Stepping back RIGHT for {STEP_BACK_TIME}s...")
        self.pulse_step(1, 1, STEP_BACK_TIME)
        time.sleep(PHASE_SETTLE_TIME)  # Let limit fully release
        print(" Stepped back from LIMIT_RIGHT")
        
        # Reset direction
        self.set_motor_direction(0, 0)
        time.sleep(PHASE_SETTLE_TIME)  # Settle before next phase

        # ---- PHASE 2: HOME Y (move DOWN/Y- to LIMIT_DOWN) ----
        print(" Phase 2: Moving DOWN (Y-) to LIMIT_DOWN...")
        self.set_motor_direction(1, 0)  # DOWN (Y-)
        self.start_motors(HOMING_SPEED, HOMING_SPEED)
        
        phase2_start = time.time()
        while pi.read(LIMIT_DOWN) == 1:  # Wait for LIMIT_DOWN (Y-) to trigger
            # Timeout check
            if time.time() - phase2_start > HOMING_TIMEOUT:
                print(" ERROR: Phase 2 timeout!")
                break
            time.sleep(0.01)
        
        print(" LIMIT_DOWN reached. Stopping motor...")
        self.stop_motors()
        pi.set_PWM_dutycycle(STEP1, 0)
        pi.set_PWM_dutycycle(STEP2, 0)
        time.sleep(0.5)  # Ensure motor stops completely
        
        # Step back UP (Y+) with time control
        print(f" Stepping back UP for {STEP_BACK_TIME}s...")
        self.pulse_step(0, 1, STEP_BACK_TIME)
        time.sleep(PHASE_SETTLE_TIME)  # Let limit fully release
        print(" Stepped back from LIMIT_DOWN")
        
        # Reset direction
        self.set_motor_direction(0, 0)
        time.sleep(PHASE_SETTLE_TIME)  # Final settling time

        self.running = False
        print(" Homing complete (HOME position)")
    
    def cleanup(self):
        """Cleanup GPIO"""
        self.stop_motors()
        pi.stop()


class ControlGUI:
    def __init__(self, root, controller):
        self.root = root
        self.controller = controller
        
        self.root.title("Wall Scanner Manual Control")
        self.root.geometry("400x550")
        self.root.configure(bg="#2b2b2b")
        
        # Title
        title = tk.Label(root, text="Wall Scanner Control", 
                        font=("Arial", 20, "bold"), 
                        bg="#2b2b2b", fg="white")
        title.pack(pady=20)
        
        # Control frame
        control_frame = tk.Frame(root, bg="#2b2b2b")
        control_frame.pack(pady=30)
        
        # Button style
        btn_style = {
            "font": ("Arial", 14, "bold"),
            "width": 8,
            "height": 2,
            "bg": "#4CAF50",
            "fg": "white",
            "activebackground": "#45a049",
            "relief": "raised",
            "bd": 3
        }
        
        # UP button
        self.btn_up = tk.Button(control_frame, text="▲\nUP", **btn_style)
        self.btn_up.grid(row=0, column=1, padx=10, pady=10)
        self.btn_up.bind("<ButtonPress-1>", lambda e: self.on_button_press("UP"))
        self.btn_up.bind("<ButtonRelease-1>", lambda e: self.on_button_release())
        
        # LEFT button
        self.btn_left = tk.Button(control_frame, text="◄\nLEFT", **btn_style)
        self.btn_left.grid(row=1, column=0, padx=10, pady=10)
        self.btn_left.bind("<ButtonPress-1>", lambda e: self.on_button_press("LEFT"))
        self.btn_left.bind("<ButtonRelease-1>", lambda e: self.on_button_release())
        
        # CENTER (stop indicator)
        center_label = tk.Label(control_frame, text="●", 
                               font=("Arial", 30), 
                               bg="#2b2b2b", fg="#888")
        center_label.grid(row=1, column=1, padx=10, pady=10)
        
        # RIGHT button
        self.btn_right = tk.Button(control_frame, text="►\nRIGHT", **btn_style)
        self.btn_right.grid(row=1, column=2, padx=10, pady=10)
        self.btn_right.bind("<ButtonPress-1>", lambda e: self.on_button_press("RIGHT"))
        self.btn_right.bind("<ButtonRelease-1>", lambda e: self.on_button_release())
        
        # DOWN button
        self.btn_down = tk.Button(control_frame, text="▼\nDOWN", **btn_style)
        self.btn_down.grid(row=2, column=1, padx=10, pady=10)
        self.btn_down.bind("<ButtonPress-1>", lambda e: self.on_button_press("DOWN"))
        self.btn_down.bind("<ButtonRelease-1>", lambda e: self.on_button_release())
        
        # HOME button
        home_btn = tk.Button(
            root,
            text="🏠 HOME",
            font=("Arial", 14, "bold"),
            bg="#2196F3",
            fg="white",
            width=15,
            height=2,
            command=self.start_homing
        )
        home_btn.pack(pady=10)
        
        # Keyboard bindings
        self.root.bind("<Up>", lambda e: self.controller.start_movement("UP"))
        self.root.bind("<Down>", lambda e: self.controller.start_movement("DOWN"))
        self.root.bind("<Left>", lambda e: self.controller.start_movement("LEFT"))
        self.root.bind("<Right>", lambda e: self.controller.start_movement("RIGHT"))
        
        self.root.bind("<KeyRelease-Up>", lambda e: self.controller.stop_movement())
        self.root.bind("<KeyRelease-Down>", lambda e: self.controller.stop_movement())
        self.root.bind("<KeyRelease-Left>", lambda e: self.controller.stop_movement())
        self.root.bind("<KeyRelease-Right>", lambda e: self.controller.stop_movement())
        
        # Status label
        self.status_label = tk.Label(root, text="Ready", 
                                     font=("Arial", 12), 
                                     bg="#2b2b2b", fg="#4CAF50")
        self.status_label.pack(pady=20)
        
        # Limit switch status
        limit_frame = tk.Frame(root, bg="#2b2b2b")
        limit_frame.pack(pady=10)
        
        tk.Label(limit_frame, text="Limit Switches:", 
                font=("Arial", 10, "bold"), 
                bg="#2b2b2b", fg="white").pack()
        
        self.limit_status = tk.Label(limit_frame, text="", 
                                     font=("Arial", 9), 
                                     bg="#2b2b2b", fg="#888")
        self.limit_status.pack()
        
        self.update_limit_status()
        
        # Exit button
        exit_btn = tk.Button(root, text="EXIT", 
                           font=("Arial", 12, "bold"),
                           bg="#f44336", fg="white",
                           command=self.on_closing,
                           width=15, height=2)
        exit_btn.pack(pady=20)
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def on_button_press(self, direction):
        print(f"Button pressed: {direction}")
        self.status_label.config(text=f"Moving {direction}")
        self.controller.start_movement(direction)
    
    def on_button_release(self):
        print("Button released")
        self.status_label.config(text="Ready")
        self.controller.stop_movement()
        pi.write(DIR1,0)
        pi.write(DIR2,0)

    def update_limit_status(self):
        limits = []
        try:
            if pi.read(LIMIT_UP) == 0:
                limits.append("UP")
            if pi.read(LIMIT_DOWN) == 0:
                limits.append("DOWN")
            if pi.read(LIMIT_LEFT) == 0:
                limits.append("LEFT")
            if pi.read(LIMIT_RIGHT) == 0:
                limits.append("RIGHT")
        except Exception as e:
            print(f"Error reading limits: {e}")
        
        if limits:
            self.limit_status.config(text=f"Active: {', '.join(limits)}", fg="#ff9800")
        else:
            self.limit_status.config(text="All Clear", fg="#4CAF50")
        
        self.root.after(100, self.update_limit_status)
    
    def start_homing(self):
        if self.controller.running:
            return
        self.status_label.config(text="Homing...")
        threading.Thread(target=self._run_home, daemon=True).start()

    def _run_home(self):
        self.controller.home_sequence()
        self.status_label.config(text="Home Position Reached")
    
    def on_closing(self):
        self.controller.stop_movement()
        self.controller.cleanup()
        self.root.destroy()


if __name__ == "__main__":
    try:
        controller = WallScannerController()
        root = tk.Tk()
        gui = ControlGUI(root, controller)
        root.mainloop()
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        try:
            controller.cleanup()
        except:
            pass
        print("Program ended.")
