"""
Godex RT863i Label Printer - LAN/Network Connection
Prints 2 labels on 20mm x 8mm die-cut stock
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageDraw, ImageFont, ImageTk
import qrcode
import socket
import os

# ----------------------------
# Configuration
# ----------------------------
DPI = 203
WIDTH_MM, HEIGHT_MM = 20, 8
WIDTH_PX = int((WIDTH_MM / 25.4) * DPI)  # 160 pixels
HEIGHT_PX = int((HEIGHT_MM / 25.4) * DPI)  # 64 pixels

# Network settings
DEFAULT_PRINTER_IP = "192.168.1.100"  # Change to your printer's IP
PRINTER_PORT = 9100  # Standard raw print port

TDK_LOGO_PATH = r"C:\Users\a493353\Downloads\TDK-Logo.png"

try:
    RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE = Image.ANTIALIAS

_images = {}

# ----------------------------
# Label Generation Functions
# ----------------------------
def load_tdk_logo():
    try:
        logo = Image.open(TDK_LOGO_PATH).convert("RGBA")
        w, h = logo.size
        new_h = int(HEIGHT_PX * 0.30)
        new_w = int((w / h) * new_h)
        return logo.resize((new_w, new_h), RESAMPLE)
    except:
        return None

def make_label1():
    """Label 1: CONFIDENTIAL + TDK Logo + BMS-SENSOR-05"""
    img = Image.new("RGB", (WIDTH_PX, HEIGHT_PX), "white")
    draw = ImageDraw.Draw(img)
    
    try:
        font1 = ImageFont.truetype("arial.ttf", int(HEIGHT_PX * 0.22))
        font2 = ImageFont.truetype("arialbd.ttf", int(HEIGHT_PX * 0.25))
    except:
        font1 = font2 = ImageFont.load_default()
    
    # CONFIDENTIAL
    text = "CONFIDENTIAL"
    bbox = draw.textbbox((0, 0), text, font=font1)
    w = bbox[2] - bbox[0]
    draw.text(((WIDTH_PX - w) // 2, 2), text, font=font1, fill="black")
    
    # TDK Logo
    logo = load_tdk_logo()
    if logo:
        lw, lh = logo.size
        img.paste(logo, ((WIDTH_PX - lw) // 2, int(HEIGHT_PX * 0.30)), logo)
    
    # BMS-SENSOR-05
    text = "BMS-SENSOR-05"
    bbox = draw.textbbox((0, 0), text, font=font2)
    w = bbox[2] - bbox[0]
    draw.text(((WIDTH_PX - w) // 2, int(HEIGHT_PX * 0.70)), text, font=font2, fill="black")
    
    return img

def make_label2(sensor_id):
    """Label 2: Sensor ID + QR Code"""
    img = Image.new("RGB", (WIDTH_PX, HEIGHT_PX), "white")
    draw = ImageDraw.Draw(img)
    
    try:
        font = ImageFont.truetype("arial.ttf", int(HEIGHT_PX * 0.24))
    except:
        font = ImageFont.load_default()
    
    # QR Code
    qr_size = int(HEIGHT_PX * 0.90)
    qr = qrcode.make(sensor_id).resize((qr_size, qr_size), RESAMPLE)
    img.paste(qr, (WIDTH_PX - qr_size - 3, (HEIGHT_PX - qr_size) // 2))
    
    # Sensor ID text
    lines = sensor_id.split('-') if '-' in sensor_id else [sensor_id]
    text = "\n".join(lines)
    draw.multiline_text((3, 3), text, font=font, fill="black", spacing=0)
    
    return img

# ----------------------------
# EZPL Command Generation
# ----------------------------
def image_to_ezpl(img, x=0, y=0):
    """Convert image to EZPL GW command"""
    bw = img.convert('1')
    w, h = bw.size
    pixels = bw.load()
    
    bytes_per_row = (w + 7) // 8
    data = []
    
    for row in range(h):
        byte_val = 0
        bit_pos = 7
        for col in range(w):
            if pixels[col, row] == 0:  # Black
                byte_val |= (1 << bit_pos)
            bit_pos -= 1
            if bit_pos < 0:
                data.append(byte_val)
                byte_val = 0
                bit_pos = 7
        if bit_pos != 7:
            data.append(byte_val)
    
    hex_data = ''.join(f'{b:02X}' for b in data)
    return f"GW{x},{y},{bytes_per_row},{h},{hex_data}"

def generate_ezpl(img):
    """Generate complete EZPL command for one label"""
    cmds = [
        "^Q8,3",      # Label height 8mm, gap 3mm
        "^W20",       # Label width 20mm
        "^H5",        # Print darkness
        "^P1",        # Print 1 copy
        "^S3",        # Print speed
        "^AD",        # Print direction
        "^C1",        # Clear buffer
        "^~1",        # Cut mode off
        "^L",         # Start label
        image_to_ezpl(img, 0, 0),
        "E",          # End and print
    ]
    return '\r\n'.join(cmds) + '\r\n'

# ----------------------------
# Network Printing
# ----------------------------
def send_to_printer(data, ip, port=9100, timeout=5):
    """Send raw data to printer via TCP"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, port))
        sock.sendall(data.encode('ascii'))
        sock.close()
        return True
    except socket.timeout:
        raise Exception(f"Connection timeout - check if printer is on and IP is correct")
    except ConnectionRefusedError:
        raise Exception(f"Connection refused - printer may be offline or port {port} blocked")
    except Exception as e:
        raise Exception(f"Network error: {e}")

