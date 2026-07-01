#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
filter design utility
"""

import sys
from copy import deepcopy

import os
import numpy as np
import scipy.signal as sig
from enum import Enum, auto
import pprint
import ctypes

try:
    from PySide2.QtWidgets import QApplication
    QT_TYPE = "PySide2"
except Exception as e:
    QT_TYPE = "PyQt5"
    # print(e)
    
if QT_TYPE == "PySide2":
    from PySide2.QtCore import (Qt, QObject, Slot, Signal, Property, QSize, QUrl,
                                QCoreApplication,)
    from PySide2.QtWidgets import (
            QApplication,
            QMainWindow, QWidget, QFrame,
            QAction, QPushButton, QStyle,
            QHBoxLayout, QVBoxLayout, QFormLayout, QGridLayout,
            QSplitter, QScrollArea,
            QComboBox, QLabel, QLineEdit,
            QListView, QAbstractItemView,
            QDialogButtonBox, QDialog,
            QGroupBox, QRadioButton,
            QStackedWidget,
            QTextBrowser,
            )
    from PySide2.QtQml import (QQmlEngine, QQmlComponent, qmlRegisterType)
    from PySide2.QtQuick import (QQuickView, QQuickWindow, QQuickItem,)
    qtSlot = Slot
    qtSignal = Signal
    qtProperty = Property
elif QT_TYPE == "PyQt5":
    from PyQt5.QtCore import (Qt, QObject, pyqtSlot, pyqtSignal, pyqtProperty,
                              QSize, QUrl,
                              QCoreApplication,)
    from PyQt5.QtWidgets import (
            QApplication,
            QMainWindow, QWidget, QFrame,
            QAction, QPushButton, QStyle,
            QHBoxLayout, QVBoxLayout, QFormLayout, QGridLayout,
            QSplitter, QScrollArea,
            QComboBox, QLabel, QLineEdit,
            QListView, QAbstractItemView,
            QDialogButtonBox, QDialog,
            QGroupBox, QRadioButton,
            QStackedWidget,
            QTextBrowser,
            )
    from PyQt5.QtQml import (QQmlEngine, QQmlComponent, qmlRegisterType)
    from PyQt5.QtQuick import (QQuickView, QQuickWindow, QQuickItem,)
    qtSlot = pyqtSlot
    qtSignal = pyqtSignal
    qtProperty = pyqtProperty
    
# import matplotlib
# import matplotlib as mpl
import matplotlib.pyplot as plt
# import mpl_toolkits.mplot3d
# import matplotlib.gridspec as gridspec
# from matplotlib import cm
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure as MplFigure
# from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
# import mpl_toolkits.mplot3d.axes3d
# from mpl_toolkits.axes_grid1 import make_axes_locatable
# from PIL import Image

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import filter_processor as fp

class LastUpdateFrom(Enum):
    design = auto()
    spec_design = auto()
    spec_coef = auto()
    

class FreqFilterDesignGUI(QDialog):
    
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.last_update_from = LastUpdateFrom.design
        self.init_gui()
        self.on_spec_design_changed(self.design_widget.get_filtspec())
    
    def init_gui(self) -> None:
        self.setWindowTitle('Frequency Filter Designer')
        self.setWindowFlags(Qt.Window)

        # functional widgets
        self.data_widget = DataWidget()
        self.design_widget = DesignWidget()
        self.spec_widget = SpecificationsWidget()
        self.chart_widget = CharacteristicsWidget()
        self.func_buttons = FuncButtons()

        # connections
        self.func_buttons.accepted.connect(self.my_accept)
        self.func_buttons.rejected.connect(self.my_reject)

        self.data_widget.sig_info_changed.connect(self.on_data_info_changed)
        self.design_widget.sig_filt_changed.connect(self.on_design_changed)
        #self.spec_widget.sig_spec_changed.connect(self.on_spec_changed)
        #self.spec_widget.sig_coef_changed.connect(self.on_coef_changed)
        self.spec_widget.sig_coef_changed.connect(self.on_coef_changed)

        # layouts
        self.lay = QVBoxLayout()
        self.setLayout(self.lay)

        self.lay4panes = QGridLayout()
        self.lay.addLayout(self.lay4panes)

        self.lay4panes.addWidget(self.data_widget, 0, 0, 1, 1)
        self.lay4panes.addWidget(self.design_widget, 1, 0, 1, 1)
        self.lay4panes.addWidget(self.spec_widget, 2, 0, 1, 1)
        self.lay4panes.addWidget(self.chart_widget, 0, 1, 3, 1)

        self.lay.addWidget(self.func_buttons)

        # appearances
        self.setMinimumSize(QSize(320, 240))


    def start(self):
        if QT_TYPE == "PySide2":
            r = self.exec_()
        elif QT_TYPE == "PyQt5":
            r = self.exec()
        else:
            raise(ValueError, "unknown QT_TYPE: %s" % QT_TYPE)
        return r

    def update_filter_spec(self):
        if self.last_update_from == LastUpdateFrom.design:
            spec = self.design_widget.get_filtspec()
        elif self.last_update_from == LastUpdateFrom.spec_design:
            spec = self.spec_widget.get_spec_from_design()
        elif self.last_update_from == LastUpdateFrom.spec_coef:
            spec = self.spec_widget.get_spec_from_coef()

        self.filter_spec["filters_list"] = [spec]
        ################

    @qtSlot(dict)
    def on_data_info_changed(self, data_spec: dict={}) -> None:
        self.spec_widget.on_data_changed(self.filter_spec, self.get_data_spec())
        return

    @qtSlot(dict)
    def on_design_changed(self, filt_spec: dict={}) -> None:
        self.last_update_from = LastUpdateFrom.design
        #self.filter_spec["filters_list"] = [filt_spec]
        self.filter_spec = filt_spec
        self.spec_widget.on_filter_changed(self.filter_spec, self.get_data_spec())

    @qtSlot(dict)
    def on_spec_design_changed(self, filt_spec: dict={}) -> None:
        self.last_update_from = LastUpdateFrom.spec_design
        #self.filter_spec["filters_list"] = [filt_spec]
        self.filter_spec = filt_spec
        self.spec_widget.on_spec_design_changed(filt_spec, self.get_data_spec())

    @qtSlot(dict)
    def on_spec_coef_changed(self, filt_spec: dict={}) -> None:
        self.last_update_from = LastUpdateFrom.spec_coef
        #self.filter_spec["filters_list"] = [filt_spec]
        self.filter_spec = filt_spec
        ###################
        ###################
        
    @qtSlot(dict)
    def on_coef_changed(self, coefs):
        #print(coefs)
        self.chart_widget.update_plot(coefs)

    def get_filter_spec(self) -> dict:
        return deepcopy(self.filter_spec)

    def get_data_spec(self) -> dict:
        return self.data_widget.get_data_spec()

    @qtSlot()
    def my_accept(self):
        if fp.check_filtspec_validity(self.filter_spec):
            pass
        else:
            pass

        print("accepted")
        # self.close()
        self.accept()
        
    @qtSlot()
    def my_reject(self):
        print("rejected")
        #self.close()
        #return
        self.reject()


class FuncButtons(QWidget):
    
    accepted = qtSignal()
    rejected = qtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # self.filtspec
        self.init_gui(parent)
    
    def init_gui(self, parent):
        self.btn_export = QPushButton("Export to file")
        self.btn_import = QPushButton("Import from file") 
        self.btn_okng = QDialogButtonBox(
                QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
                Qt.Horizontal, parent)

        self.setLayout(QHBoxLayout())
        self.layout().addWidget(self.btn_export)
        self.layout().addWidget(self.btn_import)
        self.layout().addWidget(self.btn_okng)
        
        # signal-to-signal connection
        self.btn_okng.accepted.connect(self.accepted)
        self.btn_okng.rejected.connect(self.rejected)


class DataWidget(QFrame):
    
    sig_info_changed = qtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_gui()
        
    def init_gui(self):
        self.ed_fs = QLineEdit("1.0")
        self.ed_fs.textChanged.connect(self.on_fs_changed)
        
        self.lay = QFormLayout()
        self.setLayout(self.lay)
        self.lay.addRow(QLabel("Sampling rate [Hz]"), self.ed_fs)
        
        self.ed_fs.textChanged.connect(self.on_info_changed)
    
    def get_data_spec(self) -> dict:
        data_spec = {}
        fs = self.update_fs()
        if fs>0.0:
            data_spec["sampling_rate"] = fs
        return data_spec

    @qtSlot()
    def on_info_changed(self):
        data_spec = {}
        fs = self.update_fs()
        if fs > 0.0:
            data_spec["sampling_rate"] = fs
        self.sig_info_changed.emit(data_spec)
        return

    @qtSlot(str)
    def on_fs_changed(self, s):
        fs = self.update_fs()
        return fs

    def update_fs(self):
        try:
            s = self.ed_fs.text()
            fs = float(s)
        except Exception as e:
            print(e)
            print(s)
            return -1.0
        return fs



class DesignWidget(QFrame):
    
    sig_filt_changed = qtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.filtspec = {}
        self.filtspec["spec_format"] = "single_filter_spec_01"
        self.filtspec["definition_type"] = "design"
        self.filtspec["params"] = {}
        self.init_gui()
        
    def init_gui(self):
        # functional widgets
        self.main_selection_pane = MainSelectionPane()
        self.parameter_pane = ParameterPane()
        
        # connections
        self.main_selection_pane.sig_mainsel_changed.connect(
                self.parameter_pane.on_mainsel_changed)
        self.main_selection_pane.sig_mainsel_changed.connect(
                self.on_mainsel_changed)
        self.parameter_pane.sig_param_changed.connect(
                self.on_param_changed)

        # layouts
        self.lb = QLabel("Design")

        self.setLayout(QVBoxLayout())
        self.layout().addWidget(self.lb)
        
        #self.layout().addWidget(self.drawing_pane)
        self.layout().addWidget(self.main_selection_pane)
        self.layout().addWidget(self.parameter_pane)
        return

    @qtSlot(dict)
    def on_mainsel_changed(self, sel={}):
        # print("Design Widget received main selection change")
        params = self.parameter_pane.get_params()
        self.filtspec["params"]["response_type"] = sel["response_type"]
        self.filtspec["params"]["fir_iir"] = sel["fir_iir"]
        self.filtspec["params"]["design"] = sel["design"]
        self.filtspec["params"]["params"] = params
        print(self.filtspec)
        self.sig_filt_changed.emit(self.filtspec)
    
    @qtSlot(dict)
    def on_param_changed(self, param={}):
        print("Design Widget received parameter change")
        params = self.parameter_pane.get_params()
        self.filtspec["params"]["params"] = params
        print(param)
        self.sig_filt_changed.emit(self.filtspec)

    @qtSlot()
    def get_filtspec(self):
        sel = self.main_selection_pane.get_spec()
        params = self.parameter_pane.get_params()
        self.filtspec["params"] = {}
        self.filtspec["params"]["response_type"] = sel["response_type"]
        self.filtspec["params"]["fir_iir"] = sel["fir_iir"]
        self.filtspec["params"]["design"] = sel["design"]
        self.filtspec["params"]["params"] = params
        return deepcopy(self.filtspec)


class MainSelectionPane(QFrame):
    '''Band response type, FIR/IIR, design
    '''
    
    sig_mainsel_changed = qtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.band_response_types = [
                c.value[0] for c in fp.ResponseType]
        self.impulse_response_types = [
                c.value for c in fp.ImpulseResponseLength]
        self.init_gui()
    
    def init_gui(self):
        # functional widgets
        self.lb = QLabel("Main Selection")

        self.lbRes = QLabel("response type")
        self.cb_restype = QComboBox()
        self.cb_restype.addItems(self.band_response_types)
        
        self.lbFI = QLabel("FIR/IIR")
        self.cb_irlen = QComboBox()
        self.cb_irlen.addItems(self.impulse_response_types)

        # order matters
        self.fir_iir_design_holder = QStackedWidget()
        self.fir_widgets = self.make_ir_widget("FIR", self.fir_iir_design_holder)
        self.iir_widgets = self.make_ir_widget("IIR", self.fir_iir_design_holder)
        self.fir_notch_q = QLabel("FIR_notch_Q")
        self.iir_notch_q = QLabel("IIR_notch_Q")
        self.fir_iir_design_holder.addWidget(self.fir_notch_q)
        self.fir_iir_design_holder.addWidget(self.iir_notch_q)
        
        # connections
        self.cb_restype.currentIndexChanged.connect(self.on_resptype_changed)
        self.cb_irlen.currentIndexChanged.connect(self.on_irlen_changed)
        # self.cbResType.currentIndexChanged.connect(self.onSomethingChanged)

        # layouts
        self.setLayout(QFormLayout())
        self.layout().addRow(self.lb)
        self.layout().addRow(self.lbRes, self.cb_restype)
        self.layout().addRow(self.lbFI, self.cb_irlen)
        self.layout().addWidget(self.fir_iir_design_holder)
       
        return

    def make_ir_widget(self, s, holder):
        x = {}
        if s.lower() == "fir":
            x["designs"] = [c.value[0] for c in fp.FirDesign]
        elif s.lower() == "iir":
            x["designs"] = [c.value[0] for c in fp.IirDesign]
        else:
            raise(ValueError, "only fir or iir")

        x["widget"] = QWidget()
        x["lb"] = QLabel("%s design" % s)
        x["cb"] = QComboBox()
        x["cb"].addItems(x["designs"])

        x["layout"] = QHBoxLayout()
        x["widget"].setLayout(x["layout"])
        x["layout"].addWidget(x["lb"])
        x["layout"].addWidget(x["cb"])
        holder.addWidget(x["widget"])

        x["cb"].currentIndexChanged.connect(self.on_something_changed)
        
        return x

    @qtSlot(int)
    def on_resptype_changed(self, ind=None):
        self.on_something_changed()

    @qtSlot(int)
    def on_irlen_changed(self, ind=None):
        self.on_something_changed()
        
    @qtSlot()
    def on_something_changed(self):
        rp, fir_iir, design = self.get_widget_status()

        if rp in fp.ResponseType.notch.value:
            self.fir_iir_design_holder.setEnabled(False)
            if fir_iir == fp.ImpulseResponseLength.fir:
                self.fir_iir_design_holder.setCurrentIndex(2)
            else:
                self.fir_iir_design_holder.setCurrentIndex(3)
        else:
            if fir_iir == fp.ImpulseResponseLength.fir:
                self.fir_iir_design_holder.setCurrentIndex(0)
            else:
                self.fir_iir_design_holder.setCurrentIndex(1)
            self.fir_iir_design_holder.setEnabled(True)

        self.sig_mainsel_changed.emit(self.get_spec())
        return

    @qtSlot()
    def get_spec(self):
        rp, fir_iir, design = self.get_widget_status()

        sel = {}
        sel["response_type"] = rp
        sel["fir_iir"] = fir_iir.value
        sel["design"] = design
        return sel

    @qtSlot()
    def get_widget_status(self):
        ind_rp = self.cb_restype.currentIndex()
        rp = self.band_response_types[ind_rp]

        ind_ir = self.cb_irlen.currentIndex()
        fir_iir = fp.ImpulseResponseLength(
                self.impulse_response_types[ind_ir])

        if rp in fp.ResponseType.notch.value:
            if fir_iir == fp.ImpulseResponseLength.fir:
                design = "fir_notch_q"
            else:
                design = "iir_notch_q"
        else:
            if fir_iir == fp.ImpulseResponseLength.fir:
                design = self.fir_widgets["designs"][self.fir_widgets["cb"].currentIndex()]
            else:
                design = self.iir_widgets["designs"][self.iir_widgets["cb"].currentIndex()]
        
        return rp, fir_iir, design


class ParameterPane(QFrame):
    
    sig_param_changed = qtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_gui()
    
    def init_gui(self):
        self.fh_index_to_use = {
                fp.ResponseType.lowpass: 0,
                fp.ResponseType.highpass: 1,
                fp.ResponseType.bandpass: 2,
                fp.ResponseType.bandstop: 3,
                fp.ResponseType.notch: 4,
                }
        self.ao_index_to_use = {
                "iir_butterworth": 0,
                }

        # functional widgets
        self.freq_holder = QStackedWidget()
        self.lp_widgets = self.make_cutoff_widget_type1("Lowpass cutoff")
        self.hp_widgets = self.make_cutoff_widget_type1("Highpass cutoff")
        self.bp_widgets = self.make_cutoff_widget_type2("Bandpass")
        self.bs_widgets = self.make_cutoff_widget_type2("Bandstop")
        self.notch_widgets = self.make_cutoff_widget_type1("Notch target")
        # order matters - see self.fh_index_to_use
        self.freq_holder.addWidget(self.lp_widgets["widget"])
        self.freq_holder.addWidget(self.hp_widgets["widget"])
        self.freq_holder.addWidget(self.bp_widgets["widget"])
        self.freq_holder.addWidget(self.bs_widgets["widget"])
        self.freq_holder.addWidget(self.notch_widgets["widget"])
        #self.freq_holder.setCurrentIndex(0)

        self.strength_holder = QStackedWidget()
        self.ao_holder = QStackedWidget()
        self.o_widgets = self.make_o_widgets()
        self.ao_holder.addWidget(self.o_widgets["widget"])
        #self.a_widgets = self.make_a_widgets()
        #self.order_widgets = self.make_order_widgets()
        self.q_widgets = self.make_q_widgets()

        self.strength_holder.addWidget(self.ao_holder)
        #self.strength_holder.addWidget(self.a_widgets["widget"])
        #self.strength_holder.addWidget(self.order_widgets["widget"])
        self.strength_holder.addWidget(self.q_widgets["widget"])

        # connections

        # layouts
        self.setLayout(QVBoxLayout())
        self.lb = QLabel("Parameters")
        self.layout().addWidget(self.lb)
        self.layout().addWidget(self.freq_holder)
        self.layout().addWidget(self.strength_holder)
        
        # self.update_freq_gui()
        
        return

    def make_cutoff_widget_type1(self, s):
        x = {}
        x["widget"] = QWidget()
        x["layout"] = QHBoxLayout()
        x["widget"].setLayout(x["layout"])
        x["lb_co"] = QLabel("%s frequency [Hz]" % s)
        x["ed_co"] = QLineEdit("0.25")
        x["layout"].addWidget(x["lb_co"])
        x["layout"].addWidget(x["ed_co"])
        
        x["ed_co"].textChanged.connect(self.notify_params)
        return x

    def make_cutoff_widget_type2(self, s):
        x = {}
        x["widget"] = QWidget()
        x["layout"] = QHBoxLayout()
        x["widget"].setLayout(x["layout"])
        x["lb_co"] = QLabel("%s cutoff frequencies [Hz]" % s)
        x["lb_co_low"] = QLabel("low")
        x["ed_co_low"] = QLineEdit("0.1")
        x["lb_co_high"] = QLabel("high")
        x["ed_co_high"] = QLineEdit("0.3")
        x["layout"].addWidget(x["lb_co"])
        x["layout"].addWidget(x["lb_co_low"])
        x["layout"].addWidget(x["ed_co_low"])
        x["layout"].addWidget(x["lb_co_high"])
        x["layout"].addWidget(x["ed_co_high"])
        
        x["ed_co_low"].textChanged.connect(self.notify_params)
        x["ed_co_high"].textChanged.connect(self.notify_params)
        return x

    def make_o_widgets(self):
        '''
        attenuation / order
        '''
        x = {}
        x["widget"] = QWidget()
        x["layout"] = QHBoxLayout()
        x["widget"].setLayout(x["layout"])
        x["lb_o"] = QLabel("order" )
        x["ed_o"] = QLineEdit("10")
        x["layout"].addWidget(x["lb_o"])
        x["layout"].addWidget(x["ed_o"])
        
        x["ed_o"].textChanged.connect(self.notify_params)
        return x

    def make_q_widgets(self):
        '''
        notch Q
        '''
        x = {}
        x["widget"] = QWidget()
        x["layout"] = QHBoxLayout()
        x["widget"].setLayout(x["layout"])
        x["lb_q"] = QLabel("Q" )
        x["ed_q"] = QLineEdit("2.0")
        x["layout"].addWidget(x["lb_q"])
        x["layout"].addWidget(x["ed_q"])
        
        x["ed_q"].textChanged.connect(self.notify_params)
        return x

    
    @qtSlot(dict)
    def on_mainsel_changed(
            self,
            mainsel = {"response_type": fp.ResponseType.bandpass.value[0]}
            ):
        
        rp = fp.get_enum_key_from_value(fp.ResponseType,
                                        mainsel["response_type"])
        
        # change frequency specification widgets
        if rp in self.fh_index_to_use:
            #print(rp.value[0])
            self.freq_holder.setCurrentIndex(self.fh_index_to_use[rp])
        else:
            print(rp)
            raise(ValueError, "unsupported ResponseType")

        # change strength specification widgets
        if rp == fp.ResponseType.notch:
            self.strength_holder.setCurrentIndex(1)
        else:
            # lp, hp, bp, bs (i.e., not notch)
            self.strength_holder.setCurrentIndex(0)
            if ((mainsel["fir_iir"].lower() == "iir") and
                (mainsel["design"].lower() in fp.IirDesign.butterworth)):
                self.strength_holder.currentWidget().setCurrentIndex(
                        self.ao_index_to_use["iir_butterworth"])
            else:
                print("unsupported pattern: %s / %s"
                      % mainsel["fir_iir"], mainsel["design"])

        self.notify_params()
        return
    
    @qtSlot()
    def notify_params(self):
        params = self.get_params()
        if params:
            self.sig_param_changed.emit(params)
        return

    def get_params(self):
        params = {}
        ind = self.freq_holder.currentIndex()
        if (ind == 0) or (ind == 1):
            # lp, hp ... single cutoff
            w = self.lp_widgets if ind == 0 else self.hp_widgets
            try:
                s = w["ed_co"].text()
                f = float(s)
                params["cutoff"] = f
            except Exception as e:
                print(e)
                print(s)
                return
        elif (ind == 2) or (ind == 3):
            w = self.bp_widgets if ind == 2 else self.bs_widgets
            try:
                s0 = w["ed_co_low"].text()
                f0 = float(s0)
                s1 = w["ed_co_high"].text()
                f1 = float(s1)
                params["cutoff"] = [f0, f1]
            except Exception as e:
                print(e)
                print(s0)
                print(s1)
                return
        elif ind == 4:
            # f
            try:
                s = self.notch_widgets["ed_co"].text()
                f = float(s)
                params["f"] = f
            except Exception as e:
                print(e)
                print(s)
                return
            #            # Q
            #            try:
            #                s = self.q_widgets["ed_q"].text()
            #                Q = float(s)
            #                params["Q"] = Q
            #            except Exception as e:
            #                print(e)
            #                print(s)
            #                return
        else:
            raise(ValueError, "unsupported freq_holder index: %d" % ind)

        ind = self.strength_holder.currentIndex()
        if ind == 0:
            # not notch
            ind2 = self.ao_holder.currentIndex()
            if ind2 == 0:
                # o_widget
                try:
                    s = self.o_widgets["ed_o"].text()
                    order = int(s)
                    params["order"] = order
                except Exception as e:
                    print(e)
                    print(s)
                    return
                
        elif ind == 1:
            # notch Q
            try:
                s = self.q_widgets["ed_q"].text()
                Q = float(s)
                params["Q"] = Q
            except Exception as e:
                print(e)
                print(s)
                return
        else:
            raise(ValueError, "unsupported strength_holder index: %d" % ind)

        return params


class SpecificationsWidget(QFrame):
    
    sig_coef_changed = qtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_gui()
    
    def init_gui(self):
        self.setLayout(QFormLayout())
        self.lb = QLabel("Specifications")
        self.layout().addWidget(self.lb)
        
        self.lbSpec = QLabel("filter_spec")
        self.spec_box = QTextBrowser()
        self.layout().addRow(self.lbSpec, self.spec_box)

        self.lbCoef = QLabel("coefficients")
        self.coef_box = QTextBrowser()
        self.layout().addRow(self.lbCoef, self.coef_box)
        
        # appearances
        set_font_family(self.spec_box, "Consolas")
        set_font_family(self.coef_box, "Consolas")
       
        return

    @qtSlot(dict, dict)
    def on_filter_changed(self, filter_info={}, data_spec: dict={}):
        print("Spec Widget received filter change:")
        # print(filter_info)
        s = pprint.pformat(filter_info)
        self.spec_box.setText(s)
        #if fp.check_single_filtspec_validity(filter_info):
        filter_spec = fp.append_filter({}, filter_info)
        print(filter_spec)
        print(data_spec)
        #try:
        params_list, bidir = fp.get_freq_filters(filter_spec, data_spec["sampling_rate"])
        sp = pprint.pformat(params_list)
        self.coef_box.setText(sp)
        print("got filter")
        self.sig_coef_changed.emit(params_list[0])
        #        except Exception as e:
        #            print(e)
        #            self.coef_box.setText(str(e))
        #        return

    @qtSlot(dict, dict)
    def on_spec_design_changed(self, filter_info={}, data_spec: dict={}):
        print("Spec Widget received filter change:")
        # print(filter_info)
        s = pprint.pformat(filter_info)
        self.spec_box.setText(s)
        #if fp.check_single_filtspec_validity(filter_info):
        filter_spec = fp.append_filter({}, filter_info)
        print(filter_spec)
        print(data_spec)
        #try:
        params_list, bidir = fp.get_freq_filters(filter_spec, data_spec["sampling_rate"])
        sp = pprint.pformat(params_list)
        self.coef_box.setText(sp)
        print("got filter")
        self.sig_coef_changed.emit(params_list[0])
        #        except Exception as e:
        #            print(e)
        #            self.coef_box.setText(str(e))
        #        return

    @qtSlot(dict, dict)
    def on_data_changed(self, filter_info={}, data_spec: dict={}):
        print("Spec Widget received filter change:")
        # print(filter_info)
        s = pprint.pformat(filter_info)
        self.spec_box.setText(s)
        #if fp.check_single_filtspec_validity(filter_info):
        filter_spec = fp.append_filter({}, filter_info)
        print(filter_spec)
        print(data_spec)
        #try:
        params_list, bidir = fp.get_freq_filters(filter_spec, data_spec["sampling_rate"])
        sp = pprint.pformat(params_list)
        self.coef_box.setText(sp)
        print("got filter")
        self.sig_coef_changed.emit(params_list[0])
        #        except Exception as e:
        #            print(e)
        #            self.coef_box.setText(str(e))
        #        return




class CharacteristicsWidget(QFrame):
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayout(QFormLayout())
        self.lb = QLabel("Characteristics")
        self.layout().addWidget(self.lb)
        setMyFrameStyle(self)
        setMyFrameStyle(self.lb)

        self.plots_pane = CharacteristicsPlotPane()
        self.layout().addWidget(self.plots_pane)
    
    def update_plot(self, coefs):
        self.plots_pane.update_plot(coefs)

#from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
#from matplotlib.figure import Figure as MplFigure
class CharacteristicsPlotPane(QFrame):
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_gui()
    
    def init_gui(self):
        self.setLayout(QVBoxLayout())

        self.lb = QLabel("Characteristics Plots")
        self.layout().addWidget(self.lb)

        self.figure = MplFigure(constrained_layout=True)
        self.canvas = FigureCanvas(self.figure)
        self.layout().addWidget(self.canvas)
        self.ah1 = self.figure.add_subplot(2, 1, 1)
        self.ah2 = self.figure.add_subplot(2, 1, 2)
        # self.ah3 = self.figure.add_subplot(3, 1, 3)
        #self.ah1.plot(**)
        #self.ah1.scatter(**)
        setMyFrameStyle(self)
        setMyFrameStyle(self.lb)
        
        return

    def update_plot(self, coefs):
        plot_freq_response_single(self.ah1, self.ah2, coefs)
        self.canvas.draw()


#https://docs.scipy.org/doc/scipy-0.16.0/reference/generated/scipy.signal.freqz.html
#https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.sosfreqz.html

def plot_freq_response_single(ax_amp, ax_phase, coefs):

    worN = 1024
    print("plotter")
    print(coefs)
    if 'sos' in coefs:
        # sos
        sos = coefs["sos"]
        w, h = sig.sosfreqz(sos, worN=worN)
    else:
        # a and b
        b = coefs["b"]
        a = coefs["a"]
        w, h = sig.freqz(b, a, worN=worN)

    if (("descriptions" in coefs)
        and ("data_sampling_freq" in coefs["descriptions"])):
        nyq = coefs["descriptions"]["data_sampling_freq"] / 2.0
        f = w / np.pi * nyq
        tt = f
        xlabel = "Frequency [Hz]"
    else:
        tt = w 
        xlabel = "Frequency [rad/sample]"

    ax_amp.clear()
    ax_amp.plot(tt, 20*np.log10(abs(h)), 'b')
    ax_amp.set_ylabel('Amplitude [dB]', color='b')
    ax_amp.set_xlabel(xlabel)
    ax_amp.grid(True)
    ax_amp.autoscale(enable=True, axis='x', tight=True)

    ang = np.unwrap(np.angle(h))
    #ang = np.angle(h)
    ax_phase.clear()
    ax_phase.plot(tt, ang, 'g')
    ax_phase.set_ylabel("Angle [rad]", color='g')
    ax_amp.set_xlabel(xlabel)
    ax_phase.grid(True)
    ax_phase.autoscale(enable=True, axis='x', tight=True)

    return


def setMyFrameStyle(qw):
    # qw.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
    # qw.setLineWidth(4)
    return    


def set_font_family(w, font_family: str):
    font = w.font()
    font.setFamily(font_family)
    w.setFont(font)
    return w.font()


def design_freq_filter():

    instance = QApplication.instance()
    app = instance if instance else QApplication(sys.argv)

    #print("fontsize %f" % app.font().pointSizeF())
    font = app.font()
    # font.setFamily('Consolas')
    font.setPointSizeF(12.0)
    app.setFont(font)
    #app.font().setPointSizeF(15.0)

    gui = FreqFilterDesignGUI()
    gui.show()
    gui.start()
    
    filter_spec = gui.get_filter_spec()
    
    # need to delete app/gui explicitly?
    if not instance:
        app.deleteLater()

    return filter_spec


if __name__ == "__main__":

    
    filter_spec = design_freq_filter()
    print("filter_spec: %s" % filter_spec)
    
    
    '''
    qmlUrl = QUrl.fromLocalFile("filter_design_utility.qml")
    
    instance = QApplication.instance()
    if instance is None:
        app = QApplication()
    else:
        app = instance

    engine = QQmlEngine()
    qqc = QQmlComponent(engine)
    qqc.loadUrl(qmlUrl)
    qqw = qqc.create()
    # qqw.setColor("green")
    # qqw.show()
    # print(type(qqw))
    
    qw = QWidget.createWindowContainer(qqw)
    qw.show()
    qw.setWindowTitle("Widget for QML")
    
    
    
    app.exec_()    

    filtspec = {
            "filter_list": [
                    {"definition_type": "design",
                     "params": {
                             "response_type": "bandpass",
                             "fir_iir": "iir",
                             "design": "butterworth",
                             "params": {
                                     "cutoff": [10.0, 20.0],
                                     "order": 15}}},
                    {"definition_type": "design",
                     "params": {
                             "response_type": "notch",
                             "fir_iir": "iir",
                             "design": "second_order_iir_notch",
                             "params": {
                                     "f": 18.0,
                                     "Q": 15}}},
                    ],
            "common_params": {
                    "bidirectional": True,
                    # padding, etc.
                    }
            }
    '''
    
    print(os.path.basename(__file__) + ": finished main")


"""
special variables
"""

__author__ = "Yasushi Terazono <Yasushi.Terazono@us.tdk.com>"
__version__ = "0.0.1"
__date__ = "Thu Mar 26 17:53:18 2020"

"""
Thu Mar 26 17:53:18 2020  Yasushi Terazono <teraz@jp.tdk.com>
                           <Yasushi.Terazono@us.tdk.com>
