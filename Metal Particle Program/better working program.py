#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Scan system for long loop - Auto-start version (Fullscreen + Toggleable Controls)
Ver 0.9R-stable12   2025-11-05  (Independent X/Y dimensions)

FEATURES:
- Auto-detects scan dimensions from hardware (X: 50-300, Y: auto-detected)
- Saves raw CSV data for all scan sizes
- Auto-saves PNG at end of scan
- Loads and displays any size raw data (50x50 to 300x300)
- Maintains square 2D display with proper axis scaling
- X and Y dimensions are now independent (supports 100x200, 200x100, etc.)
- X-Lim manual buttons and label removed
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
import threading
import serial
import time
import tkinter as tk
from tkinter import messagebox, filedialog
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

# ---------------- Global vars ----------------
x, y, z = [], [], []
zmin, zmax = -0.1, 0.1
fixed_zmin, fixed_zmax = -0.1, 0.1  # Fixed range for colorbar when locked
use_fixed_range = False  # Toggle for fixed vs auto colorbar range
x_range = 100  # Default X-axis range (50-300)
y_max = 100    # Auto-detected Y-axis maximum from hardware
raw_file = None
csv_writer = None
current_filename = None
loaded_filename = None   # Track filename of loaded raw data for saving
pause_live = False       # used when user loads a CSV and wants to pause live updates
scan_active = False      # True while an active scan is happening; becomes False after end-of-scan
last_data_time = time.time()  # Track when we last received serial data

# ---------------- Image ----------------
try:
    im_Migne = plt.imread('/home/pi/Desktop/Migne_black_frameless.png')
except FileNotFoundError:
    print("[WARNING] Migne image not found, creating blank placeholder")
    im_Migne = np.ones((100, 100, 4)) * 0.5  # Gray placeholder

# ---------------- Serial ----------------
try:
    # Try common Raspberry Pi serial ports first
    import glob
    possible_ports = ["/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyACM0", "/dev/ttyACM1", "COM7", "COM6"]
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
def save_figure_direct(filename):
    """Save the current figure directly (no multiprocessing)"""
    try:
        # Save at exactly 800x373 pixels
        width_inches = 800 / 100
        height_inches = 480 / 100

        # Store original size
        original_size = fig.get_size_inches()

        # Temporarily set exact size for saving
        fig.set_size_inches(width_inches, height_inches)
        fig.savefig(filename, dpi=100, bbox_inches=None)

        # Restore original size
        fig.set_size_inches(original_size)

        print(f"[INFO] Figure saved successfully to: {filename}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to save figure: {e}")
        try:
            fig.set_size_inches(original_size)
        except:
            pass
        return False

# ---------------- Raw Data Handling ----------------
def start_new_raw_file(name_hint=""):
    """Start a new CSV for saving live scan data"""
    global raw_file, csv_writer, current_filename
    if not name_hint:
        name_hint = time.strftime("%Y%m%d_%H%M%S")

    raw_dir = '/home/pi/Shared/raw_data'
    os.makedirs(raw_dir, exist_ok=True)
    # Add "raw_" prefix for consistency
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
    try:
        print(f"[DEBUG] Setting button state to: {state}")
        for btn in [load_btn, resume_btn]:
            btn.config(state=state)
        print(f"[DEBUG] Buttons successfully set to: {state}")
    except NameError as e:
        print(f"[DEBUG] Buttons not created yet: {e}")
    except Exception as e:
        print(f"[ERROR] Failed to set button state: {e}")

def check_serial_timeout():
    """Check if serial data has stopped coming and re-enable buttons if needed"""
    global scan_active, last_data_time

    try:
        current_time = time.time()
        time_since_last_data = current_time - last_data_time

        # Check timeout condition: scan is active AND timeout reached (5 seconds)
        # Increased timeout to 5 seconds to be more reliable
        if scan_active and time_since_last_data > 5.0:
            print(f"[INFO] Timeout reached ({time_since_last_data:.1f}s), re-enabling buttons")
            scan_active = False
            set_controls_state("normal")

        # Schedule next check
        root.after(1000, check_serial_timeout)  # Check every 1 second
    except Exception as e:
        print(f"[ERROR] check_serial_timeout: {e}")
        # Try to schedule next check anyway
        try:
            root.after(1000, check_serial_timeout)
        except:
            pass

