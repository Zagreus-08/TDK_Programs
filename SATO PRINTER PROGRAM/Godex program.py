import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageDraw, ImageFont, ImageTk
import qrcode
import os
import tempfile
import usb.core
import usb.util

# ----------------------------
# Configuration
# ----------------------------
MM_TO_INCH = 1 / 25.4

# Default settings (can be changed via GUI)
class PrintSettings:
    def __init__(self):
        self.dpi = 203
        self.width_mm = 20
        self.height_mm = 8
        self.x_offset = 0
        self.y_offset = 0
        
        # Label 1 element positions
        self.conf_y_offset = 4
        self.bms_y_offset = 4
        
        # Label 2 element positions
        self.qr_size = 56
        self.qr_x_margin = 2
        self.qr_y_offset = 0
        self.text_x_margin = 2
        self.text_y_offset = 2
        
        self.update_dimensions()
    
    def update_dimensions(self):
        self.width_px = int(self.width_mm * self.dpi * MM_TO_INCH)
        self.height_px = int(self.height_mm * self.dpi * MM_TO_INCH)
        self.preview_w = self.width_px * 2
        self.preview_h = self.height_px * 2

settings = PrintSettings()

# Global image references (to prevent garbage collection)
_global_images = {}

# ✅ Compatibility wrapper for resampling
try:
    RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE = Image.ANTIALIAS

# TDK Logo Path
TDK_LOGO_PATH = r"C:\Users\a493353\Downloads\TDK-Logo.png"

# Godex RT863i USB Settings
GODEX_VENDOR_ID = 0x0B9B  # Godex vendor ID
GODEX_PRODUCT_ID = 0x0863  # RT863i product ID (may vary, will auto-detect)

# Fonts for final rendered image
def load_pillow_fonts(height_px):
    try:
        # Optimized fonts for 128x64 label (16mm x 8mm printable area)
        font_confidential = ImageFont.truetype("arial.ttf", 11)
        font_bms = ImageFont.truetype("arialbd.ttf", 13)
        font_sensor = ImageFont.truetype("arial.ttf", 15)
    except Exception: 
        font_confidential = font_bms = font_sensor = ImageFont.load_default()
    return font_confidential, font_bms, font_sensor
    return font_confidential, font_bms, font_sensor

# Generate Label 1: CONFIDENTIAL + TDK Logo + BMS-SENSOR-05
def make_label1_image():
    label1 = Image.new("RGB", (settings.width_px, settings.height_px), "white")
    draw = ImageDraw.Draw(label1)
    font_confidential, font_bms, _ = load_pillow_fonts(settings.height_px)
    
    # Load TDK logo
    tdk_logo = load_tdk_logo(settings.height_px)
    
    # Draw CONFIDENTIAL at top
    conf_text = "CONFIDENTIAL"
    try:
        bbox = draw.textbbox((0, 0), conf_text, font=font_confidential)
        conf_width = bbox[2] - bbox[0]
    except:
        conf_width = len(conf_text) * 16
    conf_x = (settings.width_px - conf_width) // 2
    draw.text((conf_x, settings.conf_y_offset), conf_text, font=font_confidential, fill="black")
    
    # Paste TDK logo in center
    if tdk_logo:
        logo_w, logo_h = tdk_logo.size
        logo_x = (settings.width_px - logo_w) // 2
        logo_y = (settings.height_px - logo_h) // 2
        label1.paste(tdk_logo, (logo_x, logo_y), tdk_logo)
    
    # Draw BMS-SENSOR-05 at bottom
    bms_text = "BMS-SENSOR-05"
    try:
        bbox = draw.textbbox((0, 0), bms_text, font=font_bms)
        bms_width = bbox[2] - bbox[0]
    except:
        bms_width = len(bms_text) * 20
    bms_x = (settings.width_px - bms_width) // 2
    bms_y = settings.height_px - 20 - settings.bms_y_offset
    draw.text((bms_x, bms_y), bms_text, font=font_bms, fill="black")
    
    return label1

