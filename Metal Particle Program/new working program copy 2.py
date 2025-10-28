#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Scan system for long loop - Auto-start version (Fullscreen + Toggleable Controls)
Ver 0.9R-stable9   2025-10-28  (with automatic scan-reset and button state handling)
"""

import copy
import sys
import os
import csv
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib import gridspec
from mpl_toolkits.mplot3d import Axes3D
from scipy.interpolate import griddata
import numpy as np
from mpl_toolkits.axes_grid1 import make_axes_locatable
from multiprocessing import Process, Queue
import threading
import serial
import time
import tkinter as tk
from tkinter import messagebox, filedialog
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

# ---------------- Global vars ----------------
x, y, z = [], [], []
zmin, zmax = -0.1, 0.1
raw_file = None
csv_writer = None
current_filename = None
pause_live = False       # used when user loads a CSV and wants to pause live updates
scan_active = True       # True while an active scan is happening; becomes False after end-of-scan (100,100)

# ---------------- Image ----------------
im_Migne = plt.imread(
    r"C:\Users\a493353\Desktop\Lans Galos\Raspberry Pi Program\Metal Particle Program\Migne_black_frameless.png"
)

# ---------------- Serial ----------------
try:
    # Try common Raspberry Pi serial ports first
    import glob
    possible_ports = ["/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyACM0", "/dev/ttyACM1", "COM7"]
    ser = None
    
    for port in possible_ports:
        try:
            ser = serial.Serial(port, 115200, timeout=1)
            print(f"Connected to serial port: {port}")
            break
        except (serial.SerialException, FileNotFoundError):
            continue
    
    if ser is None:
        # If no port found, try to find any available port
        available_ports = glob.glob('/dev/tty[A-Za-z]*')
        for port in available_ports:
            try:
                ser = serial.Serial(port, 115200, timeout=1)
                print(f"Connected to serial port: {port}")
                break
            except (serial.SerialException, PermissionError):
                continue
                
except Exception as e:
    print(f"Error: Could not open serial port.\n{str(e)}")
    ser = None

if ser is None:
    print("Warning: No serial port available. Running in demo mode.")
    # Don't exit, allow program to run without serial connection

# ---------------- Save figures ----------------
def save_figures(queue):
    while True:
        item = queue.get()
        if item is None:
            break
        fig_obj, filename = item
        try:
            fig_obj.savefig(filename)
        except Exception as e:
            print("Failed to save figure:", e)

queue = Queue()
saving_process = Process(target=save_figures, args=(queue,))
saving_process.start()

# ---------------- Raw Data Handling ----------------
def start_new_raw_file(name_hint=""):
    """Start a new CSV for saving live scan data"""
    global raw_file, csv_writer, current_filename
    if not name_hint:
        name_hint = time.strftime("%Y%m%d_%H%M%S")

    raw_dir = r"C:\Users\a493353\Desktop\Lans Galos\Raspberry Pi Program\Metal Particle Program\raw data"
    os.makedirs(raw_dir, exist_ok=True)
    raw_path = os.path.join(raw_dir, f"raw_{name_hint}.csv")

    try:
        raw_file = open(raw_path, "w", newline="")
        csv_writer = csv.writer(raw_file)
        csv_writer.writerow(["x", "y", "z"])
        current_filename = raw_path
        print(f"[INFO] Started raw data file: {raw_path}")
    except Exception as e:
        print(f"[ERROR] Could not create raw file: {e}")
        raw_file = None
        csv_writer = None

# ---------------- Button state control ----------------
def set_controls_state(state):
    """Enable or disable Load Raw and Resume Live buttons"""
    for btn in [load_btn, resume_btn]:
        btn.config(state=state)

# ---------------- Serial loop ----------------
def read_loop():
    global raw_file, csv_writer, current_filename, scan_active
    data_cnt = 0
    filename_from_serial = ""

    while True:
        if ser is None:
            time.sleep(1)  # Sleep and continue if no serial connection
            continue

        if pause_live:
            time.sleep(0.2)
            continue

        rcv_data = ser.readline()
        if len(rcv_data) == 0:
            continue

        try:
            parts = rcv_data.decode("ascii", errors="ignore").strip().split(",")
            x0 = float(parts[0])
            y0 = float(parts[1])
            z0 = float(parts[2])
        except (ValueError, IndexError):
            print("data error @count=", data_cnt)
            continue

        # Detect filename sent by 1st program (captured once per scan)
        if len(parts) >= 4 and not filename_from_serial:
            filename_from_serial = parts[3].strip()
            start_new_raw_file(filename_from_serial)

        # ---------- New scan detection ----------
        if x0 == 0 and y0 == 0:
            if len(x) > 0 or not scan_active:
                print("[INFO] New scan detected (0,0). Clearing buffers and starting fresh.")
                x.clear()
                y.clear()
                z.clear()
                try:
                    if raw_file:
                        raw_file.close()
                except Exception:
                    pass
                raw_file = None
                csv_writer = None
                current_filename = None
                filename_from_serial = ""
                scan_active = True
                # Disable Load/Resume buttons during scanning
                root.after(0, lambda: set_controls_state("disabled"))
            elif scan_active:
                # Also disable buttons if we're starting a fresh scan
                root.after(0, lambda: set_controls_state("disabled"))

        data_cnt += 1

        # Append new data to buffers (live)
        x.append(x0)
        y.append(y0)
        z.append(z0)

        if csv_writer:
            try:
                csv_writer.writerow([x0, y0, z0])
            except Exception:
                pass

        if len(x) > 1500 and x0 == 3 and y0 >= 5:
            del x[0:-309]
            del y[0:-309]
            del z[0:-309]

        # ---------- End of scan ----------
        if x0 == 100 and y0 == 100:
            try:
                if filename_from_serial:
                    queue.put((fig, os.path.join(
                        r"C:\Users\a493353\Desktop\Lans Galos\Raspberry Pi Program\Metal Particle Program",
                        filename_from_serial + ".png")))
                print(f"[INFO] Scan complete, saved image {filename_from_serial}.png")
            except Exception as e:
                print("[ERROR] Could not save image:", e)

            if raw_file:
                try:
                    raw_file.close()
                    print(f"[INFO] Raw data saved: {current_filename}")
                except Exception:
                    pass
                raw_file = None
                csv_writer = None

            scan_active = False
            filename_from_serial = ""
            # Re-enable Load/Resume buttons after scan finishes
            root.after(0, lambda: set_controls_state("normal"))

        if data_cnt >= 6000000:
            break

# ---------------- Initialize blank plot ----------------
def initialize_blank_plot():
    ax.cla()
    axh.cla()
    axm.cla()  # Clear the image subplot as well
    
    ax.grid(True, linestyle="--", alpha=0.7)
    ax.set_xticks(np.arange(0, 101, 20))
    ax.set_yticks(np.arange(0, 101, 20))
    ax.set_facecolor("white")

    axh.grid(True, linestyle="-", alpha=0.7)
    axh.set_xticks(np.arange(0, 101, 20))
    axh.set_yticks(np.arange(0, 101, 25))
    axh.set_zticks(np.arange(-0.4, 0.41, 0.2))
    axh.set_facecolor("none")

    ax.set_xlabel("x")
    ax.set_ylabel("y")
    ax.set_xlim([0, 100])
    ax.set_ylim([0, 100])

    ax.set_title("Foreign object detection", fontsize=16, color=(0.2, 0.2, 0.2), y=1.05)
    axh.set_title("Foreign object detection (3D)", fontsize=16, color=(0.2, 0.2, 0.2), y=1.06)

    axh.view_init(elev=20, azim=300)
    # Handle set_box_aspect for Raspberry Pi compatibility
    try:
        axh.set_box_aspect((5, 5, 3.5))
    except AttributeError:
        pass  # Older matplotlib versions don't have this method
    
    axh.set_xlabel("x")
    axh.set_ylabel("y")
    axh.set_zlabel("output")
    axh.set_xlim([0, 100])
    axh.set_ylim([0, 100])
    axh.set_zlim([zmin, zmax])

    ax.imshow(im_Migne, extent=[16, 84, 40, 60], alpha=0.08)
    axm.imshow(im_Migne, alpha=0.7)
    axm.axis("off")

# ---------------- Update animation ----------------
def update(i, xt, yt, zt, zmin, zmax):
    global ax, axh, axm, cax  # Make sure we can update these references
    if (not scan_active) or pause_live or len(x) < 2:
        return
    xs = copy.copy(x)
    ys = copy.copy(y)
    zs = copy.copy(z)
    if len(xs) != len(zs):
        diff = len(xs) - len(zs)
        if diff > 0:
            xs = xs[diff:]
            ys = ys[diff:]
    if len(np.unique(xs)) < 2 or len(np.unique(ys)) < 2:
        return
    x_new, y_new = np.meshgrid(np.unique(xs), np.unique(ys))
    try:
        z_new0 = griddata((xs, ys), zs, (x_new, y_new), method="cubic")
    except Exception:
        z_new0 = griddata((xs, ys), zs, (x_new, y_new), method="nearest")
    z_new = np.nan_to_num(z_new0, nan=0)

    local_max, local_min = np.nanmax(z_new), np.nanmin(z_new)
    if local_max > zmax:
        zmax = local_max
    if local_min < zmin:
        zmin = local_min

    z_max = max(z) if z else 0
    z_min = min(z) if z else 0

    fig.clf()
    spec = gridspec.GridSpec(ncols=2, nrows=2, width_ratios=[5, 5], height_ratios=[1, 12.5], figure=fig)
    ax = fig.add_subplot(spec[1:, 0])
    axh = fig.add_subplot(spec[1:, 1], projection="3d")
    axm = fig.add_subplot(spec[0, 0:])
    divider = make_axes_locatable(ax)
    cax = divider.append_axes("right", size="5%", pad=0.5)

    axh.view_init(elev=20, azim=300)
    # Remove set_box_aspect for Raspberry Pi compatibility
    try:
        axh.set_box_aspect((5, 5, 3.5))
    except AttributeError:
        pass  # Older matplotlib versions don't have this method
    
    ax.imshow(im_Migne, extent=[16, 84, 40, 60], alpha=0.08)
    ps = ax.contourf(x_new, y_new, z_new, 128, cmap="jet", vmin=zmin, vmax=zmax, alpha=0.9)
    try:
        surf = axh.plot_surface(x_new, y_new, z_new, cmap="jet", vmin=zmin, vmax=zmax, rstride=1, cstride=1)
        ax.figure.colorbar(surf, cax=cax, shrink=1, orientation="vertical")
    except Exception:
        ax.figure.colorbar(ps, cax=cax, shrink=1, orientation="vertical")

    axm.imshow(im_Migne, alpha=0.7)
    axm.axis("off")
    axh.text2D(0.70, 0.95, f"Z Max: {z_max:.6f}", transform=axh.transAxes)
    axh.text2D(0.70, 0.90, f"Z Min: {z_min:.6f}", transform=axh.transAxes)
    axh.set_xlim([0, 100])
    axh.set_zlim([zmin, zmax])
    ax.set_xlim([0, 100])
    axh.set_facecolor((0.9, 0.9, 0.9))
    axh.set_xlabel("x")
    axh.set_ylabel("y")
    axh.set_zlabel("output")

    ax.set_title("Foreign object detection", fontsize=16, color=(0.2, 0.2, 0.2), y=1.05)
    axh.set_title("Foreign object detection (3D)", fontsize=16, color=(0.2, 0.2, 0.2), y=1.06)

# ---------------- Load Raw CSV ----------------
def load_raw_data():
    global pause_live
    pause_live = True
    
    # Set initial directory - try multiple possible paths for Raspberry Pi
    possible_paths = [
        "/home/pi/Desktop/Metal Particle Program/raw data",
        "/home/pi/Desktop/raw data", 
        "/home/pi/raw data",
        os.path.join(os.path.expanduser("~"), "Desktop", "Metal Particle Program", "raw data"),
        os.path.join(os.path.expanduser("~"), "Desktop", "raw data"),
        r"C:\Users\a493353\Desktop\Lans Galos\Raspberry Pi Program\Metal Particle Program\raw data"
    ]
    
    raw_dir = os.getcwd()  # Default fallback
    
    # Find the first existing path
    for path in possible_paths:
        if os.path.exists(path):
            raw_dir = path
            print(f"[INFO] Using raw data directory: {raw_dir}")
            break
    else:
        print(f"[WARNING] No raw data directory found, using: {raw_dir}")
    
    file_path = filedialog.askopenfilename(
        title="Select Raw CSV File", 
        filetypes=[("CSV Files", "*.csv")],
        initialdir=raw_dir
    )
    
    if not file_path:
        pause_live = False
        return
    try:
        data = np.loadtxt(file_path, delimiter=",", skiprows=1)
        xs, ys, zs = data[:, 0], data[:, 1], data[:, 2]
        show_loaded(xs, ys, zs)
    except Exception as e:
        messagebox.showerror("Error", f"Failed to load file:\n{e}")
        pause_live = False

def show_loaded(xs, ys, zs):
    global zmin, zmax, ax, axh, axm, cax
    zmin, zmax = np.min(zs), np.max(zs)

    fig.clf()
    spec = gridspec.GridSpec(ncols=2, nrows=2, width_ratios=[5, 5], height_ratios=[1, 12.5], figure=fig)
    ax = fig.add_subplot(spec[1:, 0])
    axh = fig.add_subplot(spec[1:, 1], projection="3d")
    axm = fig.add_subplot(spec[0, 0:])
    divider = make_axes_locatable(ax)
    cax = divider.append_axes("right", size="5%", pad=0.5)

    x_new, y_new = np.meshgrid(np.unique(xs), np.unique(ys))
    try:
        z_new = griddata((xs, ys), zs, (x_new, y_new), method="cubic", fill_value=0)
    except Exception:
        z_new = griddata((xs, ys), zs, (x_new, y_new), method="nearest", fill_value=0)

    ps = ax.contourf(x_new, y_new, z_new, 128, cmap="jet", vmin=zmin, vmax=zmax, alpha=0.9)
    ax.imshow(im_Migne, extent=[16, 84, 40, 60], alpha=0.08)
    surf = axh.plot_surface(x_new, y_new, z_new, cmap="jet", vmin=zmin, vmax=zmax)
    ax.figure.colorbar(ps, cax=cax)

    axm.imshow(im_Migne, alpha=0.7)
    axm.axis("off")
    axh.view_init(elev=20, azim=300)
    
    # Handle set_box_aspect for Raspberry Pi compatibility
    try:
        axh.set_box_aspect((5, 5, 3.5))
    except AttributeError:
        pass  # Older matplotlib versions don't have this method
    
    axh.set_xlim([0, 100])
    axh.set_ylim([0, 100])
    axh.set_zlim([zmin, zmax])
    
    # Handle pane properties for Raspberry Pi compatibility
    try:
        axh.xaxis.pane.fill = False
        axh.yaxis.pane.fill = False
        axh.zaxis.pane.fill = False
        axh.xaxis.pane.set_edgecolor('w')
        axh.yaxis.pane.set_edgecolor('w')
        axh.zaxis.pane.set_edgecolor('w')
        axh.set_facecolor((0, 0, 0, 0))
    except AttributeError:
        pass  # Older matplotlib versions might not have these properties

    ax.set_xlim([0, 100])
    ax.set_ylim([0, 100])

    ax.set_title("Loaded Raw Data (2D)", fontsize=16, y=1.05)
    axh.set_title("Loaded Raw Data (3D)", fontsize=16, y=1.06)
    canvas.draw()

def resume_live():
    """Reset the plot to blank display and clear all data"""
    global pause_live, x, y, z, zmin, zmax, ax, axh, axm, cax
    pause_live = False
    # Clear all data buffers
    x.clear()
    y.clear()
    z.clear()
    # Reset z-axis limits to default
    zmin, zmax = -0.1, 0.1
    
    # Recreate the figure structure (same as in GUI setup)
    fig.clf()
    spec = gridspec.GridSpec(ncols=2, nrows=2, width_ratios=[5, 5], height_ratios=[1, 12.5], figure=fig)
    ax = fig.add_subplot(spec[1:, 0])
    axh = fig.add_subplot(spec[1:, 1], projection="3d")
    axm = fig.add_subplot(spec[0, 0:])
    divider = make_axes_locatable(ax)
    cax = divider.append_axes("right", size="5%", pad=0.5)
    
    initialize_blank_plot()
    canvas.draw()

# ---------------- GUI setup ----------------
th_ser = threading.Thread(target=read_loop, daemon=True)
th_ser.start()

root = tk.Tk()
root.title("Scan system ver.0.9R-stable9")
root.configure(bg="#e5e5e5")
root.attributes("-fullscreen", True)
root.bind("<Escape>", lambda e: root.attributes("-fullscreen", False))

main_frame = tk.Frame(root, bg="#e5e5e5")
main_frame.pack(fill=tk.BOTH, expand=True)
main_frame.grid_rowconfigure(0, weight=1)
main_frame.grid_columnconfigure(0, weight=1)
main_frame.grid_columnconfigure(1, weight=0)

plot_frame = tk.Frame(main_frame, bg="#e5e5e5")
plot_frame.grid(row=0, column=0, sticky="nsew")

controls_frame = tk.Frame(main_frame, bg="#d9d9d9", padx=6, pady=6, relief="ridge", bd=3)
controls_frame.grid(row=0, column=1, sticky="ns")

fig = plt.Figure(figsize=[13, 6], facecolor=(0.9, 0.9, 0.9))
spec = gridspec.GridSpec(ncols=2, nrows=2, width_ratios=[5, 5], height_ratios=[1, 12.5], figure=fig)
ax = fig.add_subplot(spec[1:, 0])
axh = fig.add_subplot(spec[1:, 1], projection="3d")
axm = fig.add_subplot(spec[0, 0:])
divider = make_axes_locatable(ax)
cax = divider.append_axes("right", size="5%", pad=0.5)
fig.subplots_adjust(left=0.08, right=0.92, bottom=0.08, top=0.92, hspace=0.25, wspace=0.25)
initialize_blank_plot()

canvas = FigureCanvasTkAgg(fig, master=plot_frame)
canvas_widget = canvas.get_tk_widget()
canvas_widget.pack(fill=tk.BOTH, expand=True)

hidden_toolbar = NavigationToolbar2Tk(canvas, root)
hidden_toolbar.pack_forget()

btn_style = {"font": ("Arial", 11, "bold"), "bg": "#f2f2f2", "width": 14, "height": 1, "relief": "raised"}

def safe_action(func):
    ani.event_source.stop()
    root.after(200, lambda: (func(), ani.event_source.start()))

def do_home(): safe_action(hidden_toolbar.home)
def do_pan(): safe_action(hidden_toolbar.pan)
def do_zoom(): safe_action(hidden_toolbar.zoom)
def do_save(): safe_action(hidden_toolbar.save_figure)
def do_reboot():
    if messagebox.askyesno("Reboot", "Reboot the system?"):
        os.system("sudo reboot")
def do_shutdown():
    if messagebox.askyesno("Shutdown", "Shutdown the system?"):
        os.system("sudo shutdown -h now")
def do_exit():
    if messagebox.askyesno("Exit", "Close the program?"):
        try: ser.close()
        except: pass
        if raw_file:
            raw_file.close()
        queue.put(None)
        saving_process.join()
        root.destroy()
        sys.exit(0)

# ---------------- Buttons ----------------
buttons = [
    ("📂 Load Raw File", load_raw_data),
    ("▶ Resume Live", resume_live),
    ("🔄 Reboot", do_reboot),
    ("⏻ Shutdown", do_shutdown),
    ("❌ Exit", do_exit),
]

for text, cmd in buttons:
    b = tk.Button(controls_frame, text=text, command=cmd, **btn_style)
    b.pack(pady=4, fill=tk.X)
    if text == "📂 Load Raw File":
        load_btn = b
    if text == "▶ Resume Live":
        resume_btn = b

# Initially enabled (buttons start enabled when no scan is active)
set_controls_state("normal")

def toggle_controls():
    if controls_frame.winfo_viewable():
        controls_frame.grid_remove()
    else:
        controls_frame.grid()
    root.update_idletasks()

toggle_btn = tk.Button(root, text="⚙️", font=("Arial", 14, "bold"), bg="#cccccc", relief="raised", width=3, height=1, command=toggle_controls)
toggle_btn.place(x=10, y=10)

xt, yt, zt = [], [], []
ani = animation.FuncAnimation(fig, update, fargs=(xt, yt, zt, zmin, zmax), interval=250, cache_frame_data=False, save_count=100)

canvas.draw()
root.mainloop()
queue.put(None)
saving_process.join()
