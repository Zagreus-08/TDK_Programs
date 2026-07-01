





    



 
# -*- coding: utf-8 -*-
"""
Created on Mon May 18 14:37:23 2020

@author: a627534
"""

import numpy as np
import scipy.signal as sig
from PyQt5.QtWidgets import (QPushButton, QGridLayout, QVBoxLayout, QHBoxLayout,
                             QFormLayout, QLabel, QLineEdit, QComboBox,
                             QDialog, QMessageBox, QMainWindow, QWidget,
                             QSizePolicy, QAction, QMenu, QMenuBar, QApplication,
                             QFileDialog, QSlider, QCheckBox
                             )
from PyQt5.QtCore import (Qt, pyqtSignal, pyqtSlot, QObject, QRect, QTimer, QMetaObject)
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
import matplotlib.ticker as ptick

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
import tkinter
import tkinter.filedialog
from time import sleep
import datetime



import fileload
import freqfilt
import subplot_click_to_popup as popup


class PowerSpectrumAnalyser(QMainWindow):

    def __init__(self, filename, parent=None):

        super(PowerSpectrumAnalyser, self).__init__(parent)
        self.filename = filename
        self.setWindowTitle('PowerSpectrumAnalyser')
        self.data, self.info, sensor = fileload.load_data.load_data(filename)
        #self.data = np.loadtxt('chirp')
        self.sr = self.info['sampling_rate']
        self.num_ch = self.info['number_of_channels']
        self.time = np.arange(0, self.info['measurement_time'], 1/self.sr)
        filtspec = {
            "spec_format": "filter_spec_01",
            "filters_list": [
                    {"definition_type": "design",
                     "params": {
                             "response_type": "bandpass",
                             "fir_iir": "iir",
                             "design": "butterworth",
                             "params": {
                                     "cutoff": [0.5, 100.0],
                                     "order": 3}}},
                    {"definition_type": "design",
                     "params": {
                             "response_type": "notch",
                             "fir_iir": "iir",
                             "design": "second_order_iir_notch",
                             "params": {
                                     "f": 60.0,
                                     "Q": 15}}},
                    {"definition_type": "design",
                     "params": {
                             "response_type": "notch",
                             "fir_iir": "iir",
                             "design": "second_order_iir_notch",
                             "params": {
                                     "f": 120.0,
                                     "Q": 15}}},
                    {"definition_type": "design",
                     "params": {
                             "response_type": "notch",
                             "fir_iir": "iir",
                             "design": "second_order_iir_notch",
                             "params": {
                                     "f": 180.0,
                                     "Q": 15}}},
                    {"definition_type": "design",
                     "params": {
                             "response_type": "notch",
                             "fir_iir": "iir",
                             "design": "second_order_iir_notch",
                             "params": {
                                     "f": 240.0,
                                     "Q": 15}}},
                    ],
            "common_params": {
                    "bidirectional": True,
                    # padding, etc.
                    }
            }
        #self.data, mcg_ffilt_params_list = freqfilt.filter_processor.apply_freq_filters(
        #   filtspec, self.data, data_fs=self.sr, axis=0)

        self.left = 30
        self.top = 30
        self.width = 1200
        self.height = 700
        self.disp_width = 5.0
        self.step_width = 1.0

        self.segment = 20.0
        self.overlap = 18.0
        self.st = 0
        self.rp = 1

        self.initui()

    def initui(self):

        self.setGeometry(self.left, self.top, self.width, self.height)

        self.w = QWidget(self)
        self.setCentralWidget(self.w)

        self.ch_full = list(range(self.num_ch))
        self.ch_disp = list(range(self.num_ch))
        ch_disp_str = ''
        for i in range(len(self.ch_disp)-1):
            ch_disp_str = ch_disp_str + str(self.ch_disp[i]+1) + ' '
        ch_disp_str = ch_disp_str + str(self.ch_disp[-1]+1)

        self.sld_time = QSlider(Qt.Horizontal, self)
        self.sld_time.setMinimum(0)
        self.sld_time.setMaximum(len(self.data))
        self.sld_time.setSingleStep(int(self.sr*self.step_width))
        self.sld_time.setPageStep(int(self.sr*self.step_width*5))
        self.sld_time.valueChanged[int].connect(self.change_view)
        self.adj_offset = 2**0
        self.le_ch = QLineEdit(str(ch_disp_str))
        self.le_dw = QLineEdit(str(self.disp_width))
        self.le_dw.textChanged.connect(self.change_disp_width)

        self.lb_mtd = QLabel('method')
        self.cb_mtd = QComboBox()  # calculation method
        self.cb_mtd.addItem('Welch')
        self.cb_mtd.addItem('Periodogram')
        self.lb_win = QLabel('window')
        self.cb_win = QComboBox()  # window
        self.cb_win.addItem('hanning')
        self.cb_win.addItem('hamming')
        self.lb_scl = QLabel('scale')
        self.cb_scl = QComboBox()  # scale
        self.cb_scl.addItem('density [V/Hz^(1/2)]')
        self.cb_scl.addItem('spectrum [V]')

        self.lb_seg = QLabel('segment[s]')
        self.le_seg = QLineEdit(f"{self.segment}")
        self.lb_ovlp = QLabel('overlap[s]')
        self.le_ovlp = QLineEdit(f"{self.overlap}")

        self.lb_st = QLabel('start')
        self.le_st = QLineEdit(f"{self.st}")
        self.lb_tl = QLabel('length[s]')
        self.le_tl = QLineEdit(str(self.data.shape[0]/self.sr))
        self.lb_rp = QLabel('repeat')
        self.le_rp = QLineEdit(f"{self.rp}")

        self.pb_calc = QPushButton('calculation')
        self.pb_calc.clicked.connect(self.calculation_psd)
        self.pb_disp = QPushButton('display')
        self.pb_disp.clicked.connect(self.display_psd)
        self.pb_disp.setEnabled(False)
        self.pb_csv = QPushButton('csv')
        self.pb_csv.clicked.connect(self.output_csv)
        self.pb_csv.setEnabled(False)

        self.linename = []
        self.text_ch = []
        for i in range(self.num_ch):
            self.linename.append('line'+str(i))
            self.text_ch.append('text'+str(i))
        self.lines = {}
        self.texts = {}
        self.now = 0

        offset_ori = (np.max(self.data[self.now:int(self.now+self.disp_width*self.sr), self.ch_disp], 0)
                           - np.min(self.data[self.now:int(self.now+self.disp_width*self.sr), self.ch_disp], 0))/2
        offset = np.zeros(offset_ori.shape[0])
        for i in range(offset_ori.shape[0]-1):
            offset[i+1] = offset_ori[i] + offset_ori[i+1]
        offset[0] = 0
        self.offset = np.cumsum(offset)/self.adj_offset
        """
        self.offset = abs(np.max(self.data[self.now:int(self.now+self.disp_width*self.sr), self.ch_disp[0]])
                        - np.min(self.data[self.now:int(self.now+self.disp_width*self.sr), self.ch_disp[0]]))/self.adj_offset
        """
        self.fig = Figure()
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setGeometry(self.left, self.top, self.width, self.height)
        self.ax = self.fig.add_subplot(1, 1, 1)

        for i in range(len(self.ch_disp)):
            self.lines[self.linename[self.ch_disp[i]]], = self.ax.plot(
                    self.time[self.now:int(self.now+self.disp_width*self.sr)],
                    self.data[self.now:int(self.now+self.disp_width*self.sr), self.ch_disp[i]]-self.offset[i])
            self.texts[self.text_ch[self.ch_disp[i]]] = self.ax.text(self.time[self.now], self.data[self.now,i]-self.offset[i], 'ch.'+str(self.ch_disp[i]+1))
        self.ax.grid(True)
        self.ax.set_xlim([self.time[self.now],
                          self.time[self.now+int(self.disp_width*self.sr)]])
        self.ax.set_ylim([np.min(self.data[self.now:self.now+int(self.disp_width*self.sr), self.ch_disp[-1]])-self.offset[i]-np.mean(offset),
                          np.max(self.data[self.now:self.now+int(self.disp_width*self.sr), self.ch_disp[0]])+np.mean(offset)])
        self.canvas.draw()

        self.lay1 = QFormLayout()
        self.lay1.addRow('channel', self.le_ch)
        self.lay1.addRow('display width[s]', self.le_dw)

        self.lay2 = QGridLayout()
        self.lay2.setSpacing(10)
        self.lay2.addWidget(self.lb_mtd, 0, 0)
        self.lay2.addWidget(self.cb_mtd, 0, 1, 1, 2)
        self.lay2.addWidget(self.lb_win, 0, 4)
        self.lay2.addWidget(self.cb_win, 0, 5, 1, 2)
        self.lay2.addWidget(self.lb_scl, 0, 8)
        self.lay2.addWidget(self.cb_scl, 0, 9, 1, 2)
        self.lay2.addWidget(self.lb_seg, 1, 0)
        self.lay2.addWidget(self.le_seg, 1, 1, 1, 2)
        self.lay2.addWidget(self.lb_ovlp, 1, 4)
        self.lay2.addWidget(self.le_ovlp, 1, 5, 1, 2)
        self.lay2.addWidget(self.lb_st, 2, 0)
        self.lay2.addWidget(self.le_st, 2, 1, 1, 2)
        self.lay2.addWidget(self.lb_tl, 2, 4)
        self.lay2.addWidget(self.le_tl, 2, 5, 1, 2)
        self.lay2.addWidget(self.lb_rp, 2, 8)
        self.lay2.addWidget(self.le_rp, 2, 9, 1, 2)
        self.lay2.addWidget(self.pb_calc, 3, 3, 1, 2)
        self.lay2.addWidget(self.pb_disp, 3, 5, 1, 2)
        self.lay2.addWidget(self.pb_csv, 3, 7, 1, 2)

        self.lay0 = QVBoxLayout(self.w)
        self.lay0.addWidget(self.canvas, 8)
        self.lay0.addWidget(self.sld_time, 1)
        self.lay0.addLayout(self.lay1, 1)
        self.lay0.addLayout(self.lay2, 1)

        self.show()

    @pyqtSlot()
    def change_view(self):

        self.now = self.sld_time.value()
        self.plot_update(self.now)

    @pyqtSlot()
    def change_disp_width(self):

        self.disp_width = float(self.le_dw.text())

    @pyqtSlot()
    def calculation_psd(self):

        self.sld_time.setEnabled(False)
        self.le_ch.setEnabled(False)
        self.le_dw.setEnabled(False)
        self.cb_mtd.setEnabled(False)
        self.cb_win.setEnabled(False)
        self.cb_scl.setEnabled(False)
        self.le_seg.setEnabled(False)
        self.le_ovlp.setEnabled(False)
        self.le_st.setEnabled(False)
        self.le_tl.setEnabled(False)
        self.le_rp.setEnabled(False)
        self.pb_disp.setEnabled(False)
        self.pb_csv.setEnabled(False)
        QApplication.processEvents()  # for GUI update
        # QMetaObject.invokeMethod(self, "calculation_psd_body", Qt.QueuedConnection)

    # @pyqtSlot()
    # def calculation_psd_body(self):

        print('start calculation')
        self.segment = int(self.sr * float(self.le_seg.text()))
        self.overlap = int(float(self.le_ovlp.text()) * self.sr)
        self.window = self.cb_win.currentText()
        self.method = self.cb_mtd.currentText()
        self.scale = self.cb_scl.currentText().split(' ')[0]
        ch_disp_str = self.le_ch.text()
        self.tag = []
        for i in ch_disp_str.split(' '):
            self.tag.append('ch.'+i)
        self.ch_disp = [int(i)-1 for i in ch_disp_str.split(' ')]
        self.st = int(self.sr * float(self.le_st.text()))
        self.tl = int(self.sr * float(self.le_tl.text()))
        self.rpt = int(self.le_rp.text())
        if self.st+self.tl*self.rpt > self.data.shape[0]:
            self.rpt = int(np.floor((self.data.shape[0]-self.st)/self.tl))
            print('The number of repetitions changed to ' + str(self.rpt))

        n = 1
        self.psds = np.zeros((int(np.floor(self.segment/2)+1), len(self.ch_disp), self.rpt))
        self.section = []
        while self.rpt >= n:
            if self.method == 'Welch':
                self.freq, self.psd = sig.welch(self.data[self.st+self.tl*(n-1):self.st+self.tl*n, self.ch_disp], self.sr, self.window, nperseg=self.segment, noverlap=self.overlap, scaling=self.scale, axis=0)
            else:
                step_width = self.segment - self.overlap
                n_fft = int(self.data.shape[0] / step_width)
                self.psd = np.zeros([int(self.segment/2)+1, n_fft])
                for i in range(n_fft):
                    self.freq, psd = sig.periodogram(self.data[i*step_width:], self.sr, self.window, nfft=self.segment, scaling=self.scale, axis=0)
                    self.psd[: ,i] = psd[:, 0]
                self.psd = np.sum(self.psd, axis=1)
            self.psds[: ,:, n-1] = np.sqrt(self.psd)
            self.section.append('section'+str(n))
            n += 1

        print('finished calculation')

        self.sld_time.setEnabled(True)
        self.le_ch.setEnabled(True)
        self.le_dw.setEnabled(True)
        self.cb_mtd.setEnabled(True)
        self.cb_win.setEnabled(True)
        self.cb_scl.setEnabled(True)
        self.le_seg.setEnabled(True)
        self.le_ovlp.setEnabled(True)
        self.le_st.setEnabled(True)
        self.le_tl.setEnabled(True)
        self.le_rp.setEnabled(True)
        self.pb_disp.setEnabled(True)
        self.pb_csv.setEnabled(True)

    @pyqtSlot()
    def display_psd(self):

        if self.rpt == 1:
            fig = plt.figure()
            fig.canvas.set_window_title('stack')
            ax = fig.add_subplot(111)
            ax.plot(self.freq, self.psds[:, :, 0])
            ax.set_xscale('log')
            ax.set_yscale('log')
            ax.grid(which='major',color='black',linestyle='-')
            plot_psd = popup.subplot_click_to_popup(self.freq, self.psds[:, :, 0], self.tag, 'grid')
        else:
            for i in range(len(self.tag)):
                plot_psd = popup.subplot_click_to_popup(self.freq, self.psds[:, i, :], self.section, self.tag[i])

    @pyqtSlot()
    def output_csv(self):

        foln = QFileDialog.getExistingDirectory()
        self.foldername = foln
        now = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        freq = self.freq.reshape(self.freq.shape[0], 1)
        header = ('sampling rate: ' + str(self.sr) + 'Hz'
           + ',segment: ' + str(self.segment/self.sr) + 's'
           + ',overlap: ' + str(self.overlap/self.sr) + 's'
           + ',window: ' + self.window
           + ',method: ' + self.method
           + ',scaling: ' + self.scale
           + ',start: ' + str(self.st/self.sr) + 's'
           + ',length: ' + str(self.tl/self.sr) + 's'
           +  ',repeat: ' + str(self.rpt))
        index = 'frequency[Hz]'

        if self.rpt == 1:
            data_spect = np.concatenate([freq, self.psds[:, :, 0]], axis=1)
            for i in self.tag:
                index += ',' + i
            csvfile = foln + '/' + self.filename.split('/')[-1].split('.')[0] + '_spectrum_' + now + '.csv'
            np.savetxt(csvfile, data_spect, delimiter=',', newline='\r', header=header+'\r'+index)

        else:
            for i in self.section:
                index += ',' + i
            for i in range(len(self.tag)):
                csvfile = foln + '/' + self.filename.split('/')[-1].split('.')[0] + '_spectrum_' + self.tag[i] + '_'+ now + '.csv'
                data_spect = np.concatenate([freq, self.psds[:, i, :]], axis=1)
                np.savetxt(csvfile, data_spect, delimiter=',', newline='\r', header=header+'\r'+index)

        print('saved')


    def closeEvent(self, event):
        event.accept()

    def plot_update(self, now):

        for i in range(self.num_ch):
            self.lines[self.linename[i]].set_visible(False)
            self.texts[self.text_ch[i]].set_visible(False)

        ch_disp_str = self.le_ch.text()
        self.ch_disp = [int(i)-1 for i in ch_disp_str.split(' ')]

        if now < 0:
            now = 0
        elif now+int(self.disp_width*self.sr) >= len(self.data):
            now =  len(self.data) - int(self.disp_width*self.sr) - 1

        offset_ori = (np.max(self.data[now:int(now+self.disp_width*self.sr), self.ch_disp], 0)
                           - np.min(self.data[now:int(now+self.disp_width*self.sr), self.ch_disp], 0))/2
        offset = np.zeros(offset_ori.shape[0])
        for i in range(offset_ori.shape[0]-1):
            offset[i+1] = offset_ori[i] + offset_ori[i+1]
        offset[0] = 0
        self.offset = np.cumsum(offset)/self.adj_offset

        for i in range(len(self.ch_disp)):
            self.lines[self.linename[self.ch_disp[i]]].set_visible(True)
            self.lines[self.linename[self.ch_disp[i]]].set_data(
                    self.time[now:now+int(self.disp_width*self.sr)],
                    self.data[now:now+int(self.disp_width*self.sr), self.ch_disp[i]]-self.offset[i])
            self.texts[self.text_ch[self.ch_disp[i]]].set_visible(True)
            self.texts[self.text_ch[self.ch_disp[i]]].set_position([self.time[now], self.data[now, self.ch_disp[i]]-self.offset[i]])
        self.ax.set_xlim([self.time[now], self.time[now+int(self.disp_width*self.sr)]])
        self.ax.set_ylim([np.min(self.data[self.now:self.now+int(self.disp_width*self.sr), self.ch_disp[-1]])-self.offset[i]-offset_ori[0]/3,
                          np.max(self.data[self.now:self.now+int(self.disp_width*self.sr), self.ch_disp[0]])+offset_ori[0]/3])

        self.canvas.draw()

        self.sld_time.setValue(self.now)
        self.now = now


if __name__ == '__main__':

    import sys

    if not QApplication.instance():
        app = QApplication(sys.argv)
    else:
        app = QApplication.instance()

    # file dialog
    tk = tkinter.Tk()
    tk.withdraw()
    fTyp = [("", "*.bin")]
    filename = tkinter.filedialog.askopenfilename(filetypes=fTyp)
    tk.destroy()

    
    window = PowerSpectrumAnalyser(filename)
    sys.exit(app.exec_())
