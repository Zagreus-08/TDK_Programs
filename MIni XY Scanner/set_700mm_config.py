#!/usr/bin/env python3
"""
Manual configuration script to set 700x700mm area
Use this ONLY if you have physically upgraded your system to 700x700mm
but the calibration is not detecting it correctly.

This will create/update scan_config.json with 700x700mm values.
"""

import json
import os

# Get script directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "scan_config.json")

# Configuration for 700x700mm system
config = {
    "area_x_mm": 700.0,
    "area_y_mm": 700.0,
    "row_step_mm": 33.0,  # Example: 700mm / 21 rows = 33mm per row
    "x_speed_rpm": 60,
    "y_speed_rpm": 60,
    "x_count": None,  # Optional
    "y_count": 21     # Example: 21 rows for 700mm system
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
    print(f"\nUsable scan area: 680x680mm (with 20mm margin)")
    print(f"\nNOTE: This assumes your physical hardware can actually move 700mm!")
    print(f"      If your limit switches are at 200mm, you need to move them first.")
except Exception as e:
    print(f"✗ Error saving configuration: {e}")
