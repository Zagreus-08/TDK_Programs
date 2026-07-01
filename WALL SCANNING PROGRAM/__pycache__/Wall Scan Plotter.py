#!/usr/bin/env python3
import os
import sys
import time
import threading
import csv

import numpy as np

import tkinter as tk
from tkinter import messagebox, filedialog

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib import animation, gridspec
import matplotlib.tri as mtri

try:
    from PIL import ImageGrab
    HAS_IMAGEGRAB = True
except Exception:
    HAS_IMAGEGRAB = False

try:
    import serial
except ImportError:
    serial = None

# ---------------- Constants ----------------
MAX_POS = 270.0  # fixed max for X and Y axes (mm)
BAUDRATE = 115200

# Base directory for raw CSVs and auto-saved images
AUTO_SAVE_DIR = r"C:\Eduard_Files\BMS\XYZ Axis Stage\Migne Scanning for 3D Print\Mini XY Plotter\Scanning_Program"

SERIAL_PORT_CANDIDATES = [
    '/dev/ttyACM0',
    '/dev/ttyUSB0',
    'COM13',
    'COM4',
]

# ---------------- Serial Setup ----------------
ser = None
if serial is not None:
    for port in SERIAL_PORT_CANDIDATES:
        try:
            ser = serial.Serial(port, BAUDRATE, timeout=1)
            print(f"[INFO] Opened serial port: {port}")
            break
        except Exception:
            continue

if ser is None:
    print("[WARNING] No serial port available. Running in demo mode (no live data).")

# ---------------- Global vars ----------------
# Data buffers: x, y positions and two voltage channels
x, y, z1, z2 = [], [], [], []

# Z-range (color scale) – shared by both plots
zmin, zmax = -0.1, 0.1

# X/Y extents (we still track, but display is fixed 0–270)
x_range = MAX_POS
y_max = MAX_POS

raw_file = None
csv_writer = None
current_filename = None
loaded_filename = None

pause_live = False       # True when viewing loaded data (no live updates)
scan_active = True       # True while hardware scan is ongoing
last_data_time = time.time()

# Z-range lock feature
z_range_locked = False
locked_zmin = -0.1
locked_zmax = 0.1

# Loaded data cache for re-rendering with adjusted Z-range
loaded_data_cache = None

# GUI globals (axes, canvas, etc.)
root = None
fig = None
ax = None         # left 2D (V1)
axh = None        # right 2D (V2)
axm = None        # top header/image axis
cax = None        # shared colorbar axis in the middle
cbar = None       # persistent Colorbar object
canvas = None
ani = None

# Buttons and controls
load_btn = None
resume_btn = None
z_lock_checkbox = None
adjust_range_btn = None

# Migne image
im_Migne = None
possible_image_paths = [
    r"C:\Eduard_Files\BMS\XYZ Axis Stage\Migne Scanning for 3D Print\Mini XY Plotter\Scanning_Program\Nivio_S.png",
    os.path.join(os.path.expanduser('~'), 'Downloads', 'Nivio_S.png'),
    os.path.join(os.path.dirname(__file__), 'Nivio_S.png'),
]
for p in possible_image_paths:
    if os.path.exists(p):
        try:
            im_Migne = plt.imread(p)
            print(f"[INFO] Loaded Migne image from: {p}")
            break
        except Exception as e:
            print(f"[WARNING] Failed to load image from {p}: {e}")
            continue
if im_Migne is None:
    print("[WARNING] Migne image not found. Continuing without background image.")

# ---------------- Button state control ----------------
def set_controls_state(state):
    """Enable or disable Load Raw, Resume Live, and Z-lock controls"""
    global load_btn, resume_btn, z_lock_checkbox, adjust_range_btn
    try:
        print(f"[DEBUG] Setting button state to: {state}")
        if load_btn is not None:
            load_btn.config(state=state)
        if resume_btn is not None:
            resume_btn.config(state=state)

        if z_lock_checkbox is not None:
            z_lock_checkbox.config(state=state)
        if adjust_range_btn is not None:
            if state == "normal" and z_range_locked:
                adjust_range_btn.config(state="normal")
            else:
                adjust_range_btn.config(state="disabled")

        print(f"[DEBUG] Buttons successfully set to: {state}")
    except Exception as e:
        print(f"[ERROR] Failed to set button state: {e}")

# ---------------- Serial timeout checker ----------------
def check_serial_timeout():
    """Check if serial data has stopped coming and re-enable buttons if needed"""
    global scan_active, last_data_time
    try:
        current_time = time.time()
        time_since_last_data = current_time - last_data_time

        if scan_active and time_since_last_data > 5.0:
            print(f"[INFO] Timeout reached ({time_since_last_data:.1f}s), re-enabling buttons")
            scan_active = False
            set_controls_state("normal")

        root.after(1000, check_serial_timeout)
    except Exception as e:
        print(f"[ERROR] check_serial_timeout: {e}")
        try:
            root.after(1000, check_serial_timeout)
        except Exception:
            pass

