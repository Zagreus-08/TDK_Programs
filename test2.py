import tkinter as tk
from tkinter import messagebox
import RPi.GPIO as GPIO
import time
import threading
import os

# ---------------- GPIO Setup ----------------
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

OUTPUT_Y0 = 14      # Solenoid locker (energize to lock)
GREEN_LIGHT = 15
RED_LIGHT = 17
ORANGE_LIGHT = 18
EMERGENCY_STOP_GPIO = 25
BUZZER_PIN = 23

GPIO.setup(OUTPUT_Y0, GPIO.OUT)
GPIO.setup(GREEN_LIGHT, GPIO.OUT)
GPIO.setup(RED_LIGHT, GPIO.OUT)
GPIO.setup(ORANGE_LIGHT, GPIO.OUT)
GPIO.setup(BUZZER_PIN, GPIO.OUT)
GPIO.output(BUZZER_PIN, GPIO.LOW)   # ensure buzzer is off on program start
GPIO.setup(EMERGENCY_STOP_GPIO, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# Buzzer state management - ensure only one buzzer thread runs
buzzer_active = False
buzzer_thread = None
estop_active = False

# ---------------- Hardware helpers ----------------

def buzzer_alarm():
    """Runs in a single background thread and toggles buzzer 1s ON / 1s OFF while buzzer_active is True."""
    global buzzer_active
    try:
        while buzzer_active:
            GPIO.output(BUZZER_PIN, GPIO.HIGH)
            time.sleep(1)
            # Check again in case buzzer was stopped during the sleep
            if not buzzer_active:
                break
            GPIO.output(BUZZER_PIN, GPIO.LOW)
            time.sleep(1)
    finally:
        # ensure buzzer is off when the thread exits
        try:
            GPIO.output(BUZZER_PIN, GPIO.LOW)
        except RuntimeError:
            pass


def start_buzzer():
    global buzzer_active, buzzer_thread
    if not buzzer_active:
        buzzer_active = True
        buzzer_thread = threading.Thread(target=buzzer_alarm, daemon=True)
        buzzer_thread.start()


def stop_buzzer():
    global buzzer_active, buzzer_thread
    if buzzer_active:
        buzzer_active = False
        try:
            GPIO.output(BUZZER_PIN, GPIO.LOW)
        except RuntimeError:
            pass
        buzzer_thread = None


def lock_solenoid():
    try:
        GPIO.output(OUTPUT_Y0, GPIO.HIGH)
    except RuntimeError:
        pass


def unlock_solenoid():
    try:
        GPIO.output(OUTPUT_Y0, GPIO.LOW)
    except RuntimeError:
        pass


def lights_standby():
    try:
        GPIO.output(GREEN_LIGHT, GPIO.LOW)
        GPIO.output(RED_LIGHT, GPIO.LOW)
        GPIO.output(ORANGE_LIGHT, GPIO.HIGH)
    except RuntimeError:
        pass


def estop_light():
    try:
        GPIO.output(GREEN_LIGHT, GPIO.HIGH)
        GPIO.output(RED_LIGHT, GPIO.HIGH)
        GPIO.output(ORANGE_LIGHT, GPIO.HIGH)
    except RuntimeError:
        pass


# ---------------- UI / Timer logic ----------------
class TimerSection:
    def __init__(self, parent, title, default_seconds, app):
        self.app = app
        self.title = title
        self.default_seconds = default_seconds
        self.initial_seconds = default_seconds  # Track the current "set" time
        self.remaining = self.initial_seconds
        self.running = False
        self.blinking = False
        self.state = "idle"

        # Frame
        self.frame = tk.LabelFrame(parent, padx=6, pady=6, font=("Helvetica", 12))
        self.frame.grid_propagate(False)

        # Title row
        title_row = tk.Frame(self.frame)
        title_row.pack(anchor="n", pady=(0, 4))
        self.title_label = tk.Label(title_row, text=title, font=("Helvetica", 14, "bold"), fg="black")
        self.title_label.pack(side=tk.LEFT)
        self.edit_btn = tk.Button(title_row, text="", font=("Helvetica", 12, "bold"),
                                  width=3, command=self.edit_title, bg="lightblue")
        self.edit_btn.pack(side=tk.LEFT, padx=4)
        self.edit_btn.config(state="disabled")

        # Timer display
        self.time_label = tk.Label(self.frame, text=self.format_time(self.remaining), font=("Helvetica", 28))
        self.time_label.pack(pady=4)

        # Time adjustment buttons
        adjust_frame = tk.Frame(self.frame)
        adjust_frame.pack(pady=4)

        adjustments = [
            [("+Hr", 3600), ("+Min", 60), ("+Sec", 1)],
            [("-Hr", -3600), ("-Min", -60), ("-Sec", -1)],
        ]
        for row in adjustments:
            row_frame = tk.Frame(adjust_frame)
            row_frame.pack()
            for text, delta in row:
                tk.Button(row_frame, text=text, font=("Helvetica", 10), width=6,
                          command=lambda d=delta: self.adjust_time(d)).pack(side=tk.LEFT, padx=2, pady=2)

        # Control buttons
        self.start_btn = tk.Button(self.frame, text="Start", font=("Helvetica", 16),
                                   bg="green", fg="white", command=self.start_timer)
        self.start_btn.pack(fill="x", pady=4)

        self.buzzer_btn = tk.Button(self.frame, text="Buzzer Reset", font=("Helvetica", 16),
                                    bg="yellow", fg="black", command=self.on_buzzer_reset, state="disabled")
        self.buzzer_btn.pack(fill="x", pady=4)

        self.reset_btn = tk.Button(self.frame, text="Reset", font=("Helvetica", 16),
                                   bg="red", fg="white", command=self.reset_timer, state="disabled")
        self.reset_btn.pack(fill="x", pady=4)

        # Status label
        self.status_label = tk.Label(self.frame, text="Idle", font=("Helvetica", 26, "bold"), fg="orange")
        self.status_label.pack(side=tk.BOTTOM, pady=4)

    def format_time(self, seconds):
        mins, secs = divmod(int(seconds), 60)
        hrs, mins = divmod(mins, 60)
        return f"{hrs:02}:{mins:02}:{secs:02}"

    def adjust_time(self, delta):
        if self.app.maintenance_active:
            self.remaining = max(0, self.remaining + delta)
            self.initial_seconds = self.remaining
            self.time_label.config(text=self.format_time(self.remaining))

    def edit_title(self):
        if not self.app.maintenance_active:
            return
        popup = tk.Toplevel(self.app.root)
        popup.transient(self.app.root)
        popup.grab_set()
        popup.lift()
        popup.focus_force()
        popup.overrideredirect(True)
        popup.attributes("-fullscreen", True)
        popup.configure(bg="lightgrey")

        tk.Label(popup, text="Enter New Title", font=("Helvetica", 20), bg="lightgrey").pack(pady=(12, 4))
        title_var = tk.StringVar(value=self.title)
        entry = tk.Entry(popup, textvariable=title_var, font=("Helvetica", 18), width=36)
        entry.pack(pady=(0, 8))
        entry.focus_set()
        entry.selection_range(0, tk.END)

        self.app._add_keyboard(popup, title_var, entry)

        # Escape button at top-left
        tk.Button(popup, text="Escape", font=("Helvetica", 12, "bold"),
                  bg="red", fg="white", command=popup.destroy).place(x=10, y=10)
        
        # Bottom row with OK/Cancel only
        btn_frame = tk.Frame(popup, bg="lightgrey")
        btn_frame.pack(pady=10, side=tk.BOTTOM)
        tk.Button(btn_frame, text="OK", font=("Helvetica", 14), bg="green", fg="white",
                  command=lambda: self._apply_title(popup, title_var)).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Cancel", font=("Helvetica", 14), bg="grey", fg="white",
                  command=popup.destroy).pack(side=tk.LEFT, padx=10)


        popup.bind("<Return>", lambda e: self._apply_title(popup, title_var))
        popup.bind("<Escape>", lambda e: popup.destroy())

    def _apply_title(self, popup, var):
        new_title = var.get().strip()
        if new_title == "":
            messagebox.showwarning("Invalid Title", "Title cannot be empty.")
            return
        self.title = new_title
        self.title_label.config(text=self.title)
        popup.destroy()

    def start_timer(self):
        if self.running:
            return
        self.stop_blinking()
        self.running = True
        self.state = "running"
        self.status_label.config(text="Running", fg="blue")
        lock_solenoid()
        try:
            GPIO.output(GREEN_LIGHT, GPIO.HIGH)
            GPIO.output(RED_LIGHT, GPIO.LOW)
            GPIO.output(ORANGE_LIGHT, GPIO.LOW)
        except RuntimeError:
            pass

        self.start_btn.config(state="disabled")
        self.buzzer_btn.config(state="disabled")
        self.reset_btn.config(state="disabled")

        self.start_blinking()
        # begin countdown from current remaining - 1 after 1 second
        self.frame.after(1000, lambda: self._countdown_step(self.remaining - 1))

    def _countdown_step(self, seconds_left):
        if not self.running:
            return
        if seconds_left >= 0:
            self.time_label.config(text=self.format_time(seconds_left))
            self.remaining = seconds_left
            if seconds_left > 0:
                self.frame.after(1000, lambda: self._countdown_step(seconds_left - 1))
                return
        # reached 0
        if self.running:
            self.running = False
            self.state = "done"
            try:
                GPIO.output(GREEN_LIGHT, GPIO.LOW)
                GPIO.output(RED_LIGHT, GPIO.HIGH)
                GPIO.output(ORANGE_LIGHT, GPIO.HIGH)
            except RuntimeError:
                pass

            # start the single buzzer thread
            start_buzzer()

            self.status_label.config(text="Done!", fg="green")
            self.start_blinking()
            self.buzzer_btn.config(state="normal")
            # keep reset disabled until buzzer reset to avoid accidental reset while alarm is active
            self.reset_btn.config(state="disabled")

    def on_buzzer_reset(self):
        # Stop the buzzer and enable Reset button
        stop_buzzer()
        self.buzzer_btn.config(state="disabled")
        self.reset_btn.config(state="normal")

    def start_blinking(self):
        self.stop_blinking()
        if self.state == "running":
            self.blinking = True
            self._blink_running()
        elif self.state == "done":
            self.blinking = True
            self._blink_done()

    def _blink_running(self):
        if not self.blinking or self.state != "running":
            return
        current_fg = self.status_label.cget("fg")
        new_fg = "blue" if current_fg == "white" else "white"
        self.status_label.config(fg=new_fg)
        self.blink_job = self.frame.after(500, self._blink_running)

    def _blink_done(self):
        if not self.blinking or self.state != "done":
            return
        current_fg = self.status_label.cget("fg")
        new_fg = "green" if current_fg == "white" else "white"
        self.status_label.config(fg=new_fg)
        self.blink_job = self.frame.after(300, self._blink_done)

    def stop_blinking(self):
        self.blinking = False
        if hasattr(self, "blink_job"):
            try:
                self.frame.after_cancel(self.blink_job)
            except Exception:
                pass
        if self.state == "running":
            self.status_label.config(fg="blue")
        elif self.state == "done":
            self.status_label.config(fg="green")
        else:
            self.status_label.config(fg="orange")

    def reset_timer(self):
        self.running = False
        self.state = "idle"
        stop_buzzer()
        unlock_solenoid()
        lights_standby()
        self.stop_blinking()
        self.remaining = self.initial_seconds
        self.time_label.config(text=self.format_time(self.remaining))
        self.status_label.config(text="Idle", fg="orange")
        self.buzzer_btn.config(state="disabled")
        self.reset_btn.config(state="disabled")
        self.start_btn.config(state="normal")

    def open_edit(self):
        self.edit_btn.config(state="normal")

    def close_edit(self):
        self.edit_btn.config(state="disabled")