# Generate Label 2: Sensor ID + QR Code
def make_label2_image(sensor_text):
    label2 = Image.new("RGB", (settings.width_px, settings.height_px), "white")
    draw = ImageDraw.Draw(label2)
    _, _, font_sensor = load_pillow_fonts(settings.height_px)
    
    # Generate QR code
    qr_size = min(settings.qr_size, settings.height_px - 8)
    qr = qrcode.make(sensor_text)
    qr = qr.resize((qr_size, qr_size), RESAMPLE)
    
    # Paste QR code on the right side
    qr_x = settings.width_px - qr_size - settings.qr_x_margin
    qr_y = (settings.height_px - qr_size) // 2 + settings.qr_y_offset
    label2.paste(qr, (qr_x, qr_y))
    
    # Draw sensor text on the left (split into lines if needed)
    sensor_lines = []
    s = sensor_text or ""
    # Split by dashes for better readability
    if '-' in s:
        parts = s.split('-')
        for part in parts:
            sensor_lines.append(part)
    else:
        # Fallback: split every 6 characters
        for i in range(0, len(s), 6):
            sensor_lines.append(s[i:i+6])
    
    sensor_multiline = "\n".join(sensor_lines)
    text_x = settings.text_x_margin
    text_y = settings.text_y_offset
    draw.multiline_text((text_x, text_y), sensor_multiline, font=font_sensor, fill="black", spacing=0)
    
    return label2

# Load and resize TDK logo
def load_tdk_logo(size_px):
    try:
        logo = Image.open(TDK_LOGO_PATH).convert("RGBA")
        logo_w, logo_h = logo.size
        # Resize logo to fit within the narrower label
        new_h = 18
        if new_h > 0:
            new_w = int((logo_w / logo_h) * new_h)
            logo = logo.resize((new_w, new_h), RESAMPLE)
        return logo
    except FileNotFoundError:
        messagebox.showwarning("Warning", f"TDK logo file not found at: {TDK_LOGO_PATH}")
        return None
    except Exception as e:
        messagebox.showwarning("Warning", f"Could not load TDK logo: {e}")
        return None

# Create combined preview showing both labels
def make_combined_preview(label1, label2):
    # Create a preview showing both labels stacked vertically
    preview_label1 = label1.resize((settings.preview_w, settings.preview_h), RESAMPLE)
    preview_label2 = label2.resize((settings.preview_w, settings.preview_h), RESAMPLE)
    
    # Combine both previews vertically with a small gap
    gap = 10
    combined_height = settings.preview_h * 2 + gap
    combined = Image.new("RGB", (settings.preview_w, combined_height), "lightgray")
    combined.paste(preview_label1, (0, 0))
    combined.paste(preview_label2, (0, settings.preview_h + gap))
    
    return combined

# Find Godex printer via USB
def find_godex_printer():
    """Find Godex RT863i printer via USB"""
    try:
        # Try to find Godex printer by vendor ID
        devices = usb.core.find(find_all=True, idVendor=GODEX_VENDOR_ID)
        godex_devices = []
        
        for dev in devices:
            try:
                product_name = usb.util.get_string(dev, dev.iProduct) if dev.iProduct else "Unknown"
                godex_devices.append({
                    'device': dev,
                    'name': product_name,
                    'vid': hex(dev.idVendor),
                    'pid': hex(dev.idProduct)
                })
            except:
                pass
        
        return godex_devices
    except Exception as e:
        return []

# Send to printer via USB
def send_to_printer_usb(data, device):
    """Send EZPL data to Godex RT863i via USB"""
    try:
        # Detach kernel driver if necessary
        if device.is_kernel_driver_active(0):
            try:
                device.detach_kernel_driver(0)
            except:
                pass
        
        # Set configuration
        device.set_configuration()
        
        # Get endpoint
        cfg = device.get_active_configuration()
        intf = cfg[(0,0)]
        
        # Find OUT endpoint
        ep_out = usb.util.find_descriptor(
            intf,
            custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT
        )
        
        if ep_out is None:
            raise Exception("Could not find USB OUT endpoint")
        
        # Send data
        ep_out.write(data.encode('ascii'))
        
        return True
        
    except usb.core.USBError as e:
        raise Exception(f"USB Error: {e}\nMake sure no other program is using the printer.")
    except Exception as e:
        raise Exception(f"Communication Error: {e}")