# ---------------- Raw Data Handling ----------------
def start_new_raw_file(name_hint=""):
    """Start a new CSV for saving live scan data"""
    global raw_file, csv_writer, current_filename
    if not name_hint:
        name_hint = time.strftime("%Y%m%d_%H%M%S")

    raw_dir = r"C:\Eduard_Files\BMS\XYZ Axis Stage\Migne Scanning for 3D Print\Mini XY Plotter\Scanning_Program"
    os.makedirs(raw_dir, exist_ok=True)
    raw_path = os.path.join(raw_dir, f"{name_hint}.csv")

    try:
        raw_file = open(raw_path, "w", newline="")
        csv_writer = csv.writer(raw_file)
        csv_writer.writerow(["x", "y", "v1", "v2"])  # new format
        current_filename = raw_path
        print(f"[INFO] Started raw data file: {raw_path}")
    except Exception as e:
        print(f"[ERROR] Could not create raw file: {e}")
        raw_file = None
        csv_writer = None

# ---------------- Save figures ----------------
def save_figure_direct(filename):
    """Save the current figure directly (no multiprocessing)"""
    global fig
    try:
        width_inches = 800 / 100
        height_inches = 480 / 100

        original_size = fig.get_size_inches()
        fig.set_size_inches(width_inches, height_inches)
        fig.savefig(filename, dpi=100, bbox_inches=None)
        fig.set_size_inches(original_size)

        print(f"[INFO] Figure saved successfully to: {filename}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to save figure: {e}")
        try:
            fig.set_size_inches(original_size)
        except Exception:
            pass
        return False

def auto_save_current_figure():
    """
    Automatically save the current figure when a scan finishes.

    - On systems where PIL.ImageGrab works (e.g. Windows, Raspberry Pi with X11),
      it captures a screenshot of the plotting widget so the saved image matches
      exactly what is on screen.

    - If screenshotting is not available or fails (e.g. headless Pi),
      it falls back to saving via fig.savefig.
    """
    global current_filename, canvas

    # Decide base name (same as raw CSV, without extension)
    if current_filename:
        base_name = os.path.splitext(os.path.basename(current_filename))[0]
    else:
        base_name = time.strftime("%Y%m%d_%H%M%S")

    # Build full path in AUTO_SAVE_DIR
    os.makedirs(AUTO_SAVE_DIR, exist_ok=True)
    image_path = os.path.join(AUTO_SAVE_DIR, base_name + ".png")

    # -------- Try screenshot first (if available) --------
    if HAS_IMAGEGRAB:
        try:
            widget = canvas.get_tk_widget()
            widget.update_idletasks()

            x = widget.winfo_rootx()
            y = widget.winfo_rooty()
            w = widget.winfo_width()
            h = widget.winfo_height()
            bbox = (x, y, x + w, y + h)

            screenshot = ImageGrab.grab(bbox=bbox)
            screenshot.save(image_path)
            print(f"[INFO] Auto-screenshot saved to: {image_path}")
            return
        except Exception as e:
            print(f"[WARNING] Screenshot save failed ({e}). Falling back to fig.savefig.")

    # -------- Fallback: use Matplotlib's fig.savefig --------
    try:
        save_figure_direct(image_path)
        print(f"[INFO] Auto-saved figure via fig.savefig to: {image_path}")
    except Exception as e:
        print(f"[ERROR] Auto-save via fig.savefig failed: {e}")

# ---------------- Initialize blank plot ----------------
def initialize_blank_plot():
    global ax, axh, axm  # NOTE: cbar is intentionally not touched here

    ax.cla()
    axh.cla()
    axm.cla()

    # Fixed ranges 0–270 mm
    ax.set_xlim(0, MAX_POS)
    ax.set_ylim(0, MAX_POS)
    axh.set_xlim(0, MAX_POS)
    axh.set_ylim(0, MAX_POS)

    # Ticks every 27 mm (0, 27, 54, ..., 270)
    ticks = np.linspace(0, MAX_POS, 11)
    ax.set_xticks(ticks)
    ax.set_yticks(ticks)
    axh.set_xticks(ticks)
    axh.set_yticks(ticks)

    ax.grid(True, linestyle="--", alpha=0.7)
    ax.set_facecolor("white")
    axh.grid(True, linestyle="--", alpha=0.7)
    axh.set_facecolor("white")

    ax.set_xlabel("X position (mm)")
    ax.set_ylabel("Y position (mm)")
    axh.set_xlabel("X position (mm)")
    axh.set_ylabel("Y position (mm)")

    # Titles
    ax.set_title("X Data", fontsize=12, pad=20)
    axh.set_title("Y Data", fontsize=12, pad=20)

    if im_Migne is not None:
        axm.imshow(im_Migne, alpha=0.7)
        axm.axis("off")
    else:
        axm.set_axis_off()

