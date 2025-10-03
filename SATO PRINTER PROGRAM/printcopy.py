import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageDraw, ImageFont, ImageTk, ImageWin
import qrcode
import os
import tempfile
import subprocess
import win32print
import win32ui

# ---- Label and preview sizing ----
MM_TO_INCH = 1 / 25.4
DPI = 203
WIDTH_MM, HEIGHT_MM = 19, 18
WIDTH_PX = int(WIDTH_MM * DPI * MM_TO_INCH)   # ~720
HEIGHT_PX = int(HEIGHT_MM * DPI * MM_TO_INCH) # ~400

PREVIEW_W, PREVIEW_H = 190, 180
SCALE_F = PREVIEW_W / WIDTH_PX

# ---- Layout positions (preview-space coords) ----
positions_preview_page1 = {
    "confidential": (35, 50),
    "tdk_logo": (25, 50),
    "bms": (25, 110),
}

positions_preview_page2 = {
    "sensor": (50, -55),
}

canvas_items_page1 = {
    "bg": None,
    "confidential": None,
    "tdk_logo": None,
    "bms": None,
}

canvas_items_page2 = {
    "bg": None,
    "sensor": None,
}

_global_images = {}

# ---- Pillow resample mode ----
try:
    RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE = Image.ANTIALIAS

TDK_LOGO_PATH = r"C:\Users\a493353\Downloads\TDK-Logo.png"

# ---- Fonts ----
def load_pillow_fonts(height_px):
    try:
        font_large = ImageFont.truetype("arialbd.ttf", int(height_px * 0.19))
        font_medium = ImageFont.truetype("arial.ttf", int(height_px * 0.10))
        font_small = ImageFont.truetype("arial.ttf", int(height_px * 0.12))
        font_bms = ImageFont.truetype("arialbd.ttf", int(height_px * 0.10))
    except Exception:
        font_large = font_medium = font_small = font_bms = ImageFont.load_default()
    return font_large, font_medium, font_small, font_bms

# ---- Page generators ----
def make_page1_image():
    page1 = Image.new("RGB", (WIDTH_PX, HEIGHT_PX), "white")
    draw = ImageDraw.Draw(page1)
    _, font_medium, _, font_bms = load_pillow_fonts(HEIGHT_PX)

    # "CONFIDENTIAL" text
    draw.text(
        (int(positions_preview_page1["confidential"][0] / SCALE_F),
         int(positions_preview_page1["confidential"][1] / SCALE_F)),
        "CONFIDENTIAL", font=font_medium, fill="black"
    )

    # TDK logo
    tdk_logo = load_tdk_logo(HEIGHT_PX)
    if tdk_logo:
        logo_x = int(positions_preview_page1["tdk_logo"][0] / SCALE_F)
        logo_y = int(positions_preview_page1["tdk_logo"][1] / SCALE_F)
        page1.paste(tdk_logo, (logo_x, logo_y), tdk_logo)

    # BMS text
    draw.text(
        (int(positions_preview_page1["bms"][0] / SCALE_F),
         int(positions_preview_page1["bms"][1] / SCALE_F)),
        "BMS-SENSOR-05", font=font_bms, fill="black"
    )

    return page1, tdk_logo

def make_page2_image(sensor_text):
    page2 = Image.new("RGB", (WIDTH_PX, HEIGHT_PX), "white")

    # QR code
    qr_size = int(HEIGHT_PX * 0.50)
    qr = qrcode.make(sensor_text)
    qr = qr.resize((qr_size, qr_size), RESAMPLE)
    page2.paste(qr, (WIDTH_PX - qr_size - 10, 35))

    # Sensor ID text (wrapped and rotated)
    _, _, font_small, _ = load_pillow_fonts(HEIGHT_PX)
    parts = []
    s = sensor_text or ""
    if len(s) > 0:
        parts.append(s[:6])
    if len(s) > 6:
        parts.append(s[6:12])
    if len(s) > 12:
        parts.append(s[12:])
    sensor_multiline = "\n".join(parts)

    sensor_img_full = Image.new("RGBA", (HEIGHT_PX, 400), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sensor_img_full)
    sd.multiline_text((0, 0), sensor_multiline, font=font_small, fill=(0, 0, 0, 255), spacing=2)
    rotated_sensor_full = sensor_img_full.rotate(90, expand=True)

    px, py = positions_preview_page2["sensor"]
    full_x = int(px / SCALE_F)
    full_y = int(py / SCALE_F)
    page2.paste(rotated_sensor_full, (full_x, full_y), rotated_sensor_full)

    return page2

# ---- Assets ----
def load_tdk_logo(size_px):
    try:
        logo = Image.open(TDK_LOGO_PATH).convert("RGBA")
        logo_w, logo_h = logo.size
        new_h = int(size_px * 0.45)
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

# ---- Print helper (Windows Picture Printer dialog) ----
def open_print_dialog(filepath):
    """Open Windows Print Pictures dialog"""
    if os.name == 'nt':
        try:
            subprocess.Popen(['rundll32.exe', 'shimgvw.dll,ImageView_PrintTo', filepath])
        except Exception:
            os.startfile(filepath, "print")
    else:
        raise Exception("Printing only supported on Windows")

# ---- GUI ----
root = tk.Tk()
root.title("TDK Sensor Label Generator - Two Page (90x50mm)")

tk.Label(root, text="Enter Sensor ID:").pack(pady=5)
entry = tk.Entry(root, width=30)
entry.pack(pady=5)

btn_generate = tk.Button(root, text="Generate Label Preview")
btn_generate.pack(pady=5)

