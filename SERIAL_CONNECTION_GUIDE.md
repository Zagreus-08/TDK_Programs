# Serial Connection Guide: Mini XY Scanner → Migne Realtime Plotter

## Overview
This guide explains how to connect the Mini XY Scanner to the Migne Realtime Plotter using a USB-to-TTL serial adapter for real-time data visualization during scanning.

## Hardware Requirements

### 1. USB-to-TTL Serial Adapter
- **Recommended**: FTDI FT232RL, CP2102, or CH340 based adapters
- **Voltage**: 3.3V or 5V (match your Raspberry Pi GPIO voltage)
- **Connections needed**: TX, RX, GND

### 2. Wiring Diagram
```
Mini XY Scanner (Raspberry Pi)    USB-to-TTL Adapter    Migne Plotter (Raspberry Pi)
================================    ==================    ============================
GPIO 14 (TXD) ------------------>  RX
GPIO 15 (RXD) <------------------  TX
GND          <------------------->  GND
```

**Important Notes:**
- Connect TX of Scanner to RX of Adapter
- Connect RX of Scanner to TX of Adapter  
- Always connect GND between devices
- Do NOT connect VCC/5V unless powering the adapter

## Software Setup

### 1. Install Required Python Packages

On **both** Raspberry Pi systems:

```bash
# Install pyserial
pip3 install pyserial

# Verify installation
python3 -c "import serial; print(serial.__version__)"
```

### 2. Enable Serial Port on Raspberry Pi

On **both** systems:

```bash
# Edit boot config
sudo nano /boot/config.txt

# Add or uncomment these lines:
enable_uart=1
dtoverlay=disable-bt

# Save and reboot
sudo reboot
```

### 3. Check Serial Port Permissions

```bash
# Add user to dialout group (allows serial access)
sudo usermod -a -G dialout $USER

# Logout and login again for changes to take effect
```

### 4. Identify Serial Ports

On **Mini XY Scanner** (sender):
```bash
# List available serial ports
ls -l /dev/ttyUSB* /dev/ttyAMA*

# Common ports:
# /dev/ttyUSB0 - USB-to-TTL adapter
# /dev/ttyAMA0 - Built-in UART (if enabled)
```

On **Migne Plotter** (receiver):
```bash
# The plotter already has serial detection code
# It will auto-detect USB serial adapters
# Default ports checked: /dev/ttyUSB0, /dev/ttyUSB1, /dev/ttyACM0, COM7 (Windows)
```

## Configuration

### Mini XY Scanner Configuration

1. **Launch the scanner program:**
   ```bash
   cd "MIni XY Scanner"
   python3 V2_Mini_XY_Scanner.py
   ```

2. **Serial Port Setting:**
   - The GUI has a "Serial Port" field (bottom right)
   - Default value: "AUTO" (auto-detects USB-to-TTL adapter)
   - Manual override: Enter specific port like `/dev/ttyUSB0`

3. **Serial Status Indicator:**
   - **Green "Serial: Connected"** = Ready to send data
   - **Yellow "Serial: Not Connected"** = No adapter found (scanning still works, no data sent)

### Migne Plotter Configuration

The plotter is already configured to receive data. No changes needed!

- **Baud Rate**: 115200 (default)
- **Auto-detection**: Checks common ports automatically
- **Data Format**: Expects "X,Y,Z" comma-separated values

## Data Protocol

### Message Format

The scanner sends ASCII text over serial in this format:

```
X,Y,Z\n
```

Where:
- **X**: X-axis position in millimeters (float, 3 decimals)
- **Y**: Y-axis position in millimeters (float, 3 decimals)  
- **Z**: Sensor reading (float, 6 decimals) - currently 0.0 placeholder
- **\n**: Newline terminator

### Special Markers

**Scan Start Marker:**
```
0,0,0,FILENAME\n
```
- Sent at the beginning of each scan
- FILENAME format: `scan_YYYYMMDD_HHMMSS`
- Example: `0,0,0,scan_20250505_143022`

