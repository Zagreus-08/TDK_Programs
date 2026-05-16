# Plotter Display Fixes - V4_Nivio-S_Realtime_Plotter copy 2.py

## Issues Fixed

### Issue 1: Display Always Shows 920x920mm
**Problem:** The display was hardcoded to always show 920x920mm regardless of actual scan area.

**Root Cause:** 
- The code was forcing `x_range = y_max = 920` at multiple points
- Axis labels were hardcoded to show 920mm range
- End-of-scan detection was looking for (920, 920) coordinates

**Fix Applied:**
1. **Dynamic Range Detection:** Now uses `scan_area_x` and `scan_area_y` from metadata to set display range
2. **Flexible Axis Labels:** Axis labels now use actual `x_range` and `y_max` values instead of hardcoded 920
3. **Smart End-of-Scan Detection:** Detects scan completion based on actual scan dimensions with 5mm tolerance

**Code Changes:**
```python
# Before (hardcoded):
frozen_x_range = 920
frozen_y_max = 920
label_x_range = 920
label_y_max = 920

# After (dynamic):
frozen_x_range = x_range  # Uses actual scan area
frozen_y_max = y_max      # Uses actual scan area
label_x_range = frozen_x_range if frozen_x_range is not None else x_range
label_y_max = frozen_y_max if frozen_y_max is not None else y_max
```

---

### Issue 2: Color Range Changes During Scan (Early Plots Change Color)
**Problem:** As the scan progresses and new data with higher/lower values arrives, the color scale (zmin/zmax) expands. This causes previously plotted data to change colors - for example, a point that was red (high value) at the start becomes blue (mid-range) when the scale expands.

**Root Cause:**
```python
# Old code - continuously expands range
if not z_range_locked:
    if local_max > zmax:
        zmax = local_max  # Expands max
    if local_min < zmin:
        zmin = local_min  # Expands min
```

This meant:
- First data point: zmin=-0.1, zmax=0.1 → red = 0.1
- Later data point with z=0.5 arrives → zmax expands to 0.5 → red = 0.5, old 0.1 becomes blue

**Fix Applied:**
The color range is now **locked after the first data update** to prevent color shifts:

```python
# New code - locks range after first update
if not z_range_locked:
    # Only set range on FIRST update (when still at defaults)
    if zmin == -0.1 and zmax == 0.1:
        # First data - set range based on actual data
        zmax = max(local_max, 0.1)
        zmin = min(local_min, -0.1)
        print(f"[INFO] Color range initialized: zmin={zmin:.6f}, zmax={zmax:.6f}")
    # After first update, DON'T expand - keep colors consistent
```

**Behavior:**
- ✅ First data establishes the color range
- ✅ All subsequent data uses the same color scale
- ✅ Early plots keep their original colors throughout the scan
- ✅ User can still manually lock/adjust range using the Z-lock feature

---

## Testing Recommendations

1. **Test with Different Scan Sizes:**
   - Small scan (e.g., 100x100mm) - should display correctly, not stretched to 920x920
   - Medium scan (e.g., 500x500mm) - should show proper dimensions
   - Large scan (920x920mm) - should work as before

2. **Test Color Consistency:**
   - Start a scan and note the color of the first few data points
   - Let the scan complete
   - Verify that the early data points maintain their original colors
   - Check that the color bar range doesn't change during the scan

3. **Test Metadata Reception:**
   - Verify that the scanner sends META message before (0,0)
   - Check console output for: `[INFO] Received scan metadata: XXXxYYYmm`
   - Confirm display uses these dimensions

---

## Benefits

1. **Accurate Display:** Shows actual scan area dimensions, not always 920x920
2. **Consistent Colors:** Data points maintain their colors throughout the scan
3. **Better Data Interpretation:** Users can clearly see anomalies without color shifts
4. **Flexible Scanning:** Supports any scan size from 50x50 to 920x920mm

---

## Backward Compatibility

- ✅ Works with old scans that don't send metadata (falls back to dynamic growth)
- ✅ Z-lock feature still works as before
- ✅ Load Raw Data feature unaffected
- ✅ All existing features preserved
