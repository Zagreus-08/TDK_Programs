import tkinter as tk
from tkinter import messagebox, ttk
import RPi.GPIO as GPIO
import time
import threading
import os
import datetime
import csv

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

# Buzzer state management
buzzer_active = False
buzzer_thread = None
estop_active = False

LOG_FILE = "/home/pi/door_unlock_log.csv"
try:
    if not os.path.exists(LOG_FILE) or os.path.getsize(LOG_FILE) == 0:
        with open(LOG_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Timestamp", "ID", "Name"])
except Exception as e:
    print(f"WARNING: cannot create or open log file {LOG_FILE}: {e}")

USERS = {
    "01029187": "Lans Galos",
    "29187": "Lans Galos",

}

def get_name_from_id(uid: str) -> str:
    """Return name matched to uid or empty string if not found."""
    return USERS.get(uid, "")

def safe_showinfo(parent, title, message):
        parent.update_idletasks()  # make sure window is realized
        messagebox.showinfo(title, message, parent=parent)
    
def safe_showwarning(parent, title, message):
        parent.update_idletasks()
        messagebox.showwarning(title, message, parent=parent)
        
def safe_showerror(parent, title, message):
        parent.update_idletasks()
        messagebox.showerror(title, message, parent=parent)

# ---------------- Hardware helpers ----------------
def buzzer_alarm():
    global buzzer_active
    try:
        while buzzer_active:
            GPIO.output(BUZZER_PIN, GPIO.HIGH)
            time.sleep(1)
            if not buzzer_active:
                break
            GPIO.output(BUZZER_PIN, GPIO.LOW)
            time.sleep(1)
    finally:
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
        self.initial_seconds = default_seconds
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
        # edit button enabled/disabled by maintenance open_edit/close_edit
        self.edit_btn.config(state="normal")

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
        if self.app.maintenance_active:  # Only in maintenance mode
            self.remaining = max(0, self.remaining + delta)
            self.initial_seconds = self.remaining
            self.time_label.config(text=self.format_time(self.remaining))

    def edit_title(self):
        # Dropdown rename (allowed in both modes per your request)
        popup = tk.Toplevel(self.app.root)
        popup.transient(self.app.root)
        popup.grab_set()
        popup.lift()
        popup.focus_force()
        popup.overrideredirect(True)
        popup.attributes("-fullscreen", True)
        popup.configure(bg="lightgrey")

        tk.Label(popup, text="Select New Title", font=("Helvetica", 20), bg="lightgrey").pack(pady=(12, 4))

        options = ["Migne Evaluation", "Nivio Evaluation", "Nivio S Evaluation",
                   "Pinocchio Evaluation", "Migne", "Nivio", "Nivio S", "Pinocchio",
                   "Timer 1", "Timer 2", "Timer 3"]
        selected = tk.StringVar(value=self.title)

        dropdown = ttk.Combobox(popup, textvariable=selected, values=options,
                                font=("Helvetica", 18), state="readonly", width=24)
        dropdown.pack(pady=(0, 8))
        dropdown.focus_set()

        def apply_choice():
            self.title = selected.get()
            self.title_label.config(text=self.title)
            popup.destroy()

        btn_frame = tk.Frame(popup, bg="lightgrey")
        btn_frame.pack(pady=10, side=tk.BOTTOM)
        tk.Button(btn_frame, text="OK", font=("Helvetica", 14), bg="green", fg="white",
                  command=apply_choice).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Cancel", font=("Helvetica", 14), bg="grey", fg="white",
                  command=popup.destroy).pack(side=tk.LEFT, padx=10)

        tk.Button(popup, text="Esc", font=("Helvetica", 12, "bold"),
                  bg="red", fg="white", command=popup.destroy).place(x=10, y=10)

    # ---------------- Timer Controls ----------------
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
        unlock_solenoid()
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
        lock_solenoid()
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
        self.edit_btn.config(state="normal")

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

        # Data Log and Door Unlock (Data Log is left of Door Unlock)
        tk.Button(footer, text="Data Log", font=("Helvetica", 14),
                  bg="purple", fg="white", command=self.view_log).pack(side=tk.RIGHT, padx=8)
        tk.Button(footer, text="Door Unlock", font=("Helvetica", 14), bg="blue", fg="white",
                  command=self.doorunlock_pi).pack(side=tk.RIGHT, padx=8)

        lights_standby()
        self.root.after(200, self._monitor_estop)

    # ---------------- Onscreen Keyboard (single per popup) ----------------
    def _add_keyboard(self, popup, entry_widgets, on_change=None):
        """
        Create a single keyboard for the popup and attach it to one or more Entry widgets.
        entry_widgets: single Entry or list/tuple of Entry widgets.
        """
        if not isinstance(entry_widgets, (list, tuple)):
            entries = [entry_widgets]
        else:
            entries = list(entry_widgets)

        # Keep track of which entry is active; default to first
        active = {'entry': entries[0]}

        # When user clicks an entry, make it active
        def set_active(e, ent):
            active['entry'] = ent
            try:
                ent.focus_set()
            except Exception:
                pass

        for ent in entries:
            ent.bind("<FocusIn>", lambda ev, en=ent: set_active(ev, en))
            ent.bind("<Button-1>", lambda ev, en=ent: set_active(ev, en))

        kb_frame = tk.Frame(popup, bg="lightgrey")
        kb_frame.pack(pady=8)

        layout = ["1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm"]
        keys_map = []  # (button, char)
        self._kb_shift = False

        def update_keys():
            for btn, ch in keys_map:
                # show upper/lower alphabet, numbers unchanged
                if ch.isalpha():
                    btn.config(text=ch.upper() if self._kb_shift else ch.lower())
                else:
                    btn.config(text=ch)

        def toggle_shift():
            self._kb_shift = not self._kb_shift
            update_keys()

        def insert_char(ch):
            ent = active['entry']
            if ent is None:
                return
            c = ch.upper() if (self._kb_shift and ch.isalpha()) else ch
            ent.insert(tk.INSERT, c)
            if self._kb_shift and ch.isalpha():
                self._kb_shift = False
                update_keys()
            if on_change:
                on_change()

        def backspace():
            ent = active['entry']
            if ent is None:
                return
            try:
                pos = ent.index(tk.INSERT)
            except Exception:
                pos = None
            if pos is None:
                # fallback: delete last char
                ent.delete(len(ent.get()) - 1, tk.END)
            else:
                if pos > 0:
                    ent.delete(pos - 1)
            if on_change:
                on_change()

        def clear_all():
            ent = active['entry']
            if ent is None:
                return
            ent.delete(0, tk.END)
            if on_change:
                on_change()

        def add_space():
            ent = active['entry']
            if ent is None:
                return
            ent.insert(tk.INSERT, " ")

        def press_enter():
            # generate Return on the active entry so any bound <Return> handler runs
            ent = active['entry']
            if ent is None:
                return
            ent.event_generate("<Return>")

        # Create key buttons
        for row in layout:
            row_frame = tk.Frame(kb_frame, bg="lightgrey")
            row_frame.pack(pady=2)
            for ch in row:
                btn = tk.Button(row_frame, text=ch, width=4, height=2,
                                command=lambda c=ch: insert_char(c))
                btn.pack(side=tk.LEFT, padx=2, pady=2)
                keys_map.append((btn, ch))

        # Control row
        ctrl_frame = tk.Frame(kb_frame, bg="lightgrey")
        ctrl_frame.pack(pady=6)
        tk.Button(ctrl_frame, text="Shift", width=6, height=2, command=toggle_shift).pack(side=tk.LEFT, padx=4)
        tk.Button(ctrl_frame, text="Space", width=8, height=2, command=add_space).pack(side=tk.LEFT, padx=4)
        tk.Button(ctrl_frame, text="⌫", width=4, height=2, command=backspace).pack(side=tk.LEFT, padx=4)
        tk.Button(ctrl_frame, text="Clear", width=6, height=2, command=clear_all).pack(side=tk.LEFT, padx=4)
        tk.Button(ctrl_frame, text="Enter", width=6, height=2, command=press_enter).pack(side=tk.LEFT, padx=4)

        update_keys()
        # ensure the first entry is focused
        try:
            entries[0].focus_set()
            active['entry'] = entries[0]
        except Exception:
            pass

    # ---------------- Maintenance Mode ----------------
    def open_maintenance(self):
        popup = tk.Toplevel(self.root)
        popup.transient(self.root)
        popup.grab_set()
        popup.lift()
        popup.focus_force()
        popup.overrideredirect(True)
        popup.attributes("-fullscreen", True)
        popup.configure(bg="lightgrey")

        tk.Label(popup, text="Enter Maintenance Password", font=("Helvetica", 20), bg="lightgrey").pack(pady=20)
        pwd_var = tk.StringVar()
        pwd_entry = tk.Entry(popup, textvariable=pwd_var, font=("Helvetica", 18), show="*", width=24)
        pwd_entry.pack(pady=10)
        pwd_entry.focus_set()

        # attach single keyboard to the password entry
        self._add_keyboard(popup, pwd_entry)

        def check_password(event=None):
            if pwd_var.get() == "tdk123":  # your chosen password
                self.maintenance_active = True
                for t in self.timers:
                    t.open_edit()
                # add Operation Mode button to exit maintenance if not present
                if not self.operation_button:
                    header = self.root.winfo_children()[0]
                    self.operation_button = tk.Button(header, text="Operation Mode", font=("Helvetica", 14),
                                                      bg="green", fg="white", command=self._exit_maintenance)
                    self.operation_button.pack(side=tk.RIGHT, padx=8)
                popup.destroy()
                messagebox.showinfo("Maintenance", "Maintenance enabled.")
            else:
                safe_showerror(popup,"Access Denied", "Incorrect password.")
                pwd_var.set("")
                pwd_entry.focus_set()

        # allow Enter on entry to validate
        pwd_entry.bind("<Return>", check_password)

        btn_row = tk.Frame(popup, bg="lightgrey")
        btn_row.pack(pady=20, side=tk.BOTTOM)

        tk.Button(popup, text="Esc", font=("Helvetica", 12, "bold"),
                  bg="red", fg="white", command=popup.destroy).place(x=10, y=10)

    def _exit_maintenance(self):
        self.maintenance_active = False
        for t in self.timers:
            t.close_edit()
        if self.operation_button:
            self.operation_button.destroy()
            self.operation_button = None
        messagebox.showinfo("Operation Mode", "Returned to Operation Mode.")

    # ---------------- Door Unlock with Logging ----------------
    def doorunlock_pi(self):
        popup = tk.Toplevel(self.root)
        popup.transient(self.root)
        popup.grab_set()
        popup.lift()
        popup.focus_force()
        popup.overrideredirect(True)
        popup.attributes("-fullscreen", True)
        popup.configure(bg="lightgrey")

        tk.Label(popup, text="Enter ID Number", font=("Helvetica", 20), bg="lightgrey").pack(pady=10)
        id_var = tk.StringVar()
        id_entry = tk.Entry(popup, textvariable=id_var, font=("Helvetica", 18), width=24)
        id_entry.pack(pady=5)
    
        name_var = tk.StringVar()
        name_entry = tk.Entry(popup, textvariable=name_var, font=("Helvetica", 18),
                              width=24, state="readonly")
        name_entry.pack(pady=5)
    
        # --- define the helper before creating the keyboard ---
        def update_name_from_id(event=None):
            uid = id_var.get().strip()
            uname = get_name_from_id(uid)
            name_entry.config(state="normal")
            name_var.set(uname)
            name_entry.config(state="readonly")
            print(f"DEBUG update_name_from_id: uid='{uid}' -> uname='{uname}'")
    
        # now you can safely pass it
        self._add_keyboard(popup, id_entry, on_change=update_name_from_id)
    
        # still keep binding for real keyboards
        id_entry.bind("<KeyRelease>", update_name_from_id)

        def confirm_unlock(event=None):
            uid = id_var.get().strip()
            uname = name_var.get().strip()
            if not uid:
                safe_showwarning(popup, "Invalid Input", "ID is required.")
                return
            # If name not found, set to "Unknown" for logging/display (optional)
            if not uname:
                uname = "Unknown"

            # Save to log
            # Save to CSV log
            try:
                with open(LOG_FILE, "a", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow([datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), uid, uname])
            except Exception as e:
                safe_showwarning(popup, "Log Error", f"Could not write to log: {e}")


            # Perform unlock
            unlock_solenoid()
            safe_showinfo(popup,"Door Unlocked", f"Door unlocked by {uname} (ID {uid}).")
            popup.destroy()

        # when user types ID, update the name automatically
        id_entry.bind("<KeyRelease>", update_name_from_id)
        # allow Enter key on ID to confirm unlock
        id_entry.bind("<Return>", confirm_unlock)

        # Optionally preset focus to ID
        try:
            id_entry.focus_set()
        except Exception:
            pass

        btn_row = tk.Frame(popup, bg="lightgrey")
        btn_row.pack(pady=20, side=tk.BOTTOM)
        tk.Button(popup, text="Esc", font=("Helvetica", 12, "bold"),
                  bg="red", fg="white", command=popup.destroy).place(x=10, y=10)


    # ---------------- Data Log Viewer ----------------
    def view_log(self):
        popup = tk.Toplevel(self.root)
        popup.title("Door Unlock Log")
        popup.attributes("-fullscreen", True)
        popup.configure(bg="lightgrey")
    
        # Frame for the log table
        table_frame = tk.Frame(popup, bg="lightgrey")
        table_frame.pack(expand=True, fill="both", pady=10)
    
        cols = ("Timestamp", "ID", "Name")
        tree = ttk.Treeview(table_frame, columns=cols, show="headings")
        for col in cols:
            tree.heading(col, text=col)
            tree.column(col, width=250, anchor="center")
        tree.pack(side=tk.LEFT, expand=True, fill="both")
    
        scrollbar = tk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill="y")
    
        # Load CSV log and insert rows
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, newline="") as f:
                reader = csv.reader(f)
                next(reader, None)  # skip header
                last_item = None
                for row in reader:
                    if len(row) == 3:
                        last_item = tree.insert("", tk.END, values=row)
                if last_item:
                    tree.see(last_item)
                    tree.selection_set(last_item)
        else:
            safe_showinfo(popup, "Log Viewer", "No log records yet.")
    
        # Footer with Close button (fixed at bottom)
        footer = tk.Frame(popup, bg="lightgrey")
        footer.pack(fill="x", pady=10)
        close_btn = tk.Button(footer, text="Close", font=("Helvetica", 14),
                              bg="red", fg="white", command=popup.destroy)
        close_btn.pack(pady=5)
    
        # Make sure the Close button has focus so it’s clickable on touchscreen
        close_btn.focus_set()





    # ---------------- Emergency Stop Monitoring ----------------
    def _monitor_estop(self):
        global estop_active
        if GPIO.input(EMERGENCY_STOP_GPIO) == GPIO.HIGH:  # pressed
            if not estop_active:
                estop_active = True
                    # Stop all timers immediately and show EMERGENCY STOP
                for t in self.timers:
                    t.running = False
                    t.state = "idle"
                    t.stop_blinking()
                    t.start_btn.config(state="disabled")
                    t.buzzer_btn.config(state="disabled")
                    t.reset_btn.config(state="disabled")

                    # Hardware actions
                unlock_solenoid()
                estop_light()
                start_buzzer()
                safe_showerror(self.root, "EMERGENCY STOP", "Emergency Stop Activated!\nAll operations halted.")
        else:
            if estop_active:
                estop_active = False
                stop_buzzer()
                lock_solenoid()
                lights_standby()
                for t in self.timers:
                    t.running = False
                    t.state = "idle"
                    t.stop_blinking()
                    t.initial_seconds = t.default_seconds
                    t.remaining = t.default_seconds
                    t.time_label.config(text=t.format_time(t.remaining))
                    t.status_label.config(text="Idle", fg="orange")
                    t.start_btn.config(state="normal")
                    t.buzzer_btn.config(state="disabled")
                    t.reset_btn.config(state="disabled")
        self.root.after(200, self._monitor_estop)

    # ---------------- App Control ----------------
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


# ---------------- Run ----------------
def main():
    root = tk.Tk()
    app = ESPEC_Oven_GUI(root)
    root.mainloop()

if __name__ == "__main__":
    try:
        main()
    finally:
        try:
            GPIO.cleanup()
        except Exception as e:
            print(f"Could not perform GPIO cleanup: {e}")