**Scan End Marker:**
```
X_MAX,Y_MAX,0\n
```
- Sent at the end of scan
- X_MAX, Y_MAX = maximum scan dimensions in mm
- Example: `200.000,150.000,0`

### Example Data Stream

```
0,0,0,scan_20250505_143022
0.000,0.000,0.000000
5.234,0.000,0.000123
10.468,0.000,0.000089
...
195.766,0.000,0.000156
200.000,0.000,0.000134
0.000,5.000,0.000145
5.234,5.000,0.000167
...
200.000,150.000,0.000091
200.000,150.000,0
```

## Operation Procedure

### Step-by-Step Workflow

1. **Physical Setup:**
   - Connect USB-to-TTL adapter between both Raspberry Pis
   - Verify wiring: TX→RX, RX→TX, GND→GND
   - Power on both systems

2. **Start Migne Plotter (Receiver) FIRST:**
   ```bash
   cd "Metal Particle Program"
   python3 Ver2.3_Migne_Realtime_Plotter\ copy.py
   ```
   - Wait for "Connected to serial port: /dev/ttyUSB0" message
   - The plotter will show a blank display, waiting for data

3. **Start Mini XY Scanner (Sender):**
   ```bash
   cd "MIni XY Scanner"
   python3 V2_Mini_XY_Scanner.py
   ```
   - Check serial status indicator (should be green)
   - If yellow, check connections and port settings

4. **Configure Scan Parameters:**
   - Set Row Step, X Speed, Y Speed
   - Set X Scan Count and Y Scan Count
   - Optionally run "Calibrate Area" first

5. **Run Homing:**
   - Press "HOME" button
   - Wait for axes to home (status shows "Homed")

6. **Start Scanning:**
   - Press "SCAN" button
   - Scanner will:
     - Send start marker with timestamp filename
     - Begin snake-pattern scan
     - Send X,Y,Z data every 50ms during horizontal movement
     - Send end marker when complete

7. **Monitor on Plotter:**
   - Migne plotter will display data in real-time
   - 2D contour plot and 3D surface update live
   - Auto-saves PNG image at scan completion
   - Raw CSV data saved to `/home/pi/Shared/raw_data/`

## Troubleshooting

### Problem: "Serial: Not Connected" on Scanner

**Solutions:**
1. Check USB-to-TTL adapter is plugged in
2. Verify port with `ls -l /dev/ttyUSB*`
3. Check permissions: `groups` (should include "dialout")
4. Try manual port entry instead of "AUTO"
5. Test adapter: `sudo minicom -D /dev/ttyUSB0 -b 115200`

### Problem: Plotter Not Receiving Data

**Solutions:**
1. Ensure plotter started BEFORE scanner
2. Check wiring (TX/RX might be swapped)
3. Verify GND connection
4. Check baud rate matches (115200 on both)
5. Look for error messages in plotter terminal

### Problem: Data Appears Corrupted

**Solutions:**
1. Check for loose connections
2. Verify voltage levels (3.3V vs 5V compatibility)
3. Reduce cable length if too long (>1 meter)
4. Add ferrite beads to reduce EMI
5. Check for ground loops

### Problem: Plotter Shows Old Data

**Solutions:**
1. Press "Live Scan" button on plotter to clear
2. Restart plotter program
3. Check that scanner sent start marker (0,0,0,filename)

## Testing Serial Connection

### Test 1: Loopback Test (on Scanner Pi)

```bash
# Connect TX to RX on the adapter (short them together)
# Run this test:
python3 << EOF
import serial
import time

ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=1)
test_msg = "10.5,20.3,0.000456\n"

ser.write(test_msg.encode('ascii'))
time.sleep(0.1)

received = ser.readline().decode('ascii')
print(f"Sent: {test_msg.strip()}")
print(f"Received: {received.strip()}")
print("PASS" if received == test_msg else "FAIL")

ser.close()
EOF
```

### Test 2: Manual Data Send (on Scanner Pi)

