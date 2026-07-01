# -*- coding: utf-8 -*-
"""
Created on Tue Sep  1 11:48:20 2020

@author: a627534
"""

import numpy as np
import matplotlib.pyplot as plt

class subplot_click_to_popup():

    def __init__(self, x, y, tag, title, parent=None):

        num_ch = y.shape[1]
        row = np.floor(np.sqrt(num_ch))
        col = np.ceil(num_ch/row)

        fig = plt.figure(figsize=(10,8))
        fig.canvas.set_window_title(title)
        for i in range(num_ch):
            ax = fig.add_subplot(col, row, i+1)
            ax.plot(x, y[: , i])
            ax.set_title(tag[i], fontsize=8)
            plt.connect('button_press_event', popup_single_ch)
            plt.xticks(fontsize=6)
            plt.yticks(fontsize=6)
            #ax.set_xlim([0, 250])
            ax.set_xscale('log')
            ax.set_yscale('log')
            if i != 0:
                ax.set_xticks([])
                ax.set_yticks([])
        plt.tight_layout()

def popup_single_ch(event):

    if event.button == 1 and event.inaxes is not None:

        ch = event.inaxes.get_title()
        line = event.inaxes.get_lines()[0]
        fig = plt.figure()
        ax = fig.add_subplot(111)
        ax.plot(line._x, line._y)
        ax.set_title(ch)
        ax.set_xscale('log')
        ax.set_yscale('log')
        ax.grid(which='major',color='black',linestyle='-')