# ---------------- Main GUI ----------------
class ESPEC_Oven_GUI:
    def __init__(self, root):
        self.root = root
        self.root.title("ESPEC Oven Timer")
        self.root.attributes("-fullscreen", True)
        self.root.configure(bg="lightgrey")
        self.maintenance_active = False
        self.operation_button = None

        # Header
        header = tk.Frame(root, bg="lightgrey")
        header.pack(fill="x", pady=6)
        tk.Label(header, text="ESPEC Oven Timer Control", font=("Helvetica", 26, "bold"),
                 bg="lightgrey").pack(side=tk.LEFT, padx=12)
        tk.Button(header, text="Maintenance", font=("Helvetica", 14),
                  bg="blue", fg="white", command=self.open_maintenance).pack(side=tk.RIGHT, padx=12)

        # Main frame
        self.main_frame = tk.Frame(root, bg="lightgrey")
        self.main_frame.pack(expand=True, fill="both", pady=8)

        self.timers = []
        titles = ["Timer 1", "Timer 2", "Timer 3"]
        defaults = [2 * 60 * 60, 1 * 60 * 60, 45 * 60]

        for i, (title, secs) in enumerate(zip(titles, defaults)):
            timer = TimerSection(self.main_frame, title, secs, self)
            self.timers.append(timer)
            timer.frame.grid(row=0, column=i, sticky="nsew", padx=5, pady=5)

        for i in range(3):
            self.main_frame.columnconfigure(i, weight=1)

        # Footer
        footer = tk.Frame(root, bg="lightgrey")
        footer.pack(side=tk.BOTTOM, fill="x", pady=8)
        tk.Button(footer, text="Exit", font=("Helvetica", 14), bg="grey", fg="white",
                  command=self.exit_app).pack(side=tk.LEFT, padx=8)
        tk.Button(footer, text="Reboot", font=("Helvetica", 14), bg="orange", fg="white",
                  command=self.reboot_pi).pack(side=tk.LEFT, padx=8)
        tk.Button(footer, text="Shutdown", font=("Helvetica", 14), bg="red", fg="white",
                  command=self.shutdown_pi).pack(side=tk.LEFT, padx=8)
        tk.Button(footer, text="Door Unlock", font=("Helvetica", 14), bg="blue", fg="white",
                  command=self.doorunlock_pi).pack(side=tk.RIGHT, padx=8)

        lights_standby()
        self.root.after(200, self._monitor_estop)
    
    def _monitor_estop(self):
        global estop_active
        try:
            # FIX: With GPIO.PUD_UP, the input pin reads LOW when the button is pressed (connected to ground).
            # The original code checked for HIGH, causing it to trigger constantly.
            if GPIO.input(EMERGENCY_STOP_GPIO) == GPIO.HIGH:  # Button is pressed
                if not estop_active:
                    estop_active = True
                    # Stop all timers immediately and show EMERGENCY STOP
                    for t in self.timers:
                        t.running = False
                        t.state = "idle"
                        t.stop_blinking()
                        t.status_label.config(text="EMERGENCY STOP", fg="red")
                        t.start_btn.config(state="disabled")
                        # allow user to press Buzzer Reset even during E-Stop
                        t.buzzer_btn.config(state="disabled")
                        t.reset_btn.config(state="disabled")

                    # Hardware actions
                    unlock_solenoid()
                    estop_light()

                    # start the buzzer (single thread)
                    start_buzzer()
            else:  # Button is not pressed (released)
                if estop_active:
                    # E-Stop was just released
                    estop_active = False
                    # Stop buzzer
                    stop_buzzer()
                    # Restore normal lights
                    lights_standby()
                    # Reset each timer back to its factory/default preset and update UI
                    for t in self.timers:
                        t.running = False
                        t.state = "idle"
                        t.stop_blinking()
                        # Reset both the editable 'initial_seconds' and current 'remaining'
                        t.initial_seconds = t.default_seconds
                        t.remaining = t.default_seconds
                        t.time_label.config(text=t.format_time(t.remaining))
                        t.status_label.config(text="Idle", fg="orange")
                        t.start_btn.config(state="normal")
                        t.buzzer_btn.config(state="disabled")
                        t.reset_btn.config(state="disabled")
        except RuntimeError:
            pass

        self.root.after(200, self._monitor_estop)


    # ---------------- Maintenance ----------------
    def _add_keyboard(self, popup, var, entry):
        kb_frame = tk.Frame(popup, bg="lightgrey")
        kb_frame.pack(pady=20)

        self.shift_on = False
        layout = ["1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm"]

        def insert_char(ch):
            if self.shift_on:
                ch = ch.upper()
                self.shift_on = False
                update_keys()
            entry.insert(tk.INSERT, ch)

        def backspace():
            pos = entry.index(tk.INSERT)
            if pos > 0:
                entry.delete(pos - 1)

        def clear_text():
            entry.delete(0, tk.END)

        def add_space():
            entry.insert(tk.INSERT, " ")

        def toggle_shift():
            self.shift_on = not self.shift_on
            update_keys()

        def enter_key():
            popup.event_generate("<Return>")

        def update_keys():
            for btn, ch in keys_map:
                btn.config(text=ch.upper() if self.shift_on else ch.lower())

        keys_map = []
        for row_chars in layout:
            row_frame = tk.Frame(kb_frame, bg="lightgrey")
            row_frame.pack(pady=4)
            for ch in row_chars:
                btn = tk.Button(
                    row_frame, text=ch, font=("Helvetica", 16, "bold"),
                    width=4, height=2, bg="white",
                    command=lambda c=ch: insert_char(c)
                )
                btn.pack(side=tk.LEFT, padx=3, pady=3)
                keys_map.append((btn, ch))

        sp_frame = tk.Frame(kb_frame, bg="lightgrey")
        sp_frame.pack(pady=6)
        tk.Button(sp_frame, text="Shift", font=("Helvetica", 14), width=8, height=2,
                  bg="lightblue", command=toggle_shift).pack(side=tk.LEFT, padx=6)
        tk.Button(sp_frame, text="Backspace", font=("Helvetica", 14), width=10, height=2,
                  bg="orange", command=backspace).pack(side=tk.LEFT, padx=6)
        tk.Button(sp_frame, text="Space", font=("Helvetica", 14), width=8, height=2,
                  bg="lightgreen", command=add_space).pack(side=tk.LEFT, padx=6)
        tk.Button(sp_frame, text="Clear", font=("Helvetica", 14), width=8, height=2,
                  bg="red", fg="white", command=clear_text).pack(side=tk.LEFT, padx=6)
        tk.Button(sp_frame, text="Enter", font=("Helvetica", 14), width=8, height=2,
                  bg="lightblue", command=enter_key).pack(side=tk.LEFT, padx=6)

    def open_maintenance(self):
        popup = tk.Toplevel(self.root)
        popup.transient(self.root)
        popup.grab_set()
        popup.lift()
        popup.focus_force()
        popup.overrideredirect(True)
        popup.attributes("-fullscreen", True)
        popup.configure(bg="lightgrey")

        tk.Label(popup, text="Enter Password", font=("Helvetica", 20), bg="lightgrey").pack(pady=(12, 4))
        pwd_var = tk.StringVar()
        pwd_entry = tk.Entry(popup, textvariable=pwd_var, show="*", font=("Helvetica", 18), width=24)
        pwd_entry.pack(pady=(0, 8))
        pwd_entry.focus_set()

        self._add_keyboard(popup, pwd_var, pwd_entry)

        # Escape button at top-left
        tk.Button(popup, text="Escape", font=("Helvetica", 12, "bold"),
                  bg="red", fg="white", command=popup.destroy).place(x=10, y=10)
        
        # Bottom row with OK/Cancel only
        btn_row = tk.Frame(popup, bg="lightgrey")
        btn_row.pack(pady=10, side=tk.BOTTOM)
        ok_btn = tk.Button(btn_row, text="OK", font=("Helvetica", 14), bg="green", fg="white",
                           command=lambda: self._check_maintenance_password(popup, pwd_var))
        ok_btn.pack(side=tk.LEFT, padx=10)
        tk.Button(btn_row, text="Cancel", font=("Helvetica", 14), bg="grey", fg="white",
                  command=popup.destroy).pack(side=tk.LEFT, padx=10)

        popup.bind("<Return>", lambda e: self._check_maintenance_password(popup, pwd_var))
        popup.bind("<Escape>", lambda e: popup.destroy())

    def _check_maintenance_password(self, popup, pwd_var):
        if pwd_var.get() == "tdk123":
            self.maintenance_active = True
            for t in self.timers:
                t.open_edit()
            if not self.operation_button:
                header = self.root.winfo_children()[0]
                self.operation_button = tk.Button(header, text="Operation Mode", font=("Helvetica", 14),
                                                  bg="green", fg="white", command=self._exit_maintenance)
                self.operation_button.pack(side=tk.RIGHT, padx=8)
            popup.destroy()
            messagebox.showinfo("Maintenance", "Maintenance enabled.")
        else:
            messagebox.showerror("Access Denied", "Incorrect password.")
            pwd_var.set("")

    def _exit_maintenance(self):
        self.maintenance_active = False
        for t in self.timers:
            t.close_edit()
        if self.operation_button:
            self.operation_button.destroy()
            self.operation_button = None
        messagebox.showinfo("Operation Mode", "Returned to Operation Mode.")

    # ---------------- System Controls ----------------
    def exit_app(self):
        if messagebox.askyesno("Exit", "Are you sure you want to exit the program?"):
            stop_buzzer()
            try:
                GPIO.cleanup()
            except Exception:
                pass
            try:
                self.root.attributes('-fullscreen', False)
                self.root.quit()
                self.root.destroy()
            except Exception:
                pass
            # give background threads a short moment (they are daemon threads so process will exit)
            time.sleep(0.05)
            os._exit(0)

    def reboot_pi(self):
        if messagebox.askyesno("Reboot", "Are you sure you want to reboot?"):
            os.system("sudo reboot")

    def shutdown_pi(self):
        if messagebox.askyesno("Shutdown", "Are you sure you want to shut down?"):
            os.system("sudo shutdown now")

    def doorunlock_pi(self):
        unlock_solenoid()


# ---------------- Run ----------------
def main():
    root = tk.Tk()
    app = ESPEC_Oven_GUI(root)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    finally:
        # Final cleanup in case of an unhandled exit
        try:
            GPIO.cleanup()
        except Exception as e:
            print(f"Could not perform GPIO cleanup: {e}")