def test_connection(ip, port=9100):
    """Test if printer is reachable"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except:
        return False

# ----------------------------
# GUI
# ----------------------------
root = tk.Tk()
root.title("Godex RT863i - LAN Printer")
root.geometry("450x650")

# Title
tk.Label(root, text="Godex RT863i Label Printer", font=("Arial", 14, "bold")).pack(pady=10)
tk.Label(root, text="20mm x 8mm Die-Cut Labels", font=("Arial", 10)).pack()

# Sensor ID
tk.Label(root, text="Sensor ID:", font=("Arial", 11)).pack(pady=(15, 5))
entry_sensor = tk.Entry(root, width=30, font=("Arial", 11))
entry_sensor.pack()
entry_sensor.insert(0, "12-23-12345-123456")

# Network Settings
net_frame = tk.LabelFrame(root, text="Network Settings", padx=10, pady=10)
net_frame.pack(pady=15, padx=20, fill="x")

tk.Label(net_frame, text="Printer IP:").grid(row=0, column=0, sticky="e", padx=5)
entry_ip = tk.Entry(net_frame, width=20)
entry_ip.grid(row=0, column=1, padx=5)
entry_ip.insert(0, DEFAULT_PRINTER_IP)

tk.Label(net_frame, text="Port:").grid(row=0, column=2, sticky="e", padx=5)
entry_port = tk.Entry(net_frame, width=8)
entry_port.grid(row=0, column=3, padx=5)
entry_port.insert(0, "9100")

status_label = tk.Label(net_frame, text="Not connected", fg="gray")
status_label.grid(row=1, column=0, columnspan=4, pady=5)

def check_connection():
    ip = entry_ip.get().strip()
    port = int(entry_port.get().strip())
    if test_connection(ip, port):
        status_label.config(text=f"✓ Connected to {ip}:{port}", fg="green")
    else:
        status_label.config(text=f"✗ Cannot reach {ip}:{port}", fg="red")

tk.Button(net_frame, text="Test Connection", command=check_connection).grid(row=1, column=3, pady=5)

# Preview
preview_frame = tk.LabelFrame(root, text="Preview", padx=10, pady=10)
preview_frame.pack(pady=10, padx=20, fill="x")

canvas1 = tk.Canvas(preview_frame, width=320, height=64, bg="white", relief="sunken", bd=1)
canvas1.pack(pady=2)
tk.Label(preview_frame, text="Label 1: CONFIDENTIAL + TDK + BMS", font=("Arial", 8)).pack()

canvas2 = tk.Canvas(preview_frame, width=320, height=64, bg="white", relief="sunken", bd=1)
canvas2.pack(pady=2)
tk.Label(preview_frame, text="Label 2: Sensor ID + QR Code", font=("Arial", 8)).pack()

def update_preview():
    sensor_id = entry_sensor.get().strip()
    if not sensor_id:
        return
    
    label1 = make_label1()
    label2 = make_label2(sensor_id)
    
    # Store for printing
    root.label1 = label1
    root.label2 = label2
    
    # Scale for preview
    p1 = label1.resize((320, 64), RESAMPLE)
    p2 = label2.resize((320, 64), RESAMPLE)
    
    _images['p1'] = ImageTk.PhotoImage(p1)
    _images['p2'] = ImageTk.PhotoImage(p2)
    
    canvas1.delete("all")
    canvas1.create_image(160, 32, image=_images['p1'])
    canvas2.delete("all")
    canvas2.create_image(160, 32, image=_images['p2'])

tk.Button(root, text="Generate Preview", command=update_preview, font=("Arial", 10)).pack(pady=10)

# Buttons
btn_frame = tk.Frame(root)
btn_frame.pack(pady=15)

def save_labels():
    sensor_id = entry_sensor.get().strip()
    if not sensor_id:
        messagebox.showwarning("Error", "Enter sensor ID first")
        return
    
    folder = filedialog.askdirectory(title="Save labels to folder")
    if not folder:
        return
    
    label1 = make_label1()
    label2 = make_label2(sensor_id)
    
    safe_id = sensor_id.replace('/', '-').replace('\\', '-')
    p1 = os.path.join(folder, f"{safe_id}_Label1.png")
    p2 = os.path.join(folder, f"{safe_id}_Label2.png")
    
    label1.save(p1, dpi=(DPI, DPI))
    label2.save(p2, dpi=(DPI, DPI))
    
    messagebox.showinfo("Saved", f"Labels saved:\n{p1}\n{p2}")
    os.startfile(folder)

def print_labels():
    sensor_id = entry_sensor.get().strip()
    if not sensor_id:
        messagebox.showwarning("Error", "Enter sensor ID first")
        return
    
    ip = entry_ip.get().strip()
    port = int(entry_port.get().strip())
    
    if not test_connection(ip, port):
        messagebox.showerror("Error", f"Cannot connect to printer at {ip}:{port}\n\nCheck:\n1. Printer is on\n2. IP address is correct\n3. Network connection")
        return
    
    try:
        status_label.config(text="Printing label 1...", fg="blue")
        root.update()
        
        label1 = make_label1()
        ezpl1 = generate_ezpl(label1)
        send_to_printer(ezpl1, ip, port)
        
        root.after(500)  # Wait between labels
        
        status_label.config(text="Printing label 2...", fg="blue")
        root.update()
        
        label2 = make_label2(sensor_id)
        ezpl2 = generate_ezpl(label2)
        send_to_printer(ezpl2, ip, port)
        
        status_label.config(text="✓ Both labels printed!", fg="green")
        messagebox.showinfo("Success", "Both labels sent to printer!")
        
    except Exception as e:
        status_label.config(text="✗ Print failed", fg="red")
        messagebox.showerror("Print Error", str(e))

tk.Button(btn_frame, text="Save Labels", command=save_labels, 
         font=("Arial", 10), padx=15, pady=5).pack(side="left", padx=10)

tk.Button(btn_frame, text="Print Labels", command=print_labels,
         font=("Arial", 11, "bold"), bg="lightgreen", padx=20, pady=8).pack(side="left", padx=10)

# Instructions
tk.Label(root, text="Instructions:\n1. Enter printer IP address\n2. Click 'Test Connection'\n3. Enter Sensor ID\n4. Click 'Print Labels'",
        font=("Arial", 9), fg="gray", justify="left").pack(pady=10)

# Initial preview
update_preview()

root.mainloop()