# ---------------- Serial loop ----------------
def read_loop():
    global raw_file, csv_writer, current_filename, scan_active, last_data_time, pause_live, x_range, y_max, zmin, zmax
    data_cnt = 0
    filename_from_serial = ""

    while True:
        if ser is None:
            time.sleep(1)  # Sleep and continue if no serial connection
            continue

        rcv_data = ser.readline()
        if len(rcv_data) == 0:
            if pause_live:
                time.sleep(0.2)
            continue

        try:
            parts = rcv_data.decode("ascii", errors="ignore").strip().split(",")
            x0 = float(parts[0])
            y0 = float(parts[1])
            z0 = float(parts[2])

            # Update last data received time
            last_data_time = time.time()

        except (ValueError, IndexError):
            print("data error @count=", data_cnt)
            continue

        # ---------- Auto-resume live scan when data received while paused ----------
        if pause_live:
            print("[INFO] Serial data received while viewing loaded data. Auto-resuming live scan.")
            pause_live = False
            x.clear()
            y.clear()
            z.clear()
            scan_active = False  # Will be set to True when (0,0) is received
            filename_from_serial = ""
            # Reset plot to blank and disable buttons - use thread-safe call
            def resume_and_disable():
                resume_live()
                set_controls_state("disabled")
            root.after(0, resume_and_disable)

        # ---------- New scan detection (0,0 marks start of scan) ----------
        if x0 == 0 and y0 == 0:
            print("[INFO] New scan detected (0,0). Resetting everything...")
            
            # Close previous scan's raw file if it exists
            if raw_file:
                try:
                    raw_file.close()
                    print(f"[INFO] Closed previous raw file: {current_filename}")
                except Exception:
                    pass

            # CRITICAL: Clear ALL buffers for new scan
            x.clear()
            y.clear()
            z.clear()

            # Reset variables for new scan
            raw_file = None
            csv_writer = None
            current_filename = None
            filename_from_serial = ""
            scan_active = True
            data_cnt = 0  # Reset data counter for new scan

            # Reset y_max and x_range for new scan
            y_max = 100
            x_range = 100
            
            # CRITICAL: Reset zmin/zmax for new scan to default values
            zmin, zmax = -0.1, 0.1
            print(f"[INFO] Reset color bar range to zmin={zmin}, zmax={zmax}")

            # Disable Load/Resume buttons during scanning
            def disable_controls():
                set_controls_state("disabled")
            root.after(0, disable_controls)

            # Detect filename sent by 1st program (should come with or after 0,0)
            if len(parts) >= 4:
                filename_from_serial = parts[3].strip()
                start_new_raw_file(filename_from_serial)
                print(f"[INFO] Started new scan with filename: {filename_from_serial}")
            
            # Skip adding the (0,0) marker to the data buffers
            continue

        # Detect filename if it comes after (0,0) - backup detection
        elif len(parts) >= 4 and not filename_from_serial and scan_active:
            filename_from_serial = parts[3].strip()
            start_new_raw_file(filename_from_serial)
            print(f"[INFO] Started raw file with filename: {filename_from_serial}")

        # Track maximum X and Y values during scan (don't update display yet)
        # We'll update both at the end of scan to keep them synchronized

        data_cnt += 1

        # Append new data to buffers (live)
        x.append(x0)
        y.append(y0)
        z.append(z0)

        # Write data to CSV file (skip the 0,0 marker)
        if csv_writer and not (x0 == 0 and y0 == 0):
            try:
                csv_writer.writerow([x0, y0, z0])
                # Flush every 100 rows to ensure data is saved
                if data_cnt % 100 == 0:
                    raw_file.flush()
            except Exception as e:
                print(f"[ERROR] Failed to write CSV row: {e}")

        if len(x) > 1500 and x0 == 3 and y0 >= 5:
            del x[0:-309]
            del y[0:-309]
            del z[0:-309]

        # ---------- End of scan ----------
        # Detect end of scan: hardware sends matching max values (e.g., 100,100 or 200,200)
        # Check if x0 and y0 are equal and within valid range (with tolerance for floating point)
        if scan_active and data_cnt > 50 and abs(x0 - y0) <= 1 and x0 >= 50 and x0 <= 300:
            print(f"[INFO] End of scan detected at ({x0},{y0}). Finalizing scan...")
            
            # Set BOTH x_range and y_max to the same value (synchronized square scan)
            # Round to nearest valid size (50, 100, 150, 200, 250, 300)
            detected_size = int(round(x0))
            x_range = detected_size
            y_max = detected_size
            print(f"[INFO] Scan dimensions set to: {x_range}x{y_max}")
            
            try:
                if filename_from_serial:
                    # Use same path logic as load_raw_data function
                    possible_paths = [
                        '/home/pi/Shared'
                    ]

                    save_dir = os.getcwd()  # Default fallback

                    # Find the first existing path
                    for path in possible_paths:
                        if os.path.exists(path):
                            save_dir = path
                            break

                    save_path = os.path.join(save_dir, filename_from_serial + ".png")
                    print(f"[INFO] Scan complete, attempting to save to: {save_path}")
                    # Save directly in main thread using root.after to ensure thread safety
                    # Use a proper function reference to avoid lambda closure issues
                    def save_scan_image():
                        save_figure_direct(save_path)
                    root.after(0, save_scan_image)
            except Exception as e:
                print("[ERROR] Could not save image:", e)

            if raw_file:
                try:
                    raw_file.flush()  # Ensure all data is written
                    raw_file.close()
                    print(f"[INFO] Raw data saved successfully: {current_filename}")
                    print(f"[INFO] Total data points saved: {data_cnt}")
                except Exception as e:
                    print(f"[ERROR] Failed to close raw file: {e}")
                raw_file = None
                csv_writer = None

            # Mark scan as complete and reset for next scan
            scan_active = False
            filename_from_serial = ""
            
            # Re-enable Load/Resume buttons after scan finishes
            print("[INFO] Re-enabling buttons after scan completion")
            def enable_controls():
                set_controls_state("normal")
            root.after(0, enable_controls)
            
            # Reset last_data_time to trigger timeout mechanism
            last_data_time = time.time()

        if data_cnt >= 6000000:
            break

