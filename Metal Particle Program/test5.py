#!/usr/bin/env python
# -*- coding: utf-8 -*-
import copy
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib import gridspec
from mpl_toolkits.mplot3d import Axes3D
from mpl_toolkits.axes_grid1 import make_axes_locatable
from scipy.interpolate import griddata
import numpy as np
import threading
import serial

# --- Global data ---
x = []
y = []
z = []

zmin = -0.4
zmax = 0.4

# --- Load logo ---
im_Migne = plt.imread(r"C:\Users\a493353\Desktop\Lans Galos\Raspberry Pi Program\Metal Particle Program\Migne_black_frameless.png")

# --- Serial init ---
ser = serial.Serial("COM7", 115200, timeout=1)

# --- Serial reading thread ---
def read_loop():
    while True:
        rcv_data = ser.readline()
        if len(rcv_data) == 0:
            continue
        try:
            rcv_data = rcv_data.decode('ascii').strip().split(',')
            x0 = float(rcv_data[0])
            y0 = float(rcv_data[1])
            z0 = float(rcv_data[2])
        except (ValueError, IndexError):
            continue
        else:
            x.append(x0)
            y.append(y0)
            z.append(z0)
            if len(x) > 1500 and x0 == 3 and y0 >= 5:
                del x[0:-309]
                del y[0:-309]
                del z[0:-309]

# Start serial reading in background
threading.Thread(target=read_loop, daemon=True).start()

# --- Figure setup ---
fig = plt.figure('Scan system ver.0.7', figsize=[13,6], facecolor=(0.9, 0.9, 0.9))
spec = gridspec.GridSpec(ncols=2, nrows=2, width_ratios=[5,5], height_ratios=[1,12.5])

ax = fig.add_subplot(spec[1:, 0])
axh = fig.add_subplot(spec[1:, 1], projection='3d')
axm = fig.add_subplot(spec[0, 0:])
axm.axis("off")
axm.imshow(im_Migne, alpha=0.7)

# Initialize blank plots
ax.set_xlim([0, 100])
ax.set_ylim([0, 100])
ax.set_facecolor((0.92,0.92,0.92))
ax.set_xlabel('x')
ax.set_ylabel('y')
ax.set_title('Foreign object detection')

axh.set_xlim([0, 100])
axh.set_ylim([0, 100])
axh.set_zlim([zmin, zmax])
axh.set_facecolor((0.9,0.9,0.9))
axh.set_xlabel('x')
axh.set_ylabel('y')
axh.set_zlabel('output')
axh.set_title('Foreign object detection (3D)', fontsize=16, color=(0.2,0.2,0.2))

# --- Update function ---
def update(frame):
    if len(x) < 3:  # Need at least 3 points for griddata cubic
        return

    xs = copy.copy(x)
    ys = copy.copy(y)
    zs = copy.copy(z)

    x_new, y_new = np.meshgrid(np.unique(xs), np.unique(ys))
    try:
        z_new0 = griddata((xs, ys), zs, (x_new, y_new), method='cubic')
        z_new = np.nan_to_num(z_new0, nan=0)
    except:
        return

    global zmin, zmax
    zmax = max(zmax, np.max(z_new))
    zmin = min(zmin, np.min(z_new))

    # 2D plot
    ax.cla()
    ax.imshow(im_Migne, extent=[16, 84, 40, 60], alpha=0.5)
    ps = ax.contourf(x_new, y_new, z_new, 64, cmap='jet', vmin=zmin, vmax=zmax)
    divider = make_axes_locatable(ax)
    cax = divider.append_axes("right", size="5%", pad=0.5)
    ax.figure.colorbar(ps, cax=cax)
    ax.set_xlim([0,100])
    ax.set_ylim([0,100])
    ax.set_facecolor((0.92,0.92,0.92))
    ax.set_xlabel('x')
    ax.set_ylabel('y')
    ax.set_title('Foreign object detection')

    # 3D plot (do not fully clear to keep Axes3D working)
    axh.cla()
    axh.plot_surface(x_new, y_new, z_new, cmap='jet', vmin=zmin, vmax=zmax)
    axh.set_xlim([0,100])
    axh.set_ylim([0,100])
    axh.set_zlim([zmin,zmax])
    axh.set_facecolor((0.9,0.9,0.9))
    axh.set_xlabel('x')
    axh.set_ylabel('y')
    axh.set_zlabel('output')
    axh.set_title('Foreign object detection (3D)')

# --- Animate ---
ani = animation.FuncAnimation(fig, update, interval=250)
figmanager = plt.get_current_fig_manager()

plt.show()