# ---------------- Live update animation ----------------
def update(i, xt, yt, zt, zmin_arg, zmax_arg):
    global ax, axh, axm, cax, cbar
    global zmin, zmax, current_filename

    if pause_live or len(x) < 2:
        return

    xs = np.array(x, dtype=float)
    ys = np.array(y, dtype=float)
    zs1 = np.array(z1, dtype=float)
    zs2 = np.array(z2, dtype=float)

    n = min(len(xs), len(ys), len(zs1), len(zs2))
    if n < 2:
        return
    xs, ys, zs1, zs2 = xs[:n], ys[:n], zs1[:n], zs2[:n]

    # Keep only points within 0–270 mm
    mask = (xs >= 0) & (xs <= MAX_POS) & (ys >= 0) & (ys <= MAX_POS)
    xs, ys, zs1, zs2 = xs[mask], ys[mask], zs1[mask], zs2[mask]
    if len(xs) < 2:
        return

    # Per-channel actual ranges (for labels)
    v1_zmin = float(zs1.min())
    v1_zmax = float(zs1.max())
    v2_zmin = float(zs2.min())
    v2_zmax = float(zs2.max())

    # Shared Z range for colorbar / colormap
    actual_zmin = min(v1_zmin, v2_zmin)
    actual_zmax = max(v1_zmax, v2_zmax)
    if not z_range_locked:
        zmin, zmax = actual_zmin, actual_zmax
    else:
        zmin, zmax = locked_zmin, locked_zmax

    ax.cla()
    axh.cla()
    axm.cla()

    # Decide if data is truly 2D (enough unique X and Y points)
    unique_x = np.unique(xs)
    unique_y = np.unique(ys)
    has_2d_structure = (len(unique_x) >= 2) and (len(unique_y) >= 2) and (len(xs) >= 3)

    # ---- Left plot: X Data (V1) ----
    if has_2d_structure:
        try:
            triang1 = mtri.Triangulation(xs, ys)
            cs1 = ax.tricontourf(triang1, zs1, 128, cmap="jet", vmin=zmin, vmax=zmax)
        except Exception:
            cs1 = ax.scatter(xs, ys, c=zs1, cmap="jet", vmin=zmin, vmax=zmax)
    else:
        cs1 = ax.scatter(xs, ys, c=zs1, cmap="jet", vmin=zmin, vmax=zmax)

    ax.set_xlabel("X position (mm)")
    ax.set_ylabel("Y position (mm)")
    ax.set_title("X Data", fontsize=12, pad=20)
    ax.grid(True, linestyle="--", alpha=0.7)
    ax.set_xlim(0, MAX_POS)
    ax.set_ylim(0, MAX_POS)

    ticks = np.linspace(0, MAX_POS, 11)  # 0, 27, 54, ..., 270
    ax.set_xticks(ticks)
    ax.set_yticks(ticks)

    # Z labels for X Data (top-left, just above the plot)
    ax.text(0.02, 1.04, f"Z max: {v1_zmax:.3f}",
            transform=ax.transAxes, ha="left", va="bottom", fontsize=9, color="black")
    ax.text(0.02, 1.00, f"Z min: {v1_zmin:.3f}",
            transform=ax.transAxes, ha="left", va="bottom", fontsize=9, color="black")

    # ---- Right plot: Y Data (V2) ----
    if has_2d_structure:
        try:
            triang2 = mtri.Triangulation(xs, ys)
            cs2 = axh.tricontourf(triang2, zs2, 128, cmap="jet", vmin=zmin, vmax=zmax)
        except Exception:
            cs2 = axh.scatter(xs, ys, c=zs2, cmap="jet", vmin=zmin, vmax=zmax)
    else:
        cs2 = axh.scatter(xs, ys, c=zs2, cmap="jet", vmin=zmin, vmax=zmax)

    axh.set_xlabel("X position (mm)")
    axh.set_ylabel("Y position (mm)")
    axh.set_title("Y Data", fontsize=12, pad=20)
    axh.grid(True, linestyle="--", alpha=0.7)
    axh.set_xlim(0, MAX_POS)
    axh.set_ylim(0, MAX_POS)

    axh.set_xticks(ticks)
    axh.set_yticks(ticks)

    # Z labels for Y Data (top-left, just above the plot)
    axh.text(0.02, 1.04, f"Z max: {v2_zmax:.3f}",
             transform=axh.transAxes, ha="left", va="bottom", fontsize=9, color="black")
    axh.text(0.02, 1.00, f"Z min: {v2_zmin:.3f}",
             transform=axh.transAxes, ha="left", va="bottom", fontsize=9, color="black")

    # Shared colorbar in the middle – keep it, do not remove each frame
    try:
        if cbar is None:
            cbar = fig.colorbar(cs1, cax=cax)
        else:
            cbar.update_normal(cs1)
    except Exception as e:
        print(f"[WARNING] Colorbar failed: {e}")

    # Header axis
    if im_Migne is not None:
        axm.imshow(im_Migne, alpha=0.7)
    axm.axis("off")

    display_name = ""
    if current_filename:
        base_name = os.path.splitext(os.path.basename(current_filename))[0]
        if base_name.startswith("raw_"):
            base_name = base_name[4:]
        display_name = f"Live Scan: {base_name}"

    if display_name:
        axm.text(0.5, -0.1, display_name, transform=axm.transAxes,
                 ha='center', va='top', fontsize=10, color='black', weight='bold')

    axm.text(0.01, 0.95, f"Z range (global): {zmin:.6f} to {zmax:.6f}",
             transform=axm.transAxes, fontsize=9, color='black')

    try:
        canvas.draw()
    except Exception:
        pass

