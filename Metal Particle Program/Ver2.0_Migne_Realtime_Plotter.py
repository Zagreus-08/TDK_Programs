#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Scan system for long loop - Auto-start version (Fullscreen + Toggleable Controls)
Ver 0.9R-stable11   2025-11-03  (X/Y auto-sync, X-Lim controls removed)

FEATURES:
- Auto-detects scan dimensions from hardware (X: 50-300, Y: auto-detected)
- Saves raw CSV data for all scan sizes
- Auto-saves PNG at end of scan
- Loads and displays any size raw data (50x50 to 300x300)
- Maintains square 2D display with proper axis scaling
- X/Y now auto-sync: whichever axis expands, the other follows
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
x_range = 100  # Default X-axis range (50-300)
y_max = 100    # Auto-detected Y-axis maximum from hardware
raw_file = None
csv_writer = None
current_filename = None
loaded_filename = None   # Track filename of loaded raw data for saving
pause_live = False       # used when user loads a CSV and wants to pause live updates
scan_active = True       # True while an active scan is happening; becomes False after end-of-scan (100,100)
last_data_time = time.time()  # Track when we last received serial data
scan_finished = False

# Z-range lock feature
z_range_locked = False   # Toggle for lock mode
locked_zmin = -0.1       # Stored locked values
locked_zmax = 0.1

# Loaded data cache for re-rendering with adjusted Z-range
loaded_data_cache = None

# ---------------- Image ----------------
# Try multiple paths for Migne image (Raspberry Pi and Windows)
possible_image_paths = [
    '/home/pi/Desktop/Migne_black_frameless.png',  # Raspberry Pi
    os.path.join(os.path.expanduser('~'), 'Downloads', 'Migne_black_frameless.png'),  # Windows Downloads
    os.path.join(os.path.dirname(__file__), 'Migne_black_frameless.png'),  # Same directory as script
]

im_Migne = None
for img_path in possible_image_paths:
    if os.path.exists(img_path):
        try:
            im_Migne = plt.imread(img_path)
            print(f"[INFO] Loaded Migne image from: {img_path}")
            break
        except Exception as e:
            print(f"[WARNING] Failed to load image from {img_path}: {e}")
            continue

