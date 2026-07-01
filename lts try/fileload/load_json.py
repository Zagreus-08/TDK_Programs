# -*- coding: utf-8 -*-
"""
Created on Fri Feb 21 12:30:49 2020

@author: a627534
"""

"""Load auxiliary file(.json)
"""


import json
import os
import math
import glob


def load_json(filename):
    """Load auxiliary information data

    Args:
        filename(str): filename of recorded data

    Returns:
        info(dict): auxiliary information
    """

    # make filename
    file_dir = os.path.dirname(filename)
    file_base = os.path.basename(filename).rsplit('.', 3)[0]
    filename_info = file_dir + '/' + file_base + '.supp_beta.utf-8.json'
    device_name = filename.rsplit('.')[-3]

    # read file
    print('information file: ' + filename_info)
    with open(filename_info, 'r', encoding="utf-8") as f:
        info0 = json.load(f)

    # detect device name
    n = 0
    while n < info0['numDAQmxAIChannelGroup']:
        if device_name == info0['daqmxAIChannelGroup'][n]['name']:
            break
        n = n + 1

    info = {}
    info['filename'] = info0['recFile']
    info['number_of_files'] = info0['numDAQmxAIChannelGroup']
    info['sampling_rate'] = info0['daqmxAIChannelGroup'][n]['samplingRate']
    names_dev = []
    num_ch = []
    names_ch = []
    for i in range(info['number_of_files']):
        names_dev.append(info0['daqmxAIChannelGroup'][i]['name'])
        num_ch.append(info0['daqmxAIChannelGroup'][i]['numChannels'])
        names_ch.extend(info0['daqmxAIChannelGroup'][i]['chNames'])
    info['names_device'] = names_dev
    info['number_of_channels'] = sum(num_ch)
    info['channels_per_device'] = num_ch
    info['channel_names'] = names_ch
    info['filesize'] = os.path.getsize(filename)
    info['samples_per_channel'] = math.floor(info['filesize'] / (info['channels_per_device'][n] * 8))
    info['measurement_time'] = info['samples_per_channel'] / info['sampling_rate']

    return info


if __name__ == '__main__':

    import tkinter
    import tkinter.filedialog

    # file dialog
    tk = tkinter.Tk()
    tk.withdraw()

    filename_data = tkinter.filedialog.askopenfilename()

    tk.destroy()

    info = load_json(filename_data)
