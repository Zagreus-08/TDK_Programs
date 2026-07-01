#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
filter_processor: apply frequency fileters as specified by filter_spec

filter_spec >> get_freq_filters() >> params_list
params_list, data, axis, bidirectional >> apply_freq_filters_core() >> data output

entry point is apply_freq_filters()
filter_spec is human readable
params_list is mainly for computers


References:
    https://github.com/scipy/scipy/blob/451b09f/scipy/signal/signaltools.py#L4075-L4184

ToDo:
    fully cover options of scipy.signal filtering functions

"""

import os
import sys
import numpy as np
import scipy.signal as sig
from enum import Enum

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def check_filter_spec(filter_spec: dict):
    is_good = True

    raise
    
    return is_good


def check_filtspec_validity(spec: dict):
    is_good = True
    #"spec_format": "filter_spec_01",
    #"spec_format": "single_filter_spec_01",
    if "filter_spec_01" in spec:
        pass
    elif "single_filter_spec_01" in spec:
        is_good = check_single_filtspec_validity(spec)

    return is_good


def check_single_filtspec_validity(spec: dict):
    is_good = True
    
    if not ("definition_type" in spec):
        print("definition_type not found")
        return False

    if spec["definition_type"].lower() == "design":
        if not ("params" in spec):
            print("params not found in 'design' type spec definition")
            return False

        return check_design_spec(spec["params"])

    # elif spec["definition_type"].lower() == "direct":
    #    if not ("params" in spec):
    #        print("params not found in 'direct' type spec definition")
    #        return False
    #     check_direct_spec(spec["params"])

    else:
        print("currently only 'design' type spec definition is supported")
        return False

    return is_good

def check_design_spec(spec: dict):
    if not ("response_type" in spec):
        print("response_type not found in spec")
        return False
    
    vs = []
    for c in ResponseType:
        vs.extend(*c.value)
    
    rp = spec["response_type"].lower()
    if not rp in vs:
        print("non-supported response_type")
        return False
    
    if rp in ResponseType.bandpass.values:
        print("check_design_spec - bandpass")
    #    if 
    #     "response_type": "bandpass",
    #     "fir_iir": "iir",
    #     "design": "butterworth",
    #     "params": {
    #             "cutoff": [10.0, 20.0],
    #             "order": 15}}},
    return True


def append_filter(filter_spec, single_filter_spec):
    if "spec_format" in filter_spec:
        filter_spec["filters_list"].append(single_filter_spec)
    elif (filter_spec is None) or (filter_spec == {}):
        filter_spec = {}
        filter_spec["spec_format"] = "filter_spec_01"
        filter_spec["filters_list"] = [single_filter_spec]
        filter_spec["common_params"] = {}
        filter_spec["common_params"]["bidirectional"] = True

    return filter_spec


def apply_freq_filters(
        filter_spec: dict,
        data: np.ndarray,
        data_fs: float = 1.0,
        axis: int = -1):
    '''apply frequency filters to the given data

    Args:
        filter_spec (dict): filter specifications. see ** for details
        data (numpy.ndarray): data to apply filters
        data_fs (float): data sampling frequency
        axis (int): data axis to apply filters, from 0 to ndim-1 (?? -1 ??)

    Returns:
        numpy.ndarray: filtered data. same size as the given data.
        list: list of parameters used in apply_freq_filters_core().
              generated from filter_spec and data_fs
    '''

    # assumes check_filter_spec(filter_spec) == True
    
    params_list, bidir = get_freq_filters(filter_spec, data_fs, axis)
   
    filtered_data = apply_freq_filters_core(
            params_list, data, axis=axis, bidirectional=bidir)
        
    return filtered_data, params_list


def get_freq_filters(
        filter_spec: dict,
        data_fs: float = 1.0,
        axis: int = -1):

    common_params = filter_spec["common_params"]
    print("get_freq_filters")

    params_list = []
    for flt in filter_spec["filters_list"]:
        # "definition_type": "design", "direct"=="coefficient", 
        definition_type = flt["definition_type"].lower()
        if definition_type in ["design"]:
            filter_params = get_filter_by_design(
                    design_params=flt["params"], data_fs=data_fs,
                    common_params=common_params)
        elif definition_type in ["direct", "coefficient"]:
            filter_params = get_filter_by_coefs(
                    direct_params=flt["params"], data_fs=data_fs,
                    common_params=common_params)
        else:
            # should not happen -- use check_filter_spec first
            raise
        params_list.append(filter_params)

    bidir = True if ("bidirectional" not in common_params
                     ) else bool(common_params["bidirectional"])

    return params_list, bidir

def get_filter_by_design(
        design_params: dict,
        data_fs: float = 1.0,
        axis: int = -1,
        common_params: dict = {}):

    print("get_filter_by_design")

    # "fir_iir": "fir", "iir"
    fir_iir = design_params["fir_iir"].lower()
    if fir_iir == "iir":
        params = get_iir_filter(
                iir_params=design_params, data_fs=data_fs,
                axis=axis, common_params=common_params)
    elif fir_iir == "fir":
        params = get_fir_filter(
                fir_params=design_params, data_fs=data_fs,
                axis=axis,common_params=common_params)
    else:
        # should not happen -- use check_filter_spec first
        pass

    return params


def get_fir_filter(
        fir_params: dict,
        data_fs: float = 1.0,
        axis: int = -1,
        common_params: dict = {}):
    
    print("get_fir_filter")
    design = fir_params["design"].lower()
    if design in ["window_fir1"]:
        params = get_window_fir1_filter(
                response_type=fir_params["response_type"],
                window_fir1_params=fir_params["params"],
                data_fs=data_fs, axis=axis, common_params=common_params)
    elif design in ["fir_notch", "fir_notch_q", "notch"]:
        params = get_firnotch_filter(
                firnotch_params=fir_params["params"],
                data_fs=data_fs, axis=axis, common_params=common_params)
    else:
        # should not happen -- use check_filter_spec first
        raise(ValueError, "not supported %s" % design)
        pass

    return params


def get_iir_filter(
        iir_params: dict,
        data_fs: float = 1.0,
        axis: int = -1,
        common_params: dict = {}):
    
    print("get_iir_filter")
    design = iir_params["design"].lower()
    if design in ["butter", "butterworth"]:
        params = get_butterworth_filter(
                response_type=iir_params["response_type"],
                butter_params=iir_params["params"],
                data_fs=data_fs, axis=axis, common_params=common_params)
    elif design in ["second_order_iir_notch", "iir_notch", "iir_notch_q", "notch"]:
        params = get_iirnotch_filter(
                iirnotch_params=iir_params["params"],
                data_fs=data_fs, axis=axis, common_params=common_params)
    else:
        # should not happen -- use check_filter_spec first
        raise(ValueError, "not supported %s" % design)
        pass

    return params


def normalize_response_type(rtype):
    rlow = rtype.lower()
    rdict = {"lowpass": ["lowpass", "lp", "highcut", "hc"],
             "highpass": ["highpass", "hp", "lowcut", "lc"],
             "bandpass": ["bandpass", "bp"],
             "bandstop": ["bandstop", "bs"],}

    print("normalize_response_type")

    # if rlow() not in rdict.values(): raise
    rtype_normalized = [k for k, v in rdict.items() if rlow in v][0]

    return rtype_normalized


def get_window_fir1_filter(
        response_type: str,
        window_fir1_params: dict,
        data_fs: float = 1.0,
        axis: int = -1,
        common_params: dict = {}):
    
    print("get_window_fir1_filter")
    nyq = data_fs / 2.0
    try:
        cutoff = window_fir1_params["cutoff"]/nyq
    except Exception as e:
        cutoff = [a/nyq for a in window_fir1_params["cutoff"]]

    btype = normalize_response_type(response_type)
    if "numtaps" in window_fir1_params:
        numtaps = window_fir1_params["numtaps"]
    else:
        numtaps = 12
    window = "hamming"
    h = sig.firwin(numtaps, cutoff,
                   width=None, window=window, pass_zero=btype)

    params = {}
    params["descriptions"] = {
            "response_type": btype,
            "data_sampling_freq": data_fs,
            "data_nyquist_freq": nyq,
            "cutoff": window_fir1_params["cutoff"],
            "normalized_cutoff": cutoff,
            "numtaps": numtaps,
            "window": window,
            }
    params["b"] = h
    params["a"] = 1.0
    params["axis"] = axis

    return params


def get_butterworth_filter(
        response_type: str,
        butter_params: dict,
        data_fs: float = 1.0,
        axis: int = -1,
        common_params: dict = {}):
    
    print("get_butterworth_filter")
    nyq = data_fs / 2.0
    try:
        cutoff = butter_params["cutoff"]/nyq
    except Exception as e:
        cutoff = [a/nyq for a in butter_params["cutoff"]]

    btype = normalize_response_type(response_type)

    sos = sig.butter(butter_params["order"], cutoff, btype=btype, output='sos')

    params = {}
    params["descriptions"] = {
            "response_type": btype,
            "data_sampling_freq": data_fs,
            "data_nyquist_freq": nyq,
            "cutoff": butter_params["cutoff"],
            "normalized_cutoff": cutoff,
            }
    params["sos"] = sos
    params["axis"] = axis

    return params


def get_firnotch_filter(
        firnotch_params: dict,
        data_fs: float = 1.0,
        axis: int = -1,
        common_params: dict = {}):

    nyq = data_fs / 2.0
    f = firnotch_params["f"]/nyq
    Q = firnotch_params["Q"]

    #b, a = sig.iirnotch(f, Q)

    params = {}
    params["descriptions"] = {
            "response_type": "notch",
            "data_sampling_freq": data_fs,
            "data_nyquist_freq": nyq,
            "f": firnotch_params["f"],
            "normalized_f": f,
            "Q": Q,
            }
    #params["b"] = b
    #params["a"] = a
    #params["axis"] = axis

    return params


def get_iirnotch_filter(
        iirnotch_params: dict,
        data_fs: float = 1.0,
        axis: int = -1,
        common_params: dict = {}):

    nyq = data_fs / 2.0
    f = iirnotch_params["f"]/nyq
    Q = iirnotch_params["Q"]

    b, a = sig.iirnotch(f, Q)

    params = {}
    params["descriptions"] = {
            "response_type": "notch",
            "data_sampling_freq": data_fs,
            "data_nyquist_freq": nyq,
            "f": iirnotch_params["f"],
            "normalized_f": f,
            "Q": Q,
            }
    params["b"] = b
    params["a"] = a
    params["axis"] = axis

    return params


def apply_freq_filters_core(filter_spec: dict, data, axis, bidirectional=True):

    filtered_data = data.copy()

    for flt in filter_spec:
    
        if ("b" in flt) and ("a" in flt):
            coef_type = "ba"
        elif "sos" in flt:
            coef_type = "sos"
        else:
            raise
    
        if coef_type == "ba" and bidirectional:
            filtered_data = sig.filtfilt(
                    flt["b"], flt["a"], filtered_data, axis=axis)
        elif coef_type == "ba" and not bidirectional:
            filtered_data = sig.lfilter(
                    flt["b"], flt["a"], filtered_data, axis=axis)
        elif coef_type == "sos" and bidirectional:
            filtered_data = sig.sosfiltfilt(
                    flt["sos"], filtered_data, axis=axis)
        elif coef_type == "sos" and not bidirectional:
            filtered_data = sig.sosfilt(
                    flt["sos"], filtered_data, axis=axis)

    return filtered_data


def get_enum_key_from_value(c, v):
    for k in c:
        if (v in k.value) or (v == k.value):
            return k
    else:
        raise(ValueError, "unsupported key %s for %s" % str(v), str(c))


class ResponseType(Enum):
    # the first value is "nominal" value
    lowpass = ["lowpass", "lp", "highcut", "hc"]
    highpass = ["highpass", "hp", "lowcut", "lc"]
    bandpass = ["bandpass", "bp"]
    bandstop = ["bandstop", "bs"]
    notch = ["notch"]
    

class ImpulseResponseLength(Enum):
    fir = "fir"
    iir = "iir"
    

class FirDesign(Enum):
    # https://www.mathworks.com/help/signal/ug/fir-filter-design.html
    window_fir1 = ["window_fir1"]
    #    window_fir2 = ["window_fir2"]
    #    window_kaiserord = ["window_kaiserord"]
    #    multiband_with_tansition_bands_firls = ["multiband_with_tansition_bands_firls"]
    #    multiband_with_tansition_bands_firpm = ["multiband_with_tansition_bands_firpm"]
    #    multiband_with_tansition_bands_firpmord = ["multiband_with_tansition_bands_firpmord"]
    #    constrained_least_squares_fircls = ["constrained_least_squares_fircls"]
    #    constrained_least_squares_fircls1 = ["constrained_least_squares_fircls1"]
    #    arbitrary_response_cfirpm = ["arbitrary_response_cfirpm"]
    #    raised_cosign_cfirpm = ["raised_cosign_cfirpm"]
	

class IirDesign(Enum):
    butterworth = ["butterworth", "butter", "bw"]
    #    chebyshev = ["chebyshev", "chebyshev1", "chebyshevi"]
    #    chebyshev_ii = ["chebyshev2", "chebyshevii", "chebyshev_2",
    #                    "chebyshev_ii", "inverse_chebyshev", "type2_chebyshev"]
    #    elliptic = ["elliptic", "cauer"]
    #    bessel = ["bessel"]
    

class CoefType(Enum):
    ba = "ba"
    sos = "ab"


if __name__ == "__main__":

    x = np.random.rand(1000, 10)
    # example filter specifications
    x_fs = 100.0
    filtspec = {
            "spec_format": "filter_spec_01",
            "filters_list": [
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
    
    x_filtered, params_list = apply_freq_filters(
            filtspec, x, data_fs=x_fs, axis=0)


    import matplotlib.pyplot as plt
    
    F = plt.figure()
    F.show()
    AH = []
    for i in range(x.shape[1]):
        ah = F.add_subplot(x.shape[1], 1, i+1)
        ah.plot(x[:, i], 'b')
        ah.plot(x_filtered[:, i], 'r')
        AH.append(ah)
        


    print(os.path.basename(__file__) + ": finished main")


"""
special variables
"""

__author__ = "Yasushi Terazono <Yasushi.Terazono@us.tdk.com>"
__version__ = "0.0.1"
__date__ = "Thu Mar 26 10:16:09 2020"

"""
Thu Mar 26 10:16:09 2020  Yasushi Terazono <teraz@jp.tdk.com>
                           <Yasushi.Terazono@us.tdk.com>