* created
"""

'''
print('PipelineInitConfig myAccept()')
s = self.leSR.text()
print(s)
sspec = copy.deepcopy(self.sspec)
print('trying sample rate handling..')
try:
    sf = float(s)
    if (sf > 0):
        sspec['sampling_rate_type'] = b'float'
        sspec['sampling_rate_f'] = sf
        if 'sampling_rate_i' in sspec:
            del sspec['sampling_rate_i']
except Exception as e:
    print(e)

print('PipelineInitConfig myAccept() sspec')
_tgt = ('sampling_rate_type', 'sampling_rate_i', 'sampling_rate_f')
for t in _tgt:
    if t in sspec:
        print(t)
        print(sspec[t])

if self.rb_simple.isChecked():
    self.pipeline = "simple"
    print("pipeline: " + self.pipeline)
elif self.rb_avg.isChecked():
    self.pipeline = "averaging"
    print("pipeline-averaging: " + self.pipeline)
else:
    raise

self.sspec_new = copy.deepcopy(sspec)
'''


"""

class FreqFilterDesignGUI3P(QDialog):
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.filter_spec = {
                "filter_list": [],
                "common_params": {},
                }
        self.init_gui()
    
    def init_gui(self):
        self.setWindowTitle('Frequency Filter Designer')
        self.setLayout(QVBoxLayout())
        self.layForPanes = QHBoxLayout()
        self.layForPanes.setContentsMargins(2, 2, 2, 2)
        self.layout().addLayout(self.layForPanes)
        self.designWidget = DesignWidget()
        self.layForPanes.addWidget(self.designWidget, stretch=1)
        self.specWidget = SpecificationsWidget()
        self.layForPanes.addWidget(self.specWidget, stretch=1)
        self.charWidget = CharacteristicsWidget()
        self.layForPanes.addWidget(self.charWidget, stretch=1)
        self.addgui_the_buttons()
        
        self.setMinimumSize(QSize(320, 240))

        self.designWidget.sigFilterChanged.connect(self.specWidget.onFilterChanged)

    def addgui_the_buttons(self):
        self.okng_buttons = QDialogButtonBox(
                QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
                Qt.Horizontal, self)
        self.layout().addWidget(self.okng_buttons)
        self.okng_buttons.accepted.connect(self.myAccept)
        self.okng_buttons.rejected.connect(self.reject)


    def start(self):
        if QT_TYPE == "PySide2":
            self.exec_()
        elif QT_TYPE == "PyQt5":
            self.exec()
        else:
            raise(ValueError, "unknown QT_TYPE: %s" % QT_TYPE)

    def get_filter_spec(self):
        return deepcopy(self.filter_spec)

    @qtSlot()
    def myAccept(self):
        '''
        print('PipelineInitConfig myAccept()')
        s = self.leSR.text()
        print(s)
        sspec = copy.deepcopy(self.sspec)
        print('trying sample rate handling..')
        try:
            sf = float(s)
            if (sf > 0):
                sspec['sampling_rate_type'] = b'float'
                sspec['sampling_rate_f'] = sf
                if 'sampling_rate_i' in sspec:
                    del sspec['sampling_rate_i']
        except Exception as e:
            print(e)

        print('PipelineInitConfig myAccept() sspec')
        _tgt = ('sampling_rate_type', 'sampling_rate_i', 'sampling_rate_f')
        for t in _tgt:
            if t in sspec:
                print(t)
                print(sspec[t])

        if self.rb_simple.isChecked():
            self.pipeline = "simple"
            print("pipeline: " + self.pipeline)
        elif self.rb_avg.isChecked():
            self.pipeline = "averaging"
            print("pipeline-averaging: " + self.pipeline)
        else:
            raise

        self.sspec_new = copy.deepcopy(sspec)
        '''
        print("accepted")
        self.accept()