# ---------------- Load Raw CSV ----------------
def load_raw_data():
    global pause_live, loaded_filename
    pause_live = True

    raw_dir = r"C:\Eduard_Files\BMS\XYZ Axis Stage\Migne Scanning for 3D Print\Mini XY Plotter\Scanning_Program"
    if not os.path.isdir(raw_dir):
        raw_dir = os.getcwd()

    file_path = filedialog.askopenfilename(
        title="Select Raw CSV File",
        initialdir=raw_dir,
        filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
    )
    if not file_path:
        pause_live = False
        return

    try:
        data = np.loadtxt(file_path, delimiter=",", skiprows=1)
        if data.ndim == 1:
            data = data.reshape(1, -1)
        xs, ys, zs1, zs2 = data[:, 0], data[:, 1], data[:, 2], data[:, 3]
        loaded_filename = file_path
        show_loaded(xs, ys, zs1, zs2)
        print(f"[INFO] Loaded file: {loaded_filename}")
    except Exception as e:
        messagebox.showerror("Error", f"Failed to load file:\n{e}")
        pause_live = False
        loaded_filename = None

def show_loaded(xs, ys, zs1, zs2):
    global zmin, zmax, ax, axh, axm, cax, cbar
    global x_range, y_max, loaded_data_cache

    xs = np.array(xs, dtype=float)
    ys = np.array(ys, dtype=float)
    zs1 = np.array(zs1, dtype=float)
    zs2 = np.array(zs2, dtype=float)

    n = min(len(xs), len(ys), len(zs1), len(zs2))
    if n < 2:
        messagebox.showerror("Error", "Loaded CSV has insufficient data.")
        return
    xs, ys, zs1, zs2 = xs[:n], ys[:n], zs1[:n], zs2[:n]

    # Keep only points within 0–270 mm
    mask = (xs >= 0) & (xs <= MAX_POS) & (ys >= 0) & (ys <= MAX_POS)
    xs, ys, zs1, zs2 = xs[mask], ys[mask], zs1[mask], zs2[mask]
    if len(xs) < 2:
        messagebox.showerror("Error", "Loaded CSV has insufficient data after filtering.")
        return

    x_range = MAX_POS
    y_max = MAX_POS

    # Per-channel actual ranges (for labels)
    v1_zmin = float(zs1.min())
    v1_zmax = float(zs1.max())
    v2_zmin = float(zs2.min())
    v2_zmax = float(zs2.max())

    # Shared actual range
    actual_zmin = min(v1_zmin, v2_zmin)
    actual_zmax = max(v1_zmax, v2_zmax)

    loaded_data_cache = {
        'xs': xs.copy(),
        'ys': ys.copy(),
        'zs1': zs1.copy(),
        'zs2': zs2.copy(),
        'actual_zmin': actual_zmin,
        'actual_zmax': actual_zmax
    }

    if not z_range_locked:
        zmin, zmax = actual_zmin, actual_zmax
    else:
        zmin, zmax = locked_zmin, locked_zmax

    # When rebuilding the figure, the old colorbar belongs to old axes – remove once here
    if cbar is not None:
        try:
            cbar.remove()
        except Exception:
            pass
        cbar = None

    fig.clf()
    spec = gridspec.GridSpec(
        ncols=3, nrows=2,
        width_ratios=[5, 0.3, 5],
        height_ratios=[1, 12.5],
        figure=fig
    )

    ax = fig.add_subplot(spec[1:, 0])
    axh = fig.add_subplot(spec[1:, 2])
    axm = fig.add_subplot(spec[0, 0:])
    cax = fig.add_subplot(spec[1:, 1])
    cbar = None  # will be created below

    unique_x = np.unique(xs)
    unique_y = np.unique(ys)
    has_2d_structure = (len(unique_x) >= 2) and (len(unique_y) >= 2) and (len(xs) >= 3)

    if has_2d_structure:
        triang1 = mtri.Triangulation(xs, ys)
        triang2 = mtri.Triangulation(xs, ys)
        cs1 = ax.tricontourf(triang1, zs1, 128, cmap="jet", vmin=zmin, vmax=zmax)
        cs2 = axh.tricontourf(triang2, zs2, 128, cmap="jet", vmin=zmin, vmax=zmax)
    else:
        cs1 = ax.scatter(xs, ys, c=zs1, cmap="jet", vmin=zmin, vmax=zmax)
        cs2 = axh.scatter(xs, ys, c=zs2, cmap="jet", vmin=zmin, vmax=zmax)

    ax.set_xlabel("X position (mm)")
    ax.set_ylabel("Y position (mm)")
    ax.set_title("Loaded X Data", fontsize=12, pad=20)
    ax.grid(True, linestyle="--", alpha=0.7)
    ax.set_xlim(0, MAX_POS)
    ax.set_ylim(0, MAX_POS)

    axh.set_xlabel("X position (mm)")
    axh.set_ylabel("Y position (mm)")
    axh.set_title("Loaded Y Data", fontsize=12, pad=20)
    axh.grid(True, linestyle="--", alpha=0.7)
    axh.set_xlim(0, MAX_POS)
    axh.set_ylim(0, MAX_POS)

    ticks = np.linspace(0, MAX_POS, 11)
    ax.set_xticks(ticks)
    ax.set_yticks(ticks)
    axh.set_xticks(ticks)
    axh.set_yticks(ticks)

    # Z labels for X Data (top-left)
    ax.text(0.02, 1.04, f"Z max: {v1_zmax:.3f}",
            transform=ax.transAxes, ha="left", va="bottom", fontsize=9, color="black")
    ax.text(0.02, 1.00, f"Z min: {v1_zmin:.3f}",
            transform=ax.transAxes, ha="left", va="bottom", fontsize=9, color="black")

    # Z labels for Y Data (top-left)
    axh.text(0.02, 1.04, f"Z max: {v2_zmax:.3f}",
             transform=axh.transAxes, ha="left", va="bottom", fontsize=9, color="black")
    axh.text(0.02, 1.00, f"Z min: {v2_zmin:.3f}",
             transform=axh.transAxes, ha="left", va="bottom", fontsize=9, color="black")

    # Shared colorbar for loaded data
    try:
        cbar = fig.colorbar(cs1, cax=cax)
    except Exception as e:
        print(f"[WARNING] Colorbar (loaded) failed: {e}")

    if im_Migne is not None:
        axm.imshow(im_Migne, alpha=0.7)
    axm.axis("off")
    axm.text(0.01, 0.95, f"Z range (global): {zmin:.6f} to {zmax:.6f}",
             transform=axm.transAxes, fontsize=9, color='black')

    try:
        canvas.draw()
    except Exception:
        pass