# ---------------- Initialize blank plot ----------------
def initialize_blank_plot():
    global x_range, y_max
    ax.cla()
    axh.cla()
    axm.cla()  # Clear the image subplot as well

    ax.grid(True, linestyle="--", alpha=0.7)
    ax.set_xticks(np.arange(0, x_range + 1, max(10, int(x_range / 5))))
    ax.set_yticks(np.arange(0, 101, 20))
    ax.set_facecolor("white")

    axh.grid(True, linestyle="-", alpha=0.7)
    axh.set_xticks(np.arange(0, x_range + 1, max(10, int(x_range / 5))))
    axh.set_yticks(np.arange(0, 101, 25))
    axh.set_zticks(np.arange(-0.4, 0.41, 0.2))
    axh.set_facecolor("none")

    ax.set_xlabel("x")
    ax.set_ylabel("y")
    ax.set_xlim([0, 100])  # Display coordinates always 0-100
    ax.set_ylim([0, 100])

    # Force equal aspect on 2D plot so pixels are square
    try:
        ax.set_aspect('equal', adjustable='box')
    except Exception:
        pass

    # Adjust ticks to show x_range and y_max
    ax.set_xticks(np.linspace(0, 100, 6))
    ax.set_xticklabels([str(int(np.round(i * x_range / 100))) for i in np.linspace(0, 100, 6)])
    axh.set_xticks(np.linspace(0, 100, 6))
    axh.set_xticklabels([str(int(np.round(i * x_range / 100))) for i in np.linspace(0, 100, 6)])

    # Set Y-axis tick labels to show actual y_max values
    ax.set_yticks(np.linspace(0, 100, 6))
    ax.set_yticklabels([str(int(np.round(i * y_max / 100))) for i in np.linspace(0, 100, 6)])
    axh.set_yticks(np.linspace(0, 100, 6))
    axh.set_yticklabels([str(int(np.round(i * y_max / 100))) for i in np.linspace(0, 100, 6)])

    ax.set_title("Foreign object detection", fontsize=12, color=(0.2, 0.2, 0.2), pad=30)
    axh.set_title("Foreign object detection (3D)", fontsize=12, color=(0.2, 0.2, 0.2), pad=10)

    axh.view_init(elev=20, azim=300)
    # Handle set_box_aspect for Raspberry Pi compatibility (3D)
    try:
        axh.set_box_aspect((1, 1, 0.7))
    except AttributeError:
        pass  # Older matplotlib versions don't have this method

    axh.set_xlabel("x")
    axh.set_ylabel("y")
    axh.set_zlabel("output")
    axh.set_xlim([0, 100])  # Display coordinates always 0-100
    axh.set_ylim([0, 100])
    axh.set_zlim([zmin, zmax])

    ax.imshow(im_Migne, extent=[16, 84, 40, 60], alpha=0.08)
    axm.imshow(im_Migne, alpha=0.7)
    axm.axis("off")

