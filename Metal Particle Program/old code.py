#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Scan system for long loop

Ver 0.7      Oct12, 2022

Implemented exceptional handling for float()
Implemented continuous sweep/ Fixed indent
added Migne logo and fixed  ratio
added excursion setting
Modified colorbar
Modified for matlab3.50 or upperversion
Modified colorbar range setting from -0.4 to +0.4, see line42-43
Implemented colorbar range iuput

"""
#
# library imports (order according to PEP8)
#

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
import threading # key_send_to_ume.py
import serial
import time

#data
global x, y, z, zmin, zmax
x = []
y = []
z = []
zmin = -0.4
zmax = +0.4
"""
222
"""
#
print('original recursionlimit=', sys.getrecursionlimit())
sys.setrecursionlimit(1000)
print('set recursionlimit=', sys.getrecursionlimit())

print('----------------------------------------------')
print('colorbar range setting (-cbr to +cbr)')
print('original mode: 0, [return]: 0.4 ')
input_range = input('>>>>>>>>>>>>>>>>>> Input colorbar range [cbr] ---> ')
if input_range == '':
    zmin = -0.4
    zmax = +0.4
else:
    zmin = -abs(float(input_range))
    zmax =  abs(float(input_range))
print('colorbar initial setting range: ', zmin, ' to ', zmax)

# import migne image
im_Migne = plt.imread(r"C:\Users\a493353\Desktop\Lans Galos\Raspberry Pi Program\Metal Particle Program\Migne_black_frameless.png")
#im_Migne = plt.imread('Migne_black_blank.png')

#serial init
ser = serial.Serial("COM7",115200,timeout=1)

#serial event hundler

def save_figures(queue):
    while True:
        fig, filename = queue.get()
        fig.savefig(filename)
        
queue = Queue()

saving_process = Process(target=save_figures, args=(queue,))
saving_process.start()

def read_loop():
   data_cnt = 0
   while True :
      rcv_data = ser.readline() # binary入力
      if len(rcv_data) != 0:
          data_cnt += 1
          try:
              print(rcv_data)
              rcv_data = rcv_data.decode('ascii').split(',')
              x0 = float(rcv_data[0])
              y0 = float(rcv_data[1])
              z0 = float(rcv_data[2])

          except ValueError:
              print('data error @count=',data_cnt)
          else:
              x.append(x0)
              y.append(y0)
              z.append(z0)
              
              if len(x) >1500 and x0 == 3 and y0 >= 5:
                  print('-----------------------------------')
                  print('cleared data @(x,y)=(','{:.1f}'.format(x0), ',',
                                                    '{:.1f}'.format(y0),
                                                    '), and continue scanning!')
                  del x[0:-309]   # keep data for griddata
                  del y[0:-309]
                  del z[0:-309]    
             
              if x0 == 100 and y0 == 100:
                  fn_parts = rcv_data[3].split('\n')
                  time.sleep(5)
                  queue.put((fig, '/home/pi/Shared/' + fn_parts[0] + '.png'))
                  #time.sleep(5)
                  #plt.savefig('/home/pi/Shared/' + fn_parts[0] + '.png')
                  #time.sleep(3)
                  #plt.clf()

              if data_cnt == 6000000:
                  print(data_cnt,'counts,  finished plotting!!')
                  return

# スレッドに read_loop 関数を渡す
th_ser = threading.Thread(target=read_loop)
th_ser.daemon = True
th_ser.start()


def update(i, xt, yt, zt, zmin, zmax):

   xs = copy.copy(x)
   ys = copy.copy(y)
   zs = copy.copy(z)
   
   if len(xs) != len(zs) :
      del xs[len(zs) - len(xs)] 
      del ys[len(zs) - len(ys)] 
        
   #データ変化
   x_new, y_new = np.meshgrid(np.unique(xs), np.unique(ys))
   z_new0 = griddata((xs, ys), zs, (x_new, y_new), method='cubic')
   z_new = np.nan_to_num(z_new0, nan=0)

   if np.max(z_new) > zmax:
       zmax = np.max(z_new)
   if np.min(z_new) < zmin:
       zmin = np.min(z_new)
    
   if x == 0 and y == 0:
       z_max = 0
       z_min = 0
       
   z_max = max(z)
   z_min = min(z)
    
   fig.clf()
   ax = fig.add_subplot(spec[1:, 0])
   axh = fig.add_subplot(spec[1:, 1], projection='3d')
   axm = fig.add_subplot(spec[0, 0:])
   divider = make_axes_locatable(ax)
   cax = divider.append_axes("right", size="5%", pad=0.5)
   #axh.view_init(elev=90, azim=270)
   ax.imshow(im_Migne, extent=[16, 84, 40, 60], alpha=np.random.randint(6,10)/100)
   ps = ax.contourf(x_new, y_new, z_new , 128, cmap="jet", vmin=zmin, vmax=zmax, alpha=0.9)
   psh = axh.plot_surface(x_new, y_new, z_new , cmap="jet", vmin=zmin, vmax=zmax)
   ax.figure.colorbar(psh, cax=cax,
                      shrink=1, orientation='vertical')
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
   fig.tight_layout()

fig = plt.figure('Scan system    ver.0.7', figsize=[13,6], facecolor=(0.9, 0.9, 0.9))
spec = gridspec.GridSpec(ncols=2, nrows=2,
                         width_ratios=[5, 5],
                         height_ratios=[1, 12.5])
ax = fig.add_subplot(spec[1:, 0])
axh = fig.add_subplot(spec[1:, 1], projection='3d')
#axb = fig.add_subplot(spec[0:, 1])
axm = fig.add_subplot(spec[0, 0:])
divider = make_axes_locatable(ax)
cax = divider.append_axes("right", size="5%", pad=0.5)
#axh.view_init(elev=90, azim=270)
axh.set_facecolor(color=(0.9, 0.9, 0.9))
axh.set_xlabel('x')
axh.set_ylabel('y')
axh.set_zlabel('output')
ax.set_facecolor(color=(0.92, 0.92, 0.92))
ax.set_xlabel('x')
ax.set_ylabel('y')
ax.set_title('Foreign object detection')
#fig.tight_layout()

print("Waiting for comming data...")

#datas整理
while (len(x) < 200) :
   pass

xt = copy.copy(x)
yt = copy.copy(y)
zt = copy.copy(z)

if len(xt) != len(zt) :
   del xt[len(zt) - len(xt)] 
   del yt[len(zt) - len(yt)] 

print(len(xt))
print(len(yt))
print(len(zt))

x_new, y_new = np.meshgrid(np.unique(xt), np.unique(yt))
z_new0 = griddata((xt, yt), zt, (x_new, y_new), method='cubic')
z_new = np.nan_to_num(z_new0, nan=0) 

if np.max(z_new) > zmax:
    zmax = np.max(z_new)
if np.min(z_new) < zmin:
    zmin = np.min(z_new)
    
pim = ax.imshow(im_Migne, extent=[16, 84, 40, 60], alpha=0.5)
ps = ax.contourf(x_new, y_new, z_new , 64, cmap="jet", vmin=zmin, vmax=zmax, alpha=0.9)
psh = axh.plot_surface(x_new, y_new, z_new , cmap="jet", vmin=zmin, vmax=zmax)
psb = ax.figure.colorbar(psh, cax=cax,
                         shrink=1, orientation='vertical')
axm.imshow(im_Migne, alpha=0.7)
axm.axis("off")
#limit
axh.set_xlim([0, 100])
axh.set_zlim([zmin, zmax])
ax.set_xlim([0, 100])

#z = -5
#arr= im_Migne
#X1, Y1 = np.ogrid[0:arr.shape[0], 0:arr.shape[1]]
#axh.plot_surface(X1, Y1, np.atleast_2d(z), rstride=5, cstride=5, facecolors=arr)

ani = animation.FuncAnimation(fig, update, fargs=(xt, yt, zt, zmin, zmax), interval=250)
figmanager = plt.get_current_fig_manager()
figmanager.window.showMaximized()
plt.show()

queue.put(None)
saving_process.join()