# ---------------- Resume live ----------------
def resume_live():
    """Reset the plot to blank display and clear all data"""
    global pause_live, x, y, z1, z2
    global zmin, zmax, loaded_filename, loaded_data_cache

    pause_live = False
    loaded_filename = None
    loaded_data_cache = None

    x.clear()
    y.clear()
    z1.clear()
    z2.clear()

    zmin, zmax = -0.1, 0.1

    initialize_blank_plot()
    try:
        canvas.draw()
    except Exception:
        pass

# ---------------- Z-range lock UI ----------------
def setup_z_lock_controls(parent_frame):
    global z_lock_checkbox, adjust_range_btn
    global z_range_locked, locked_zmin, locked_zmax

    z_lock_frame = tk.Frame(parent_frame, bg="#d9d9d9")
    z_lock_frame.pack(pady=8, fill=tk.X)

    z_lock_var = tk.BooleanVar(value=False)

    z_range_label = tk.Label(
        z_lock_frame,
        text="Auto-range enabled",
        font=("Arial", 9),
        bg="#d9d9d9",
        fg="green",
        wraplength=150,
        justify="left"
    )
    z_range_label.pack(anchor="w", padx=5, pady=2)

    def open_adjust_dialog():
        global locked_zmin, locked_zmax, loaded_data_cache

        dialog = tk.Toplevel(root)
        dialog.title("Adjust Z-Range")
        dialog.geometry("350x250")
        dialog.configure(bg="#e5e5e5")
        dialog.resizable(False, False)
        dialog.transient(root)
        dialog.grab_set()

        current_zmin = tk.DoubleVar(value=locked_zmin)
        current_zmax = tk.DoubleVar(value=locked_zmax)

        # Z Min
        tk.Label(dialog, text="Z Min:", font=("Arial", 12, "bold"),
                 bg="#e5e5e5").grid(row=0, column=0, padx=10, pady=15, sticky="w")
        zmin_frame = tk.Frame(dialog, bg="#e5e5e5")
        zmin_frame.grid(row=0, column=1, columnspan=3, padx=10, pady=15)

        zmin_entry = tk.Entry(zmin_frame, font=("Arial", 12, "bold"),
                              width=10, justify="center", relief="sunken", bd=2)
        zmin_entry.insert(0, f"{current_zmin.get():.3f}")
        zmin_entry.pack(side=tk.LEFT, padx=5)

        def update_zmin(delta):
            try:
                current_val = float(zmin_entry.get())
                new_val = current_val + delta
                current_zmin.set(new_val)
                zmin_entry.delete(0, tk.END)
                zmin_entry.insert(0, f"{new_val:.3f}")
            except ValueError:
                pass

        tk.Button(zmin_frame, text="-0.1", command=lambda: update_zmin(-0.1),
                  font=("Arial", 10, "bold"), bg="#ff9800", fg="white", width=5)\
            .pack(side=tk.LEFT, padx=2)
        tk.Button(zmin_frame, text="+0.1", command=lambda: update_zmin(0.1),
                  font=("Arial", 10, "bold"), bg="#ff9800", fg="white", width=5)\
            .pack(side=tk.LEFT, padx=2)

        # Z Max
        tk.Label(dialog, text="Z Max:", font=("Arial", 12, "bold"),
                 bg="#e5e5e5").grid(row=1, column=0, padx=10, pady=15, sticky="w")
        zmax_frame = tk.Frame(dialog, bg="#e5e5e5")
        zmax_frame.grid(row=1, column=1, columnspan=3, padx=10, pady=15)

        zmax_entry = tk.Entry(zmax_frame, font=("Arial", 12, "bold"),
                              width=10, justify="center", relief="sunken", bd=2)
        zmax_entry.insert(0, f"{current_zmax.get():.3f}")
        zmax_entry.pack(side=tk.LEFT, padx=5)

        def update_zmax(delta):
            try:
                current_val = float(zmax_entry.get())
                new_val = current_val + delta
                current_zmax.set(new_val)
                zmax_entry.delete(0, tk.END)
                zmax_entry.insert(0, f"{new_val:.3f}")
            except ValueError:
                pass

        tk.Button(zmax_frame, text="-0.1", command=lambda: update_zmax(-0.1),
                  font=("Arial", 10, "bold"), bg="#ff9800", fg="white", width=5)\
            .pack(side=tk.LEFT, padx=2)
        tk.Button(zmax_frame, text="+0.1", command=lambda: update_zmax(0.1),
                  font=("Arial", 10, "bold"), bg="#ff9800", fg="white", width=5)\
            .pack(side=tk.LEFT, padx=2)

        def apply_changes():
            global locked_zmin, locked_zmax, z_range_locked
            try:
                new_zmin = float(zmin_entry.get())
                new_zmax = float(zmax_entry.get())
                if new_zmin >= new_zmax:
                    messagebox.showerror("Invalid Range", "Z Min must be less than Z Max!")
                    return

                locked_zmin = new_zmin
                locked_zmax = new_zmax
                z_range_label.config(text=f"Locked: {locked_zmin:.3f} to {locked_zmax:.3f}", fg="red")
                print(f"[INFO] Z-range adjusted to [{locked_zmin:.3f}, {locked_zmax:.3f}]")

                if pause_live and loaded_data_cache is not None:
                    show_loaded(loaded_data_cache['xs'],
                                loaded_data_cache['ys'],
                                loaded_data_cache['zs1'],
                                loaded_data_cache['zs2'])
                dialog.destroy()
            except ValueError:
                messagebox.showerror("Invalid Input", "Please enter valid numbers!")

        btn_frame = tk.Frame(dialog, bg="#e5e5e5")
        btn_frame.grid(row=2, column=0, columnspan=4, pady=20)

        tk.Button(btn_frame, text="Apply", command=apply_changes,
                  font=("Arial", 11, "bold"), bg="#4CAF50", fg="white",
                  width=10, height=2).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Cancel", command=dialog.destroy,
                  font=("Arial", 11, "bold"), bg="#f44336", fg="white",
                  width=10, height=2).pack(side=tk.LEFT, padx=5)

    def toggle_z_lock():
        global z_range_locked, locked_zmin, locked_zmax, zmin, zmax
        z_range_locked = z_lock_var.get()
        if z_range_locked:
            locked_zmin = zmin
            locked_zmax = zmax
            z_range_label.config(text=f"Locked: {locked_zmin:.3f} to {locked_zmax:.3f}", fg="red")
            print(f"[INFO] Z-range locked at [{locked_zmin:.3f}, {locked_zmax:.3f}]")
            adjust_range_btn.config(state="normal")
        else:
            z_range_label.config(text="Auto-range enabled", fg="green")
            print("[INFO] Z-range unlocked - auto-ranging enabled")
            adjust_range_btn.config(state="disabled")

    z_lock_checkbox = tk.Checkbutton(
        z_lock_frame,
        text="Lock Z-Range",
        variable=z_lock_var,
        command=toggle_z_lock,
        font=("Arial", 10, "bold"),
        bg="#d9d9d9",
        activebackground="#d9d9d9",
        selectcolor="#ffcc00"
    )
    z_lock_checkbox.pack(anchor="w", padx=5)

    adjust_range_btn = tk.Button(
        z_lock_frame,
        text="Adjust Range",
        command=open_adjust_dialog,
        font=("Arial", 9, "bold"),
        bg="#f2f2f2",
        width=12,
        state="disabled"
    )
    adjust_range_btn.pack(anchor="w", padx=5, pady=5)

