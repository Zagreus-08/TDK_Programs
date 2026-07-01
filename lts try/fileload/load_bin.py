# -*- coding: utf-8 -*-
"""
Created on Fri Feb 21 11:12:38 2020

@author: a627534
"""

"""Load recorded file(.bin)
"""


import numpy as np


def load_bin(filename):
    """Load recorded data

    Args:
        filename(str): filename of recorded data

    Returns:
        data0(vector): recorded data whose length is sample*channel
    """

    with open(filename, "rb") as f:
        data0 = np.fromfile(f)

    return data0


if __name__ == '__main__':

    import tkinter
    import tkinter.filedialog

    # file dialog
    tk = tkinter.Tk()
    tk.withdraw()

    filename_data = tkinter.filedialog.askopenfilename()

    tk.destroy()

    data = load_bin(filename_data)