# Convert image to EZPL bitmap format for Godex printer
def image_to_ezpl_bitmap(image, x=None, y=None):
    """Convert PIL Image to EZPL bitmap command"""
    if x is None:
        x = settings.x_offset
    if y is None:
        y = settings.y_offset
    
    # Convert to 1-bit black and white
    bw_image = image.convert('1')
    width, height = bw_image.size
    
    # Get image data
    pixels = bw_image.load()
    
    # Calculate bytes per row (must be multiple of 8)
    bytes_per_row = (width + 7) // 8
    
    # Build bitmap data
    bitmap_data = []
    for row in range(height):
        byte_val = 0
        bit_pos = 7
        for col in range(width):
            if pixels[col, row] == 0:  # Black pixel
                byte_val |= (1 << bit_pos)
            bit_pos -= 1
            if bit_pos < 0:
                bitmap_data.append(byte_val)
                byte_val = 0
                bit_pos = 7
        # Pad last byte if needed
        if bit_pos != 7:
            bitmap_data.append(byte_val)
    
    # Create EZPL command
    ezpl_cmd = f"GW{x},{y},{bytes_per_row},{height},"
    ezpl_cmd += ''.join([f"{b:02X}" for b in bitmap_data])
    return ezpl_cmd

# Generate EZPL commands for label
def generate_ezpl_label(label_image, label_num):
    """Generate EZPL commands for Godex RT863i"""
    commands = []
    
    # Start label format
    commands.append(f"^Q{settings.height_mm},3")  # Set label height and gap (3mm)
    commands.append(f"^W{int(settings.width_mm * 4)}")  # Set label width
    commands.append("^H10")    # Set print speed
    commands.append("^P1")     # Print quantity: 1
    commands.append("^S4")     # Print speed
    commands.append("^AT")     # Tear-off mode
    commands.append("^C1")     # Clear image buffer
    commands.append("^E20")    # Gap/black mark sensor
    
    # Convert and add bitmap
    bitmap_cmd = image_to_ezpl_bitmap(label_image)
    commands.append(bitmap_cmd)
    
    # End and print
    commands.append("E")
    
    return '\n'.join(commands)

# Alternative: Send via Windows print spooler for USB printers
def send_to_printer_windows(label_image, printer_name="Godex RT863i+"):
    """Send image to printer via Windows print spooler"""
    try:
        import win32print
        import win32ui
        from PIL import ImageWin
        
        # Get printer handle
        hprinter = win32print.OpenPrinter(printer_name)
        
        # Start document
        hdc = win32ui.CreateDC()
        hdc.CreatePrinterDC(printer_name)
        hdc.StartDoc("Label")
        hdc.StartPage()
        
        # Print image
        dib = ImageWin.Dib(label_image)
        dib.draw(hdc.GetHandleOutput(), (0, 0, label_image.width, label_image.height))
        
        # End document
        hdc.EndPage()
        hdc.EndDoc()
        hdc.DeleteDC()
        
        win32print.ClosePrinter(hprinter)
        return True
        
    except ImportError:
        raise Exception("pywin32 not installed. Install with: pip install pywin32")
    except Exception as e:
        raise Exception(f"Windows Print Error: {e}")

# -------------------------
# GUI
# -------------------------
root = tk.Tk()
root.title("TDK Sensor Label Generator - Godex RT863i (Serial)")

# Settings Panel
settings_panel = tk.LabelFrame(root, text="Label Settings", padx=10, pady=10)
settings_panel.pack(pady=10, padx=10, fill="x")

# Create two columns for settings
left_col = tk.Frame(settings_panel)
left_col.pack(side="left", padx=10, fill="both", expand=True)

right_col = tk.Frame(settings_panel)
right_col.pack(side="left", padx=10, fill="both", expand=True)

# LEFT COLUMN - Basic Settings
tk.Label(left_col, text="Basic Settings", font=("Arial", 9, "bold")).pack(anchor="w", pady=(0,5))

# DPI Setting
dpi_frame = tk.Frame(left_col)
dpi_frame.pack(pady=2, fill="x")
tk.Label(dpi_frame, text="DPI:", width=15, anchor="w").pack(side="left")
dpi_var = tk.StringVar(value="203")
dpi_entry = tk.Entry(dpi_frame, textvariable=dpi_var, width=10)
dpi_entry.pack(side="left", padx=5)

# Width Setting
width_frame = tk.Frame(left_col)
width_frame.pack(pady=2, fill="x")
tk.Label(width_frame, text="Width (mm):", width=15, anchor="w").pack(side="left")
width_var = tk.StringVar(value="20")
width_entry = tk.Entry(width_frame, textvariable=width_var, width=10)
width_entry.pack(side="left", padx=5)

