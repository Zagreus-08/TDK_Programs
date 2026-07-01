# -*- coding: utf-8 -*-
"""
Created on Sun May 24 21:40:31 2020

@author: a627534
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import load_data
import load_bin
import load_json
import load_sensor
import combine_files


if __name__ == "__main__":

    print('imported fileload')
