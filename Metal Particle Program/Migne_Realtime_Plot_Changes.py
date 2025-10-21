#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Scan system for long loop - Auto-start version
Ver 0.9      2025-10-20
"""

import copy
import sys
import gc
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import matplotlib.widgets as wg
from matplotlib import gridspec
from mpl_toolkits.mplot3d import Axes3D
from scipy.interpolate import griddata
import numpy as np
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
from mpl_toolkits.axes_grid1 import make_axes_locatable, ImageGrid 
from multiprocessing import Process, Queue
import threading
import serial
import time
import tkinter as tk


# Global variables with default values
global x, y, z, zmin, zmax
x = []
y = []
z = []
zmin = -0.4
zmax = 0.4

# Import Migne image
im_Migne = plt.imread(r"C:\Users\a493353\Desktop\Lans Galos\Raspberry Pi Program\Metal Particle Program\Migne_black_frameless.png")

# Serial initialization
try:
    ser = serial.Serial("COM6", 115200, timeout=1)
except serial.SerialException as e:
    print(f"Error: Could not open serial port.\n{str(e)}")
    ser = None
    sys.exit("Serial port not available. Exiting.")

def save_figures(queue):
    while True:
        fig, filename = queue.get()
        if fig is None:
            break

queue = Queue()
saving_process = Process(target=save_figures, args=(queue,))
saving_process.start()

def read_loop():
    data_cnt = 0
    while True:
        if ser is None:
            break  # Should never happen due to sys.exit above

        # Read real serial data
        rcv_data = ser.readline()
        if len(rcv_data) == 0:
            continue

        try:
            rcv_data = rcv_data.decode('ascii').split(',')
            x0 = float(rcv_data[0])
            y0 = float(rcv_data[1])
            z0 = float(rcv_data[2])
        except (ValueError, IndexError):
            print('data error @count=', data_cnt)
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

def initialize_blank_plot():
    ax.cla()
    axh.cla()
    
    ax.grid(True, linestyle='--', alpha=0.7)
    ax.set_xticks(np.arange(0, 101, 20))
    ax.set_yticks(np.arange(0, 101, 20))
    ax.set_facecolor('white')
    
    axh.grid(True, linestyle='-', alpha=0.7)
    axh.set_xticks(np.arange(0, 101, 20))
    axh.set_yticks(np.arange(0, 101, 25))
    axh.set_zticks(np.arange(-0.4, 0.41, 0.2))
    axh.set_facecolor('none')
    
    ax.set_xlabel('x')
    ax.set_ylabel('y')
    ax.set_title('Foreign object detection')
    ax.set_xlim([0, 100])
    ax.set_ylim([0, 100])
    
    axh.view_init(elev=20, azim=300)
    axh.set_box_aspect((5, 5, 3.5))
    axh.set_xlabel('x')
    axh.set_ylabel('y')
    axh.set_zlabel('output')
    axh.set_title('Foreign object detection (3D)')
    axh.set_xlim([0, 100])
    axh.set_ylim([0, 100])
    axh.set_zlim([zmin, zmax])
    
    ax.imshow(im_Migne, extent=[16, 84, 40, 60], alpha=np.random.randint(6,10)/100)
    axm.imshow(im_Migne, alpha=0.7)
    axm.axis("off")

def update(i, xt, yt, zt, zmin, zmax):
    if len(x) < 2:
        return
        
    xs = copy.copy(x)
    ys = copy.copy(y)
    zs = copy.copy(z)
    
    if len(xs) != len(zs):
        del xs[len(zs) - len(xs)] 
        del ys[len(zs) - len(ys)]
        
    if len(np.unique(xs)) < 2 or len(np.unique(ys)) < 2:
        return
        
    x_new, y_new = np.meshgrid(np.unique(xs), np.unique(ys))
    z_new0 = griddata((xs, ys), zs, (x_new, y_new), method='cubic')
    z_new = np.nan_to_num(z_new0, nan=0)

    if np.max(z_new) > zmax:
        zmax = np.max(z_new)
    if np.min(z_new) < zmin:
        zmin = np.min(z_new)
    
    z_max = max(z) if z else 0
    z_min = min(z) if z else 0
    
    fig.clf()
    ax = fig.add_subplot(spec[1:, 0])
    axh = fig.add_subplot(spec[1:, 1], projection='3d')
    axm = fig.add_subplot(spec[0, 0:])
    divider = make_axes_locatable(ax)
    cax = divider.append_axes("right", size="5%", pad=0.5)

    axh.view_init(elev=20, azim=300)
    axh.set_box_aspect((5, 5, 2))
    axh.mouse_init(rotate_btn=None)

    ax.imshow(im_Migne, extent=[16, 84, 40, 60], alpha=np.random.randint(6,10)/100)
    ps = ax.contourf(x_new, y_new, z_new, 128, cmap="jet", vmin=zmin, vmax=zmax, alpha=0.9)
    psh = axh.plot_surface(x_new, y_new, z_new, cmap="jet", vmin=zmin, vmax=zmax,
                          rstride=1, cstride=1)
    ax.figure.colorbar(psh, cax=cax, shrink=1, orientation='vertical')
    axm.imshow(im_Migne, alpha=0.7)
    axm.axis("off")
    
    z_max_text = axh.text2D(0.70, 0.95, 'Z Max: {:.6f}'.format(z_max), transform=axh.transAxes)
    z_min_text = axh.text2D(0.70, 0.90, 'Z Min: {:.6f}'.format(z_min), transform=axh.transAxes)
    
    axh.set_xlim([0, 100])
    axh.set_zlim([zmin, zmax])
    ax.set_xlim([0, 100])
    axh.set_facecolor(color=(0.9, 0.9, 0.9))
    axh.set_xlabel('x')
    axh.set_ylabel('y')
    axh.set_zlabel('output')
    axh.set_title('Foreign object detection (3D)', fontsize=16, color=(0.2, 0.2, 0.2))
    ax.set_facecolor(color=(0.92, 0.92, 0.92))
    ax.set_xlabel('x')
    ax.set_ylabel('y')
    ax.set_title('Foreign object detection', fontsize=16, color=(0.2, 0.2, 0.2))
    
    # Add grid to match original
    axh.grid(True, linestyle='-', alpha=0.2)
    ax.grid(True, linestyle='--', alpha=0.7)

# Start serial reading thread
th_ser = threading.Thread(target=read_loop)
th_ser.daemon = True
th_ser.start()

# Create main figure and subplots
fig = plt.figure('Scan system    ver.0.9', figsize=[13,6], facecolor=(0.9, 0.9, 0.9))
spec = gridspec.GridSpec(ncols=2, nrows=2,
                        width_ratios=[5, 5],
                        height_ratios=[1, 12.5])
ax = fig.add_subplot(spec[1:, 0])
axh = fig.add_subplot(spec[1:, 1], projection='3d')
axm = fig.add_subplot(spec[0, 0:])
divider = make_axes_locatable(ax)
cax = divider.append_axes("right", size="5%", pad=0.5)

# Adjust subplot spacing for smaller display
fig.subplots_adjust(left=0.08, right=0.92, 
                   bottom=0.08, top=0.92,
                   hspace=0.25, wspace=0.25)  # Tighter spacing

# Initialize with blank plot
initialize_blank_plot()

# Start animation
xt = []
yt = []
zt = []

# Create animation with explicit save_count
ani = animation.FuncAnimation(fig, update, 
                            fargs=(xt, yt, zt, zmin, zmax),
                            interval=250,
                            cache_frame_data=False,
                            save_count=100)

# Set window to maximize

plt.show()

# Cleanup
queue.put(None)
saving_process.join()