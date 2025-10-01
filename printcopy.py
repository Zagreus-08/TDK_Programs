import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageDraw, ImageFont, ImageTk
import qrcode
import os
import tempfile

# ----------------------------
# Configuration
# ----------------------------
MM_TO_INCH = 1 / 25.4
DPI = 203
WIDTH_MM, HEIGHT_MM = 19, 18
WIDTH_PX = int(WIDTH_MM * DPI * MM_TO_INCH)
HEIGHT_PX = int(HEIGHT_MM * DPI * MM_TO_INCH)

# GUI preview settings
PREVIEW_W, PREVIEW_H = 190, 180
SCALE_F = PREVIEW_W / WIDTH_PX

positions_preview = {
    "sensor": (23, -105),
    "confidential": (30, 105),
    "tdk_logo": (20, 100),
    "bms": (20, 158),
}

canvas_items = {
    "bg": None,
    "sensor": None,
    "confidential": None,
    "tdk_logo": None,
    "bms": None,
}

_global_images = {}

try:
    RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE = Image.ANTIALIAS

TDK_LOGO_PATH = r"C:\Users\a493353\Downloads\TDK-Logo.png"

def load_pillow_fonts(height_px):
    try:
        font_large = ImageFont.truetype("arialbd.ttf", int(height_px * 0.19))
        font_medium = ImageFont.truetype("arial.ttf", int(height_px * 0.10))
        font_small = ImageFont.truetype("arial.ttf", int(height_px * 0.10))
        font_bms = ImageFont.truetype("arialbd.ttf", int(height_px * 0.14))
    except Exception:
        font_large = font_medium = font_small = font_bms = ImageFont.load_default()
    return font_large, font_medium, font_small, font_bms

# ---------- Label 1 (TDK Logo Version) ----------
def make_base_and_sensor_images(sensor_text):
    base = Image.new("RGB", (WIDTH_PX, HEIGHT_PX), "white")
    qr_size = int(HEIGHT_PX * 0.48)
    qr = qrcode.make(sensor_text)
    qr = qr.resize((qr_size, qr_size), RESAMPLE)
    base.paste(qr, (WIDTH_PX - qr_size - 15, 10))

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

    sensor_img_full = Image.new("RGBA", (HEIGHT_PX, 200), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sensor_img_full)
    sd.multiline_text((0, 0), sensor_multiline, font=font_small, fill=(0, 0, 0, 255), spacing=2)
    rotated_sensor_full = sensor_img_full.rotate(90, expand=True)

    return base, rotated_sensor_full

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
        messagebox.showerror("Error", f"TDK logo file not found at: {TDK_LOGO_PATH}")
        return None
    except Exception as e:
        messagebox.showerror("Error", f"Could not load TDK logo: {e}")
        return None

def make_preview_images(base_full, sensor_full, tdk_logo_full):
    preview_base = base_full.resize((PREVIEW_W, PREVIEW_H), RESAMPLE)
    f = SCALE_F
    w_s, h_s = sensor_full.size
    preview_sensor = sensor_full.resize((max(1, int(w_s * f)), max(1, int(h_s * f))), RESAMPLE)
    if tdk_logo_full:
        w_l, h_l = tdk_logo_full.size
        preview_tdk_logo = tdk_logo_full.resize((max(1, int(w_l * f)), max(1, int(h_l * f))), RESAMPLE)
    else:
        preview_tdk_logo = None
    return preview_base, preview_sensor, preview_tdk_logo

def compose_final_image(base_full, sensor_full, tdk_logo_full, positions_preview_local):
    final = base_full.copy()
    draw = ImageDraw.Draw(final)
    font_large, font_medium, font_small, font_bms = load_pillow_fonts(HEIGHT_PX)

    px, py = positions_preview_local["sensor"]
    full_x = int(px / SCALE_F)
    full_y = int(py / SCALE_F)
    final.paste(sensor_full, (full_x, full_y), sensor_full)

    draw.text((int(positions_preview_local["confidential"][0] / SCALE_F),
               int(positions_preview_local["confidential"][1] / SCALE_F)),
              "CONFIDENTIAL", font=font_medium, fill="black")

    if tdk_logo_full:
        logo_x = int(positions_preview_local["tdk_logo"][0] / SCALE_F)
        logo_y = int(positions_preview_local["tdk_logo"][1] / SCALE_F)
        final.paste(tdk_logo_full, (logo_x, logo_y), tdk_logo_full)

    draw.text((int(positions_preview_local["bms"][0] / SCALE_F),
               int(positions_preview_local["bms"][1] / SCALE_F)),
              "BMS-SENSOR-05", font=font_small, fill="black")

    return final

# ---------- Label 2 (QR + Sensor Only) ----------
def compose_qr_only_label(sensor_text):
    qr_only = Image.new("RGB", (WIDTH_PX, HEIGHT_PX), "white")
    qr_size = int(HEIGHT_PX * 0.48)
    qr = qrcode.make(sensor_text)
    qr = qr.resize((qr_size, qr_size), RESAMPLE)
    qr_only.paste(qr, (WIDTH_PX - qr_size - 15, 10))

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

    sensor_img_full = Image.new("RGBA", (HEIGHT_PX, 200), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sensor_img_full)
    sd.multiline_text((0, 0), sensor_multiline, font=font_small, fill=(0, 0, 0, 255), spacing=2)
    rotated_sensor_full = sensor_img_full.rotate(90, expand=True)

    # Paste text on left
    qr_only.paste(rotated_sensor_full, (10, 0), rotated_sensor_full)
    return qr_only

# -------------------------
# GUI
# -------------------------
root = tk.Tk()
root.title("TDK Sensor Label Generator (dual print)")

