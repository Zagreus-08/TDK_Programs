"""
Godex Label Generator - Creates GoLabel compatible output
Prints 2 labels: 
  Label 1: CONFIDENTIAL + TDK Logo + BMS-SENSOR-05
  Label 2: Sensor ID + QR Code
"""
import tkinter as tk
from tkinter import messagebox, filedialog
from PIL import Image, ImageDraw, ImageFont, ImageTk
import qrcode
import os
import subprocess

# Configuration for 20mm x 8mm label at 300 DPI (GoLabel default)
DPI = 300
WIDTH_MM, HEIGHT_MM = 20, 8
WIDTH_PX = int((WIDTH_MM / 25.4) * DPI)  # ~236 pixels
HEIGHT_PX = int((HEIGHT_MM / 25.4) * DPI)  # ~94 pixels

TDK_LOGO_PATH = r"C:\Users\a493353\Downloads\TDK-Logo.png"

try:
    RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE = Image.ANTIALIAS

_images = {}

def load_tdk_logo():
    try:
        logo = Image.open(TDK_LOGO_PATH).convert("RGBA")
        logo_w, logo_h = logo.size
        new_h = int(HEIGHT_PX * 0.30)  # 30% of label height
        new_w = int((logo_w / logo_h) * new_h)
        return logo.resize((new_w, new_h), RESAMPLE)
    except:
        return None

