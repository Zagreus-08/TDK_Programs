#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Scan System GUI (Hybrid v1.8)
- Uses v1.7 GUI interface (system controls on right)
- Uses v0.7 scanning & plotting logic (continuous build, single colorbar)
- No Start/Stop controls (external program triggers scanning)
- Default serial port: COM6 (Windows test). Change to '/dev/ttyUSB0' for Pi.
"""

import copy
import sys
import time
import threading
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib import gridspec
from mpl_toolkits.mplot3d import Axes3D
from scipy.interpolate import griddata
import numpy as np
from multiprocessing import Process, Queue
import serial
import tkinter as tk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from mpl_toolkits.axes_grid1 import make_axes_locatable

# ------------------ Config ------------------
SERIAL_PORT = "COM7"        # Windows testing (change to "/dev/ttyUSB0" on Pi)
BAUDRATE = 115200
GRID_NX = 80
GRID_NY = 80
LOGO_PATH = r"C:\Users\a493353\Desktop\Lans Galos\Raspberry Pi Program\Metal Particle Program\Migne_black_frameless.png"
AUTO_FULLSCREEN_ON_PI = False  # set True on Pi if you want fullscreen

# ------------------ Global Variables ------------------
x, y, z = [], [], []
zmin, zmax = -0.4, 0.4
colorbar_ref = None
cax = None
_contour_collections = []
save_queue = Queue()

# ------------------ Load logo ------------------
try:
    im_Migne = plt.imread(LOGO_PATH)
except Exception:
    im_Migne = None
    print("Warning: logo not found at", LOGO_PATH)

# ------------------ Serial init ------------------
try:
    ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=1)
    print("Serial opened:", SERIAL_PORT)
except Exception as e:
    print("Warning: could not open serial:", e)
    ser = None

# ------------------ Saver process ------------------
def save_figures(q):
    while True:
        item = q.get()
        if item is None:
            break
        fig_obj, filename = item
        try:
            fig_obj.savefig(filename, dpi=150)
            print("Saved:", filename)
        except Exception as ex:
            print("Save failed:", ex)

saver_proc = Process(target=save_figures, args=(save_queue,))
saver_proc.start()

# ------------------ Serial reading (v0.7 style) ------------------
def read_loop():
    """Continuously read serial lines and append x,y,z floats."""
    data_cnt = 0
    while True:
        if ser is None:
            time.sleep(0.1)
            continue
        try:
            raw = ser.readline()
        except Exception:
            time.sleep(0.1)
            continue
        if not raw:
            continue
        try:
            parts = raw.decode('ascii', errors='ignore').strip().split(',')
            if len(parts) < 3:
                continue
            x0 = float(parts[0]); y0 = float(parts[1]); z0 = float(parts[2])
        except Exception:
            # ignore bad lines
            continue

        data_cnt += 1
        x.append(x0); y.append(y0); z.append(z0)

        # legacy behavior: trim when huge
        if len(x) > 1500 and x0 == 3 and y0 >= 5:
            # keep last ~309 points per original logic
            del x[0:-309]; del y[0:-309]; del z[0:-309]

        # legacy behavior: if marker (100,100) with filename in 4th field, save figure
        try:
            if x0 == 100 and y0 == 100 and len(parts) >= 4 and parts[3].strip() != '':
                fn = parts[3].splitlines()[0].strip()
                # safe filename: use current working dir (Windows test)
                outpath = fn + ".png"
                # ask animation to render next frame then save (put fig object)
                try:
                    save_queue.put((fig, outpath))
                    print("Queueing save:", outpath)
                except Exception as e:
                    print("Save queue error:", e)
        except Exception:
            pass

        # avoid runaway memory
        if len(x) > 6000:
            del x[0:1000]; del y[0:1000]; del z[0:1000]

# ------------------ Plot / GUI Setup (v1.7 style) ------------------
fig = plt.figure('Scan System v1.8 (integrated)', figsize=[8, 3.8])
spec = gridspec.GridSpec(ncols=2, nrows=1, width_ratios=[1, 1])
ax = fig.add_subplot(spec[0, 0])
axh = fig.add_subplot(spec[0, 1], projection='3d')

def initialize_blank_plot():
    global cax, colorbar_ref
    ax.cla(); axh.cla()
    fig.patch.set_facecolor('#0042C1')
    ax.set_facecolor("#F8FAFF")
    axh.set_facecolor("none")
    if im_Migne is not None:
        ax.imshow(im_Migne, extent=[16, 84, 40, 60], alpha=0.08)
    ax.set_title('Foreign Object Detection', color="white", fontsize=10)
    ax.set_xlim([0, 100]); ax.set_ylim([0, 100])
    ax.grid(True, linestyle='--', alpha=0.4)
    ax.set_xlabel('x', color="white"); ax.set_ylabel('y', color="white")
    ax.tick_params(colors="white")
    axh.set_title('3D View', color="white", fontsize=10)
    axh.set_xlim([0, 100]); axh.set_ylim([0, 100]); axh.set_zlim([zmin, zmax])
    axh.view_init(elev=20, azim=300); axh.tick_params(colors="white")
    # create fixed colorbar axis (cax) to avoid stacking
    divider = make_axes_locatable(ax)
    cax = divider.append_axes("right", size="5%", pad=0.5)
    colorbar_ref = None

initialize_blank_plot()

# ------------------ Update function (old plotting behavior integrated) ------------------
def update(frame):
    global colorbar_ref, zmin, zmax, _contour_collections

    if len(x) < 3:
        return

    xs = np.array(x); ys = np.array(y); zs = np.array(z)

    if len(np.unique(xs)) < 2 or len(np.unique(ys)) < 2:
        return

    # Use unique coordinates in the order they appear (v0.7 used np.unique)
    x_grid, y_grid = np.meshgrid(np.unique(xs), np.unique(ys))

    try:
        z_new0 = griddata((xs, ys), zs, (x_grid, y_grid), method='cubic')
    except Exception:
        z_new0 = griddata((xs, ys), zs, (x_grid, y_grid), method='nearest')

    # keep zeros only for display where interpolation succeeded
    z_new = np.nan_to_num(z_new0, nan=0)

    # update z range based on valid values
    valid_mask = ~np.isnan(z_new0)
    if np.any(valid_mask):
        cur_min = np.nanmin(z_new0)
        cur_max = np.nanmax(z_new0)
        zmin = min(zmin, cur_min)
        zmax = max(zmax, cur_max)

    # --- 2D: clear whole axis like old code (this matches v0.7 rendering) ---
    ax.cla()
    if im_Migne is not None:
        ax.imshow(im_Migne, extent=[16, 84, 40, 60], alpha=np.random.randint(6,10)/100, zorder=0)

    ps = ax.contourf(x_grid, y_grid, z_new, 128, cmap="jet", vmin=zmin, vmax=zmax, alpha=0.9)
    # remove old collections (not necessary since clared) but keep for consistency
    _contour_collections = ps.collections if hasattr(ps, 'collections') else []

    # --- colorbar: attach to cax; create once or update ---
    if colorbar_ref is None:
        try:
            colorbar_ref = fig.colorbar(ps, cax=cax, shrink=1, orientation='vertical')
            colorbar_ref.ax.tick_params(colors='white')
            colorbar_ref.set_label("Z Value", color='white')
        except Exception as e:
            print("Colorbar create failed:", e)
            colorbar_ref = None
    else:
        try:
            colorbar_ref.update_normal(ps)
        except Exception:
            # fallback recreate
            try:
                colorbar_ref.remove()
            except Exception:
                pass
            try:
                colorbar_ref = fig.colorbar(ps, cax=cax, shrink=1, orientation='vertical')
                colorbar_ref.ax.tick_params(colors='white')
                colorbar_ref.set_label("Z Value", color='white')
            except Exception as e:
                print("Colorbar recreate failed:", e)
                colorbar_ref = None

    ax.set_xlim([0, 100]); ax.set_ylim([0, 100])
    ax.set_xlabel('x'); ax.set_ylabel('y')
    ax.set_title('Foreign object detection', fontsize=12, color=(0.2, 0.2, 0.2))

    # compute Z max/min for text (original behavior)
    try:
        z_max = max(z)
        z_min = min(z)
    except Exception:
        z_max = 0; z_min = 0

    # --- 3D ---
    axh.cla()
    try:
        axh.plot_surface(x_grid, y_grid, z_new, cmap="jet", vmin=zmin, vmax=zmax)
    except Exception:
        with np.errstate(invalid='ignore'):
            axh.plot_wireframe(x_grid, y_grid, z_new, rstride=4, cstride=4)

    # text in 3D like old code
    axh.text2D(0.70, 0.95, 'Z Max: {:.6f}'.format(z_max), transform=axh.transAxes)
    axh.text2D(0.70, 0.90, 'Z Min: {:.6f}'.format(z_min), transform=axh.transAxes)

    axh.set_xlim([0, 100]); axh.set_zlim([zmin, zmax]); ax.set_xlim([0, 100])
    axh.set_facecolor(color=(0.9, 0.9, 0.9))
    axh.set_xlabel('x'); axh.set_ylabel('y'); axh.set_zlabel('output')
    axh.set_title('Foreign object detection (3D)', fontsize=12, color=(0.2, 0.2, 0.2))
    ax.set_facecolor(color=(0.92, 0.92, 0.92))

# ------------------ Tk GUI (v1.7 interface) ------------------
root = tk.Tk()
root.title("Migne - Scan System")
root.geometry("800x480")
root.configure(bg="#0042C1")
root.resizable(False, False)
# If testing on Pi and want fullscreen, uncomment next line:
# root.attributes("-fullscreen", True)

# Grid layout
root.grid_rowconfigure(0, weight=1)
root.grid_columnconfigure(0, weight=1)
root.grid_columnconfigure(1, weight=0)

# Left (Figure)
frame_left = tk.Frame(root, bg="#0042C1")
frame_left.grid(row=0, column=0, sticky="nsew")
canvas = FigureCanvasTkAgg(fig, master=frame_left)
canvas.draw()
canvas.get_tk_widget().pack(fill="both", expand=True)

# Right (Controls)
frame_right = tk.Frame(root, bg="#003090", width=180)
frame_right.grid(row=0, column=1, sticky="ns")
frame_right.grid_propagate(False)

tk.Label(frame_right, text="System Controls", font=("Segoe UI", 11, "bold"),
         bg="#003090", fg="white").pack(pady=(10, 5))

# hidden toolbar instance (methods available)
toolbar = NavigationToolbar2Tk(canvas, frame_right)
toolbar.update()
toolbar.pack_forget()

btn_style = {"font": ("Segoe UI", 9, "bold"), "width": 16, "relief": "ridge"}
def make_btn(text, color, cmd=None, fg="black"):
    return tk.Button(frame_right, text=text, bg=color, fg=fg, command=cmd, **btn_style)

# keep control functions pointing to toolbar methods so they act on the canvas
make_btn("Home", "white", lambda: toolbar.home()).pack(pady=2)
make_btn("Back", "white", lambda: toolbar.back()).pack(pady=2)
make_btn("Forward", "white", lambda: toolbar.forward()).pack(pady=2)
make_btn("Pan", "white", lambda: toolbar.pan()).pack(pady=2)
make_btn("Zoom", "white", lambda: toolbar.zoom()).pack(pady=2)
make_btn("Save", "white", lambda: toolbar.save_figure()).pack(pady=2)

tk.Label(frame_right, bg="#004080", height=1).pack(fill="x", pady=8)
make_btn("Reboot", "#f5a623", cmd=lambda: print("Reboot pressed")).pack(pady=3)
make_btn("Shutdown", "#d9534f", fg="white", cmd=lambda: print("Shutdown pressed")).pack(pady=3)
tk.Button(frame_right, text="Exit", command=root.destroy,
          bg="#1C1C1C", fg="white", font=("Segoe UI", 9, "bold"),
          width=16, relief="ridge").pack(side="bottom", pady=10)

# toggle controls
def toggle_controls():
    if frame_right.winfo_ismapped():
        frame_right.grid_remove(); btn_toggle.config(text="Show Controls")
    else:
        frame_right.grid(); btn_toggle.config(text="Hide Controls")

btn_toggle = tk.Button(root, text="Hide Controls", command=toggle_controls,
                       bg="#1F4EB4", fg="white", font=("Segoe UI", 9, "bold"))
btn_toggle.place(x=5, y=5)

# ------------------ Threads & Animation ------------------
th = threading.Thread(target=read_loop, daemon=True)
th.start()

ani = animation.FuncAnimation(fig, update, interval=250, cache_frame_data=False)
canvas.draw_idle()

# run GUI
try:
    root.mainloop()
finally:
    # cleanup saver
    try:
        save_queue.put(None)
    except Exception:
        pass
    try:
        saver_proc.join(timeout=2)
    except Exception:
        pass
