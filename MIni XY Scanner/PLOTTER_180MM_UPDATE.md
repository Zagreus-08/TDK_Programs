# Plotter Display Update: 180x180mm Configuration

## Date: 2026-05-12

## Summary
Updated the plotter display from 920x920mm to 180x180mm and fixed window minimization issue.

---

## Changes Made to `V4_Nivio-S_Realtime_Plotter copy.py`

### 1. Display Range Changes (920mm → 180mm)

#### Global Variables (Lines 95-97)
```python
# BEFORE:
x_range = 100  # Default X-axis range (will grow to 920 max)
y_max = 100    # Default Y-axis maximum (will grow to 920 max)

# AFTER:
x_range = 100  # Default X-axis range (will grow to 180 max)
y_max = 100    # Default Y-axis maximum (will grow to 180 max)
```

#### Serial Data Processing (Lines 457-479)
```python
# BEFORE:
# Let X and Y grow but enforce 920x920 maximum square limit
if x0 > 0 and x0 <= 920:
    x_range = min(x0, 920)
if y0 > 0 and y0 <= 920:
    y_max = min(y0, 920)
max_range = min(max(x_range, y_max), 920)

# At 90% through scan, freeze at 920x920
frozen_x_range = 920
frozen_y_max = 920
x_range = 920
y_max = 920

# AFTER:
# Let X and Y grow but enforce 180x180 maximum square limit
if x0 > 0 and x0 <= 180:
    x_range = min(x0, 180)
if y0 > 0 and y0 <= 180:
    y_max = min(y0, 180)
max_range = min(max(x_range, y_max), 180)

# At 90% through scan, freeze at 180x180
frozen_x_range = 180
frozen_y_max = 180
x_range = 180
y_max = 180
```

#### End of Scan Detection (Lines 529-542)
```python
# BEFORE:
# Detect end of scan: hardware sends matching max values (920,920 for 920x920 scan)
# FREEZE the display range at 920x920 to prevent expansion
frozen_x_range = 920
frozen_y_max = 920
x_range = 920
y_max = 920

# AFTER:
# Detect end of scan: hardware sends matching max values (180,180 for 180x180 scan)
# FREEZE the display range at 180x180 to prevent expansion
frozen_x_range = 180
frozen_y_max = 180
x_range = 180
y_max = 180
```

#### Update Function (Lines 750-780)
```python
# BEFORE:
if len(xs) > 5000:
    step = max(1, len(xs) // 4000)  # Keep ~4000 points max for 920x920 data

# Scan has completed - use frozen 920x920 values
display_x_range = 920
display_y_max = 920

# Scan is active - use current ranges and keep them synced (max 920)
max_range = min(max(x_range, y_max), 920)

# AFTER:
if len(xs) > 3000:
    step = max(1, len(xs) // 2500)  # Keep ~2500 points max for 180x180 data

# Scan has completed - use frozen 180x180 values
display_x_range = 180
display_y_max = 180

# Scan is active - use current ranges and keep them synced (max 180)
max_range = min(max(x_range, y_max), 180)
```

#### Grid Resolution (Lines 792-798)
```python
# BEFORE:
# Limit grid resolution to max 200x200 for 920x920 live data (lower resolution for performance)

# AFTER:
# Limit grid resolution to max 200x200 for 180x180 live data (lower resolution for performance)
```

#### Load Raw Data Function (Lines 1220-1248)
```python
# BEFORE:
# Auto-detect X and Y axis maximums from loaded data (cap at 920)
detected_x_max = min(detected_x_max, 920)
detected_y_max = min(detected_y_max, 920)

# Force square at 920x920
x_range = 920
y_max = 920

# Filter and scale data based on 920x920 range
mask = (xs <= 920) & (ys <= 920)

# Scale X and Y coordinates to fit in 0-100 display range (920x920 → 100x100)
xs = 100 - (xs * 100 / 920)
ys = 100 - (ys * 100 / 920)

# AFTER:
# Auto-detect X and Y axis maximums from loaded data (cap at 180)
detected_x_max = min(detected_x_max, 180)
detected_y_max = min(detected_y_max, 180)

# Force square at 180x180
x_range = 180
y_max = 180

# Filter and scale data based on 180x180 range
mask = (xs <= 180) & (ys <= 180)

# Scale X and Y coordinates to fit in 0-100 display range (180x180 → 100x100)
xs = 100 - (xs * 100 / 180)
ys = 100 - (ys * 100 / 180)
```

#### Loaded Data Grid Resolution (Lines 1280-1286)
```python
# BEFORE:
# Limit grid resolution to max 250x250 for loaded 920x920 data (higher quality for static viewing)

# AFTER:
# Limit grid resolution to max 200x200 for loaded 180x180 data (higher quality for static viewing)
```

---

### 2. Window Minimization Fix (Lines 1414-1420)

#### Window State Change
```python
# BEFORE:
root.attributes("-fullscreen", True)

# AFTER:
# Set window to maximized state instead of fullscreen to prevent minimization
root.state('zoomed')  # Windows maximized
# Also try alternate method for cross-platform compatibility
try:
    root.attributes('-zoomed', True)  # Linux maximized
except:
    pass
```

**Reason for Change:**
- Fullscreen mode (`-fullscreen`) can cause the window to minimize unexpectedly
- Maximized mode (`zoomed`) keeps the window in a normal maximized state
- Window stays visible and accessible without minimization issues
- Users can still use Alt+Tab and taskbar normally

---

## Testing Checklist

### Display Range Testing
- [ ] Live scan displays data correctly within 180x180mm range
- [ ] Axis labels show 0-180mm on both X and Y axes
- [ ] Display maintains square aspect ratio (180x180)
- [ ] Data beyond 180mm is filtered out correctly
- [ ] Frozen display locks at 180x180mm after scan completes

### Window Behavior Testing
- [ ] Window opens in maximized state (not fullscreen)
- [ ] Window does not minimize during operation
- [ ] Alt+Tab works normally
- [ ] Taskbar remains accessible
- [ ] Escape key returns window to normal size

### Data Loading Testing
- [ ] Loading CSV files with 180x180mm data displays correctly
- [ ] Loaded data is scaled properly to fit 180x180mm display
- [ ] Grid resolution is appropriate for 180x180mm data
- [ ] Performance is acceptable with 180x180mm datasets

---

## Performance Optimizations

### Data Point Reduction
- **Live scan:** Reduced from 5000 to 3000 points threshold
- **Live scan:** Keep ~2500 points max (was 4000)
- **Loaded data:** Max 200x200 grid resolution (was 250x250)

### Grid Resolution
- **Live data:** 200x200 grid maximum
- **Loaded data:** 200x200 grid maximum
- Maintains good visual quality while improving performance

---

## Coordinate System (Unchanged)

The coordinate system remains the same:
- **Scanner hardware:** (0,0) at TOP-RIGHT corner
  - X increases LEFT
  - Y increases DOWN
- **Display:** (0,0) shown at TOP-LEFT corner
  - X-axis inverted: right becomes left
  - Y-axis inverted: bottom becomes top

---

## Files Modified

1. `V4_Nivio-S_Realtime_Plotter copy.py` - Main plotter program

---

## Notes

- All 920mm references have been changed to 180mm
- Display always shows 180x180mm square area
- Data filtering ensures only data within 180x180mm is displayed
- Window maximization fix prevents minimization issues
- Performance optimizations adjusted for smaller 180x180mm dataset

---

## Related Documentation

- See `UPGRADE_TO_700x700.md` for scanner hardware upgrade details
- See `PLOTTER_FIXES.md` for previous plotter fixes
