# Quick Start: Serial Connection Setup

## 🔌 Hardware Connection

```
Scanner Pi          USB-TTL         Plotter Pi
==========          =======         ==========
GPIO14 (TX) -----> RX
GPIO15 (RX) <----- TX
GND         <----> GND
```

## 📦 Software Installation

```bash
# On BOTH Raspberry Pis:
pip3 install pyserial

# Enable UART:
sudo nano /boot/config.txt
# Add: enable_uart=1
# Add: dtoverlay=disable-bt
sudo reboot

# Add user to dialout group:
sudo usermod -a -G dialout $USER
# Logout and login again
```

## 🚀 Quick Start Procedure

### 1. Start Plotter (Receiver) FIRST
```bash
cd "Metal Particle Program"
python3 Ver2.3_Migne_Realtime_Plotter\ copy.py
```
Wait for: `Connected to serial port: /dev/ttyUSB0`

### 2. Start Scanner (Sender)
```bash
cd "MIni XY Scanner"
python3 V2_Mini_XY_Scanner.py
```
Check: Serial status should show **green "Serial: Connected"**

### 3. Run Scan
1. Press **HOME** button (wait for "Homed")
2. Set scan parameters (Row Step, Speeds, Counts)
3. Press **SCAN** button
4. Watch real-time plot on Migne display!

## 🔍 Quick Troubleshooting

| Problem | Solution |
|---------|----------|
| Yellow "Not Connected" | Check USB adapter plugged in, verify with `ls /dev/ttyUSB*` |
| No data on plotter | Start plotter BEFORE scanner, check TX/RX wiring |
| Corrupted data | Check GND connection, reduce cable length |
| Permission denied | Run `sudo usermod -a -G dialout $USER` and re-login |

## 📊 Data Format

**Normal data:** `X,Y,Z\n` (e.g., `10.500,20.300,0.000456`)  
**Start marker:** `0,0,0,scan_20250505_143022\n`  
**End marker:** `200.000,150.000,0\n`

## ✅ Success Indicators

- ✅ Scanner GUI: Green "Serial: Connected"
- ✅ Plotter terminal: "Connected to serial port: /dev/ttyUSB0"
- ✅ Plotter display: Real-time updates during scan
- ✅ Auto-saved PNG and CSV files after scan

## 🧪 Quick Test

```bash
# On Scanner Pi - send test data:
python3 << EOF
import serial
ser = serial.Serial('/dev/ttyUSB0', 115200)
ser.write(b"0,0,0,test\n")
for i in range(5):
    ser.write(f"{i*10.0},{i*5.0},0.001\n".encode())
ser.write(b"50.0,25.0,0\n")
ser.close()
EOF
```

Watch plotter - should display test pattern!

---

**Need more details?** See `SERIAL_CONNECTION_GUIDE.md` for complete documentation.