* created
"""


'''
def apply_freq_filters_old(
        filter_spec: dict,
        data: np.ndarray,
        data_fs: float = 1.0,
        axis: int = -1):
    
    # assumes check_filter_spec(filter_spec) == True
    
    filtered_data = data.copy()
    common_params = filter_spec["common_params"]
    params_list = []
    for flt in filter_spec["filter_list"]:
        params = {}
        # "definition_type": "design", "direct"=="coefficient", 
        definition_type = flt["definition_type"].lower()
        if definition_type in ["design"]:
            filtered_data, params = apply_filter_design(
                    design_params=flt["params"], data=filtered_data,
                    data_fs=data_fs, axis=axis, common_params=common_params)
        elif definition_type in ["direct", "coefficient"]:
            filtered_data, params = apply_filter_coefs(
                    direct_params=flt["params"], data=filtered_data,
                    data_fs=data_fs, axis=axis, common_params=common_params)
        else:
            # should not happen -- use check_filter_spec first
            raise
        params_list.append(params)
        
    return filtered_data, params_list


def apply_filter_design(
        design_params: dict,
        data: np.ndarray,
        data_fs: float = 1.0,
        axis: int = -1,
        common_params: dict = {}):

    # "fir_iir": "fir", "iir"
    fir_iir = design_params["fir_iir"].lower()
    if fir_iir == "iir":
        filtered_data, params = apply_iir_filter(
                iir_params=design_params, data=data,
                data_fs=data_fs, axis=axis, common_params=common_params)
    elif fir_iir == "fir":
        filtered_data, params = apply_fir_filter(
                fir_params=design_params, data=data,
                data_fs=data_fs, axis=axis, common_params=common_params)
    else:
        # should not happen -- use check_filter_spec first
        pass

    return filtered_data, params


def apply_filter_coefs(
        direct_params: dict,
        data: np.ndarray,
        data_fs: float = 1.0,
        axis: int = -1,
        common_params: dict = {}):

    raise
    
    return filtered_data, params


def apply_iir_filter(
        iir_params: dict,
        data: np.ndarray,
        data_fs: float = 1.0,
        axis: int = -1,
        common_params: dict = {}):
    
    design = iir_params["design"].lower()
    if design in ["butter", "butterworth"]:
        filtered_data, params = apply_butterworth_filter(
                response_type=iir_params["response_type"],
                butter_params=iir_params["params"], data=data,
                data_fs=data_fs, axis=axis, common_params=common_params)
    elif design in ["second_order_iir_notch", "iir_notch", "notch"]:
        filtered_data, params = apply_iirnotch_filter(
                iirnotch_params=iir_params["params"], data=data,
                data_fs=data_fs, axis=axis, common_params=common_params)
    else:
        # should not happen -- use check_filter_spec first
        pass

    return filtered_data, params


def apply_fir_filter(
        filter_params: dict,
        data: np.ndarray,
        data_fs: float = 1.0,
        axis: int = -1,
        common_params: dict = {}):
    
    raise
    
    return filtered_data


def apply_butterworth_filter(
        response_type: str,
        butter_params: dict,
        data: np.ndarray,
        data_fs: float = 1.0,
        axis: int = -1,
        common_params: dict = {}):
    
    nyq = data_fs / 2.0
    try:
        cutoff = butter_params["cutoff"]/nyq
    except Exception as e:
        cutoff = [a/nyq for a in butter_params["cutoff"]]

    rtype = response_type.lower()
    btype_dict = {"bandpass": ["bandpass", "bp"],
                  "lowpass": ["lowpass", "lp", "highcut", "hc"],
                  "highpass": ["highpass", "hp", "lowcut", "lc"],
                  "bandstop": ["bandstop", "bs"],}

    # if response_type.lower() not in btype_dict.values(): raise
    btype = [k for k, v in btype_dict.items() if rtype in v][0]
    
    sos = sig.butter(butter_params["order"], cutoff, btype=btype, output='sos')

    if "bidirectional" in common_params:
        bidir = bool(common_params["bidirectional"])
    else:
        bidir = True

    if bidir:
        filtered_data = sig.sosfiltfilt(sos, data, axis=axis)
    else:
        filtered_data = sig.sosfilt(sos, data, axis=axis)

    params = {}
    params["btype"] = btype
    params["nyquist_freq"] = nyq
    params["normalized_cutoff"] = cutoff
    params["sos"] = sos
    params["axis"] = axis
    params["bidirectional"] = bidir

    return filtered_data, params


def apply_iirnotch_filter(
        iirnotch_params: dict,
        data: np.ndarray,
        data_fs: float = 1.0,
        axis: int = -1,
        common_params: dict = {}):

    nyq = data_fs / 2.0
    f = iirnotch_params["f"]/nyq
    Q = iirnotch_params["Q"]

    b, a = sig.iirnotch(f, Q)

    bidir = True if ("bidirectional" not in common_params
                     ) else bool(common_params["bidirectional"])

    if bidir:
        filtered_data = sig.filtfilt(b, a, data, axis=axis)
    else:
        filtered_data = sig.lfilter(b, a, data, axis=axis)

    params = {}
    params["btype"] = "notch"
    params["nyquist_freq"] = nyq
    params["f"] = f
    params["Q"] = Q
    params["b"] = b
    params["a"] = a
    params["axis"] = axis
    params["bidirectional"] = bidir

    return filtered_data, params
'''