tk.Label(root, text="Enter Sensor ID:").pack(pady=5)
entry = tk.Entry(root, width=30)
entry.pack(pady=5)

btn_generate = tk.Button(root, text="Generate Label")
btn_generate.pack(pady=5)
btn_save = tk.Button(root, text="Save Label")
btn_save.pack(pady=5)
btn_print = tk.Button(root, text="Print Label")
btn_print.pack(pady=5)

canvas = tk.Canvas(root, width=PREVIEW_W + 10, height=PREVIEW_H + 10, bg="grey")
canvas.pack(pady=10)

blank_preview = Image.new("RGB", (PREVIEW_W, PREVIEW_H), "white")
blank_photo = ImageTk.PhotoImage(blank_preview, master=root)
_global_images["blank"] = blank_photo
canvas_bg = canvas.create_image(5, 5, anchor="nw", image=blank_photo)

canvas.base_full = None
canvas.sensor_full = None
canvas.tdk_logo_full = None

canvas_items["sensor"] = canvas.create_image(positions_preview["sensor"][0] + 5,
                                             positions_preview["sensor"][1] + 5,
                                             anchor="nw", image=None, tags=("sensor",))
canvas_items["confidential"] = canvas.create_text(positions_preview["confidential"][0] + 5,
                                                 positions_preview["confidential"][1] + 5,
                                                 text="CONFIDENTIAL", anchor="nw", tags=("confidential",))
canvas_items["tdk_logo"] = canvas.create_image(positions_preview["tdk_logo"][0] + 5,
                                             positions_preview["tdk_logo"][1] + 5,
                                             anchor="nw", image=None, tags=("tdk_logo",))
canvas_items["bms"] = canvas.create_text(positions_preview["bms"][0] + 5,
                                         positions_preview["bms"][1] + 5,
                                         text="BMS-SENSOR-05", anchor="nw", tags=("bms",))

drag_data = {"item": None, "x": 0, "y": 0}

def on_button_press(event):
    items = canvas.find_overlapping(event.x, event.y, event.x, event.y)
    if items:
        item = items[-1]
        if item != canvas_bg:
            drag_data["item"] = item
            drag_data["x"] = event.x
            drag_data["y"] = event.y

def on_motion(event):
    item = drag_data.get("item")
    if item:
        dx = event.x - drag_data["x"]
        dy = event.y - drag_data["y"]
        canvas.move(item, dx, dy)
        drag_data["x"] = event.x
        drag_data["y"] = event.y
        tag = canvas.gettags(item)[0]
        coords = canvas.coords(item)
        positions_preview[tag] = (coords[0] - 5, coords[1] - 5)

def on_button_release(event):
    drag_data["item"] = None

canvas.bind("<ButtonPress-1>", on_button_press)
canvas.bind("<B1-Motion>", on_motion)
canvas.bind("<ButtonRelease-1>", on_button_release)

def update_preview():
    s = entry.get().strip()
    base_full, sensor_full = make_base_and_sensor_images(s)
    tdk_logo_full = load_tdk_logo(HEIGHT_PX)

    canvas.base_full = base_full
    canvas.sensor_full = sensor_full
    canvas.tdk_logo_full = tdk_logo_full

    preview_base, preview_sensor, preview_tdk_logo = make_preview_images(base_full, sensor_full, tdk_logo_full)
    ph = ImageTk.PhotoImage(preview_base, master=root)
    _global_images["preview_base"] = ph
    canvas.itemconfig(canvas_bg, image=ph)

    ps = ImageTk.PhotoImage(preview_sensor, master=root)
    _global_images["preview_sensor"] = ps
    canvas.itemconfig(canvas_items["sensor"], image=ps)
    canvas.coords(canvas_items["sensor"], positions_preview["sensor"][0] + 5, positions_preview["sensor"][1] + 5)

    if preview_tdk_logo:
        pl = ImageTk.PhotoImage(preview_tdk_logo, master=root)
        _global_images["preview_tdk_logo"] = pl
        canvas.itemconfig(canvas_items["tdk_logo"], image=pl)
        canvas.coords(canvas_items["tdk_logo"], positions_preview["tdk_logo"][0] + 5, positions_preview["tdk_logo"][1] + 5)
    else:
        canvas.itemconfig(canvas_items["tdk_logo"], image=None)

btn_generate.config(command=update_preview)

def save_label():
    if canvas.base_full is None:
        messagebox.showwarning("No preview", "Generate the label first.")
        return
    final = compose_final_image(canvas.base_full, canvas.sensor_full, canvas.tdk_logo_full, positions_preview)
    if final:
        fp = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG Files", "*.png")])
        if fp:
            final.save(fp, dpi=(DPI, DPI))
            messagebox.showinfo("Saved", f"Saved label to: {fp}")

btn_save.config(command=save_label)

def print_label():
    if canvas.base_full is None:
        messagebox.showwarning("No preview", "Generate the label first.")
        return

    sensor_text = entry.get().strip()

    # Label 1: Full TDK
    final1 = compose_final_image(canvas.base_full, canvas.sensor_full, canvas.tdk_logo_full, positions_preview)
    temp_dir = tempfile.gettempdir()
    temp_path1 = os.path.join(temp_dir, "temp_label1.png")
    final1.save(temp_path1, dpi=(DPI, DPI))
    if os.name == 'nt':
        os.startfile(temp_path1, "print")

    # Label 2: QR Only
    final2 = compose_qr_only_label(sensor_text)
    temp_path2 = os.path.join(temp_dir, "temp_label2.png")
    final2.save(temp_path2, dpi=(DPI, DPI))
    if os.name == 'nt':
        os.startfile(temp_path2, "print")

btn_print.config(command=print_label)

entry.insert(0, "12-23-12345-123456")
update_preview()

root.mainloop()
