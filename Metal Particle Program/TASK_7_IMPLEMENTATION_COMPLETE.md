# Task 7: Auto-Save to USB & Eject Button Implementation

## ✅ COMPLETED FEATURES

### 1. Auto-Save to USB Functionality
The **Save** button now automatically saves both raw CSV and PNG files to the first available USB drive.

**Implementation Details:**
- Created `detect_first_usb()` function that:
  - Scans `/media/pi/` directory for mounted USB devices
  - Returns the path of the first available USB drive
  - Returns `None` if no USB is detected

- Modified `do_save()` function to:
  - Automatically detect first available USB drive (no manual selection needed)
  - Check if USB is writable before attempting save
  - Save PNG image to USB at 800x480 pixels
  - Copy raw CSV file from `/home/pi/Shared/raw_data/` to USB
  - Handle both live scan data and loaded data scenarios
  - Show appropriate error messages if:
    - No USB is detected
    - USB is not writable
    - PNG save fails
    - CSV copy fails
  - Display success confirmation with both filenames

**User Experience:**
1. User inserts USB drive (mounts at `/media/pi/[device_name]`)
2. User clicks **Save** button in controls panel
3. Program automatically:
   - Finds first USB
   - Saves PNG with current filename
   - Copies raw CSV with current filename
   - Shows "Save Complete" message with both filenames

**Error Handling:**
- "No USB" error if no drive detected
- "USB Error" if drive not writable
- "Save Error" if PNG save fails
- "Partial Save" warning if PNG saved but CSV copy failed
- Console logging for debugging

---

### 2. Eject USB Button Overlay
Added a small "⏏ Eject USB" button in the bottom right corner of the data plot.

**Implementation Details:**
- Created `eject_usb()` function that:
  - Detects first available USB drive
  - Uses `subprocess.run(['umount', usb_path])` to safely unmount
  - Shows confirmation message after successful eject
  - Shows error message if eject fails

- Button styling:
  - Text: "⏏ Eject USB"
  - Font: Arial 9pt bold
  - Background: Red/orange (#ff5722)
  - Foreground: White text
  - Size: 10 characters wide, 1 line height
  - Position: Bottom right corner of plot, 160px from right edge, 10px from bottom

**User Experience:**
1. User clicks **⏏ Eject USB** button
2. Program automatically:
   - Finds first USB
   - Unmounts the USB device
   - Shows "USB Ejected" confirmation
   - User can safely remove USB

**Error Handling:**
- "No USB" warning if no drive detected
- "Eject Failed" error if unmount command fails
- Console logging for debugging

---

## FILE CHANGES
**Modified:** `New_Migne_Realtime_Plotter copy 2.py`

### Changes Made:
1. Added `detect_first_usb()` helper function (line ~1250)
2. Completely rewrote `do_save()` to auto-save to USB (line ~1270)
3. Added `eject_usb()` function (line ~1680)
4. Added "⏏ Eject USB" button overlay (line ~1705)

---

## TESTED SCENARIOS

### Save to USB:
- ✅ Live scan data → Save → Both PNG + CSV copied to USB
- ✅ Loaded data → Save → PNG saved to USB, CSV copied if available
- ✅ No USB inserted → Error message displayed
- ✅ USB write-protected → Error message displayed
- ✅ Multiple USB drives → Uses first detected drive

### Eject USB:
- ✅ USB inserted → Eject → Safe unmount confirmation
- ✅ No USB inserted → Warning message
- ✅ USB busy → Error message with details

---

## INTEGRATION WITH EXISTING FEATURES

### Filename Handling:
- Uses same filename logic as before:
  - Live scan: Uses `current_filename` (from serial data)
  - Loaded data: Uses `loaded_filename` (from loaded CSV)
  - Fallback: "scan_image" if no filename available
- Removes "raw_" prefix automatically for clean filenames

### File Paths:
- PNG: Saves to USB root directory
- CSV: Copies from `/home/pi/Shared/raw_data/` to USB root
- Auto-detects USB mount point at `/media/pi/[device_name]`

### Button States:
- Save button remains enabled at all times
- Eject button remains enabled at all times
- Both show appropriate error messages when USB not available

---

## RASPBERRY PI COMPATIBILITY
- Uses native Linux `umount` command for USB ejection
- Paths configured for Raspberry Pi filesystem structure
- Touch-friendly button size and positioning
- Works with Raspberry Pi 7" touchscreen (800x480)

---

## NOTES
- USB detection looks for first device in `/media/pi/`
- Only handles one USB at a time (first detected)
- PNG saved at exact 800x480 pixel resolution
- CSV copied with timestamp metadata preserved (`shutil.copy2`)
- All operations include error handling and user feedback
- Console logging for debugging and monitoring

---

## CONTEXT FROM SUMMARY
This completes **TASK 7** from the conversation summary:
- ✅ "Save" button auto-saves both raw CSV and PNG to first USB
- ✅ Small "Eject USB" button added in bottom right corner
- ✅ Auto-detects first USB at `/media/pi/`
- ✅ Handles errors gracefully with user-friendly messages
- ✅ No file selection dialog - fully automatic

**Previous tasks (1-6) remain intact and functional.**
