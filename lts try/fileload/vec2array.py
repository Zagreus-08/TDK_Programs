# -*- coding: utf-8 -*-
"""
Created on Fri Feb 21 15:50:55 2020

@author: a627534
"""

"""Transform vector data into array data
"""


import numpy as np


def vec2array(data, samples_per_channel, number_of_channels):
    """Transform vector data into array data

    Args:
        data(vector): target data, length=samples*ch(+n)
        samples_per_channel: number of samples for each chanel
        number_of_channels: number of channels
    Returns:
        data_array(array): target data shaped into 'sample(row) * channel(col)'
    """

    data_vec = data[0:samples_per_channel*number_of_channels]
    data_array = np.reshape(data_vec, [samples_per_channel, number_of_channels])

    return data_array


if __name__ == '__main__':

    import tkinter
    import tkinter.filedialog
    from load_bin import load_bin
    from load_json import load_json

    # file dialog
    tk = tkinter.Tk()
    tk.withdraw()

    filename_data = tkinter.filedialog.askopenfilename()

    tk.destroy()

    data0 = load_bin(filename_data)
    info = load_json(filename_data)

    data = vec2array(data0, info)