def make_label1():
    """Label 1: CONFIDENTIAL + TDK Logo + BMS-SENSOR-05"""
    label = Image.new("RGB", (WIDTH_PX, HEIGHT_PX), "white")
    draw = ImageDraw.Draw(label)
    
    try:
        font_conf = ImageFont.truetype("arial.ttf", int(HEIGHT_PX * 0.20))
        font_bms = ImageFont.truetype("arialbd.ttf", int(HEIGHT_PX * 0.22))
    except:
        font_conf = font_bms = ImageFont.load_default()
    
    # CONFIDENTIAL at top
    conf_text = "CONFIDENTIAL"
    bbox = draw.textbbox((0, 0), conf_text, font=font_conf)
    conf_w = bbox[2] - bbox[0]
    draw.text(((WIDTH_PX - conf_w) // 2, 2), conf_text, font=font_conf, fill="black")
    
    # TDK Logo in center
    logo = load_tdk_logo()
    if logo:
        logo_w, logo_h = logo.size
        label.paste(logo, ((WIDTH_PX - logo_w) // 2, int(HEIGHT_PX * 0.28)), logo)
    
    # BMS-SENSOR-05 at bottom
    bms_text = "BMS-SENSOR-05"
    bbox = draw.textbbox((0, 0), bms_text, font=font_bms)
    bms_w = bbox[2] - bbox[0]
    draw.text(((WIDTH_PX - bms_w) // 2, int(HEIGHT_PX * 0.68)), bms_text, font=font_bms, fill="black")
    
    return label

def make_label2(sensor_id):
    """Label 2: Sensor ID + QR Code"""
    label = Image.new("RGB", (WIDTH_PX, HEIGHT_PX), "white")
    draw = ImageDraw.Draw(label)
    
    try:
        font_sensor = ImageFont.truetype("arial.ttf", int(HEIGHT_PX * 0.22))
    except:
        font_sensor = ImageFont.load_default()
    
    # QR Code on right side (90% of height)
    qr_size = int(HEIGHT_PX * 0.90)
    qr = qrcode.make(sensor_id)
    qr = qr.resize((qr_size, qr_size), RESAMPLE)
    label.paste(qr, (WIDTH_PX - qr_size - 5, (HEIGHT_PX - qr_size) // 2))
    
    # Sensor ID text on left
    lines = sensor_id.split('-') if '-' in sensor_id else [sensor_id[i:i+6] for i in range(0, len(sensor_id), 6)]
    text = "\n".join(lines)
    draw.multiline_text((5, 5), text, font=font_sensor, fill="black", spacing=1)
    
    return label

# GUI
root = tk.Tk()
root.title("Godex Label Generator for GoLabel")
root.geometry("500x600")

tk.Label(root, text="Godex RT863i Label Generator", font=("Arial", 14, "bold")).pack(pady=10)
tk.Label(root, text="Creates labels for 20mm x 8mm die-cut stock", font=("Arial", 10)).pack()

tk.Label(root, text="Enter Sensor ID:", font=("Arial", 11)).pack(pady=(20, 5))
entry = tk.Entry(root, width=30, font=("Arial", 12))
entry.pack(pady=5)
entry.insert(0, "12-23-12345-123456")

# Preview frame
preview_frame = tk.LabelFrame(root, text="Preview", padx=10, pady=10)
preview_frame.pack(pady=20, padx=20, fill="x")

canvas1 = tk.Canvas(preview_frame, width=240, height=100, bg="white", relief="sunken", bd=2)
canvas1.pack(pady=5)
tk.Label(preview_frame, text="Label 1: CONFIDENTIAL + TDK + BMS", font=("Arial", 9)).pack()

canvas2 = tk.Canvas(preview_frame, width=240, height=100, bg="white", relief="sunken", bd=2)
canvas2.pack(pady=5)
tk.Label(preview_frame, text="Label 2: Sensor ID + QR Code", font=("Arial", 9)).pack()

def update_preview():
    sensor_id = entry.get().strip()
    if not sensor_id:
        return
    
    label1 = make_label1()
    label2 = make_label2(sensor_id)
    
    # Scale for preview
    preview1 = label1.resize((236, 94), RESAMPLE)
    preview2 = label2.resize((236, 94), RESAMPLE)
    
    _images['p1'] = ImageTk.PhotoImage(preview1)
    _images['p2'] = ImageTk.PhotoImage(preview2)
    
    canvas1.delete("all")
    canvas1.create_image(120, 50, image=_images['p1'])
    canvas2.delete("all")
    canvas2.create_image(120, 50, image=_images['p2'])

tk.Button(root, text="Generate Preview", command=update_preview, 
         font=("Arial", 10)).pack(pady=10)

def save_and_print():
    sensor_id = entry.get().strip()
    if not sensor_id:
        messagebox.showwarning("Input Required", "Please enter a Sensor ID.")
        return
    
    # Generate labels
    label1 = make_label1()
    label2 = make_label2(sensor_id)
    
    # Save to temp folder
    temp_folder = os.path.join(os.environ.get('TEMP', '.'), 'godex_labels')
    os.makedirs(temp_folder, exist_ok=True)
    
    safe_id = sensor_id.replace('/', '-').replace('\\', '-').replace(':', '-')
    path1 = os.path.join(temp_folder, f"Label1_{safe_id}.png")
    path2 = os.path.join(temp_folder, f"Label2_{safe_id}.png")
    
    # Save at 300 DPI for GoLabel
    label1.save(path1, dpi=(DPI, DPI))
    label2.save(path2, dpi=(DPI, DPI))
    
    # Try to open with default image viewer for printing
    try:
        os.startfile(path1, "print")
        root.after(2000, lambda: os.startfile(path2, "print"))
        messagebox.showinfo("Printing", 
                           f"Labels sent to printer!\n\n"
                           f"If labels don't print correctly:\n"
                           f"1. Open GoLabel software\n"
                           f"2. Create new label (20mm x 8mm)\n"
                           f"3. Insert > Image > select PNG file\n"
                           f"4. Resize to fit label\n"
                           f"5. Print\n\n"
                           f"Files saved at:\n{temp_folder}")
    except Exception as e:
        messagebox.showerror("Error", f"Could not print: {e}")

def save_only():
    sensor_id = entry.get().strip()
    if not sensor_id:
        messagebox.showwarning("Input Required", "Please enter a Sensor ID.")
        return
    
    folder = filedialog.askdirectory(title="Select folder to save labels")
    if not folder:
        return
    
    label1 = make_label1()
    label2 = make_label2(sensor_id)
    
    safe_id = sensor_id.replace('/', '-').replace('\\', '-').replace(':', '-')
    path1 = os.path.join(folder, f"Label1_CONFIDENTIAL_{safe_id}.png")
    path2 = os.path.join(folder, f"Label2_SENSOR_{safe_id}.png")
    
    label1.save(path1, dpi=(DPI, DPI))
    label2.save(path2, dpi=(DPI, DPI))
    
    messagebox.showinfo("Saved", 
                       f"Labels saved!\n\n"
                       f"{path1}\n{path2}\n\n"
                       f"To print in GoLabel:\n"
                       f"1. Open GoLabel\n"
                       f"2. File > New > Set 20mm x 8mm\n"
                       f"3. Insert > Image\n"
                       f"4. Select PNG and resize to fit\n"
                       f"5. Print")
    os.startfile(folder)

btn_frame = tk.Frame(root)
btn_frame.pack(pady=20)

tk.Button(btn_frame, text="Save Labels", command=save_only,
         font=("Arial", 11), padx=20, pady=10).pack(side="left", padx=10)

tk.Button(btn_frame, text="Print Labels", command=save_and_print,
         font=("Arial", 11, "bold"), bg="lightgreen", padx=20, pady=10).pack(side="left", padx=10)

tk.Label(root, text="Tip: For best results, use GoLabel software\nto import and print the PNG files",
        font=("Arial", 9), fg="gray").pack(pady=10)

# Initial preview
update_preview()

root.mainloop()
