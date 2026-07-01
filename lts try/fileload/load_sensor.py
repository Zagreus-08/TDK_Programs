# -*- coding: utf-8 -*-
"""
Created on Tue Feb 25 11:06:37 2020

@author: a627534
"""

"""Load calibration file(.csv/.rst)
"""


import os
import glob
import csv
import numpy as np


def load_sensor_csv(filename):

    filename_sensor = os.path.dirname(filename) + '/channels_96.csv'

    with open(filename_sensor, 'r') as f:
        reader = csv.reader(f)
        sensor = np.array(list(reader))

    sensor_position = sensor[:, 3:6]
    sensitivity = sensor[:, -1]
    sensor_type = sensor[:, 6]
    ch_signal1 = np.where(sensor_type == '0')
    ch_signal2 = np.where(sensor_type == '1')
    ch_reference = np.where(sensor_type == '3')
    ch_trigger = np.where(sensor_type == '5')

    return sensor_position, sensitivity, ch_signal1, ch_signal2, ch_reference, ch_trigger


def load_sensor_rst(filename):
    """Load calibration file(KIT format)

    Args:
        filename(str): filename of recorded data

    Returns:
        sensor_position(array): orthogonal coordinate system xyz, ch*3
        sensitivity(vector): Tesla-Voltage conversion factor(T/V), ch*1
        argument(array): sensitivity vectors argument in polar coordinate system
    """

    file_dir = os.path.dirname(filename)
    file_rst = glob.glob(file_dir + '/*.rst')
    if len(file_rst) != 1:
        print('Multiple calibration files exist / No calibration file exists')
        return
    else:
        filename_rst = file_rst[0]
        print('calibration file: ' + filename_rst )
        with open(filename_rst, 'r', encoding="utf-8") as f:
            reader = csv.reader(f, delimiter='\t')
            rst = np.array(list(reader))

        num_ch = int(rst[0][0])
        sensor_position = np.zeros([num_ch, 3])
        argument = np.zeros([num_ch, 2])
        sensitivity = np.zeros([num_ch, 1])
        for i in range(num_ch):
            sensor_position[i, :] = [float(n) for n in rst[i+1][2:5]]
            argument[i, :] = [float(n) for n in rst[i+1][5:7]]
            sensitivity[i, :] = float(rst[i+1][8])

        return sensor_position, sensitivity, argument


if __name__ == '__main__':

    import tkinter
    import tkinter.filedialog

    # file dialog
    tk = tkinter.Tk()
    tk.withdraw()

    filename_data = tkinter.filedialog.askopenfilename()

    tk.destroy()

    #sensor = load_sensor_csv(filename_data)
    sensor = load_sensor_rst(filename_data)