# ---------------- Serial loop ----------------
def read_loop():
    global raw_file, csv_writer, current_filename
    global scan_active, last_data_time, pause_live
    global x_range, y_max, zmin, zmax

    data_cnt = 0
    filename_from_serial = ""

    while True:
        if ser is None:
            time.sleep(1.0)
            continue

        rcv_data = ser.readline()
        if len(rcv_data) == 0:
            if pause_live:
                time.sleep(0.2)
            continue

        try:
            parts = rcv_data.decode("ascii", errors="ignore").strip().split(",")
            if len(parts) < 4:
                continue

            # Format: X, Y, V1, V2, filename
            x0 = float(parts[0])
            y0 = float(parts[1])
            v1 = float(parts[2])
            v2 = float(parts[3])
            filename_field = parts[4].strip() if len(parts) >= 5 else ""

            last_data_time = time.time()

            # Print received serial data
            print(f"Serial data: x={x0:.3f}, y={y0:.3f}, v1={v1:.6f}, v2={v2:.6f}, file='{filename_field}'")

        except (ValueError, IndexError):
            print("data error @count=", data_cnt)
            continue

        # ---------- Auto-resume live when data comes while paused ----------
        if pause_live:
            print("[INFO] Serial data received while viewing loaded data. Auto-resuming live scan.")
            pause_live = False
            x.clear()
            y.clear()
            z1.clear()
            z2.clear()
            scan_active = True
            filename_from_serial = ""
            root.after(0, lambda: (resume_live(), set_controls_state("disabled")))

        # ---------- New scan detection: (0,0) ----------
        if x0 == 0.0 and y0 == 0.0:
            print("[INFO] New scan detected (0,0). Resetting everything...")

            if raw_file:
                try:
                    raw_file.close()
                    print(f"[INFO] Closed previous raw file: {current_filename}")
                except Exception:
                    pass

            # Clear all buffers
            x.clear()
            y.clear()
            z1.clear()
            z2.clear()

            # Reset state
            raw_file = None
            csv_writer = None
            current_filename = None
            filename_from_serial = ""
            scan_active = True
            data_cnt = 0

            x_range = MAX_POS
            y_max = MAX_POS

            if not z_range_locked:
                zmin, zmax = -0.1, 0.1
                print(f"[INFO] Reset color bar range to zmin={zmin}, zmax={zmax}")
            else:
                print(f"[INFO] Z-range locked at zmin={locked_zmin}, zmax={locked_zmax}")

            # Clear plot immediately on GUI thread
            root.after(0, lambda: (initialize_blank_plot(), canvas.draw(), set_controls_state("disabled")))

            # Start new raw file if filename is provided
            if filename_field:
                filename_from_serial = filename_field
                start_new_raw_file(filename_from_serial)
                print(f"[INFO] Started new scan with filename: {filename_from_serial}")

            # Also treat this (0,0) as a real data point
            x.append(x0)
            y.append(y0)
            z1.append(v1)
            z2.append(v2)
            if csv_writer:
                try:
                    csv_writer.writerow([x0, y0, v1, v2])
                except Exception as e:
                    print(f"[WARNING] Failed to write CSV row: {e}")

            continue

        # ---------- Detect filename if it comes after (0,0) ----------
        elif filename_field and not filename_from_serial and scan_active:
            filename_from_serial = filename_field
            start_new_raw_file(filename_from_serial)
            print(f"[INFO] Started raw file with filename: {filename_from_serial}")

        data_cnt += 1

        # Append new data
        x.append(x0)
        y.append(y0)
        z1.append(v1)
        z2.append(v2)

        if csv_writer:
            try:
                csv_writer.writerow([x0, y0, v1, v2])
            except Exception as e:
                print(f"[WARNING] Failed to write CSV row: {e}")

        # ---------- End-of-scan detection: (270,270) ----------
        # Use MAX_POS (270.0) as the marker for “scan finished”.
        if abs(x0 - MAX_POS) < 1e-3 and abs(y0 - MAX_POS) < 1e-3:
            print("[INFO] End-of-scan marker (270,270) detected.")
            scan_active = False
            filename_from_serial = ""

            # Auto-save figure on GUI thread
            root.after(0, auto_save_current_figure)

            # Re-enable buttons on GUI thread
            root.after(0, lambda: set_controls_state("normal"))

            last_data_time = time.time()

