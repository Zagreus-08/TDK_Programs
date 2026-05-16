#!/usr/bin/env python3
"""
Diagnostic script to check current configuration and system status
"""

import json
import os

# Get script directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "scan_config.json")

print("=" * 60)
print("MINI XY SCANNER - CONFIGURATION CHECK")
print("=" * 60)

# Check if config file exists
if os.path.exists(CONFIG_FILE):
    print(f"\n✓ Config file found: {CONFIG_FILE}")
    
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        print("\nCurrent Configuration:")
        print("-" * 60)
        
        # Area calibration
        area_x = config.get('area_x_mm', 'NOT SET')
        area_y = config.get('area_y_mm', 'NOT SET')
        print(f"  Area X: {area_x} mm")
        print(f"  Area Y: {area_y} mm")
        
        # Calculate usable area (with 20mm margin for 700mm system)
        if isinstance(area_x, (int, float)) and isinstance(area_y, (int, float)):
            usable_x = area_x - 20.0
            usable_y = area_y - 20.0
            print(f"  Usable Area: {usable_x:.0f}x{usable_y:.0f} mm (with 20mm margin)")
        
        # Scan parameters
        row_step = config.get('row_step_mm', 'NOT SET')
        x_speed = config.get('x_speed_rpm', 'NOT SET')
        y_speed = config.get('y_speed_rpm', 'NOT SET')
        x_count = config.get('x_count', 'NOT SET')
        y_count = config.get('y_count', 'NOT SET')
        
        print(f"\n  Row Step: {row_step} mm")
        print(f"  X Speed: {x_speed} RPM")
        print(f"  Y Speed: {y_speed} RPM")
        print(f"  X Scan Count: {x_count}")
        print(f"  Y Scan Count: {y_count}")
        
        # System detection
        print("\n" + "=" * 60)
        print("SYSTEM DETECTION:")
        print("=" * 60)
        
        if isinstance(area_x, (int, float)):
            if area_x >= 650:
                print("  ✓ Detected: 700x700mm system (680mm usable)")
                print("  Status: CORRECT for upgraded system")
            elif 250 <= area_x <= 350:
                print("  ✓ Detected: 300x300mm system (280mm usable)")
                print("  Status: OLD system - needs upgrade if you have 700mm hardware")
            elif 180 <= area_x <= 220:
                print("  ⚠ Detected: 200x200mm system")
                print("  Status: SMALL system - check if this is correct")
            else:
                print(f"  ? Detected: {area_x}mm system")
                print("  Status: UNKNOWN - verify your hardware")
        
        print("\n" + "=" * 60)
        print("RECOMMENDATIONS:")
        print("=" * 60)
        
        if isinstance(area_x, (int, float)) and area_x < 650:
            print("  1. If you have 700mm hardware:")
            print("     - Check that limit switches are positioned at 700mm")
            print("     - Re-run 'Calibrate Area' button in the GUI")
            print("     - OR run: python set_700mm_config.py (manual override)")
            print("\n  2. If you have 200-300mm hardware:")
            print("     - Your system is correctly configured")
            print("     - No changes needed")
        else:
            print("  ✓ System appears to be correctly configured for 700mm")
        
    except Exception as e:
        print(f"\n✗ Error reading config file: {e}")
else:
    print(f"\n✗ Config file not found: {CONFIG_FILE}")
    print("\nThis means:")
    print("  - No calibration has been run yet")
    print("  - No scans have been performed yet")
    print("\nNext steps:")
    print("  1. Run the GUI: python V1_Compact_XY.py")
    print("  2. Press HOME button")
    print("  3. Press 'Calibrate Area' button")
    print("  4. System will measure your actual hardware dimensions")

print("\n" + "=" * 60)