"""

"""


class DesignWidget2(QFrame):
    
    sigFilterChanged = qtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_gui()
    
    @qtSlot(dict)
    def onMainSelChanged(self, sel={}):
        print("Design Widget received main selection change")
        params = self.parameter_pane.get_params()
        sel["params"]["params"] = params
        print(sel)
        self.sendOutFilterInformation(sel)
    
    @qtSlot(dict)
    def onParameterChanged(self, param={}):
        print("Design Widget received parameter change")
        print(param)

    @qtSlot(dict)
    def sendOutFilterInformation(self, filter_info={}):
        self.sigFilterChanged.emit(filter_info)

    def init_gui(self):
        self.setLayout(QVBoxLayout())
        self.lb = QLabel("Design")
        self.layout().addWidget(self.lb)
        setMyFrameStyle(self)
        setMyFrameStyle(self.lb)
        
        self.main_selection_pane = MainSelectionPane()
        self.parameter_pane = ParameterPane()
        self.layout().addWidget(self.main_selection_pane)
        self.layout().addWidget(self.parameter_pane)
        
        self.main_selection_pane.sigResponseTypeChanged.connect(
                self.parameter_pane.on_response_type_changed)

            
        self.main_selection_pane.sigMainSelChanged.connect(
                self.onMainSelChanged)
        self.parameter_pane.sigParameterChanged.connect(
                self.onParameterChanged)
        
        return


"""

"""
class DrawingPane(QFrame):
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_gui()
    
    def init_gui(self):
        self.setLayout(QVBoxLayout())

        self.lb = QLabel("Drawing")
        self.layout().addWidget(self.lb)

        self.figure = MplFigure()
        self.canvas = FigureCanvas(self.figure)
        self.layout().addWidget(self.canvas)
        self.ah = self.figure.add_subplot(1, 1, 1)
        
        setMyFrameStyle(self)
        setMyFrameStyle(self.lb)
        
        return
"""