# ---------------- Update animation ----------------
def update(i, xt, yt, zt, zmin_arg, zmax_arg):
    # note: name zmin/zmax in args to prevent shadowing globals accidentally
    global ax, axh, axm, cax, x_range, current_filename, y_max, zmin, zmax
    # Allow updates when paused (for loaded data) or when we have data
    if pause_live or len(x) < 2:
        return
    # Convert to numpy arrays for efficient processing
    xs = np.array(copy.copy(x))
    ys = np.array(copy.copy(y))
    zs = np.array(copy.copy(z))
    
    # Ensure all arrays have same length
    min_len = min(len(xs), len(ys), len(zs))
    if min_len == 0:
        return
    xs = xs[:min_len]
    ys = ys[:min_len]
    zs = zs[:min_len]

    # Filter and scale data based on x_range (zoom/crop feature) - use numpy for efficiency
    # Only show data where X <= x_range (filter for any x_range value)
    mask = xs <= x_range
    xs = xs[mask]
    ys = ys[mask]
    zs = zs[mask]

    # Scale X and Y coordinates to fit in 0-100 display range
    if x_range > 0 and y_max > 0:
        xs = xs * 100 / x_range
        ys = ys * 100 / y_max

    if len(xs) < 2 or len(np.unique(xs)) < 2 or len(np.unique(ys)) < 2:
        return

    x_new, y_new = np.meshgrid(np.unique(xs), np.unique(ys))
    try:
        z_new0 = griddata((xs, ys), zs, (x_new, y_new), method="cubic")
    except Exception:
        z_new0 = griddata((xs, ys), zs, (x_new, y_new), method="nearest")
    z_new = np.nan_to_num(z_new0, nan=0)

    # Calculate current data range
    local_max, local_min = np.nanmax(z_new), np.nanmin(z_new)
    
    # Use fixed range if enabled, otherwise auto-expand
    if use_fixed_range:
        zmin = fixed_zmin
        zmax = fixed_zmax
    else:
        # Expand zmin/zmax as needed to accommodate all data
        if local_max > zmax:
            zmax = local_max
        if local_min < zmin:
            zmin = local_min

    z_max = max(zs) if zs else 0
    z_min = min(zs) if zs else 0

    fig.clf()
    spec = gridspec.GridSpec(ncols=2, nrows=2, width_ratios=[5, 5], height_ratios=[1, 12.5], figure=fig)
    ax = fig.add_subplot(spec[1:, 0])
    axh = fig.add_subplot(spec[1:, 1], projection="3d")
    axm = fig.add_subplot(spec[0, 0:])
    divider = make_axes_locatable(ax)
    cax = divider.append_axes("right", size="5%", pad=0.5)

    axh.view_init(elev=20, azim=300)
    # Try to set 3D box aspect but be tolerant of older matplotlib
    try:
        axh.set_box_aspect((1, 1, 0.7))
    except Exception:
        pass

    # Keep Migne image at fixed position (always 16-84, 40-60)
    ax.imshow(im_Migne, extent=[16, 84, 40, 60], alpha=0.08)
    ps = ax.contourf(x_new, y_new, z_new, 128, cmap="jet", vmin=zmin, vmax=zmax, alpha=0.9)
    try:
        surf = axh.plot_surface(x_new, y_new, z_new, cmap="jet", vmin=zmin, vmax=zmax, rstride=1, cstride=1)
        ax.figure.colorbar(surf, cax=cax, shrink=1, orientation="vertical")
    except Exception:
        ax.figure.colorbar(ps, cax=cax, shrink=1, orientation="vertical")

    axm.imshow(im_Migne, alpha=0.7)
    axm.axis("off")

    # Display filename for live scan
    display_name = ""
    if current_filename:
        base_name = os.path.splitext(os.path.basename(current_filename))[0]
        # Remove "raw_" prefix if present for cleaner display
        if base_name.startswith("raw_"):
            base_name = base_name[4:]
        display_name = f"Live Scan: {base_name}"

    if display_name:
        axm.text(0.5, -0.1, display_name, transform=axm.transAxes,
                ha='center', va='top', fontsize=10, color='black', weight='bold')

    axh.text2D(0.70, 0.95, f"Z Max: {z_max:.6f}", transform=axh.transAxes)
    axh.text2D(0.70, 0.90, f"Z Min: {z_min:.6f}", transform=axh.transAxes)

    # Set axis limits - ALWAYS 0-100 to keep display square in coordinates
    axh.set_xlim([0, 100])
    axh.set_zlim([zmin, zmax])
    ax.set_xlim([0, 100])
    ax.set_ylim([0, 100])

    # Force equal aspect on 2D plot
    try:
        ax.set_aspect('equal', adjustable='box')
    except Exception:
        pass

    # Adjust ticks to show x_range and y_max
    tick_spacing = max(10, int(x_range / 5))
    ax.set_xticks(np.linspace(0, 100, 6))
    ax.set_xticklabels([str(int(np.round(i * x_range / 100))) for i in np.linspace(0, 100, 6)])
    axh.set_xticks(np.linspace(0, 100, 6))
    axh.set_xticklabels([str(int(np.round(i * x_range / 100))) for i in np.linspace(0, 100, 6)])

    # Set Y-axis tick labels to show actual y_max values
    ax.set_yticks(np.linspace(0, 100, 6))
    ax.set_yticklabels([str(int(np.round(i * y_max / 100))) for i in np.linspace(0, 100, 6)])
    axh.set_yticks(np.linspace(0, 100, 6))
    axh.set_yticklabels([str(int(np.round(i * y_max / 100))) for i in np.linspace(0, 100, 6)])

    axh.set_facecolor((0.9, 0.9, 0.9))
    axh.set_xlabel("x")
    axh.set_ylabel("y")
    axh.set_zlabel("output")

    ax.set_title("Foreign object detection", fontsize=12, color=(0.2, 0.2, 0.2), pad=30)
    axh.set_title("Foreign object detection (3D)", fontsize=12, color=(0.2, 0.2, 0.2), pad=10)

    # Draw canvas to update display
    try:
        canvas.draw()
    except Exception:
        pass