```bash
# Send test data manually
python3 << EOF
import serial
import time

ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=1)

# Send start marker
ser.write(b"0,0,0,test_scan\n")
time.sleep(0.1)

# Send some data points
for i in range(10):
    msg = f"{i*10.0},{i*5.0},0.000{i:03d}\n"
    ser.write(msg.encode('ascii'))
    print(f"Sent: {msg.strip()}")
    time.sleep(0.1)

# Send end marker
ser.write(b"100.0,50.0,0\n")

ser.close()
print("Test data sent!")
EOF
```

Watch the Migne plotter - it should display the test data.

## Performance Optimization

### Data Rate Calculation

- **Scan Speed**: ~50mm/s (typical)
- **Data Interval**: 50ms (20 Hz)
- **Points per second**: 20
- **Bytes per point**: ~25 bytes ("123.456,789.012,0.000123\n")
- **Data rate**: ~500 bytes/sec (well within 115200 baud capacity)

### Recommendations

1. **Keep data interval at 50ms** - Good balance between resolution and performance
2. **Use 115200 baud** - Fast enough, widely supported
3. **Minimize cable length** - Reduces signal degradation
4. **Use shielded cable** - Reduces electromagnetic interference
5. **Ground both systems properly** - Prevents ground loops

## Advanced Configuration

### Custom Serial Port (Scanner)

Edit the GUI initialization or modify code:

```python
# In GUIClass.__init__(), change:
self.serial_entry.insert(0, "/dev/ttyAMA0")  # Use built-in UART
```

### Custom Baud Rate

If you need different baud rate, modify both programs:

**Scanner (V2_Mini_XY_Scanner.py):**
```python
def init_serial_connection(port=None, baudrate=230400):  # Change here
```

**Plotter (Ver2.3_Migne_Realtime_Plotter copy.py):**
```python
ser = serial.Serial(port, 230400, timeout=1)  # Change here
```

### Add Actual Z Sensor Reading

Currently Z is placeholder (0.0). To add real sensor:

**In SimpleScanClass.scan_x_to_position_mm_with_data():**

```python
# Replace this line:
z_value = 0.0  # Placeholder

# With actual sensor reading:
z_value = read_sensor()  # Your sensor function

# Example for ADC sensor:
def read_sensor():
    import spidev
    spi = spidev.SpiDev()
    spi.open(0, 0)
    adc = spi.xfer2([1, (8 + 0) << 4, 0])
    data = ((adc[1] & 3) << 8) + adc[2]
    voltage = (data * 3.3) / 1024
    return voltage
```

## Safety Notes

⚠️ **Important Safety Considerations:**

1. **Voltage Compatibility**: Ensure 3.3V/5V levels match between devices
2. **Ground Connection**: Always connect GND first, disconnect last
3. **Hot Plugging**: Avoid connecting/disconnecting while powered on
4. **EMG Stop**: Emergency stop on scanner does NOT stop plotter
5. **Data Loss**: If connection drops mid-scan, data may be incomplete

## Support & Debugging

### Enable Debug Output

**Scanner:**
```python
# Add at top of scan_x_to_position_mm_with_data():
print(f"DEBUG: Sending data - X:{x_abs:.3f}, Y:{y_abs:.3f}, Z:{z_value:.6f}")
```

**Plotter:**
Already has debug output in read_loop() function.

### Log Serial Data

**On Plotter Pi:**
```bash
# Monitor serial data in real-time
cat /dev/ttyUSB0

# Or with timestamps:
while true; do
    date +"%H:%M:%S.%3N: $(cat /dev/ttyUSB0)"
done
```

## Summary

✅ **Connection**: USB-to-TTL adapter between Raspberry Pis  
✅ **Wiring**: TX→RX, RX→TX, GND→GND  
✅ **Baud Rate**: 115200  
✅ **Data Format**: "X,Y,Z\n" ASCII text  
✅ **Start Order**: Plotter first, then Scanner  
✅ **Status Check**: Green "Serial: Connected" on scanner GUI  

**You're now ready to perform real-time scanning with live data visualization!** 🎉
