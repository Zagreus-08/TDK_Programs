#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Scan system for long loop - Auto-start version (Fullscreen + Toggleable Controls)
Ver 0.9R-stable7    2025-10-27
"""

import copy
import sys
import gc
import os
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
from tkinter import messagebox
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

# ---------------- Global vars ----------------
x, y, z = [], [], []
zmin, zmax = -0.4, 0.4

# ---------------- Image ----------------
im_Migne = plt.imread(
    r"C:\Users\a493353\Desktop\Lans Galos\Raspberry Pi Program\Metal Particle Program\Migne_black_frameless.png"
)

# ---------------- Serial ----------------
try:
    ser = serial.Serial("COM7", 115200, timeout=1)
except serial.SerialException as e:
    print(f"Error: Could not open serial port.\n{str(e)}")
    ser = None
    sys.exit("Serial port not available. Exiting.")

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

# ---------------- Serial loop ----------------
def read_loop():
    data_cnt = 0
    while True:
        if ser is None:
            break
        rcv_data = ser.readline()
        if len(rcv_data) == 0:
            continue
        try:
            rcv_data = rcv_data.decode("ascii").split(",")
            x0 = float(rcv_data[0])
            y0 = float(rcv_data[1])
            z0 = float(rcv_data[2])
        except (ValueError, IndexError):
            print("data error @count=", data_cnt)
            continue

        data_cnt += 1
        x.append(x0)
        y.append(y0)
        z.append(z0)

        if len(x) > 1500 and x0 == 3 and y0 >= 5:
            del x[0:-309]
            del y[0:-309]
            del z[0:-309]

        if x0 == 100 and y0 == 100:
            try:
                fn_parts = rcv_data[3].split("\n")
                time.sleep(5)
                try:
                    queue.put((fig, "/home/pi/Shared/" + fn_parts[0] + ".png"))
                except Exception:
                    pass
            except Exception:
                pass

        if data_cnt == 6000000:
            return

# ---------------- Initialize blank plot ----------------
def initialize_blank_plot():
    ax.cla()
    axh.cla()
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

    # ---- align both titles at same Y level ----
    y_title = 1.02
    ax.set_title("Foreign object detection", fontsize=16, color=(0.2, 0.2, 0.2), y=y_title)
    axh.set_title("Foreign object detection (3D)", fontsize=16, color=(0.2, 0.2, 0.2), y=y_title)

    axh.view_init(elev=20, azim=300)
    axh.set_box_aspect((5, 5, 3.5))
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
    if len(x) < 2:
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
    axh.set_box_aspect((5, 5, 3.5))
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

    # keep same title Y level
    y_title = 1.02
    ax.set_title("Foreign object detection", fontsize=16, color=(0.2, 0.2, 0.2), y=y_title)
    axh.set_title("Foreign object detection (3D)", fontsize=16, color=(0.2, 0.2, 0.2), y=y_title)

# ---------------- GUI setup ----------------
th_ser = threading.Thread(target=read_loop, daemon=True)
th_ser.start()

root = tk.Tk()
root.title("Scan system ver.0.9R-stable7")
root.configure(bg="#e5e5e5")
root.attributes("-fullscreen", True)
root.bind("<Escape>", lambda e: root.attributes("-fullscreen", False))

main_frame = tk.Frame(root, bg="#e5e5e5")
main_frame.pack(fill=tk.BOTH, expand=True)
main_frame.grid_rowconfigure(0, weight=1)
main_frame.grid_columnconfigure(0, weight=1)
main_frame.grid_columnconfigure(1, weight=0)

# Plot frame
plot_frame = tk.Frame(main_frame, bg="#e5e5e5")
plot_frame.grid(row=0, column=0, sticky="nsew")

# Controls frame
controls_frame = tk.Frame(main_frame, bg="#d9d9d9", padx=6, pady=6, relief="ridge", bd=3)
controls_frame.grid(row=0, column=1, sticky="ns")

# Create figure
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

# ---------------- Control buttons ----------------
btn_style = {
    "font": ("Arial", 11, "bold"),
    "bg": "#f2f2f2",
    "width": 14,
    "height": 1,
    "relief": "raised",
}

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
        os.system("sudo shutdown now")
def do_exit():
    if messagebox.askyesno("Exit", "Close the program?"):
        try: ser.close()
        except: pass
        queue.put(None)
        saving_process.join()
        root.destroy()
        sys.exit(0)

buttons = [
    ("🏠 Home", do_home),
    ("✋ Pan", do_pan),
    ("🔍 Zoom", do_zoom),
    ("💾 Save", do_save),
    ("🔄 Reboot", do_reboot),
    ("⏻ Shutdown", do_shutdown),
    ("❌ Exit", do_exit),
]

for text, cmd in buttons:
    tk.Button(controls_frame, text=text, command=cmd, **btn_style).pack(pady=4, fill=tk.X)

# Toggle button to hide/show controls
def toggle_controls():
    if controls_frame.winfo_viewable():
        controls_frame.grid_remove()
    else:
        controls_frame.grid()
    root.update_idletasks()

toggle_btn = tk.Button(
    root, text="⚙️", font=("Arial", 14, "bold"),
    bg="#cccccc", relief="raised", width=3, height=1,
    command=toggle_controls
)
toggle_btn.place(x=10, y=10)

# ---------------- Animation ----------------
xt, yt, zt = [], [], []
ani = animation.FuncAnimation(fig, update, fargs=(xt, yt, zt, zmin, zmax),
                              interval=250, cache_frame_data=False, save_count=100)

canvas.draw()
root.mainloop()
queue.put(None)
saving_process.join()
