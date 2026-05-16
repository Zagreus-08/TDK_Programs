#!/usr/bin/env python3
"""
Fix configuration to match actual 190x190mm hardware
This resets the area calibration to match the physical limit switches at ~190mm
"""

import json
import os

# Get script directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "scan_config.json")

# Configuration for ACTUAL 190x190mm hardware
config = {
    "area_x_mm": 190.0,  # Actual physical X range (based on limit switch at 182mm)
    "area_y_mm": 190.0,  # Actual physical Y range
    "row_step_mm": 9.0,  # Example: 190mm / 21 rows = 9mm per row
    "x_speed_rpm": 60,
    "y_speed_rpm": 60,
    "x_count": None,  # Optional
    "y_count": 21     # 21 rows for scanning
}

# Save configuration
try:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    print(f"✓ Configuration saved to: {CONFIG_FILE}")
    print(f"\nConfiguration:")
    print(f"  Area X: {config['area_x_mm']} mm")
    print(f"  Area Y: {config['area_y_mm']} mm")
    print(f"  Row Step: {config['row_step_mm']} mm")
    print(f"  Y Scan Count: {config['y_count']}")
    print(f"\nUsable scan area: 180x180mm (with 10mm margin)")
    print(f"\nThis matches your actual hardware with limit switches at ~182mm")
    print(f"\nNEXT STEPS:")
    print(f"1. Restart the scanner program (V1_Compact_XY.py)")
    print(f"2. The scanner will now use the correct 190mm range")
    print(f"3. Run a test scan to verify it completes without hitting limits")
except Exception as e:
    print(f"✗ Error saving configuration: {e}")
