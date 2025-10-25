#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Scan System GUI (Blue Unified Theme, Fixed 800x480 Layout)
Ver 1.7.2     2025-10-22
"""

import copy
from math import pi
import sys
import gc
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib import gridspec
from mpl_toolkits.mplot3d import Axes3D
from scipy.interpolate import griddata
import numpy as np
from multiprocessing import Process, Queue
import threading
import serial
import time
import tkinter as tk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

# ------------------ Global Variables ------------------
x, y, z = [], [], []
zmin, zmax = -0.4, 0.4
colorbar_ref = None

# ------------------ Logo ------------------
im_Migne = plt.imread(r"C:\Users\a493353\Desktop\Lans Galos\Raspberry Pi Program\Metal Particle Program\Migne_black_frameless.png")


# ------------------ Serial Init ------------------
try:
    ser = serial.Serial("COM7", 115200, timeout=1)
except serial.SerialException as e:
    print(f"Error: Could not open serial port.\n{str(e)}")
    ser = None

# ------------------ Save Process ------------------
def save_figures(queue):
    while True:
        item = queue.get()
        if item is None:
            break
        fig_obj, filename = item
        try:
            fig_obj.savefig(filename, dpi=150)
            print("Saved:", filename)
        except Exception as ex:
            print("Save failed:", ex)
            
save_queue = Queue()
saving_process = Process(target=save_figures, args=(save_queue,))
saving_process.start()

# ------------------ Serial Thread ------------------
def read_loop():
    """Continuously read serial lines and append x,y,z floats."""
    while True:
        if ser is None:
            time.sleep(0.1)
            continue
        try:
            rcv = ser.readline()
        except Exception:
            time.sleep(0.1)
            continue

        if not rcv:
            continue

        try:
            vals = rcv.decode('ascii', errors='ignore').strip().split(',')
            if len(vals) < 3:
                continue
            x0, y0, z0 = map(float, vals[:3])
        except Exception:
            continue

        x.append(x0)
        y.append(y0)
        z.append(z0)

        # Optional: keep buffer bounded for very long runs
        if len(x) > 5000:
            del x[0:1000]; del y[0:1000]; del z[0:1000]

# ------------------ Plot Setup ------------------
def initialize_blank_plot():
    ax.cla()
    axh.cla()
    fig.patch.set_facecolor('#0042C1')
    ax.set_facecolor("#F8FAFF")
    axh.set_facecolor("none")
    # draw logo once (will be redrawn in update but keep initial)
    ax.imshow(im_Migne, extent=[16, 84, 40, 60], alpha=0.08)
    ax.set_title('Foreign Object Detection', color="white", fontsize=10)
    ax.set_xlim([0, 100])
    ax.set_ylim([0, 100])
    ax.grid(True, linestyle='--', alpha=0.4)
    ax.set_xlabel('x', color="white")
    ax.set_ylabel('y', color="white")
    ax.tick_params(colors="white")
    axh.set_title('3D View', color="white", fontsize=10)
    axh.set_xlim([0, 100])
    axh.set_ylim([0, 100])
    axh.set_zlim([zmin, zmax])
    axh.view_init(elev=20, azim=300)
    axh.tick_params(colors="white")

def update(frame):
    """
    Continuous scanning plot update.
    Builds 2D and 3D data progressively (no refresh wipe).
    Keeps single colorbar updated dynamically.
    """
    global zmin, zmax, contour_ref, surf_ref, colorbar_ref

    if len(x) < 3:
        return

    xs = np.array(x)
    ys = np.array(y)
    zs = np.array(z)

    if len(np.unique(xs)) < 2 or len(np.unique(ys)) < 2:
        return

    nx, ny = 80, 80
    x_vals = np.linspace(np.min(xs), np.max(xs), nx)
    y_vals = np.linspace(np.min(ys), np.max(ys), ny)
    x_new, y_new = np.meshgrid(x_vals, y_vals)

    try:
        z_new = griddata((xs, ys), zs, (x_new, y_new), method='cubic')
    except Exception:
        z_new = griddata((xs, ys), zs, (x_new, y_new), method='nearest')

    z_new = np.nan_to_num(z_new, nan=0)
    zmax = max(zmax, np.max(z_new))
    zmin = min(zmin, np.min(z_new))

    # --- 2D Plot (do NOT recreate colorbar each frame) ---
    ax.clear()
    ax.imshow(im_Migne, extent=[16, 84, 40, 60], alpha=0.08)
    contour_ref = ax.contourf(x_new, y_new, z_new, 128, cmap='jet', vmin=zmin, vmax=zmax)
    ax.set_xlim([0, 100])
    ax.set_ylim([0, 100])
    ax.set_xlabel('x', color='white')
    ax.set_ylabel('y', color='white')
    ax.set_title('Foreign Object Detection', color='white', fontsize=10)
    ax.tick_params(colors='white')
    ax.grid(True, linestyle='--', alpha=0.4)

    # Create colorbar only once
    from mpl_toolkits.axes_grid1 import make_axes_locatable
    if colorbar_ref is None:
        divider = make_axes_locatable(ax)
        cax = divider.append_axes("right", size="5%", pad=0.4)
        colorbar_ref = fig.colorbar(contour_ref, cax=cax)
        colorbar_ref.ax.tick_params(colors='white')
        colorbar_ref.set_label("Z Value", color='white')
    else:
        colorbar_ref.update_normal(contour_ref)

    # --- 3D Plot (progressive surface build-up) ---
    axh.clear()
    surf_ref = axh.plot_surface(x_new, y_new, z_new, cmap='jet',
                                vmin=zmin, vmax=zmax, linewidth=0,
                                antialiased=True, alpha=0.95)
    axh.set_xlim([0, 100])
    axh.set_ylim([0, 100])
    axh.set_zlim([zmin, zmax])
    axh.set_xlabel('x', color='white')
    axh.set_ylabel('y', color='white')
    axh.set_zlabel('z', color='white')
    axh.set_title('3D View', color='white', fontsize=10)
    axh.tick_params(colors='white')
    axh.grid(True, linestyle='--', alpha=0.3)


# ------------------ Figure ------------------
fig = plt.figure('Scan System v1.7.4', figsize=[8, 3.8])
spec = gridspec.GridSpec(ncols=2, nrows=1, width_ratios=[1, 1])
ax = fig.add_subplot(spec[0, 0])
axh = fig.add_subplot(spec[0, 1], projection='3d')
initialize_blank_plot()

# ------------------ GUI ------------------
root = tk.Tk()
root.title("Migne - Scan System")
root.geometry("800x480")
root.configure(bg="#0042C1")
root.resizable(False, False)

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

# create a hidden toolbar instance but don't pack it into the figure area
toolbar = NavigationToolbar2Tk(canvas, frame_right)
toolbar.update()
toolbar.pack_forget()  # keep toolbar methods available but hidden

btn_style = {"font": ("Segoe UI", 9, "bold"), "width": 16, "relief": "ridge"}

def make_btn(text, color, cmd=None, fg="black"):
    return tk.Button(frame_right, text=text, bg=color, fg=fg, command=cmd, **btn_style)

# Keep control functions pointing to toolbar methods so they act on the canvas
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

# ------------------ Toggle Button ------------------
def toggle_controls():
    if frame_right.winfo_ismapped():
        frame_right.grid_remove()
        btn_toggle.config(text="Show Controls")
    else:
        frame_right.grid()
        btn_toggle.config(text="Hide Controls")

btn_toggle = tk.Button(root, text="Hide Controls", command=toggle_controls,
                       bg="#1F4EB4", fg="white", font=("Segoe UI", 9, "bold"))
btn_toggle.place(x=5, y=5)

# ------------------ Threads & Animation ------------------
th_ser = threading.Thread(target=read_loop, daemon=True)
th_ser.start()

ani = animation.FuncAnimation(fig, update, interval=300, cache_frame_data=False)

canvas.draw_idle()
root.mainloop()

# ------------------ Cleanup ------------------
save_queue.put(None)
saving_process.join()