# ---------------- Load Raw CSV ----------------
def load_raw_data():
    global pause_live, loaded_filename
    pause_live = True

    # Set initial directory - try multiple possible paths for Raspberry Pi
    possible_paths = [
        '/home/pi/Shared/raw_data'
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
        # Extract filename without extension for saving
        loaded_filename = os.path.splitext(os.path.basename(file_path))[0]
        # Remove "raw_" prefix if present
        if loaded_filename.startswith("raw_"):
            loaded_filename = loaded_filename[4:]

        data = np.loadtxt(file_path, delimiter=",", skiprows=1)
        xs, ys, zs = data[:, 0], data[:, 1], data[:, 2]
        show_loaded(xs, ys, zs)
        print(f"[INFO] Loaded file: {loaded_filename}")
    except Exception as e:
        messagebox.showerror("Error", f"Failed to load file:\n{e}")
        pause_live = False
        loaded_filename = None

def show_loaded(xs, ys, zs):
    global zmin, zmax, ax, axh, axm, cax, x_range, y_max, use_fixed_range, fixed_zmin, fixed_zmax

    if len(xs) == 0 or len(ys) == 0:
        messagebox.showerror("Error", "Loaded CSV has no data.")
        return

    # Auto-detect scan dimensions from loaded data
    detected_x_max = int(np.max(xs)) if len(xs) > 0 else 100
    detected_y_max = int(np.max(ys)) if len(ys) > 0 else 100

    # For loaded data, use actual dimensions (they should match for square scans)
    # If they don't match, use the maximum to ensure all data is visible
    if abs(detected_x_max - detected_y_max) <= 5:
        # They're close enough - use the average
        detected_size = int((detected_x_max + detected_y_max) / 2)
    else:
        # They differ significantly - use maximum to show all data
        detected_size = max(detected_x_max, detected_y_max)
    
    x_range = detected_size
    y_max = detected_size

    print(f"[INFO] Loaded data dimensions: {detected_x_max}x{detected_y_max}")
    print(f"[INFO] Display set to: {x_range}x{y_max}")

    # Filter and scale data based on x_range (zoom/crop feature)
    # Only show data where X <= x_range (filter for any x_range value)
    mask = xs <= x_range
    xs = xs[mask]
    ys = ys[mask]
    zs = zs[mask]

    # Scale X and Y coordinates to fit in 0-100 display range
    xs = xs * 100 / x_range
    ys = ys * 100 / y_max

    # Use fixed range if enabled, otherwise use data range
    if use_fixed_range:
        zmin = fixed_zmin
        zmax = fixed_zmax
    else:
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

    # Display loaded filename below Migne picture
    if loaded_filename:
        axm.text(0.5, -0.1, f"Loaded: {loaded_filename}", transform=axm.transAxes,
                ha='center', va='top', fontsize=10, color='black', weight='bold')

    axh.view_init(elev=20, azim=300)

    # Handle set_box_aspect for Raspberry Pi compatibility
    try:
        axh.set_box_aspect((1, 1, 0.7))
    except AttributeError:
        pass  # Older matplotlib versions don't have this method

    # Set axis limits - ALWAYS 0-100 to keep square coordinates
    axh.set_xlim([0, 100])
    axh.set_ylim([0, 100])
    axh.set_zlim([zmin, zmax])
    ax.set_xlim([0, 100])
    ax.set_ylim([0, 100])

    # Force 2D equal aspect
    try:
        ax.set_aspect('equal', adjustable='box')
    except Exception:
        pass

    # Adjust ticks to show x_range and y_max
    ax.set_xticks(np.linspace(0, 100, 6))
    ax.set_xticklabels([str(int(np.round(i * x_range / 100))) for i in np.linspace(0, 100, 6)])
    axh.set_xticks(np.linspace(0, 100, 6))
    axh.set_xticklabels([str(int(np.round(i * x_range / 100))) for i in np.linspace(0, 100, 6)])

    ax.set_yticks(np.linspace(0, 100, 6))
    ax.set_yticklabels([str(int(np.round(i * y_max / 100))) for i in np.linspace(0, 100, 6)])
    axh.set_yticks(np.linspace(0, 100, 6))
    axh.set_yticklabels([str(int(np.round(i * y_max / 100))) for i in np.linspace(0, 100, 6)])

    # Display Z min/max values on the 3D plot
    axh.text2D(0.70, 0.95, f"Z Max: {zmax:.6f}", transform=axh.transAxes)
    axh.text2D(0.70, 0.90, f"Z Min: {zmin:.6f}", transform=axh.transAxes)

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

    axh.set_xlabel("x")
    axh.set_ylabel("y")
    axh.set_zlabel("output")

    ax.set_title("Loaded Raw Data (2D)", fontsize=12, pad=30)
    axh.set_title("Loaded Raw Data (3D)", fontsize=12, pad=10)
    canvas.draw()

def resume_live():
    """Reset the plot to blank display and clear all data"""
    global pause_live, x, y, z, zmin, zmax, ax, axh, axm, cax, loaded_filename, use_fixed_range, fixed_zmin, fixed_zmax
    pause_live = False
    loaded_filename = None  # Clear loaded filename when resuming live
    # Clear all data buffers
    x.clear()
    y.clear()
    z.clear()
    # Reset z-axis limits to default (or fixed if enabled)
    if use_fixed_range:
        zmin, zmax = fixed_zmin, fixed_zmax
    else:
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

# ---------------- Main execution ----------------
if __name__ == '__main__':
    # GUI setup
    th_ser = threading.Thread(target=read_loop, daemon=True)
    th_ser.start()

    root = tk.Tk()
    root.title("Scan system ver.1.2")
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

    btn_style = {"font": ("Arial", 11, "bold"), "bg": "#f2f2f2", "width": 10, "height": 2, "relief": "raised"}

    def safe_action(func):
        ani.event_source.stop()
        root.after(200, lambda: (func(), ani.event_source.start()))

    def do_home(): safe_action(hidden_toolbar.home)
    def do_pan(): safe_action(hidden_toolbar.pan)
    def do_zoom(): safe_action(hidden_toolbar.zoom)
    def do_save():
        def custom_save():
            global current_filename, loaded_filename

            # Determine filename based on current state
            if loaded_filename:
                # Use loaded filename (from raw data)
                base_filename = loaded_filename
            elif current_filename:
                # Use current scan filename (from live scan)
                base_filename = os.path.splitext(os.path.basename(current_filename))[0]
                # Remove "raw_" prefix if present
                if base_filename.startswith("raw_"):
                    base_filename = base_filename[4:]
            else:
                # Fallback to timestamp if no filename available
                base_filename = time.strftime("%Y%m%d_%H%M%S")

            # Determine save directory
            possible_paths = [
                '/home/pi/Shared'
            ]

            save_dir = os.getcwd()  # Default fallback

            # Find the first existing path
            for path in possible_paths:
                if os.path.exists(path):
                    save_dir = path
                    break

            # Create full filename path
            filename = os.path.join(save_dir, f"{base_filename}.png")

            try:
                # Save at exactly 800x373 pixels
                # Calculate figure size in inches for exact pixel output
                width_inches = 800 / 100  # 8 inches at 100 DPI = 800 pixels
                height_inches = 480 / 100  # 3.73 inches at 100 DPI = 373 pixels

                # Store original size
                original_size = fig.get_size_inches()

                # Temporarily set exact size for saving
                fig.set_size_inches(width_inches, height_inches)
                fig.savefig(filename, dpi=100, bbox_inches=None)

                # Immediately restore original size
                fig.set_size_inches(original_size)
                canvas.draw()  # Refresh the display

                print(f"[INFO] Figure saved to: {filename} at 800x373 pixels")
                messagebox.showinfo("Save Complete", f"Figure saved to:\n{filename}")
            except Exception as e:
                print(f"[ERROR] Failed to save figure: {e}")
                messagebox.showerror("Save Error", f"Failed to save figure:\n{e}")
                # Make sure to restore size even if save fails
                try:
                    fig.set_size_inches(original_size)
                    canvas.draw()
                except:
                    pass

        safe_action(custom_save)
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
            root.destroy()
            sys.exit(0)

    # ---------------- Buttons ----------------
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

    # Removed X-Range manual controls (buttons & label) — auto-synced X/Y now

    # Separator line
    separator = tk.Frame(controls_frame, height=2, bg="#999999")
    separator.pack(pady=8, fill=tk.X)

    # Range note (informational)
    range_note = tk.Label(controls_frame, text="Range: Auto 50-300 (X/Y synced)", 
                         font=("Arial", 8), bg="#d9d9d9", fg="#666666")
    range_note.pack(pady=(2, 4))

    # Separator line
    separator2 = tk.Frame(controls_frame, height=2, bg="#999999")
    separator2.pack(pady=8, fill=tk.X)

    # Fixed Colorbar Range Controls
    colorbar_label = tk.Label(controls_frame, text="Colorbar Range", 
                             font=("Arial", 10, "bold"), bg="#d9d9d9")
    colorbar_label.pack(pady=(4, 2))

    # Checkbox for fixed range
    fixed_range_var = tk.BooleanVar(value=False)
    
    def toggle_fixed_range():
        global use_fixed_range, fixed_zmin, fixed_zmax, zmin, zmax
        use_fixed_range = fixed_range_var.get()
        if use_fixed_range:
            # Set fixed range to current range when enabling
            fixed_zmin = zmin
            fixed_zmax = zmax
            zmin_label.config(text=f"Min: {fixed_zmin:.3f}")
            zmax_label.config(text=f"Max: {fixed_zmax:.3f}")
            print(f"[INFO] Fixed colorbar range enabled: {fixed_zmin:.3f} to {fixed_zmax:.3f}")
        else:
            print("[INFO] Auto colorbar range enabled")
    
    fixed_check = tk.Checkbutton(controls_frame, text="Lock Range", 
                                 variable=fixed_range_var, command=toggle_fixed_range,
                                 font=("Arial", 9), bg="#d9d9d9", activebackground="#d9d9d9")
    fixed_check.pack(pady=2)

    # Z-Min controls
    zmin_frame = tk.Frame(controls_frame, bg="#d9d9d9")
    zmin_frame.pack(pady=2, fill=tk.X)
    
    zmin_label = tk.Label(zmin_frame, text=f"Min: {fixed_zmin:.3f}", 
                         font=("Arial", 9), bg="#d9d9d9", width=12)
    zmin_label.pack(side=tk.LEFT, padx=2)
    
    def decrease_zmin():
        global fixed_zmin, zmin
        fixed_zmin -= 0.1
        zmin_label.config(text=f"Min: {fixed_zmin:.3f}")
        # Always update zmin immediately, regardless of checkbox state
        zmin = fixed_zmin
        print(f"[INFO] Z-Min set to: {fixed_zmin:.3f}")
    
    def increase_zmin():
        global fixed_zmin, zmin
        if fixed_zmin < fixed_zmax - 0.1:  # Ensure min < max
            fixed_zmin += 0.1
            zmin_label.config(text=f"Min: {fixed_zmin:.3f}")
            # Always update zmin immediately, regardless of checkbox state
            zmin = fixed_zmin
            print(f"[INFO] Z-Min set to: {fixed_zmin:.3f}")
    
    zmin_down = tk.Button(zmin_frame, text="−", command=decrease_zmin, 
                         font=("Arial", 10, "bold"), width=2, height=1)
    zmin_down.pack(side=tk.LEFT, padx=1)
    
    zmin_up = tk.Button(zmin_frame, text="+", command=increase_zmin, 
                       font=("Arial", 10, "bold"), width=2, height=1)
    zmin_up.pack(side=tk.LEFT, padx=1)

    # Z-Max controls
    zmax_frame = tk.Frame(controls_frame, bg="#d9d9d9")
    zmax_frame.pack(pady=2, fill=tk.X)
    
    zmax_label = tk.Label(zmax_frame, text=f"Max: {fixed_zmax:.3f}", 
                         font=("Arial", 9), bg="#d9d9d9", width=12)
    zmax_label.pack(side=tk.LEFT, padx=2)
    
    def decrease_zmax():
        global fixed_zmax, zmax
        if fixed_zmax > fixed_zmin + 0.1:  # Ensure max > min
            fixed_zmax -= 0.1
            zmax_label.config(text=f"Max: {fixed_zmax:.3f}")
            # Always update zmax immediately, regardless of checkbox state
            zmax = fixed_zmax
            print(f"[INFO] Z-Max set to: {fixed_zmax:.3f}")
    
    def increase_zmax():
        global fixed_zmax, zmax
        fixed_zmax += 0.1
        zmax_label.config(text=f"Max: {fixed_zmax:.3f}")
        # Always update zmax immediately, regardless of checkbox state
        zmax = fixed_zmax
        print(f"[INFO] Z-Max set to: {fixed_zmax:.3f}")
    
    zmax_down = tk.Button(zmax_frame, text="−", command=decrease_zmax, 
                         font=("Arial", 10, "bold"), width=2, height=1)
    zmax_down.pack(side=tk.LEFT, padx=1)
    
    zmax_up = tk.Button(zmax_frame, text="+", command=increase_zmax, 
                       font=("Arial", 10, "bold"), width=2, height=1)
    zmax_up.pack(side=tk.LEFT, padx=1)

    # Reset button for colorbar range
    def reset_colorbar_range():
        global fixed_zmin, fixed_zmax, zmin, zmax
        fixed_zmin, fixed_zmax = -0.1, 0.1
        zmin_label.config(text=f"Min: {fixed_zmin:.3f}")
        zmax_label.config(text=f"Max: {fixed_zmax:.3f}")
        if use_fixed_range:
            zmin, zmax = fixed_zmin, fixed_zmax
        print("[INFO] Colorbar range reset to default: -0.1 to 0.1")
    
    reset_range_btn = tk.Button(controls_frame, text="Reset Range", command=reset_colorbar_range,
                                font=("Arial", 9), bg="#f2f2f2", width=12, height=1)
    reset_range_btn.pack(pady=4)

    # Initially enabled (buttons start enabled when no scan is active)
    set_controls_state("normal")

    # Start the serial timeout checker
    root.after(1000, check_serial_timeout)

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