btn_frame = tk.Frame(root)
btn_frame.pack(pady=5)

btn_save = tk.Button(btn_frame, text="Save Both Labels", bg="lightblue")
btn_save.pack(side=tk.LEFT, padx=5)

btn_print_preview = tk.Button(btn_frame, text="Print (with preview)", bg="lightgreen")
btn_print_preview.pack(side=tk.LEFT, padx=5)

btn_print_direct = tk.Button(btn_frame, text="Direct Print", bg="orange")
btn_print_direct.pack(side=tk.LEFT, padx=5)

canvas_frame = tk.Frame(root)
canvas_frame.pack(pady=10)

tk.Label(canvas_frame, text="Page 1: Info", font=("Arial", 10, "bold")).grid(row=0, column=0, padx=5)
tk.Label(canvas_frame, text="Page 2: QR + ID", font=("Arial", 10, "bold")).grid(row=0, column=1, padx=5)

canvas1 = tk.Canvas(canvas_frame, width=PREVIEW_W+10, height=PREVIEW_H+10, bg="grey")
canvas1.grid(row=1, column=0, padx=5)

canvas2 = tk.Canvas(canvas_frame, width=PREVIEW_W+10, height=PREVIEW_H+10, bg="grey")
canvas2.grid(row=1, column=1, padx=5)

blank_preview = Image.new("RGB", (PREVIEW_W, PREVIEW_H), "white")
blank_photo = ImageTk.PhotoImage(blank_preview, master=root)
_global_images["blank"] = blank_photo

canvas1_bg = canvas1.create_image(5, 5, anchor="nw", image=blank_photo)
canvas2_bg = canvas2.create_image(5, 5, anchor="nw", image=blank_photo)

canvas1.page1_full = None
canvas2.page2_full = None

# ---- Preview ----
def update_preview():
    s = entry.get().strip()
    page1_full, _ = make_page1_image()
    page2_full = make_page2_image(s)

    canvas1.page1_full = page1_full
    canvas2.page2_full = page2_full

    preview1 = page1_full.resize((PREVIEW_W, PREVIEW_H), RESAMPLE)
    preview2 = page2_full.resize((PREVIEW_W, PREVIEW_H), RESAMPLE)

    ph1 = ImageTk.PhotoImage(preview1, master=root)
    _global_images["preview1"] = ph1
    canvas1.itemconfig(canvas1_bg, image=ph1)

    ph2 = ImageTk.PhotoImage(preview2, master=root)
    _global_images["preview2"] = ph2
    canvas2.itemconfig(canvas2_bg, image=ph2)

btn_generate.config(command=update_preview)

# ---- Save labels ----
def save_labels():
    if canvas1.page1_full is None or canvas2.page2_full is None:
        messagebox.showwarning("No preview", "Generate the labels first.")
        return

    fp = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG Files", "*.png")])
    if fp:
        base_name = os.path.splitext(fp)[0]
        fp1 = f"{base_name}_page1.png"
        fp2 = f"{base_name}_page2.png"

        canvas1.page1_full.save(fp1, dpi=(DPI, DPI))
        canvas2.page2_full.save(fp2, dpi=(DPI, DPI))
        messagebox.showinfo("Saved", f"Saved:\n{fp1}\n{fp2}")

btn_save.config(command=save_labels)

# ---- Print (with preview dialog) ----
def print_labels_preview():
    if canvas1.page1_full is None or canvas2.page2_full is None:
        messagebox.showwarning("No preview", "Generate the labels first.")
        return

    try:
        temp_dir = tempfile.gettempdir()
        temp_path1 = os.path.join(temp_dir, "temp_label_page1.png")
        temp_path2 = os.path.join(temp_dir, "temp_label_page2.png")

        canvas1.page1_full.save(temp_path1, dpi=(DPI, DPI))
        canvas2.page2_full.save(temp_path2, dpi=(DPI, DPI))

        if os.name == 'nt':
            os.startfile(temp_path1, "print")
            os.startfile(temp_path2, "print")
            messagebox.showinfo("Print", "Both labels sent to printer (via preview).")
        else:
            messagebox.showerror("Error", "Printing is currently only supported on Windows.")
    except Exception as e:
        messagebox.showerror("Print Error", f"Could not print: {e}")

btn_print_preview.config(command=print_labels_preview)

# ---- Direct print to SATO CG408 ----
def print_labels_direct():
    """Generate, save, and silently print through the same driver path as preview."""
    s = entry.get().strip()
    if not s:
        messagebox.showwarning("No ID", "Please enter a Sensor ID first.")
        return

    try:
        # Generate pages (so preview button not required)
        page1_full, _ = make_page1_image()
        page2_full = make_page2_image(s)

        # Save as temp PNG (or BMP)
        temp_dir = tempfile.gettempdir()
        temp1 = os.path.join(temp_dir, "tdk_auto_page1.png")
        temp2 = os.path.join(temp_dir, "tdk_auto_page2.png")
        page1_full.save(temp1, dpi=(203, 203))
        page2_full.save(temp2, dpi=(203, 203))

        # Use the same OS-level print command the preview button uses — but silently
        # This calls the printer driver *exactly* the same way, so positions match.
        os.startfile(temp1, "print")
        os.startfile(temp2, "print")

        messagebox.showinfo("✅ Printing", "Labels are being printed automatically...")

    except Exception as e:
        messagebox.showerror("Print Error", f"Direct print failed: {e}")

btn_print_direct.config(command=print_labels_direct)

# ---- Default state ----
entry.insert(0, "12-23-12345-123456")
update_preview()

root.mainloop()
