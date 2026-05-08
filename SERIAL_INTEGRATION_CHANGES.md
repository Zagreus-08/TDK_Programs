# Serial Integration Changes Summary

## Overview
Modified the Mini XY Scanner to send real-time scan data to the Migne Realtime Plotter via USB-to-TTL serial connection.

## Files Modified

### 1. `MIni XY Scanner/V2_Mini_XY_Scanner.py`

#### New Imports Added
```python
import serial
import serial.tools.list_ports
from datetime import datetime
```

#### New Global Variable
```python
ser_output = None  # Serial connection for data transmission
```

#### New Functions Added

**Serial Connection Management:**
```python
def init_serial_connection(port=None, baudrate=115200)
def send_serial_data(x, y, z)
def send_scan_start_marker(filename="")
def send_scan_end_marker(x_max, y_max)
```

**Purpose:**
- `init_serial_connection()`: Auto-detects or connects to specified serial port
- `send_serial_data()`: Sends X,Y,Z coordinates during scanning
- `send_scan_start_marker()`: Sends "0,0,0,FILENAME" at scan start
- `send_scan_end_marker()`: Sends "X_MAX,Y_MAX,0" at scan end

#### Modified Classes

**SimpleScanClass:**

1. **New Method: `scan_x_to_position_mm_with_data()`**
   - Similar to `scan_x_to_position_mm()` but sends data during movement
   - Sends X,Y,Z coordinates every 50ms while scanning
   - Converts positions to absolute coordinates (0-based from home)
   - Currently sends Z=0.0 as placeholder (ready for sensor integration)

2. **Modified Method: `simple_scan()`**
   - Generates timestamp-based filename: `scan_YYYYMMDD_HHMMSS`
   - Sends scan start marker before scanning
   - Calls `scan_x_to_position_mm_with_data()` instead of `scan_x_to_position_mm()`
   - Tracks current Y position for data transmission
   - Sends scan end marker after completion

**GUIClass:**

1. **New GUI Elements:**
   ```python
   self.serial_label      # "Serial Port:" label
   self.serial_entry      # Port entry field (default: "AUTO")
   self.serial_status     # Connection status indicator
   ```

2. **New Method: `init_serial_output()`**
   - Called during GUI initialization
   - Reads port from entry field
   - Initializes serial connection
   - Updates status indicator (green=connected, yellow=not connected)

3. **Modified Method: `gui_exit()`**
   - Added serial connection cleanup
   - Closes `ser_output` before exit

## Data Protocol Specification

### Message Format
```
X,Y,Z\n
```
- **X**: X-axis position in mm (float, 3 decimal places)
- **Y**: Y-axis position in mm (float, 3 decimal places)
- **Z**: Sensor value (float, 6 decimal places)
- **\n**: Newline terminator (ASCII 10)

### Special Markers

**Scan Start:**
```
0,0,0,FILENAME\n
```
Example: `0,0,0,scan_20250505_143022\n`

**Scan End:**
```
X_MAX,Y_MAX,0\n
```
Example: `200.000,150.000,0\n`

### Data Transmission Timing
- **Interval**: 50ms (20 Hz)
- **During**: Horizontal X-axis movement only
- **Not sent**: During Y-axis stepping (vertical movement)

## Configuration

### Default Settings
- **Baud Rate**: 115200
- **Port**: Auto-detect (searches for USB-to-TTL adapters)
- **Timeout**: 1 second
- **Data Bits**: 8
- **Parity**: None
- **Stop Bits**: 1

### Auto-Detection Logic
Searches for serial ports with these keywords in description:
- "USB"
- "UART"
- "Serial"

Common detected ports:
- `/dev/ttyUSB0` (USB-to-TTL adapters)
- `/dev/ttyUSB1` (secondary adapter)
- `/dev/ttyAMA0` (Raspberry Pi built-in UART)

## Compatibility

### Migne Plotter Compatibility
The Migne Realtime Plotter (`Ver2.3_Migne_Realtime_Plotter copy.py`) already has:
- ✅ Serial port reading capability
- ✅ CSV data parsing
- ✅ Auto-detection of scan dimensions
- ✅ Real-time plotting
- ✅ Auto-save functionality

**No modifications needed to the plotter!**