# Height Setting
height_frame = tk.Frame(left_col)
height_frame.pack(pady=2, fill="x")
tk.Label(height_frame, text="Height (mm):", width=15, anchor="w").pack(side="left")
height_var = tk.StringVar(value="8")
height_entry = tk.Entry(height_frame, textvariable=height_var, width=10)
height_entry.pack(side="left", padx=5)

# X Offset Setting
x_offset_frame = tk.Frame(left_col)
x_offset_frame.pack(pady=2, fill="x")
tk.Label(x_offset_frame, text="X Offset (px):", width=15, anchor="w").pack(side="left")
x_offset_var = tk.StringVar(value="0")
x_offset_entry = tk.Entry(x_offset_frame, textvariable=x_offset_var, width=10)
x_offset_entry.pack(side="left", padx=5)

# Y Offset Setting
y_offset_frame = tk.Frame(left_col)
y_offset_frame.pack(pady=2, fill="x")
tk.Label(y_offset_frame, text="Y Offset (px):", width=15, anchor="w").pack(side="left")
y_offset_var = tk.StringVar(value="0")
y_offset_entry = tk.Entry(y_offset_frame, textvariable=y_offset_var, width=10)
y_offset_entry.pack(side="left", padx=5)

# RIGHT COLUMN - Element Positioning
tk.Label(right_col, text="Element Positioning", font=("Arial", 9, "bold")).pack(anchor="w", pady=(0,5))

# Label 1 - CONFIDENTIAL Y offset
conf_y_frame = tk.Frame(right_col)
conf_y_frame.pack(pady=2, fill="x")
tk.Label(conf_y_frame, text="CONFIDENTIAL Y:", width=18, anchor="w").pack(side="left")
conf_y_var = tk.StringVar(value="4")
conf_y_entry = tk.Entry(conf_y_frame, textvariable=conf_y_var, width=10)
conf_y_entry.pack(side="left", padx=5)

# Label 1 - BMS text Y offset
bms_y_frame = tk.Frame(right_col)
bms_y_frame.pack(pady=2, fill="x")
tk.Label(bms_y_frame, text="BMS Text Y:", width=18, anchor="w").pack(side="left")
bms_y_var = tk.StringVar(value="4")
bms_y_entry = tk.Entry(bms_y_frame, textvariable=bms_y_var, width=10)
bms_y_entry.pack(side="left", padx=5)

# Label 2 - QR Size
qr_size_frame = tk.Frame(right_col)
qr_size_frame.pack(pady=2, fill="x")
tk.Label(qr_size_frame, text="QR Size (px):", width=18, anchor="w").pack(side="left")
qr_size_var = tk.StringVar(value="56")
qr_size_entry = tk.Entry(qr_size_frame, textvariable=qr_size_var, width=10)
qr_size_entry.pack(side="left", padx=5)

# Label 2 - QR X margin
qr_x_frame = tk.Frame(right_col)
qr_x_frame.pack(pady=2, fill="x")
tk.Label(qr_x_frame, text="QR X Margin:", width=18, anchor="w").pack(side="left")
qr_x_var = tk.StringVar(value="2")
qr_x_entry = tk.Entry(qr_x_frame, textvariable=qr_x_var, width=10)
qr_x_entry.pack(side="left", padx=5)

# Label 2 - QR Y offset
qr_y_frame = tk.Frame(right_col)
qr_y_frame.pack(pady=2, fill="x")
tk.Label(qr_y_frame, text="QR Y Offset:", width=18, anchor="w").pack(side="left")
qr_y_var = tk.StringVar(value="0")
qr_y_entry = tk.Entry(qr_y_frame, textvariable=qr_y_var, width=10)
qr_y_entry.pack(side="left", padx=5)

# Label 2 - Text X margin
text_x_frame = tk.Frame(right_col)
text_x_frame.pack(pady=2, fill="x")
tk.Label(text_x_frame, text="Text X Margin:", width=18, anchor="w").pack(side="left")
text_x_var = tk.StringVar(value="2")
text_x_entry = tk.Entry(text_x_frame, textvariable=text_x_var, width=10)
text_x_entry.pack(side="left", padx=5)

# Label 2 - Text Y offset
text_y_frame = tk.Frame(right_col)
text_y_frame.pack(pady=2, fill="x")
tk.Label(text_y_frame, text="Text Y Offset:", width=18, anchor="w").pack(side="left")
text_y_var = tk.StringVar(value="2")
text_y_entry = tk.Entry(text_y_frame, textvariable=text_y_var, width=10)
text_y_entry.pack(side="left", padx=5)

