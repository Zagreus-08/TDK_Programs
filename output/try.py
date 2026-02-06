import serial
import time

# ----------------------------
# Configuration
# ----------------------------
COM_PORT = "COM4"        # Replace with your adapter COM port
BAUDRATE = 4800          # Most 3M 747 units use 9600
TIMEOUT = 1              # Serial timeout in seconds

# ----------------------------
# Open Serial Port
# ----------------------------
try:
    ser = serial.Serial(
        port=COM_PORT,
        baudrate=BAUDRATE,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=TIMEOUT,
        xonxoff=False,     # Disable software flow control
        rtscts=False,      # Disable hardware RTS/CTS
        dsrdtr=False       # Disable DSR/DTR
    )
    # Set DTR and RTS low (optional, depends on tester)
    ser.setDTR(False)
    ser.setRTS(False)
    time.sleep(1)
    print(f"✅ Listening on {COM_PORT} for wrist strap and shoes data...\n")
except Exception as e:
    print("❌ Cannot open serial port:", e)
    exit(1)

# ----------------------------
# Parse wrist/shoes data
# ----------------------------
def parse_esd_data(raw_bytes):
    """Extract wrist strap and shoes results from tester data"""
    try:
        text = raw_bytes.decode("ascii", errors="ignore").strip()
    except:
        text = str(raw_bytes)

    # Remove STX/ETX if present
    text = text.replace("\x02", "").replace("\x03", "")

    wrist = None
    shoes = None

    # Format: ID=E102345,WRIST=PASS,SHOE=PASS
    if "WRIST=" in text and "SHOE=" in text:
        parts = text.split(",")
        for part in parts:
            if part.upper().startswith("WRIST="):
                wrist = part.split("=")[1].strip().upper()
            elif part.upper().startswith("SHOE="):
                shoes = part.split("=")[1].strip().upper()
    else:
        # Format: ID,P,P or P,P
        parts = text.split(",")
        if len(parts) == 3:
            wrist = parts[1].upper()
            shoes = parts[2].upper()
        elif len(parts) == 2:
            wrist = parts[0].upper()
            shoes = parts[1].upper()

    return wrist, shoes

# ----------------------------
# Main loop: listen continuously
# ----------------------------
try:
    while True:
        if ser.in_waiting > 0:
            raw = ser.read(ser.in_waiting)
            wrist, shoes = parse_esd_data(raw)
            if wrist is not None and shoes is not None:
                print(f"Wrist Strap: {wrist} | Shoes: {shoes}")
        time.sleep(0.1)

except KeyboardInterrupt:
    print("\nStopped by user")

finally:
    ser.close()
    print("Serial port closed")