# ---------------- Main ----------------
if __name__ == '__main__':
    th_ser = threading.Thread(target=read_loop, daemon=True)
    th_ser.start()

    root = tk.Tk()
    root.title("Ver2.1_Migne_Realtime_Plotter (2×2D, 0–270 mm)")
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
    spec = gridspec.GridSpec(
        ncols=3, nrows=2,
        width_ratios=[5, 0.3, 5],  # middle narrow column for colorbar
        height_ratios=[1, 12.5],
        figure=fig
    )

    ax = fig.add_subplot(spec[1:, 0])      # left 2D V1
    axh = fig.add_subplot(spec[1:, 2])     # right 2D V2
    axm = fig.add_subplot(spec[0, 0:])     # header image/title
    cax = fig.add_subplot(spec[1:, 1])     # shared colorbar in the middle

    fig.subplots_adjust(left=0.08, right=0.92, bottom=0.08, top=0.92,
                        hspace=0.25, wspace=0.25)

    initialize_blank_plot()

    canvas = FigureCanvasTkAgg(fig, master=plot_frame)
    canvas_widget = canvas.get_tk_widget()
    canvas_widget.pack(fill=tk.BOTH, expand=True)

    hidden_toolbar = NavigationToolbar2Tk(canvas, root)
    hidden_toolbar.pack_forget()

    btn_style = {
        "font": ("Arial", 11, "bold"),
        "bg": "#f2f2f2",
        "width": 10,
        "height": 2,
        "relief": "raised"
    }

    def safe_action(func):
        ani.event_source.stop()
        root.after(200, lambda: (func(), ani.event_source.start()))

    def do_home():
        safe_action(hidden_toolbar.home)

    def do_pan():
        safe_action(hidden_toolbar.pan)

    def do_zoom():
        safe_action(hidden_toolbar.zoom)

    def do_save():
        def custom_save():
            save_dir = r"C:\Eduard_Files\BMS\XYZ Axis Stage\Migne Scanning for 3D Print\Mini XY Plotter\Scanning_Program"
            os.makedirs(save_dir, exist_ok=True)
            filename = filedialog.asksaveasfilename(
                title="Save Figure",
                defaultextension=".png",
                initialdir=save_dir,
                filetypes=[("PNG Image", "*.png"), ("All Files", "*.*")]
            )
            if filename:
                save_figure_direct(filename)

        safe_action(custom_save)

    def do_reboot():
        if messagebox.askyesno("Reboot", "Reboot the system?"):
            os.system("sudo reboot")

    def do_shutdown():
        if messagebox.askyesno("Shutdown", "Shutdown the system?"):
            os.system("sudo shutdown -h now")

    def do_exit():
        if messagebox.askyesno("Exit", "Close the program?"):
            try:
                if ser is not None:
                    ser.close()
            except Exception:
                pass
            if raw_file:
                try:
                    raw_file.close()
                except Exception:
                    pass
            root.destroy()
            sys.exit(0)

    buttons = [
        ("Load Raw File", load_raw_data),
        ("Live Scan", resume_live),
        ("Save", do_save),
        ("Reboot", do_reboot),
        ("Shutdown", do_shutdown),
        ("Exit", do_exit),
    ]

    for text, cmd in buttons:
        b = tk.Button(controls_frame, text=text, command=cmd, **btn_style)
        b.pack(pady=4, fill=tk.X)
        if text == "Load Raw File":
            load_btn = b
        if text == "Live Scan":
            resume_btn = b

    separator = tk.Frame(controls_frame, height=2, bg="#999999")
    separator.pack(pady=8, fill=tk.X)

    setup_z_lock_controls(controls_frame)

    set_controls_state("normal")
    root.after(1000, check_serial_timeout)

    def toggle_controls():
        if controls_frame.winfo_viewable():
            controls_frame.grid_remove()
        else:
            controls_frame.grid()
        root.update_idletasks()

    toggle_btn = tk.Button(root, text="⚙️", font=("Arial", 14, "bold"),
                           bg="#cccccc", relief="raised", width=3, height=1,
                           command=toggle_controls)
    toggle_btn.place(x=10, y=10)

    xt, yt, zt = [], [], []
    ani = animation.FuncAnimation(
        fig, update,
        fargs=(xt, yt, zt, zmin, zmax),
        interval=250,
        cache_frame_data=False,
        save_count=100
    )

    canvas.draw()
    root.mainloop()