# Apply Settings Button
def apply_settings():
    try:
        settings.dpi = int(dpi_var.get())
        settings.width_mm = float(width_var.get())
        settings.height_mm = float(height_var.get())
        settings.x_offset = int(x_offset_var.get())
        settings.y_offset = int(y_offset_var.get())
        
        # Element positioning
        settings.conf_y_offset = int(conf_y_var.get())
        settings.bms_y_offset = int(bms_y_var.get())
        settings.qr_size = int(qr_size_var.get())
        settings.qr_x_margin = int(qr_x_var.get())
        settings.qr_y_offset = int(qr_y_var.get())
        settings.text_x_margin = int(text_x_var.get())
        settings.text_y_offset = int(text_y_var.get())
        
        settings.update_dimensions()
        
        # Update canvas size
        canvas_height = settings.preview_h * 2 + 20
        canvas.config(width=settings.preview_w+10, height=canvas_height)
        
        # Regenerate preview if sensor ID exists
        if entry.get().strip():
            update_preview()
        
        status_label.config(text=f"✓ Settings applied: {settings.width_px}x{settings.height_px}px @ {settings.dpi}DPI", fg="green")
    except ValueError:
        messagebox.showerror("Invalid Input", "Please enter valid numbers for all settings.")

btn_apply_settings = tk.Button(settings_panel, text="Apply Settings", command=apply_settings, bg="lightblue", font=("Arial", 9, "bold"))
btn_apply_settings.pack(pady=10)

# Sensor ID input
tk.Label(root, text="Enter Sensor ID:").pack(pady=5)
entry = tk.Entry(root, width=30)
entry.pack(pady=5)

btn_generate = tk.Button(root, text="Generate Labels")
btn_generate.pack(pady=5)

# Printer connection settings
settings_frame = tk.LabelFrame(root, text="USB Printer Settings", padx=10, pady=10)
settings_frame.pack(pady=10, padx=10, fill="x")

printer_frame = tk.Frame(settings_frame)
printer_frame.pack(pady=5)
tk.Label(printer_frame, text="Printer:").pack(side="left", padx=5)
printer_combo = ttk.Combobox(printer_frame, width=30, state="readonly")
printer_combo.pack(side="left", padx=5)
btn_refresh = tk.Button(printer_frame, text="Refresh", command=lambda: refresh_printers())
btn_refresh.pack(side="left", padx=5)

# Connection method
method_frame = tk.Frame(settings_frame)
method_frame.pack(pady=5)
connection_method = tk.StringVar(value="windows")
tk.Radiobutton(method_frame, text="Windows Print Spooler (Recommended)", 
               variable=connection_method, value="windows").pack(anchor="w")
tk.Radiobutton(method_frame, text="Direct USB (Advanced)", 
               variable=connection_method, value="usb").pack(anchor="w")

btn_save = tk.Button(root, text="Save Labels")
btn_save.pack(pady=5)
btn_print = tk.Button(root, text="Print Labels to Godex RT863i", bg="lightgreen", font=("Arial", 10, "bold"))
btn_print.pack(pady=5)

# Status label
status_label = tk.Label(root, text="Ready", fg="blue")
status_label.pack(pady=5)

def refresh_printers():
    """Refresh available printers"""
    printers = []
    
    # Try USB detection
    usb_devices = find_godex_printer()
    for dev in usb_devices:
        printers.append(f"USB: {dev['name']} (VID:{dev['vid']} PID:{dev['pid']})")
    
    # Try Windows printers
    try:
        import win32print
        win_printers = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)
        for printer in win_printers:
            printer_name = printer[2]
            if "godex" in printer_name.lower() or "rt863" in printer_name.lower():
                printers.append(f"Windows: {printer_name}")
    except:
        pass
    
    if printers:
        printer_combo['values'] = printers
        printer_combo.current(0)
        status_label.config(text=f"Found {len(printers)} printer(s)", fg="green")
    else:
        printer_combo['values'] = ["No printer found"]
        status_label.config(text="No Godex printer found! Check USB connection.", fg="red")

# Initialize printers
refresh_printers()

# Canvas to show both labels
canvas_height = settings.preview_h * 2 + 20
canvas = tk.Canvas(root, width=settings.preview_w+10, height=canvas_height, bg="grey")
canvas.pack(pady=10)

