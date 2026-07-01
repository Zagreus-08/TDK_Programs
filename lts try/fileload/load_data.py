# -*- coding: utf-8 -*-
"""
Created on Mon Feb 17 13:18:19 2020

@author: a627534
"""

"""Entrypoint for loading data

Todo:
    Prepare recorded data file/files(.bin), auxiliary information file(.json)
    and calibration file(.rst)
"""


from load_bin import load_bin
from load_json import load_json
from combine_files import combine_files
from load_sensor import load_sensor_csv, load_sensor_rst
from vec2array import vec2array


def load_data(filename):
    """Load recorded data and auxiliary information data, and combine files

    Args:
        filename(str): filename of recorded data
                       When combining multiple files, which one can be specified

    Returns:
        data_arr(array): recorded data shaped into 'sample(row) * channel(col)'
        info(dict): auxiliary information
        sensor(array): sensor position, argument, sensitivity
    """

    # load auxiliary information data
    info = load_json(filename)

    # detemine whether to load or combine from the number of files
    if info['number_of_files'] > 1:
        data_arr = combine_files(filename, info)
        print(str(info['number_of_files']) + ' files are combined.')
    else:
        data_vec = load_bin(filename)
        data_arr = vec2array(data_vec, info['samples_per_channel'], info['number_of_channels'])

    # load calibration data
    sensor = load_sensor_rst(filename)

    return data_arr, info, sensor


if __name__ == '__main__':

    import tkinter
    import tkinter.filedialog

    # file dialog
    tk = tkinter.Tk()
    tk.withdraw()

    filename_data = tkinter.filedialog.askopenfilename()

    tk.destroy()

    data, info, sensor = load_data(filename_data)