### Data Format Match
The scanner sends data in the exact format the plotter expects:
```python
# Scanner sends:
"10.500,20.300,0.000456\n"

# Plotter parses:
parts = rcv_data.decode("ascii").split(",")
x0 = float(parts[0])  # 10.500
y0 = float(parts[1])  # 20.300
z0 = float(parts[2])  # 0.000456
```

## Error Handling

### Connection Failures
- If serial connection fails, scanner continues to work normally
- Status indicator shows yellow "Serial: Not Connected"
- No data is sent, but scanning proceeds
- User can retry by restarting program

### Transmission Errors
- Individual send failures are caught and logged
- Scan continues even if some data points fail to send
- Plotter handles missing data gracefully (interpolation)

### Safety Features
- Serial operations wrapped in try-except blocks
- Global `ser_output` checked before each send
- Connection state verified with `is_open` check
- Graceful degradation if serial unavailable

## Performance Impact

### Minimal Overhead
- Serial transmission: ~1ms per data point
- Data interval: 50ms (plenty of time)
- No blocking operations during scan
- Asynchronous from motor control

### Data Rate
- **Points per second**: ~20 (during horizontal movement)
- **Bytes per point**: ~25 bytes
- **Total data rate**: ~500 bytes/sec
- **Baud capacity**: 115200 baud = ~11,520 bytes/sec
- **Utilization**: ~4.3% (very low)

## Testing Recommendations

### Unit Tests
1. **Serial Connection Test**: Verify auto-detection works
2. **Data Format Test**: Confirm X,Y,Z format is correct
3. **Marker Test**: Verify start/end markers sent properly
4. **Error Handling Test**: Disconnect cable mid-scan

### Integration Tests
1. **Full Scan Test**: Complete scan with plotter receiving
2. **Large Scan Test**: 300x300mm scan (stress test)
3. **Multiple Scans Test**: Sequential scans without restart
4. **Reconnection Test**: Unplug/replug adapter between scans

### System Tests
1. **End-to-End Test**: Scanner → Serial → Plotter → PNG/CSV
2. **Performance Test**: Measure data loss rate
3. **Reliability Test**: 10 consecutive scans
4. **Error Recovery Test**: Simulate various failure modes

## Future Enhancements

### Potential Improvements

1. **Real Z Sensor Integration**
   ```python
   # Replace placeholder in scan_x_to_position_mm_with_data():
   z_value = read_sensor()  # Add actual sensor reading
   ```

2. **Configurable Data Rate**
   ```python
   data_send_interval = 0.05  # Make this a GUI parameter
   ```

3. **Data Compression**
   - Send delta values instead of absolute
   - Reduce decimal precision where appropriate
   - Binary format instead of ASCII

4. **Bidirectional Communication**
   - Plotter sends acknowledgments
   - Scanner adjusts speed based on plotter feedback
   - Error correction protocol

5. **Multiple Plotter Support**
   - Broadcast to multiple receivers
   - Different data formats per receiver
   - Master/slave configuration

6. **Data Buffering**
   - Queue data points if transmission slow
   - Retry failed transmissions
   - Persistent storage fallback

## Known Limitations

1. **Z Value**: Currently hardcoded to 0.0 (placeholder)
2. **One-Way Communication**: Scanner → Plotter only
3. **No Acknowledgment**: Fire-and-forget transmission
4. **No Error Correction**: Lost data is not retransmitted
5. **Single Receiver**: Only one plotter can receive data
6. **ASCII Format**: Less efficient than binary

## Migration Notes

### From Previous Version
- No breaking changes to existing functionality
- Serial features are additive only
- Can run without serial connection (backward compatible)
- All existing scan parameters preserved

### Configuration Migration
- No changes to `scan_config.json` format
- Serial port setting stored in GUI only (not persisted)
- Area calibration data unchanged

## Documentation Files

1. **SERIAL_CONNECTION_GUIDE.md**: Complete setup and usage guide
2. **QUICK_START_SERIAL.md**: Quick reference for common tasks
3. **SERIAL_INTEGRATION_CHANGES.md**: This file (technical changes)

## Support

For issues or questions:
1. Check troubleshooting section in SERIAL_CONNECTION_GUIDE.md
2. Verify wiring with Quick Start guide
3. Test with manual serial commands
4. Check system logs for error messages

---

**Version**: 2.0 (Serial Integration)  
**Date**: 2025-05-05  
**Status**: Ready for Testing
