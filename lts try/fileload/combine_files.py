# -*- coding: utf-8 -*-
"""
Created on Thu Apr 23 18:44:21 2020

@author: a627534
"""

"""Combine multiple files
"""


import numpy as np
import os
import glob
from load_bin import load_bin
from vec2array import vec2array


def combine_files(filename, info):
    """Combine multiple files

    Args:
        filename(str): filename of recorded data
        info(dict): auxiliary information, output of 'load_json' function

    Returns:
        data(array): combined data (shape: sample(row) * channel(col))
    """

    num_files = info['number_of_files']
    data = np.empty([info['samples_per_channel'], 0])

    file_dir = os.path.dirname(filename)
    files = glob.glob(file_dir + '/' + info['filename']+ '.*.bin')

    if num_files != len(files):
        print("The number of files and devices don't match")
    else:
        for i in range(num_files):
            for j in range(num_files):
                if info['names_device'][i] == files[j].rsplit('.')[-3]:
                    new_file = files[j]
                    print(new_file)
                    data_new = load_bin(new_file)
                    data_new_arr = vec2array(data_new, info['samples_per_channel'], info['channels_per_device'][i])
                    data = np.append(data, data_new_arr, axis=1)

    """
    n = 0
    while n < num_files:
        new_file = filename.rsplit('.')[0]+'.'+info['names_device'][n]+'.'+filename.rsplit('.')[2]+'.bin'
        print(new_file)
        data_new = load_bin(new_file)
        data_new_arr = vec2array(data_new, info['samples_per_channel'], info['channels_per_device'][n])
        data = np.append(data, data_new_arr, axis=1)
        n = n + 1
    """
    return data


if __name__ == '__main__':

    import tkinter
    import tkinter.filedialog

    # file dialog
    tk = tkinter.Tk()
    tk.withdraw()

    filename_data = tkinter.filedialog.askopenfilename()

    tk.destroy()

    data_combined = combine_files(filename_data, info)