# Create blank preview
blank_preview = Image.new("RGB", (settings.preview_w, canvas_height), "white")
blank_photo = ImageTk.PhotoImage(blank_preview, master=root)
_global_images["blank"] = blank_photo

canvas_bg = canvas.create_image(5, 5, anchor="nw", image=blank_photo)

# Store generated labels
canvas.label1_full = None
canvas.label2_full = None

# Preview update
def update_preview():
    s = entry.get().strip()
    if not s:
        messagebox.showwarning("Input Required", "Please enter a Sensor ID.")
        return
    
    # Generate both labels
    label1 = make_label1_image()
    label2 = make_label2_image(s)
    
    canvas.label1_full = label1
    canvas.label2_full = label2
    
    # Create combined preview
    combined_preview = make_combined_preview(label1, label2)
    
    ph = ImageTk.PhotoImage(combined_preview, master=root)
    _global_images["preview"] = ph
    canvas.itemconfig(canvas_bg, image=ph)

btn_generate.config(command=update_preview)

# Save
def save_label():
    if canvas.label1_full is None or canvas.label2_full is None:
        messagebox.showwarning("No preview", "Generate the labels first.")
        return
    
    fp = filedialog.asksaveasfilename(defaultextension=".png", 
                                      filetypes=[("PNG Files", "*.png")],
                                      initialfile="sensor_label")
    if fp:
        # Save label 1
        base_name = fp.rsplit('.', 1)[0]
        label1_path = f"{base_name}_page1.png"
        label2_path = f"{base_name}_page2.png"
        
        canvas.label1_full.save(label1_path, dpi=(settings.dpi, settings.dpi))
        canvas.label2_full.save(label2_path, dpi=(settings.dpi, settings.dpi))
        
        messagebox.showinfo("Saved", f"Saved labels:\n{label1_path}\n{label2_path}")

btn_save.config(command=save_label)

# Print function
def print_label():
    if canvas.label1_full is None or canvas.label2_full is None:
        messagebox.showwarning("No preview", "Generate the labels first.")
        return
    
    # Get selected printer
    selected_printer = printer_combo.get()
    if not selected_printer or "No printer" in selected_printer:
        messagebox.showerror("Error", "Please select a printer.")
        return
    
    method = connection_method.get()
    
    try:
        if method == "windows" and selected_printer.startswith("Windows:"):
            # Use Windows print spooler
            printer_name = selected_printer.replace("Windows: ", "")
            
            status_label.config(text="Printing Label 1 via Windows...", fg="blue")
            root.update()
            send_to_printer_windows(canvas.label1_full, printer_name)
            
            root.after(500)
            
            status_label.config(text="Printing Label 2 via Windows...", fg="blue")
            root.update()
            send_to_printer_windows(canvas.label2_full, printer_name)
            
            status_label.config(text="✓ Both labels sent successfully!", fg="green")
            messagebox.showinfo("Success", f"Both labels sent to {printer_name}!")
            
        elif method == "usb" and selected_printer.startswith("USB:"):
            # Use direct USB
            usb_devices = find_godex_printer()
            if not usb_devices:
                raise Exception("USB device not found")
            
            device = usb_devices[0]['device']
            
            status_label.config(text="Printing Label 1 via USB...", fg="blue")
            root.update()
            ezpl1 = generate_ezpl_label(canvas.label1_full, 1)
            send_to_printer_usb(ezpl1, device)
            
            root.after(500)
            
            status_label.config(text="Printing Label 2 via USB...", fg="blue")
            root.update()
            ezpl2 = generate_ezpl_label(canvas.label2_full, 2)
            send_to_printer_usb(ezpl2, device)
            
            status_label.config(text="✓ Both labels sent successfully!", fg="green")
            messagebox.showinfo("Success", "Both labels sent via USB!")
            
        else:
            messagebox.showerror("Error", "Please select matching printer and connection method.")
        
    except Exception as e:
        status_label.config(text="✗ Print failed", fg="red")
        messagebox.showerror("Print Error", f"Could not print:\n{e}\n\nTry:\n1. Check USB connection\n2. Install Godex driver\n3. Use Windows Print Spooler method")

btn_print.config(command=print_label)

# Default Sensor ID
entry.insert(0, "12-23-12345-123456")
update_preview()

root.mainloop()