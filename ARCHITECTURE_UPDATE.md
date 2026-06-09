# Architecture Update: Separated DAQ Reading

## Date: 2025-01-XX

## Overview
Updated the Mini XY Scanner and Nivio-S Realtime Plotter to use a separated architecture where each Raspberry Pi has its own MCC 128 DAQ HAT for sensor reading.

## New Architecture

### V10_Mini_XY_Scanner.py (Scanner Raspberry Pi)
**Role:** Motion control and position tracking only

**Changes:**
- Removed all DAQ/sensor reading functionality
- Now only sends X,Y position coordinates via serial
- Serial format changed from `x,y,z,phase,z2` to `x,y`
- Simplified send_serial_data() function to only handle X,Y
- Removed read_sensor_value() function entirely

**Serial Output Format:**
```
x,y
```
Example: `125.50,87.32`

### V1_Nivio_S_Realtime_Plotter.py (Plotter Raspberry Pi)
**Role:** Data visualization and recording with local sensor reading

**Changes:**
- Added MCC 128 DAQ HAT support for local Z and Z2 sensor reading
- New function: read_local_sensors() - reads from local MCC 128 channels 0 and 1
- Modified serial reading loop to:
  1. Receive X,Y from scanner via serial
  2. Read Z,Z2 from local MCC 128 DAQ HAT
  3. Combine all data for plotting and saving
- CSV format remains: x, y, z, z2 (4 columns)

**Serial Input Format:**
```
x,y
```

**Data Flow:**
1. Receive X,Y from serial
2. Call read_local_sensors() to get Z,Z2
3. Combine: (x, y, z, z2)
4. Plot and save to CSV

## Hardware Configuration

### Scanner Raspberry Pi
- Controls stepper motors (X,Y movement)
- USB-to-TTL serial adapter (sends X,Y to plotter)
- NO DAQ HAT needed

### Plotter Raspberry Pi  
- MCC 128 DAQ HAT installed
- Connected to sensor coils (channels 0 and 1)
- USB-to-TTL serial adapter (receives X,Y from scanner)
- Displays real-time plots
- Saves CSV data files

## Benefits

1. **Cleaner separation of concerns**
   - Scanner: Pure motion control
   - Plotter: Pure data acquisition and visualization

2. **Better synchronization**
   - Sensor readings happen exactly when plotter receives position
   - No timing delays from serial transmission of large data

3. **Reduced serial bandwidth**
   - Only sending 2 values instead of 5 (60% reduction)
   - Faster transmission, lower latency

4. **Simpler scanner code**
   - No DAQ management complexity
   - Easier to debug motion control

5. **More reliable data collection**
   - Direct sensor reading by plotter
   - No data loss from serial buffer overflow

## Testing Checklist

- [ ] Scanner sends X,Y correctly via serial
- [ ] Plotter receives X,Y correctly from serial
- [ ] Plotter reads Z,Z2 from local MCC 128 DAQ HAT
- [ ] CSV files save complete data: x, y, z, z2
- [ ] Real-time plotting works correctly
- [ ] Display coordinates match scanner position
- [ ] Z and Z2 sensor readings are correct

## Migration Notes

**From Old System:**
- Old format: Scanner sent x,y,z,phase,z2 via serial
- New format: Scanner sends only x,y via serial

**CSV Format:**
- **Unchanged**: x, y, z, z2 (4 columns)
- Backward compatible with existing raw data files

## Code Locations

### Modified Files:
1. `V10_Mini_XY_Scanner.py` - Scanner control program
2. `V1_Nivio_S_Realtime_Plotter.py` - Plotter display program

### Key Functions:

**V10_Mini_XY_Scanner.py:**
```python
def send_serial_data(x_mm, y_mm):
    # Sends only X,Y position
```

**V1_Nivio_S_Realtime_Plotter.py:**
```python
def read_local_sensors():
    # Reads Z,Z2 from local MCC 128 DAQ HAT
    # Returns (z_voltage, z2_voltage)

def read_loop():
    # Receives X,Y from serial
    # Calls read_local_sensors() for Z,Z2
    # Combines all data for plotting/saving
```

## Troubleshooting

**If scanner doesn't send data:**
- Check USB-to-TTL connection
- Verify serial port in code (COM7, /dev/ttyUSB0, etc.)
- Check baud rate (115200)

**If plotter shows zero Z values:**
- Check MCC 128 DAQ HAT connection
- Verify sensor wiring to channels 0 and 1
- Run `daqhats_list_boards` to verify HAT detection

**If CSV data looks wrong:**
- Verify plotter is reading sensors when receiving X,Y
- Check timing in read_loop() function
- Monitor console output for sensor read errors

## Version History

- **V10_Mini_XY_Scanner.py**: Motion control with X,Y serial output
- **V1_Nivio_S_Realtime_Plotter.py**: Display with local MCC 128 DAQ reading