if im_Migne is None:
    print("[WARNING] Migne image not found. Creating blank placeholder.")
    im_Migne = np.ones((100, 100, 4)) * 0.5  # Gray placeholder image

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
    raw_path = os.path.join(raw_dir, f"{name_hint}.csv")

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
    """Enable or disable Load Raw, Resume Live, and Z-lock controls"""
    try:
        print(f"[DEBUG] Setting button state to: {state}")
        for btn in [load_btn, resume_btn]:
            btn.config(state=state)
        
        # Also control Z-lock checkbox and adjustment button
        try:
            z_lock_checkbox.config(state=state)
            # Only enable adjustment button if locked AND controls are enabled
            if state == "normal" and z_range_locked:
                adjust_range_btn.config(state="normal")
            else:
                adjust_range_btn.config(state="disabled")
        except NameError:
            pass  # Z-lock controls not created yet
        
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
            scan_active = True
            filename_from_serial = ""
            # Reset plot to blank and disable buttons
            root.after(0, lambda: (resume_live(), set_controls_state("disabled")))

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
            
            # Reset zmin/zmax for new scan to default values (unless locked)
            if not z_range_locked:
                zmin, zmax = -0.1, 0.1
                print(f"[INFO] Reset color bar range to zmin={zmin}, zmax={zmax}")
            else:
                print(f"[INFO] Z-range locked at zmin={locked_zmin}, zmax={locked_zmax}")

            # Disable Load/Resume buttons during scanning
            root.after(0, lambda: set_controls_state("disabled"))

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

        # Auto-detect X and Y axis maximums from incoming data
        if x0 > 0 and x0 <= 300:  # Reasonable range check for X
            detected_x_max = max(x0, x_range if x_range > 100 else 100)
            # Auto-adjust x_range during live scan (round to nearest 50)
            new_x_range = max(50, min(300, ((int(detected_x_max) + 49) // 50) * 50))
            if new_x_range != x_range:
                x_range = new_x_range
                # sync with y_max to keep square scaling
                max_range = max(x_range, y_max)
                x_range = y_max = max_range
                print(f"[INFO] Auto-adjusted x_range to: {x_range} (synced y_max)")

        if y0 > 0 and y0 <= 300:  # Reasonable range check for Y
            y_max = max(y_max, y0)
            # sync with x_range to keep square scaling
            max_range = max(x_range, y_max)
            x_range = y_max = max_range

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

        # ---------- End of scan ----------
        if scan_active and data_cnt > 50 and ((abs(x0 - x_range) <= 1 and abs(y0 - y_max) <= 1) or (x0 == y0 and x0 >= 100 and x0 == y_max)):
            print(f"[INFO] End of scan detected at ({x0},{y0}). Finalizing...")
            
            # 1. Close the raw file immediately so data is flushed to disk
            if raw_file:
                try:
                    raw_file.flush()
                    raw_file.close()
                except: pass
                raw_file = None
                csv_writer = None

            # 2. Trigger a final high-quality render and save
            # We use a slight delay (500ms) to ensure the last serial data 
            # points are processed by the animation update
            def final_save_sequence():
                # Force an update with the current full buffers
                update(0, [], [], [], zmin, zmax) 
                
                # Now save the completed plot
                save_dir = '/home/pi/Shared' if os.path.exists('/home/pi/Shared') else os.getcwd()
                save_path = os.path.join(save_dir, filename_from_serial + ".png")
                save_figure_direct(save_path)
                
                # Re-enable UI
                set_controls_state("normal")
                print("[INFO] Final image saved and scan finalized.")

            root.after(500, final_save_sequence)
            
            scan_active = False
            last_data_time = time.time()

# ---------------- Initialize blank plot ----------------
def initialize_blank_plot():
    global x_range, y_max
    ax.cla()
    axh.cla()
    axm.cla()  # Clear the image subplot as well

    # Ensure x_range / y_max are synced to keep square
    max_range = max(x_range, y_max)
    x_range = y_max = max_range

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
    
    # Use appropriate Z-range for blank plot
    if z_range_locked:
        axh.set_zlim([locked_zmin, locked_zmax])
    else:
        axh.set_zlim([zmin, zmax])

    ax.imshow(im_Migne, extent=[16, 84, 40, 60], alpha=0.08)
    axm.imshow(im_Migne, alpha=0.7)
    axm.axis("off")

# ---------------- Update animation ----------------
def update(i, xt, yt, zt, zmin_arg, zmax_arg):
    global ax, axh, axm, cax, x_range, current_filename, y_max, zmin, zmax
    
    # 1. Protection: If we are paused or don't have enough data, EXIT IMMEDIATELY
    if pause_live or len(x) < 5: # Increased to 5 points to be safe for griddata
        return

    xs = copy.copy(x)
    ys = copy.copy(y)
    zs = copy.copy(z)

    # ... [Keep your filtering and scaling code here] ...

    # 2. Protection: Check if we have enough unique points to interpolate
    if len(xs) < 2 or len(np.unique(xs)) < 2 or len(np.unique(ys)) < 2:
        return

    # 3. Create the grid (Now z_new is guaranteed to be defined)
    x_new, y_new = np.meshgrid(np.unique(xs), np.unique(ys))
    try:
        # Using linear is much faster for live updates on slow systems
        method = "cubic" if (pause_live or not scan_active) else "linear"
        z_new0 = griddata((xs, ys), zs, (x_new, y_new), method=method)
    except Exception:
        z_new0 = griddata((xs, ys), zs, (x_new, y_new), method="nearest")
    
    z_new = np.nan_to_num(z_new0, nan=0)

    # 4. Now it is safe to calculate max/min because z_new exists
    local_max, local_min = np.nanmax(z_new), np.nanmin(z_new)
    
    # ... [Rest of the plotting code] ...

    # Calculate current data range
    local_max, local_min = np.nanmax(z_new), np.nanmin(z_new)
    
    # Expand zmin/zmax as needed to accommodate all data (only if not locked)
    if not z_range_locked:
        if local_max > zmax:
            zmax = local_max
        if local_min < zmin:
            zmin = local_min
    else:
        # Use locked values
        zmin = locked_zmin
        zmax = locked_zmax

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
    # For 3D Z-axis, use actual data range for display (not locked range)
    # This prevents the 3D plot from extending too far
    display_zmin = min(z_min, zmin) if not z_range_locked else z_min
    display_zmax = max(z_max, zmax) if not z_range_locked else z_max
    axh.set_zlim([display_zmin, display_zmax])
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

    # Create custom file dialog for better Raspberry Pi experience
    dialog = tk.Toplevel(root)
    dialog.title("Select Raw CSV File")
    dialog.geometry("700x550")
    dialog.configure(bg="#e5e5e5")
    dialog.transient(root)
    dialog.grab_set()
    
    # Center the dialog
    dialog.update_idletasks()
    x = (dialog.winfo_screenwidth() // 2) - (700 // 2)
    y = (dialog.winfo_screenheight() // 2) - (550 // 2)
    dialog.geometry(f"700x550+{x}+{y}")
    
    selected_file = [None]  # Use list to store result
    sort_by_date = [True]  # Default: sort by date (newest first)
    file_data = {}  # Store file info: {filename: (full_path, mtime)}
    
    # Current directory label
    current_dir_var = tk.StringVar(value=raw_dir)
    dir_label = tk.Label(dialog, textvariable=current_dir_var, font=("Arial", 9), 
                         bg="#e5e5e5", anchor="w", relief="sunken", bd=1)
    dir_label.pack(fill=tk.X, padx=10, pady=(10, 5))
    
    # Sort and filter frame
    sort_filter_frame = tk.Frame(dialog, bg="#e5e5e5")
    sort_filter_frame.pack(fill=tk.X, padx=10, pady=5)
    
    # Sort toggle button
    sort_btn_text = tk.StringVar(value="📅 Newest First")
    def toggle_sort():
        sort_by_date[0] = not sort_by_date[0]
        if sort_by_date[0]:
            sort_btn_text.set("📅 Newest First")
        else:
            sort_btn_text.set("🔤 Name A-Z")
        populate_files(current_dir_var.get(), search_var.get())
    
    sort_btn = tk.Button(sort_filter_frame, textvariable=sort_btn_text, command=toggle_sort,
                         font=("Arial", 10, "bold"), bg="#2196F3", fg="white", width=14)
    sort_btn.pack(side=tk.LEFT, padx=5)
    
    # Filter entry
    tk.Label(sort_filter_frame, text="Filter:", font=("Arial", 10, "bold"), bg="#e5e5e5").pack(side=tk.LEFT, padx=(15, 5))
    search_var = tk.StringVar()
    search_entry = tk.Entry(sort_filter_frame, textvariable=search_var, font=("Arial", 11), relief="sunken", bd=2)
    search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
    
    # Trigger onboard keyboard when search entry is clicked
    def focus_search(event):
        search_entry.focus_set()
        try:
            os.system("onboard &")
        except:
            pass
    search_entry.bind("<Button-1>", focus_search)
    
    # Selected file display label (separate from filter)
    selected_frame = tk.Frame(dialog, bg="#e5e5e5")
    selected_frame.pack(fill=tk.X, padx=10, pady=2)
    
    tk.Label(selected_frame, text="Selected:", font=("Arial", 10, "bold"), bg="#e5e5e5").pack(side=tk.LEFT, padx=5)
    selected_var = tk.StringVar(value="(none)")
    selected_label = tk.Label(selected_frame, textvariable=selected_var, font=("Arial", 11), 
                              bg="#ffffcc", fg="black", relief="sunken", bd=1, anchor="w")
    selected_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
    
    # File count label
    file_count_var = tk.StringVar(value="")
    file_count_label = tk.Label(dialog, textvariable=file_count_var, font=("Arial", 9), 
                                bg="#e5e5e5", fg="#666666")
    file_count_label.pack(anchor="w", padx=15)
    
    # File listbox with scrollbar
    list_frame = tk.Frame(dialog, bg="#e5e5e5")
    list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
    
    scrollbar = tk.Scrollbar(list_frame, width=20)  # Wider scrollbar for touch
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    
    file_listbox = tk.Listbox(list_frame, font=("Courier", 10), yscrollcommand=scrollbar.set, 
                              selectmode=tk.SINGLE, relief="sunken", bd=2)
    file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.config(command=file_listbox.yview)
    
    def populate_files(directory, filter_text=""):
        file_listbox.delete(0, tk.END)
        file_data.clear()
        try:
            from datetime import datetime
            csv_files = []
            for f in os.listdir(directory):
                if f.endswith('.csv'):
                    full_path = os.path.join(directory, f)
                    try:
                        mtime = os.path.getmtime(full_path)
                        csv_files.append((f, full_path, mtime))
                    except:
                        csv_files.append((f, full_path, 0))
            
            # Apply filter
            if filter_text:
                csv_files = [item for item in csv_files if filter_text.lower() in item[0].lower()]
            
            # Sort files
            if sort_by_date[0]:
                # Sort by modification time, newest first
                csv_files.sort(key=lambda x: x[2], reverse=True)
            else:
                # Sort by name alphabetically
                csv_files.sort(key=lambda x: x[0].lower())
            
            # Populate listbox with formatted entries
            for filename, full_path, mtime in csv_files:
                file_data[filename] = (full_path, mtime)
                # Format: date/time + filename
                if mtime > 0:
                    dt = datetime.fromtimestamp(mtime)
                    date_str = dt.strftime("%m/%d %H:%M")
                    display_text = f"{date_str}  {filename}"
                else:
                    display_text = f"--/-- --:--  {filename}"
                file_listbox.insert(tk.END, display_text)
            
            # Update file count
            total = len(csv_files)
            file_count_var.set(f"{total} file(s) found")
            
            if csv_files:
                file_listbox.selection_set(0)  # Select first file by default (newest if sorted by date)
                update_selected_display()
        except Exception as e:
            print(f"[ERROR] Failed to list files: {e}")
            file_count_var.set("Error loading files")
    
    def get_filename_from_display(display_text):
        """Extract actual filename from display text (removes date prefix)"""
        # Format is "MM/DD HH:MM  filename" or "--/-- --:--  filename"
        parts = display_text.split("  ", 1)
        if len(parts) == 2:
            return parts[1]
        return display_text
    
    # Update file list when search text changes
    def on_search_change(*args):
        populate_files(current_dir_var.get(), search_var.get())
    search_var.trace('w', on_search_change)
    
    # Initial population
    populate_files(raw_dir)
    
    # Single-click to show selection in selected label (not filter)
    def on_single_click(event):
        # Small delay to ensure selection is registered
        dialog.after(10, update_selected_display)
    
    def update_selected_display():
        selection = file_listbox.curselection()
        if selection:
            display_text = file_listbox.get(selection[0])
            filename = get_filename_from_display(display_text)
            selected_var.set(filename)  # Show selected file in separate label
    
    file_listbox.bind("<<ListboxSelect>>", on_single_click)
    
    # Double-click to select
    def on_double_click(event):
        selection = file_listbox.curselection()
        if selection:
            display_text = file_listbox.get(selection[0])
            filename = get_filename_from_display(display_text)
            if filename in file_data:
                selected_file[0] = file_data[filename][0]
            else:
                selected_file[0] = os.path.join(current_dir_var.get(), filename)
            dialog.destroy()
    file_listbox.bind("<Double-Button-1>", on_double_click)
    
    # Buttons
    btn_frame = tk.Frame(dialog, bg="#e5e5e5")
    btn_frame.pack(fill=tk.X, padx=10, pady=10)
    
    def on_select():
        selection = file_listbox.curselection()
        if selection:
            display_text = file_listbox.get(selection[0])
            filename = get_filename_from_display(display_text)
            if filename in file_data:
                selected_file[0] = file_data[filename][0]
            else:
                selected_file[0] = os.path.join(current_dir_var.get(), filename)
            dialog.destroy()
        else:
            messagebox.showwarning("No Selection", "Please select a file!")
    
    def on_cancel():
        dialog.destroy()
    
    tk.Button(btn_frame, text="Select", command=on_select, font=("Arial", 11, "bold"),
             bg="#4CAF50", fg="white", width=12, height=2).pack(side=tk.LEFT, padx=5)
    tk.Button(btn_frame, text="Cancel", command=on_cancel, font=("Arial", 11, "bold"),
             bg="#f44336", fg="white", width=12, height=2).pack(side=tk.RIGHT, padx=5)
    
    # Wait for dialog to close
    dialog.wait_window()
    
    file_path = selected_file[0]
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
    global zmin, zmax, ax, axh, axm, cax, x_range, y_max, loaded_data_cache

    if len(xs) == 0 or len(ys) == 0:
        messagebox.showerror("Error", "Loaded CSV has no data.")
        return

    # Auto-detect X and Y axis maximums from loaded data
    detected_x_max = int(np.max(xs)) if len(xs) > 0 else 100
    detected_y_max = int(np.max(ys)) if len(ys) > 0 else 100

    # Auto-adjust x_range to match loaded data (round to nearest 50)
    x_range = max(50, min(300, ((detected_x_max + 49) // 50) * 50))
    y_max = detected_y_max

    # Sync X and Y so they match the larger dimension (keep square)
    max_range = max(x_range, y_max)
    x_range = y_max = max_range

    print(f"[INFO] Detected X-max: {detected_x_max}, adjusted x_range to: {x_range}")
    print(f"[INFO] Detected Y-max: {detected_y_max}, synced y_max to: {y_max}")

    # Filter and scale data based on x_range (zoom/crop feature)
    # Only show data where X <= x_range (filter for any x_range value)
    mask = xs <= x_range
    xs = xs[mask]
    ys = ys[mask]
    zs = zs[mask]

    # Scale X and Y coordinates to fit in 0-100 display range
    xs = xs * 100 / x_range
    ys = ys * 100 / y_max

    # Store actual data range for indicators
    actual_data_zmin = np.min(zs)
    actual_data_zmax = np.max(zs)

    # Cache the loaded data for re-rendering when Z-range is adjusted
    loaded_data_cache = {
        'xs': xs.copy(),
        'ys': ys.copy(),
        'zs': zs.copy(),
        'actual_zmin': actual_data_zmin,
        'actual_zmax': actual_data_zmax
    }

    # Set Z-range based on lock state
    if not z_range_locked:
        zmin, zmax = actual_data_zmin, actual_data_zmax
    else:
        zmin, zmax = locked_zmin, locked_zmax

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

    # Create explicit contour levels based on locked or actual Z-range
    contour_levels = np.linspace(zmin, zmax, 129)
    
    ps = ax.contourf(x_new, y_new, z_new, levels=contour_levels, cmap="jet", extend='both', alpha=0.9)
    ax.imshow(im_Migne, extent=[16, 84, 40, 60], alpha=0.08)
    surf = axh.plot_surface(x_new, y_new, z_new, cmap="jet", vmin=zmin, vmax=zmax)
    
    # Create colorbar with explicit ticks showing the exact locked range
    cbar = ax.figure.colorbar(ps, cax=cax)
    # Set colorbar ticks to show exact min/max values
    num_ticks = 9  # Number of tick marks on colorbar
    cbar_ticks = np.linspace(zmin, zmax, num_ticks)
    cbar.set_ticks(cbar_ticks)
    cbar.set_ticklabels([f"{t:.3f}" for t in cbar_ticks])

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
    # For 3D Z-axis in loaded data, use actual data range for display
    display_zmin = np.min(zs) if z_range_locked else zmin
    display_zmax = np.max(zs) if z_range_locked else zmax
    axh.set_zlim([display_zmin, display_zmax])
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

    # Display Z min/max values on the 3D plot (ALWAYS show actual data values)
    axh.text2D(0.70, 0.95, f"Z Max: {actual_data_zmax:.6f}", transform=axh.transAxes)
    axh.text2D(0.70, 0.90, f"Z Min: {actual_data_zmin:.6f}", transform=axh.transAxes)

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
    global pause_live, x, y, z, zmin, zmax, ax, axh, axm, cax, loaded_filename, loaded_data_cache
    pause_live = False
    loaded_filename = None  # Clear loaded filename when resuming live
    loaded_data_cache = None  # Clear loaded data cache
    # Clear all data buffers
    x.clear()
    y.clear()
    z.clear()
    # ALWAYS reset z-axis limits to default for clean display
    # Even if locked, the display should show -0.1 to 0.1 for blank plot
    zmin, zmax = -0.1, 0.1
    
    # If locked, keep the locked values but display will use default until data comes in
    if z_range_locked:
        print(f"[INFO] Z-range still locked at [{locked_zmin:.4f}, {locked_zmax:.4f}], but display reset to default")

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
    root.title("Ver1.3_Migne_Realtime_Plotter")
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

    # ---------------- Z-Range Lock Controls ----------------
    z_lock_frame = tk.Frame(controls_frame, bg="#d9d9d9")
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
    
    # Define adjustment dialog function
    def open_adjust_dialog():
        global locked_zmin, locked_zmax
        
        # Create popup window
        dialog = tk.Toplevel(root)
        dialog.title("Adjust Z-Range")
        dialog.geometry("350x250")
        dialog.configure(bg="#e5e5e5")
        dialog.resizable(False, False)
        
        # Center the dialog
        dialog.transient(root)
        dialog.grab_set()
        
        # Local variables for adjustment
        current_zmin = tk.DoubleVar(value=locked_zmin)
        current_zmax = tk.DoubleVar(value=locked_zmax)
        
        # Z Min section
        tk.Label(dialog, text="Z Min:", font=("Arial", 12, "bold"), bg="#e5e5e5").grid(row=0, column=0, padx=10, pady=15, sticky="w")
        
        zmin_frame = tk.Frame(dialog, bg="#e5e5e5")
        zmin_frame.grid(row=0, column=1, columnspan=3, padx=10, pady=15)
        
        zmin_entry = tk.Entry(zmin_frame, font=("Arial", 12, "bold"), width=10, justify="center", relief="sunken", bd=2)
        zmin_entry.insert(0, f"{current_zmin.get():.4f}")
        zmin_entry.pack(side=tk.LEFT, padx=5)
        
        # Trigger onboard keyboard when entry is clicked
        def focus_zmin(event):
            zmin_entry.focus_set()
            zmin_entry.select_range(0, tk.END)
            try:
                os.system("onboard &")
            except:
                pass
        zmin_entry.bind("<Button-1>", focus_zmin)
        
        def update_zmin(delta):
            try:
                current_val = float(zmin_entry.get())
                new_val = current_val + delta
                # Z Min must be <= 0 (negative or zero only)
                if new_val > 0:
                    new_val = 0
                current_zmin.set(new_val)
                zmin_entry.delete(0, tk.END)
                zmin_entry.insert(0, f"{new_val:.4f}")
            except ValueError:
                pass
        
        tk.Button(zmin_frame, text="-0.1", command=lambda: update_zmin(-0.1), 
                 font=("Arial", 10, "bold"), bg="#ff9800", fg="white", width=5).pack(side=tk.LEFT, padx=2)
        tk.Button(zmin_frame, text="+0.1", command=lambda: update_zmin(0.1), 
                 font=("Arial", 10, "bold"), bg="#ff9800", fg="white", width=5).pack(side=tk.LEFT, padx=2)
        
        # Z Max section
        tk.Label(dialog, text="Z Max:", font=("Arial", 12, "bold"), bg="#e5e5e5").grid(row=1, column=0, padx=10, pady=15, sticky="w")
        
        zmax_frame = tk.Frame(dialog, bg="#e5e5e5")
        zmax_frame.grid(row=1, column=1, columnspan=3, padx=10, pady=15)
        
        zmax_entry = tk.Entry(zmax_frame, font=("Arial", 12, "bold"), width=10, justify="center", relief="sunken", bd=2)
        zmax_entry.insert(0, f"{current_zmax.get():.4f}")
        zmax_entry.pack(side=tk.LEFT, padx=5)
        
        # Trigger onboard keyboard when entry is clicked
        def focus_zmax(event):
            zmax_entry.focus_set()
            zmax_entry.select_range(0, tk.END)
            try:
                os.system("onboard &")
            except:
                pass
        zmax_entry.bind("<Button-1>", focus_zmax)
        
        def update_zmax(delta):
            try:
                current_val = float(zmax_entry.get())
                new_val = current_val + delta
                # Z Max must be >= 0 (positive or zero only)
                if new_val < 0:
                    new_val = 0
                current_zmax.set(new_val)
                zmax_entry.delete(0, tk.END)
                zmax_entry.insert(0, f"{new_val:.4f}")
            except ValueError:
                pass
        
        tk.Button(zmax_frame, text="-0.1", command=lambda: update_zmax(-0.1), 
                 font=("Arial", 10, "bold"), bg="#ff9800", fg="white", width=5).pack(side=tk.LEFT, padx=2)
        tk.Button(zmax_frame, text="+0.1", command=lambda: update_zmax(0.1), 
                 font=("Arial", 10, "bold"), bg="#ff9800", fg="white", width=5).pack(side=tk.LEFT, padx=2)
        
        # Apply button
        def apply_changes():
            global locked_zmin, locked_zmax, loaded_data_cache
            try:
                new_zmin = float(zmin_entry.get())
                new_zmax = float(zmax_entry.get())
                
                # Validate Z Min must be <= 0 (negative or zero only)
                if new_zmin > 0:
                    messagebox.showerror("Invalid Z Min", "Z Min must be negative or zero (≤ 0)!")
                    return
                
                # Validate Z Max must be >= 0 (positive or zero only)
                if new_zmax < 0:
                    messagebox.showerror("Invalid Z Max", "Z Max must be positive or zero (≥ 0)!")
                    return
                
                if new_zmin >= new_zmax:
                    messagebox.showerror("Invalid Range", "Z Min must be less than Z Max!")
                    return
                
                locked_zmin = new_zmin
                locked_zmax = new_zmax
                z_range_label.config(text=f"Locked: {locked_zmin:.4f} to {locked_zmax:.4f}")
                print(f"[INFO] Z-range adjusted to [{locked_zmin:.4f}, {locked_zmax:.4f}]")
                
                # If viewing loaded data, re-render with new Z-range
                if pause_live and loaded_data_cache is not None:
                    print("[INFO] Re-rendering loaded data with adjusted Z-range")
                    show_loaded(loaded_data_cache['xs'], loaded_data_cache['ys'], loaded_data_cache['zs'])
                
                dialog.destroy()
            except ValueError:
                messagebox.showerror("Invalid Input", "Please enter valid numbers!")
        
        # Buttons frame
        btn_frame = tk.Frame(dialog, bg="#e5e5e5")
        btn_frame.grid(row=2, column=0, columnspan=4, pady=20)
        
        tk.Button(btn_frame, text="Apply", command=apply_changes, font=("Arial", 11, "bold"), 
                 bg="#4CAF50", fg="white", width=10, height=2).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Cancel", command=dialog.destroy, font=("Arial", 11, "bold"), 
                 bg="#f44336", fg="white", width=10, height=2).pack(side=tk.LEFT, padx=5)
    
    # Define toggle function before checkbox
    def toggle_z_lock():
        global z_range_locked, locked_zmin, locked_zmax, zmin, zmax
        z_range_locked = z_lock_var.get()
        
        if z_range_locked:
            # Capture current range when locking
            locked_zmin = zmin
            locked_zmax = zmax
            z_range_label.config(text=f"Locked: {locked_zmin:.4f} to {locked_zmax:.4f}", fg="red")
            print(f"[INFO] Z-range locked at [{locked_zmin:.4f}, {locked_zmax:.4f}]")
            # Enable adjustment button when locked
            adjust_range_btn.config(state="normal")
        else:
            # Unlocked - return to auto-range
            z_range_label.config(text="Auto-range enabled", fg="green")
            print("[INFO] Z-range unlocked - auto-ranging enabled")
            # Disable adjustment button when unlocked
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
    z_range_label.pack(anchor="w", padx=5, pady=2)
    
    # Single adjustment button
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
