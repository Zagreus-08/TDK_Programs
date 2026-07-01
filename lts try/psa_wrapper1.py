#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Module to automate frequency selection and CSV creation for the power spectrum analyzer script.
Uses the PowerSpectrumAnalyser class.


Note that the output_csv function is redefined in this module instead of using the one from PowerSpectrumAnalyser.


Copyright (c) 2024-, TDK Corporation. All rights res

erved.
"""

import os
import sys
import numpy as np
import datetime
import time
from PyQt5.QtWidgets import QApplication, QFileDialog
import tkinter
import tkinter.filedialog
                                                                                                                                                                                                                                                                                                    # from threading import Thread
import ctypes

from PowerSpectrumAnalyser1 import PowerSpectrumAnalyser

def output_csv(window, foln=""):
    """
    Modified version of the output_csv function from PowerSpectrumAnalyser.
    Adds the ability to specify the file via an argument instead of always opening a file selection dialog.
    Other functionality remains the same as the original function.
    
    This function was created with reference to the following file:
    powerspectrum_analyser_v2.py	
    Repository: Biomag/analyzer	
    Branch: sc_releaseeng_1_0_2	Other functionality remains the same as the original function.
    Commit: bdaf1c0bb4ad612fa2e9d3d5976a63838487eeff

    Parameters
    ----------
    window : PowerSpectrumAnalyser instance
        The instance of the PowerSpectrumAnalyser class.
    foln : str, optional
        The folder name where the CSV file will be saved. If not provided, a dialog will open to select the folder.
    """

    if not foln:
        foln = QFileDialog.getExistingDirectory()
    window.foldername = foln
    now = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    freq = window.freq.reshape(window.freq.shape[0], 1)
    header = ('sampling rate: ' + str(window.sr) + 'Hz'
        + ',segment: ' + str(window.segment/window.sr) + 's'
        + ',overlap: ' + str(window.overlap/window.sr) + 's'
        + ',window: ' + window.window
        + ',method: ' + window.method
        + ',scaling: ' + window.scale
        + ',start: ' + str(window.st/window.sr) + 's'
        + ',length: ' + str(window.tl/window.sr) + 's'
        +  ',repeat: ' + str(window.rpt))
    index = 'frequency[Hz]'

    if window.rpt == 1:
        data_spect = np.concatenate([freq, window.psds[:, :, 0]], axis=1)
        for i in window.tag:
            index += ',' + i
        csvfile = os.path.join(foln, window.filename.split('/')[-1].split('.')[0] + '_spectrum_' + now + '.csv')
        np.savetxt(csvfile, data_spect, delimiter=',', newline='\r', header=header+'\r'+index)

    else:
        for i in window.section:
            index += ',' + i
        for i in range(len(window.tag)):
            csvfile = foln + '/' + window.filename.split('/')[-1].split('.')[0] + '_spectrum_' + window.tag[i] + '_'+ now + '.csv'
            data_spect = np.concatenate([freq, window.psds[:, i, :]], axis=1)
            np.savetxt(csvfile, data_spect, delimiter=',', newline='\r', header=header+'\r'+index)

    print('saved')

def calc_psd_and_save(window, filename, segment, overlap):
    """
    Sets the segment and overlap parameters in the GUI.
    Calculates the PSD based on these parameters and saves the results to a CSV file.

    Parameters
    ----------
    window : PowerSpectrumAnalyser instance
        The instance of the PowerSpectrumAnalyser class.
    filename : str
        The name of the file to be processed.
    segment : float
        The segment length for PSD calculation.
    overlap : float
        The overlap length for PSD calculation.
    """
    
    window.le_seg.setText(str(segment))
    window.le_ovlp.setText(str(overlap))

    window.calculation_psd()
    output_csv(window, os.path.dirname(filename))

if __name__ == '__main__':
    if not QApplication.instance():
        app = QApplication(sys.argv)
    else:
        app = QApplication.instance()
        
    # File dialog
    tk = tkinter.Tk()
    tk.withdraw()
    fTyp = [("", "*.bin")]
    filename = tkinter.filedialog.askopenfilename(filetypes=fTyp)
    tk.destroy()
    
    # Create the window
    window = PowerSpectrumAnalyser(filename)

    # Calculate PSD with specific parameters and save to CSV.
    # Ensure at least 1 second between each execution as the CSV file names are time-based.
    calc_psd_and_save(window, filename, segment=20.0, overlap=18.0)
    time.sleep(1)
    calc_psd_and_save(window, filename, segment=2.0, overlap=1.8)
    time.sleep(1)
    #calc_psd_and_save(window, filename, segment=0.02, overlap=0.018)
    #time.sleep(1)
    #calc_psd_and_save(window, filename, segment=0.002, overlap=0.0018)
    
    ctypes.windll.user32.MessageBoxW(0, "CSV creation has completed!", "BMS", 0)

    
    sys.exit(app.exec_())
