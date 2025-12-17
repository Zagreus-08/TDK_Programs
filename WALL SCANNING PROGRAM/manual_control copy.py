#!/usr/bin/env python3
"""
Manual Wall Scanner Control with GUI
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
Run with: sudo python3 manual_control.py
"""

import time
import threading
import tkinter as tk
from tkinter import ttk
import pigpio

# ----- Configuration -----
# Motor pins
DIR1 = 24 # 24
STEP1 = 25 #25
DIR2 = 18 #18
STEP2 = 23 #23

# Limit switch pins
LIMIT_UP = 17   # X positive limit
LIMIT_DOWN = 19   # X negative limit
LIMIT_LEFT = 14      # Y positive limit
LIMIT_RIGHT = 15    # Y negative limit

# Motor speed (PWM frequency in Hz)
MOTOR_SPEED = 500  # Adjust this for faster/slower movement
# --------------------------

# Initialize pigpio
pi = pigpio.pi()

class WallScannerController:
    def __init__(self):
        self.running = False
        self.movement_thread = None
        self.current_direction = None
        
        # Setup limit switch pins with pull-down (pressed = HIGH)
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
    
    def start_motors(self):
        """Start PWM on both motor step pins"""
        pi.set_PWM_frequency(STEP1, MOTOR_SPEED)
        pi.set_PWM_frequency(STEP2, MOTOR_SPEED)
        pi.set_PWM_dutycycle(STEP1, 128)  # 50% duty cycle
        pi.set_PWM_dutycycle(STEP2, 128)
    
    def stop_motors(self):
        """Stop PWM on both motor step pins"""
        pi.set_PWM_dutycycle(STEP1, 0)
        pi.set_PWM_dutycycle(STEP2, 0)
        pi.write(DIR1,0)
        pi.write(DIR2,0)
    
    def start_movement(self, direction):
        """Start continuous movement in specified direction"""
        # Stop any existing movement first
        if self.running:
            self.stop_movement()
            time.sleep(0.1)  # Brief pause to ensure clean stop
        
        self.running = True
        self.current_direction = direction
        self.movement_thread = threading.Thread(target=self._movement_loop, args=(direction,))
        self.movement_thread.daemon = True
        self.movement_thread.start()
        print(f"Started moving {direction}")
    
    def stop_movement(self):
        """Stop continuous movement"""
        self.stop_motors()
        self.running = False
        if self.movement_thread and self.movement_thread.is_alive():
            self.movement_thread.join(timeout=0.5)
        self.current_direction = None
        print("Movement stopped")
    
    def _movement_loop(self, direction):
        """Continuous PWM-based movement loop"""
        # Determine motor directions based on movement direction
        # NOTE: logical button directions are mapped to physical movements
        # to match limit-switch orientation (UP checks LIMIT_LEFT etc.).
        if direction == "UP":
            # Move RIGHT (X+) because UP is wired to LIMIT_LEFT (X+)
            dir1, dir2 = 0, 0
        elif direction == "DOWN":
            # Move LEFT (X-) because DOWN is wired to LIMIT_RIGHT (X-)
            dir1, dir2 = 1, 1
        elif direction == "LEFT":
            # Move UP (Y+) because LEFT is wired to LIMIT_UP (Y+)
            dir1, dir2 = 0, 1
        elif direction == "RIGHT":
            # Move DOWN (Y-) because RIGHT is wired to LIMIT_DOWN (Y-)
            dir1, dir2 = 1, 0
        else:
            return
        
        # Set direction and start motors
        self.set_motor_direction(dir1, dir2)
        time.sleep(0.001)  # Brief settle time
        self.start_motors()
        
        # Keep motors running while button is held and limit not reached
        while self.running:
            if self.check_limit_switch(direction):
                print(f"{direction} limit reached!")
                self.running = False
                self.stop_motors()
                break
            time.sleep(0.01)  # Check limit every 10ms
        
        # Stop motors when done       self.stop_motors()
    
    def cleanup(self):
        """Cleanup GPIO"""
        self.stop_motors()
        pi.stop()


class ControlGUI:
    def __init__(self, root, controller):
        self.root = root
        self.controller = controller
        
        self.root.title("Wall Scanner Manual Control")
        self.root.geometry("400x500")
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
        
        # Update limit switch status periodically
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
        """Handle button press event"""
        print(f"Button pressed: {direction}")
        self.status_label.config(text=f"Moving {direction}")
        self.controller.start_movement(direction)
    
    def on_button_release(self):
        """Handle button release event"""
        print("Button released")
        self.status_label.config(text="Ready")
        self.controller.stop_movement()
        pi.write(DIR1,0)
        pi.write(DIR2,0)

        
    def update_limit_status(self):
        """Update limit switch status display"""
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
    
    def on_closing(self):
        """Handle window closing"""
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


