# Square Display Update - Ver2.5 Plotter

## Summary
Updated the plotter program to receive scan area metadata from the scanner and automatically adjust the display to always show a square plot based on the maximum dimension.

## Key Changes

### 1. New Global Variables
- `scan_area_x`: Actual scan area X dimension from scanner metadata (mm)
- `scan_area_y`: Actual scan area Y dimension from scanner metadata (mm)
- `display_range`: Square display range calculated from max(scan_area_x, scan_area_y), rounded down to nearest 10mm

### 2. Metadata Reception (Serial Protocol)
The plotter now receives metadata from the scanner before scan data:
```
Format: META,area_x,area_y,x_count,y_count
Example: META,292.00,297.00,50,50
```

When metadata is received:
- Extracts `scan_area_x` and `scan_area_y`
- Calculates `display_range = int(max(scan_area_x, scan_area_y) // 10) * 10`
- Sets both `x_range` and `y_max` to `display_range` for square display
- Example: If X=292mm and Y=297mm, display_range becomes 290x290mm

### 3. Square Display Logic
**Always maintains square aspect ratio:**
- Display coordinates: Always 0-100 (normalized)
- Axis labels: Show actual mm values based on `display_range`
- Both X and Y axes use the same `display_range` value
- Aspect ratio is forced to 'equal' on 2D plots

### 4. End-of-Scan Detection
Updated to use metadata-based detection:
- Checks if current position is within 5mm of `scan_area_x` and `scan_area_y`
- More reliable than previous auto-detection method
- Only triggers after metadata is received

### 5. Updated Functions

#### `read_loop()`
- Added metadata parsing for "META" messages
- Removed auto-detection of X/Y maximums from data points
- Uses fixed `display_range` from metadata

#### `initialize_blank_plot()`
- Uses `display_range` instead of separate `x_range` and `y_max`
- Ensures square display from startup

#### `update()` (Animation)
- Filters data based on `display_range` for both X and Y
- Uses `display_range` for axis scaling and labels
- Maintains square display throughout scan

#### `show_loaded()` (Load CSV)
- Calculates `display_range` from loaded data
- Applies same square display logic as live scans
- Rounds down to nearest 10mm for consistency

#### `resume_live()`
- Resets `display_range` to default (100mm)
- Clears all cached data

## Example Workflow

1. **Scanner sends metadata:**
   ```
   META,292.00,297.00,50,50
   ```

2. **Plotter calculates display:**
   ```
   max_dim = max(292, 297) = 297
   display_range = int(297 // 10) * 10 = 290mm
   ```

3. **Display shows:**
   - Square plot: 290mm × 290mm
   - X-axis: 0 to 290mm (labels)
   - Y-axis: 0 to 290mm (labels)
   - Actual data: 292mm × 297mm (some data extends beyond display)

4. **Coordinate system:**
   - (0,0) = Top-right corner (scanner home position)
   - X increases LEFT (0 → 290mm)
   - Y increases DOWN (0 → 290mm)
   - Display inverts both axes for intuitive viewing

## Benefits

✅ **Always square display** - No distortion regardless of scan area
✅ **Automatic adjustment** - No manual configuration needed
✅ **Consistent scaling** - Both axes use same scale
✅ **Clean rounding** - Display range rounded to nearest 10mm
✅ **Metadata-driven** - Reliable end-of-scan detection
✅ **Works with loaded data** - Same logic applies to CSV files

## Testing

Test with various scan areas:
- 100×100mm → Display: 100×100mm
- 200×150mm → Display: 200×200mm
- 292×297mm → Display: 290×290mm
- 300×250mm → Display: 300×300mm

All should display as perfect squares with appropriate axis labels.
