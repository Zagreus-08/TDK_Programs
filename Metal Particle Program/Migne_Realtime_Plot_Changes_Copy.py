#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Scan System GUI (Blue Unified Theme, Enhanced Display)
Ver 1.5      2025-10-22
"""

import copy
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

# ------------------ Logo ------------------
im_Migne = plt.imread(
    r"C:\Users\a493353\Desktop\Lans Galos\Raspberry Pi Program\Metal Particle Program\Migne_black_frameless.png"
)

# ------------------ Serial Init ------------------
try:
    ser = serial.Serial("COM7", 115200, timeout=1)
except serial.SerialException as e:
    print(f"Error: Could not open serial port.\n{str(e)}")
    ser = None
    sys.exit("Serial port not available. Exiting.")


# ------------------ Save Process ------------------
def save_figures(queue):
    while True:
        fig, filename = queue.get()
        if fig is None:
            break
        fig.savefig(filename, dpi=150)
        print("Saved:", filename)


queue = Queue()
saving_process = Process(target=save_figures, args=(queue,))
saving_process.start()


# ------------------ Serial Read Thread ------------------
def read_loop():
    data_cnt = 0
    while True:
        if ser is None:
            break
        rcv_data = ser.readline()
        if len(rcv_data) == 0:
            continue
        try:
            rcv_data = rcv_data.decode('ascii').split(',')
            x0 = float(rcv_data[0])
            y0 = float(rcv_data[1])
            z0 = float(rcv_data[2])
        except (ValueError, IndexError):
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
                fn_parts = rcv_data[3].split('\n')
                time.sleep(5)
                queue.put((fig, '/home/pi/Shared/' + fn_parts[0] + '.png'))
            except:
                pass

        if data_cnt == 6000000:
            return


# ------------------ Plot Initialization ------------------
def initialize_blank_plot():
    ax.cla()
    axh.cla()

    fig.patch.set_facecolor("#003366")  # unified blue background

    ax.set_facecolor("#F8FAFF")
    axh.set_facecolor("#F8FAFF")

    # 2D
    ax.imshow(im_Migne, extent=[16, 84, 40, 60], alpha=0.08)
    ax.set_title('Foreign Object Detection', color="white", fontsize=12, pad=10)
    ax.set_xlim([0, 100])
    ax.set_ylim([0, 100])
    ax.grid(True, linestyle='--', alpha=0.4)
    ax.set_xlabel('x', color="white")
    ax.set_ylabel('y', color="white")
    ax.tick_params(colors="white")

    # 3D
    axh.set_title('Foreign Object Detection (3D)', color="white", fontsize=12, pad=10)
    axh.view_init(elev=20, azim=300)
    axh.set_xlim([0, 100])
    axh.set_ylim([0, 100])
    axh.set_zlim([zmin, zmax])
    axh.set_xlabel('x', color="white")
    axh.set_ylabel('y', color="white")
    axh.set_zlabel('output', color="white")
    axh.tick_params(colors="white")

    # --- Make 3D box float with no solid background ---
    axh.set_facecolor("none")  # fully transparent background

    # brighten up grid lines and axes for visibility
    axh.xaxis._axinfo['grid']['color'] = (1, 1, 1, 0.2)
    axh.yaxis._axinfo['grid']['color'] = (1, 1, 1, 0.2)
    axh.zaxis._axinfo['grid']['color'] = (1, 1, 1, 0.2)

    # make pane faces slightly lighter (semi-transparent white tint)
    for axis in [axh.xaxis, axh.yaxis, axh.zaxis]:
        axis.pane.fill = True
        axis.pane.set_facecolor((1, 1, 1, 0.1))  # faint white tint for 3D cube visibility

    # brighter ticks and labels for better contrast
    axh.tick_params(colors="white", labelcolor="white")
    axh.xaxis.label.set_color("white")
    axh.yaxis.label.set_color("white")
    axh.zaxis.label.set_color("white")

    # adjust grid and box to fit the deep blue GUI
    axh.grid(True, linestyle='--', color='white', alpha=0.3)


    # Migne overlay on header
    axm.imshow(im_Migne, alpha=0.7)
    axm.axis("off")


# ------------------ Update Function ------------------
def update(i, xt, yt, zt, zmin, zmax):
    if len(x) < 2:
        return

    xs, ys, zs = copy.copy(x), copy.copy(y), copy.copy(z)
    if len(xs) != len(zs):
        return

    if len(np.unique(xs)) < 2 or len(np.unique(ys)) < 2:
        return

    x_new, y_new = np.meshgrid(np.unique(xs), np.unique(ys))
    z_new0 = griddata((xs, ys), zs, (x_new, y_new), method='cubic')
    z_new = np.nan_to_num(z_new0, nan=0)

    ax.cla()
    axh.cla()

    ax.imshow(im_Migne, extent=[16, 84, 40, 60], alpha=0.08)
    ps = ax.contourf(x_new, y_new, z_new, 128, cmap="jet", vmin=zmin, vmax=zmax, alpha=0.95)
    ax.figure.colorbar(ps, ax=ax, shrink=0.95, orientation='vertical')

    axh.plot_surface(x_new, y_new, z_new, cmap="jet", vmin=zmin, vmax=zmax, rstride=1, cstride=1)
        # --- Make 3D box float with no solid background ---
    axh.set_facecolor("none")  # fully transparent background

    # brighten up grid lines and axes for visibility
    axh.xaxis._axinfo['grid']['color'] = (1, 1, 1, 0.2)
    axh.yaxis._axinfo['grid']['color'] = (1, 1, 1, 0.2)
    axh.zaxis._axinfo['grid']['color'] = (1, 1, 1, 0.2)

    # make pane faces slightly lighter (semi-transparent white tint)
    for axis in [axh.xaxis, axh.yaxis, axh.zaxis]:
        axis.pane.fill = True
        axis.pane.set_facecolor((1, 1, 1, 0.1))  # faint white tint for 3D cube visibility

    # brighter ticks and labels for better contrast
    axh.tick_params(colors="white", labelcolor="white")
    axh.xaxis.label.set_color("white")
    axh.yaxis.label.set_color("white")
    axh.zaxis.label.set_color("white")

    # adjust grid and box to fit the deep blue GUI
    axh.grid(True, linestyle='--', color='white', alpha=0.3)



    # Style
    for axis in [ax, axh]:
        axis.set_xlim([0, 100])
        axis.set_ylim([0, 100])
        axis.grid(True, linestyle='--', alpha=0.4)

    axh.set_zlim([zmin, zmax])
    ax.set_title('Foreign Object Detection', color="white", fontsize=12, pad=10)
    axh.set_title('Foreign Object Detection (3D)', color="white", fontsize=12, pad=10)
    ax.tick_params(colors="white")
    axh.tick_params(colors="white")
    axh.set_xlabel('x', color="white")
    axh.set_ylabel('y', color="white")
    axh.set_zlabel('output', color="white")


# ------------------ Figure ------------------
fig = plt.figure('Scan System v1.5', figsize=[11, 5])
spec = gridspec.GridSpec(ncols=2, nrows=2, width_ratios=[5, 5], height_ratios=[1, 12])
ax = fig.add_subplot(spec[1:, 0])
axh = fig.add_subplot(spec[1:, 1], projection='3d')
axm = fig.add_subplot(spec[0, 0:])
axm.axis("off")
initialize_blank_plot()

# ------------------ GUI ------------------
root = tk.Tk()
root.title("Migne - Scan System")
root.geometry("1280x720")
root.configure(bg="#002B5C")

frame_left = tk.Frame(root, bg="#003366")
frame_left.pack(side="left", fill="both", expand=True)

canvas = FigureCanvasTkAgg(fig, master=frame_left)
canvas.draw()
canvas.get_tk_widget().pack(side="top", fill="both", expand=True)

# Right Control Frame
frame_right = tk.Frame(root, width=220, bg="#001F3F")
frame_right.pack(side="right", fill="y", padx=10, pady=10)

tk.Label(frame_right, text="System Controls", font=("Segoe UI", 12, "bold"),
         bg="#001F3F", fg="white").pack(pady=(0, 5))

toolbar = NavigationToolbar2Tk(canvas, frame_left)
toolbar.update()
toolbar.pack_forget()

btn_style = {"font": ("Segoe UI", 9, "bold"), "width": 18, "relief": "ridge"}

def make_btn(text, color, cmd=None, fg="black"):
    return tk.Button(frame_right, text=text, bg=color, fg=fg, command=cmd, **btn_style)

make_btn("Home", "white", toolbar.home).pack(pady=3)
make_btn("Back", "white", toolbar.back).pack(pady=3)
make_btn("Forward", "white", toolbar.forward).pack(pady=3)
make_btn("Pan", "white", toolbar.pan).pack(pady=3)
make_btn("Zoom", "white", toolbar.zoom).pack(pady=3)
make_btn("Save", "white", toolbar.save_figure).pack(pady=3)

tk.Label(frame_right, bg="#004080", height=1).pack(fill="x", pady=8)

make_btn("Reboot", "#f5a623").pack(pady=5)
make_btn("Shutdown", "#d9534f", fg="white").pack(pady=5)

tk.Button(frame_right, text="Exit", command=root.destroy,
          bg="#1C1C1C", fg="white", font=("Segoe UI", 9, "bold"),
          width=18, relief="ridge").pack(side="bottom", pady=15)

# ------------------ Threads and Animation ------------------
th_ser = threading.Thread(target=read_loop, daemon=True)
th_ser.start()

ani = animation.FuncAnimation(fig, update, fargs=([], [], [], zmin, zmax),
                              interval=250, cache_frame_data=False, save_count=100)

canvas.draw_idle()
root.mainloop()

# ------------------ Cleanup ------------------
queue.put(None)
saving_process.join()
