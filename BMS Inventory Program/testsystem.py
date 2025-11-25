import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import sqlite3
from datetime import datetime
import json
import win32com.client as win32
import hashlib
import os
import binascii
import sys
from tkcalendar import DateEntry
import csv

# Toggle debug prints
DEBUG = False

# --- Material Design-inspired Theme Colors ---
PRIMARY_BLUE = "#1976D2"
PRIMARY_LIGHT = "#63A4FF"
PRIMARY_DARK = "#004BA0"

ACCENT_ORANGE = "#FF9800"
ACCENT_DARK = "#C66900"

SURFACE_WHITE = "#FFFFFF"
BACKGROUND_GRAY = "#F5F5F5"
TEXT_DARK = "#212121"
TEXT_LIGHT = "#FFFFFF"
TEXT_GRAY = "#757575"
CARD_BG = SURFACE_WHITE
BTN_BG = PRIMARY_BLUE
BTN_ACTIVE = PRIMARY_DARK

# Fonts
FONT = ("Roboto", 10)
HEADER_FONT = ("Roboto", 13, "bold")
TITLE_FONT = ("Roboto", 18, "bold")
SMALL_FONT = ("Roboto", 9)

PBKDF2_ITER = 100_000
SALT_BYTES = 16

# ---------- CONFIGURATION ----------
DATA_DIR = r"\\phlsvr08\BMS Data\Lot ID's\Database\Inventory_System"
DB_PATH = os.path.join(DATA_DIR, "inventory.db")
EMAIL_JSON_PATH = os.path.join(DATA_DIR, "email_recipients.json")

# --- CONFIGURATION: LOAD EMAIL RECIPIENTS FROM JSON FILE ---
def load_email_recipients():
    try:
        with open(EMAIL_JSON_PATH, 'r') as file:
            data = json.load(file)
            return data.get('recipient_emails', []), data.get('cc_emails', []), data.get('bcc_emails', [])
    except FileNotFoundError:
        if DEBUG:
            print("email_recipients.json not found.")
        return [], [], []
    except json.JSONDecodeError:
        print("Invalid JSON in email_recipients.json")
        return [], [], []

TO_EMAILS, CC_EMAILS, BCC_EMAILS = load_email_recipients()

# -------- Password hashing helpers (PBKDF2) --------
def hash_password(password: str) -> str:
    salt = os.urandom(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, PBKDF2_ITER)
    return f"{binascii.hexlify(salt).decode()}${binascii.hexlify(dk).decode()}"

def verify_password(stored: str, provided_password: str) -> bool:
    try:
        salt_hex, hash_hex = stored.split('$')
        salt = binascii.unhexlify(salt_hex.encode())
        dk = hashlib.pbkdf2_hmac('sha256', provided_password.encode('utf-8'), salt, PBKDF2_ITER)
        return binascii.hexlify(dk).decode() == hash_hex
    except Exception:
        return False

# ----------- DATABASE SETUP -----------
def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # existing tables
    c.execute('''CREATE TABLE IF NOT EXISTS groupings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS materials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        description TEXT NOT NULL,
        part_number TEXT,
        model_specs TEXT,
        storage_location TEXT,
        maintaining_stock INTEGER,
        quantity_on_hand INTEGER,
        category TEXT,
        project TEXT,
        grouping_id INTEGER,
        FOREIGN KEY(grouping_id) REFERENCES groupings(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        material_id INTEGER,
        quantity INTEGER,
        date TEXT,
        withdrawn_by TEXT,
        issued_by TEXT,
        purpose TEXT,
        FOREIGN KEY(material_id) REFERENCES materials(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS received_parts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pr_id INTEGER,
        po_number TEXT,
        material_id INTEGER,
        material_name TEXT,
        quantity INTEGER,
        received_by TEXT,
        requestor TEXT,
        date TEXT,
        FOREIGN KEY (pr_id) REFERENCES purchase_requests (id),
        FOREIGN KEY (material_id) REFERENCES materials (id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        name TEXT,
        password TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('admin','normal'))
    )''')

    # New tables for assemblies
    c.execute('''CREATE TABLE IF NOT EXISTS assemblies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS assembly_parts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        assembly_id INTEGER NOT NULL,
        material_id INTEGER NOT NULL,
        quantity_needed INTEGER NOT NULL,
        FOREIGN KEY (assembly_id) REFERENCES assemblies(id),
        FOREIGN KEY (material_id) REFERENCES materials(id)
    )''')

    # -------- NEW: Purchase Requests (PR) table --------
    c.execute('''
        CREATE TABLE IF NOT EXISTS purchase_requests (
            id INTEGER PRIMARY KEY,
            material_id INTEGER,
            purpose TEXT,
            quantity INTEGER,
            quantity_remaining INTEGER,
            requestor TEXT,
            status TEXT,
            po_number TEXT,
            date_requested TEXT,
            date_closed TEXT,
            estimated_delivery_date TEXT,
            FOREIGN KEY (material_id) REFERENCES materials(id)
        )
    ''')

    # -------- NEW: Low Stock Dashboard table --------
    c.execute('''
        CREATE TABLE IF NOT EXISTS low_stock_dashboard (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            material_id INTEGER UNIQUE,
            remarks TEXT,
            last_updated TEXT,
            FOREIGN KEY (material_id) REFERENCES materials(id)
        )
    ''')

    conn.commit()

    # Default admin if no users
    c.execute("SELECT COUNT(*) FROM users")
    count = c.fetchone()[0]
    if count == 0:
        default_user = "admin"
        default_name = "Administrator"
        default_pass = "admin"
        hashed = hash_password(default_pass)
        c.execute("INSERT INTO users (username, name, password, role) VALUES (?, ?, ?, ?)", (default_user, default_name, hashed, "admin"))
        conn.commit()
        if DEBUG:
            print("Created default admin/admin account. Please change password on first login.")
    conn.close()

# Send an Outlook email (using JSON recipients)
def send_outlook_email(to_emails, cc_emails, bcc_emails, subject, body):
    try:
        outlook = win32.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)
        for email in to_emails:
            if email:
                mail.Recipients.Add(email)
        for email in cc_emails:
            if email:
                r = mail.Recipients.Add(email); r.Type = 2
        for email in bcc_emails:
            if email:
                r = mail.Recipients.Add(email); r.Type = 3
        mail.Recipients.ResolveAll()
        mail.Subject = subject
        mail.Body = body
        mail.Send()
        if DEBUG:
            print("Email sent successfully.")
    except Exception as e:
        if DEBUG:
            print(f"Failed to send email: {e}")
        try:
            messagebox.showwarning("Email Alert Failed", "Could not send Outlook email. Please ensure Outlook is installed and configured.")
        except Exception:
            pass

# ----------- User management DB helpers -----------
def get_user_by_username(username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, name, password, role FROM users WHERE username = ?", (username,))
    row = c.fetchone()
    conn.close()
    return row

def list_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, name, role FROM users ORDER BY username")
    rows = c.fetchall()
    conn.close()
    return rows

def create_user(username, name, password, role='normal'):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    hashed = hash_password(password)
    try:
        c.execute("INSERT INTO users (username, name, password, role) VALUES (?, ?, ?, ?)",
                  (username, name, hashed, role))
        conn.commit()
        return True, None
    except sqlite3.IntegrityError as e:
        return False, str(e)
    finally:
        conn.close()

def update_user_role(user_id, new_role):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
    conn.commit()
    conn.close()

def reset_user_password(user_id, new_password):
    hashed = hash_password(new_password)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET password = ? WHERE id = ?", (hashed, user_id))
    conn.commit()
    conn.close()

def delete_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

def change_own_password(user_id, old_password, new_password):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT password FROM users WHERE id = ?", (user_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return False, "User not found."
    stored = row[0]
    if not verify_password(stored, old_password):
        conn.close()
        return False, "Current password is incorrect."
    hashed = hash_password(new_password)
    c.execute("UPDATE users SET password = ? WHERE id = ?", (hashed, user_id))
    conn.commit()
    conn.close()
    return True, None

# ----------- Theming helpers -----------
def apply_material_style(root):
    root.config(bg=BACKGROUND_GRAY)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure("TFrame", background=BACKGROUND_GRAY)
    style.configure("Heading.TLabel", background=BACKGROUND_GRAY, foreground=TEXT_DARK, font=("Roboto", 18, "bold"))
    style.configure("Info.TLabel", background=BACKGROUND_GRAY, foreground=TEXT_GRAY, font=("Roboto", 12))
    style.configure("Primary.TButton", background=PRIMARY_BLUE, foreground=TEXT_LIGHT, borderwidth=0, relief="flat", font=("Roboto", 10, "bold"), padding=[15,8])
    style.map("Primary.TButton", background=[("active", PRIMARY_DARK)])
    style.configure("Accent.TButton", background=ACCENT_ORANGE, foreground=TEXT_LIGHT, borderwidth=0, relief="flat", font=("Roboto", 10, "bold"), padding=[15,8])
    style.map("Accent.TButton", background=[("active", ACCENT_DARK)])
    style.configure("TEntry", fieldbackground=SURFACE_WHITE, foreground=TEXT_DARK, borderwidth=1, relief="groove", padding=[5,5], font=("Roboto", 6))
    style.map("TEntry", fieldbackground=[('disabled', '#E0E0E0'), ('!disabled', SURFACE_WHITE)])
    style.configure("TCombobox", fieldbackground=SURFACE_WHITE, foreground=TEXT_DARK, background=SURFACE_WHITE, relief="flat", padding=[5,5], font=("Roboto", 6))
    style.map("TCombobox", fieldbackground=[('disabled', '#E0E0E0'), ('!disabled', SURFACE_WHITE)])
    style.configure("Treeview", background=SURFACE_WHITE, fieldbackground=SURFACE_WHITE, foreground=TEXT_DARK, rowheight=30, font=("Roboto", 8))
    style.configure("Treeview.Heading", background=PRIMARY_BLUE, foreground=TEXT_LIGHT, font=("Roboto", 8, "bold"))
    style.map("Treeview", background=[('selected', PRIMARY_DARK)], foreground=[('selected', 'white')])
    style.configure("Vertical.TScrollbar", background=BACKGROUND_GRAY, troughcolor=SURFACE_WHITE)

# ----------- MAIN APP CLASS -----------
class InventoryApp:
    def __init__(self, root, current_user):
        self.root = root
        self.current_user = current_user
        self.root.title(f"BMS Material Inventory - {self.current_user['name']} ({self.current_user['role']})")
        try:
            self.root.state('zoomed')
        except Exception:
            try:
                self.root.attributes('-zoomed', True)
            except Exception:
                pass

        apply_material_style(self.root)
        self.create_widgets()
        # ensure low stock dashboard is in sync at startup
        self.sync_all_low_stock()
        self.load_data()
        self.category_combobox.set("")
        self.grouping_combobox.set("")
        self.assemblies_map = {}
        self.load_assemblies_map()
        self.root.after(100, self.clear_filter)

    def wrap_text(self, text, every=20):
        if not text:
            return ""
        text = str(text)
        return '\n'.join(text[i:i+every] for i in range(0, len(text), every))

    def autofit_columns(self):
        for col in self.tree["columns"]:
            max_width = len(col)
            for item in self.tree.get_children():
                cell_text = str(self.tree.set(item, col))
                for line in cell_text.split("\n"):
                    if len(line) > max_width:
                        max_width = len(line)
            self.tree.column(col, width=(max_width * 7))
            
    
    # ---------------- Dashboards (with Export buttons) ----------------
    def export_treeview_to_csv(self, tree, file_title, parent=None):    
        try:
            filepath = filedialog.asksaveasfilename(parent=parent, defaultextension=".csv",
                                                      filetypes=[("CSV files","*.csv")],
                                                      initialfile=f"{file_title}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
            if not filepath:
                return
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                header = [tree.heading(col)["text"] for col in tree["columns"]]
                writer.writerow(header)
                for item in tree.get_children():
                    row = [tree.set(item, col) for col in tree["columns"]]
                    writer.writerow(row)
            messagebox.showinfo("Export Successful", f"Data exported to {filepath}", parent=parent)
        except Exception as e:
            messagebox.showerror("Export Failed", f"An error occurred: {e}", parent=parent)

    def create_widgets(self):
        # Menu bar
        menubar = tk.Menu(self.root, bg=BACKGROUND_GRAY, fg=TEXT_DARK)
        user_menu = tk.Menu(menubar, tearoff=0, bg=BACKGROUND_GRAY, fg=TEXT_DARK)
        user_menu.add_command(label="Change Password", command=self.change_password_window)
        if self.current_user['role'] == 'admin':
            user_menu.add_command(label="Manage Users", command=self.open_manage_users)
        user_menu.add_separator()
        user_menu.add_command(label="Logout", command=self.logout)
        menubar.add_cascade(label="User", menu=user_menu)
        self.root.config(menu=menubar)

        # Top search frame
        top_frame = ttk.Frame(self.root, style="Dark.TFrame")
        top_frame.pack(fill="x", padx=12, pady=(10,6))

        lbl_search = tk.Label(top_frame, text="Search:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT)
        lbl_search.pack(side="left")
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(top_frame, textvariable=self.search_var, style="Dark.TEntry", width=30)
        search_entry.pack(side="left", padx=8)
        btn_filter = ttk.Button(top_frame, text="Filter", style="Dark.TButton", command=self.load_data)
        btn_filter.pack(side="left", padx=6)
        btn_clear_filter = ttk.Button(top_frame, text="Clear Filter", style="Dark.TButton", command=self.clear_filter)
        btn_clear_filter.pack(side="left", padx=6)
        
        # Add new export button for main window
        btn_export_main = ttk.Button(top_frame, text="Export Main Materials", style="Dark.TButton", command=lambda: self.export_treeview_to_csv(self.tree, "Main_Materials_Dashboard", parent=self.root))
        btn_export_main.pack(side="left", padx=6)

        # Right-side dashboard buttons
        btn_withdraw_dash = ttk.Button(top_frame, text="Withdrawals Dashboard", style="Dark.TButton", command=self.open_withdrawal_dashboard)
        btn_withdraw_dash.pack(side="right", padx=4)
        btn_receive_dash = ttk.Button(top_frame, text="Received Parts Dashboard", style="Dark.TButton", command=self.open_received_dashboard)
        btn_receive_dash.pack(side="right", padx=4)

        # NEW: Build Capacity Dashboard button
        self.btn_build_capacity = ttk.Button(top_frame, text="Build Capacity Dashboard", style="Dark.TButton", command=self.open_build_capacity_dashboard)
        self.btn_build_capacity.pack(side="right", padx=4)

        # NEW: Low Stock Dashboard button (as self)
        self.btn_lowstock_dash = ttk.Button(top_frame, text="Low Stock Dashboard", style="Dark.TButton", command=self.open_low_stock_dashboard)
        self.btn_lowstock_dash.pack(side="right", padx=4)
        
        # Immediately check remarks and update button color
        self.check_low_stock_remarks(self.btn_lowstock_dash)

        # Material Input Card
        input_frame = ttk.Frame(self.root, style="Dark.TFrame", padding=12)
        input_frame.pack(fill="x", padx=12, pady=(6,10))

        header = tk.Label(input_frame, text="Material Info", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=("Roboto", 18, "bold"))
        header.grid(row=0, column=0, columnspan=4, sticky="w", pady=(0,8))

        labels = [
            ("Description", 1, 0), ("Part Number", 1, 2),
            ("Model/Specs", 2, 0), ("Storage Location", 2, 2),
            ("Maintaining Stock", 3, 0), ("Quantity on Hand", 3, 2),
            ("Category", 4, 0), ("Project", 4, 2),
            ("Groupings", 5, 0)
        ]
        for text, r, c in labels:
            lbl = tk.Label(input_frame, text=text + ":", bg=BACKGROUND_GRAY, fg=TEXT_GRAY, font=FONT)
            lbl.grid(row=r, column=c, sticky="w", padx=6, pady=4)

        self.desc_var = tk.StringVar()
        self.part_var = tk.StringVar()
        self.model_var = tk.StringVar()
        self.loc_var = tk.StringVar()
        self.stock_var = tk.IntVar(value=0)
        self.qty_var = tk.IntVar(value=0)
        self.cat_var = tk.StringVar(value="Direct")
        self.proj_var = tk.StringVar()
        self.grouping_var = tk.StringVar()
        self.grouping_id_var = tk.StringVar()

        e_desc = ttk.Entry(input_frame, textvariable=self.desc_var, style="Dark.TEntry", width=50)
        e_desc.grid(row=1, column=1, padx=6, pady=2)
        e_part = ttk.Entry(input_frame, textvariable=self.part_var, style="Dark.TEntry", width=50)
        e_part.grid(row=1, column=3, padx=6, pady=2)
        e_model = ttk.Entry(input_frame, textvariable=self.model_var, style="Dark.TEntry", width=50)
        e_model.grid(row=2, column=1, padx=6, pady=2)

        self.storage_combobox = ttk.Combobox(input_frame, textvariable=self.loc_var, style="Dark.TCombobox", width=48)
        self.storage_combobox.grid(row=2, column=3, padx=6, pady=2)
        self.load_storage_locations()

        e_stock = ttk.Entry(input_frame, textvariable=self.stock_var, style="Dark.TEntry", width=50)
        e_stock.grid(row=3, column=1, padx=6, pady=2)
        e_qty = ttk.Entry(input_frame, textvariable=self.qty_var, style="Dark.TEntry", width=50)
        e_qty.grid(row=3, column=3, padx=6, pady=2)

        self.category_combobox = ttk.Combobox(input_frame, textvariable=self.cat_var, values=["Direct", "Indirect"], state="readonly", style="Dark.TCombobox", width=48)
        self.category_combobox.grid(row=4, column=1, padx=6, pady=2)

        e_proj = ttk.Entry(input_frame, textvariable=self.proj_var, style="Dark.TEntry", width=50)
        e_proj.grid(row=4, column=3, padx=6, pady=2)

        # --- Groupings Combobox (now behaves like Storage Combobox) ---
        self.grouping_combobox = ttk.Combobox(input_frame, textvariable=self.grouping_var, style="Dark.TCombobox", width=48)
        self.grouping_combobox.grid(row=5, column=1, padx=6, pady=2)
        self.load_groupings_dropdown()

        # Allow typing and pressing Enter to add new grouping
        def add_new_grouping(event):
            new_grouping = self.grouping_var.get().strip()
            if new_grouping and new_grouping not in self.grouping_combobox["values"]:
                current = list(self.grouping_combobox["values"])
                current.append(new_grouping)
                self.grouping_combobox["values"] = current

        self.grouping_combobox.bind("<Return>", add_new_grouping)
        # --------------------------------------

        # Buttons panel
        btn_frame = tk.Frame(input_frame, bg=BACKGROUND_GRAY)
        btn_frame.grid(row=1, column=4, rowspan=6, padx=(10, 0), sticky="ne")
        button_width = 20
        buttons = [
            ("Add", self.add_item),
            ("Update", self.update_item),
            ("Delete", self.delete_item),
            ("Clear", self.clear_fields),
            ("Withdraw", self.open_withdraw_window),
            ("Receive Parts(w/o PR)", self.open_receive_window),
            ("Receive Parts(with PR)", self.open_receive_from_pr_window),
            ("PR Monitoring", self.open_pr_monitor_window),
            ("Withdraw Assembly", self.open_assembly_withdraw_window),
            ("Assembly Manager", self.open_assembly_manager),
        ]
        for i, (text, cmd) in enumerate(buttons):
            r, c = divmod(i, 2)
            ttk.Button(btn_frame, text=text, style="Dark.TButton", command=cmd, width=button_width).grid(row=r, column=c, padx=4, pady=4, sticky="ew")
        btn_frame.grid_columnconfigure(0, weight=1)
        btn_frame.grid_columnconfigure(1, weight=1)

        # Table frame
        table_container = ttk.Frame(self.root, style="Dark.TFrame")
        table_container.pack(fill="both", expand=True, padx=12, pady=(0,12))
        vsb = ttk.Scrollbar(table_container, orient="vertical", style="Dark.Vertical.TScrollbar")
        vsb.pack(side="right", fill="y")
        self.tree = ttk.Treeview(
            table_container,
            columns=("ID", "Description", "Part Number", "Model/Specs", "Storage", "Maintaining Stock", "Quantity on Hand", "Category", "Project", "Groupings"),
            show="headings",
            yscrollcommand=vsb.set,
            style="Dark.Treeview"
        )
        vsb.config(command=self.tree.yview)
        for col in self.tree["columns"]:
            self.tree.heading(col, text=col, command=lambda c=col: self.sort_treeview(c))
            self.tree.column(col, width=140, anchor="center")
        self.tree.column("Description", anchor="w")
        self.tree.column("Storage", anchor="w")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_row_select)

        self.tree.tag_configure('evenrow', background=BACKGROUND_GRAY, foreground=TEXT_DARK)
        self.tree.tag_configure('oddrow', background=SURFACE_WHITE, foreground=TEXT_DARK)
        self.tree.tag_configure('low', background='#5f2323', foreground='#fff')


    def check_low_stock_remarks(self, btn):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM low_stock_dashboard WHERE remarks IS NULL OR TRIM(remarks) = ''")
        missing_remarks_count = c.fetchone()[0]
        conn.close()

        style = ttk.Style()
        if missing_remarks_count > 0:
            # Create a new style for warning
            style.configure("LowStockWarning.TButton", background="#ff9999", foreground="black")
            btn.config(style="LowStockWarning.TButton")
        else:
            btn.config(style="Dark.TButton")

    # --------------- NEW: Low Stock helpers ---------------
    def sync_all_low_stock(self):
        """Scan all materials and ensure low_stock_dashboard is populated for items with QOH <= maintaining_stock."""
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT id, quantity_on_hand, maintaining_stock FROM materials")
            rows = c.fetchall()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for r in rows:
                mid = r[0]
                qoh = self._safe_int(r[1], 0)
                maint = self._safe_int(r[2], 0)
                c.execute("SELECT id FROM low_stock_dashboard WHERE material_id = ?", (mid,))
                exists = c.fetchone()
                if qoh <= maint:
                    if exists:
                        c.execute("UPDATE low_stock_dashboard SET last_updated = ? WHERE material_id = ?", (now, mid))
                    else:
                        c.execute("INSERT INTO low_stock_dashboard (material_id, remarks, last_updated) VALUES (?, ?, ?)", (mid, "", now))
                else:
                    if exists:
                        c.execute("DELETE FROM low_stock_dashboard WHERE material_id = ?", (mid,))
            conn.commit()
            conn.close()
        except Exception as e:
            if DEBUG:
                print("sync_all_low_stock error:", e)

    # ---------- Low Stock Dashboard Helpers ----------
    def update_low_stock_dashboard(self, material_id):
        """
        Ensure a material is in the low_stock_dashboard table if its QOH <= maintaining_stock,
        and remove it otherwise.
        """
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT quantity_on_hand, maintaining_stock FROM materials WHERE id = ?", (material_id,))
            row = c.fetchone()
            if not row:
                # material deleted — ensure removal
                c.execute("DELETE FROM low_stock_dashboard WHERE material_id = ?", (material_id,))
                conn.commit()
                conn.close()
                return
            qoh = self._safe_int(row[0], 0)
            maintaining = self._safe_int(row[1], 0)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if qoh <= maintaining:
                # insert or update
                c.execute("SELECT id FROM low_stock_dashboard WHERE material_id = ?", (material_id,))
                existing = c.fetchone()
                if existing:
                    c.execute("UPDATE low_stock_dashboard SET last_updated = ? WHERE material_id = ?", (now, material_id))
                else:
                    c.execute("INSERT INTO low_stock_dashboard (material_id, remarks, last_updated) VALUES (?, ?, ?)",
                             (material_id, "", now))
            else:
                # remove from dashboard
                c.execute("DELETE FROM low_stock_dashboard WHERE material_id = ?", (material_id,))
            conn.commit()
            conn.close()
        except Exception as e:
            if DEBUG:
                print("Failed to update low stock dashboard:", e)

    def open_build_capacity_dashboard(self):
        win = tk.Toplevel(self.root, bg=BACKGROUND_GRAY)
        apply_material_style(win)
        win.title("Build Capacity Dashboard")
        win.geometry("600x500")
        win.attributes('-topmost', True)
    
        # Table
        cols = ("Assembly", "Max Buildable", "Limiting Part(s)")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=20, style="Dark.Treeview")
        for col in cols:
            tree.heading(col, text=col)
            if col == "Assembly":
                tree.column(col, width=200, anchor="w")
            elif col == "Max Buildable":
                tree.column(col, width=80, anchor="center")
            else:
                tree.column(col, width=200, anchor="center")
        tree.pack(fill="both", expand=True, padx=10, pady=10)
    
        # Buttons
        btns = ttk.Frame(win, style="Dark.TFrame")
        btns.pack(fill="x", padx=10, pady=8)
        ttk.Button(btns, text="Refresh", style="Dark.TButton", command=lambda: load_data()).pack(side="left", padx=6)
        ttk.Button(btns, text="Export to CSV", style="Dark.TButton", command=lambda: self.export_treeview_to_csv(tree, "Build_Capacity_Dashboard")).pack(side="left", padx=6)
        ttk.Button(btns, text="Close", style="Dark.TButton", command=win.destroy).pack(side="right", padx=6)
    
        def load_data():
            for r in tree.get_children():
                tree.delete(r)
    
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
    
            # Get all assemblies
            c.execute("SELECT id, name FROM assemblies")
            assemblies = c.fetchall()
    
            for assembly_id, assembly_name in assemblies:
                # Get required parts
                c.execute("""
                    SELECT ap.material_id, ap.quantity_needed, m.description, m.quantity_on_hand
                    FROM assembly_parts ap
                    JOIN materials m ON ap.material_id = m.id
                    WHERE ap.assembly_id = ?
                """, (assembly_id,))
                required_parts = c.fetchall()
    
                max_build = float("inf")
                limiting_parts = []
    
                for mat_id, req_qty, desc, stock_qty in required_parts:
                    stock_qty = self._safe_int(stock_qty, 0)
                    if req_qty > 0:
                        possible = stock_qty // req_qty
                        if possible < max_build:
                            max_build = possible
                            limiting_parts = [f"{desc} (Stock {stock_qty}, Need {req_qty})"]
                        elif possible == max_build:
                            # Another limiting part with same ratio
                            limiting_parts.append(f"{desc} (Stock {stock_qty}, Need {req_qty})")
    
                if max_build == float("inf"):
                    max_build = 0
    
                tree.insert("", "end", values=(assembly_name, max_build, "; ".join(limiting_parts)))
    
            conn.close()
    
        load_data()

    def open_low_stock_dashboard(self):
        win = tk.Toplevel(self.root, bg=BACKGROUND_GRAY)
        apply_material_style(win)
        win.title("Low Stock Dashboard")
        win.geometry("1000x520")
        win.attributes('-topmost', True)

        # When the window is closed, trigger cleanup + check
        def on_close():
            win.destroy()
            self.check_low_stock_remarks(self.btn_lowstock_dash)

        win.protocol("WM_DELETE_WINDOW", on_close)

        top = ttk.Frame(win, style="Dark.TFrame")
        top.pack(fill="x", padx=12, pady=8)
        tk.Label(top, text="Low Stock Items (<= Maintaining Stock)", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=HEADER_FONT).pack(side="left")
        search_var = tk.StringVar()
        ttk.Entry(top, textvariable=search_var, style="Dark.TEntry", width=30).pack(side="right", padx=6)
        tk.Label(top, text="Search:", bg=BACKGROUND_GRAY, fg=TEXT_GRAY, font=FONT).pack(side="right")

        table_frame = ttk.Frame(win, style="Dark.TFrame")
        table_frame.pack(fill="both", expand=True, padx=12, pady=8)
        vsb = ttk.Scrollbar(table_frame, orient="vertical", style="Dark.Vertical.TScrollbar")
        vsb.pack(side="right", fill="y")
        cols = ("ID", "Material ID", "Description", "Project", "Quantity on Hand", "Maintaining Stock", "Remarks", "Last Updated")
        table = ttk.Treeview(table_frame, columns=cols, show="headings", yscrollcommand=vsb.set, style="Dark.Treeview")
        vsb.config(command=table.yview)

        for col in cols:
            table.column(col, anchor="center" if col in ("ID","Material ID","Quantity on Hand","Maintaining Stock","Project") else "w", width=120)
            table.heading(col, text=col)
        table.column("ID", width=40)
        table.column("Material ID", width=80)
        table.column("Description", width=240)
        table.column("Remarks", width=200)
        table.column("Last Updated", width=140)
        table.pack(fill="both", expand=True)

        table.tag_configure('evenrow', background=BACKGROUND_GRAY, foreground=TEXT_DARK)
        table.tag_configure('oddrow', background=SURFACE_WHITE, foreground=TEXT_DARK)

        # -------------------- LOAD DATA --------------------
        def load_table():
            for r in table.get_children():
                table.delete(r)
            q = """
                SELECT l.id, m.id, m.description, m.project, m.quantity_on_hand, m.maintaining_stock, l.remarks, l.last_updated
                FROM low_stock_dashboard l
                JOIN materials m ON l.material_id = m.id
                WHERE m.maintaining_stock > 0 -- ADDED: Filter out items with zero or NULL maintaining stock
                ORDER BY l.last_updated DESC
            """
            val = search_var.get().strip()
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            if val:
                like = f"%{val}%"
                q = """
                    SELECT l.id, m.id, m.description, m.project, m.quantity_on_hand, m.maintaining_stock, l.remarks, l.last_updated
                    FROM low_stock_dashboard l
                    JOIN materials m ON l.material_id = m.id
                    WHERE m.maintaining_stock > 0 -- ADDED: Filter out items with zero or NULL maintaining stock
                    AND (m.description LIKE ? OR m.project LIKE ? OR l.remarks LIKE ?)
                    ORDER BY l.last_updated DESC
                """
                c.execute(q, (like, like, like))
            else:
                c.execute(q)
            rows = c.fetchall()
            conn.close()
            for i, r in enumerate(rows):
                tag = 'evenrow' if i % 2 == 0 else 'oddrow'
                r_list = list(r)
                r_list[2] = self.wrap_text(r_list[2], every=48)
                r_list[6] = self.wrap_text(r_list[6] or "", every=40)
                table.insert("", "end", values=r_list, tags=(tag,))
            update_low_stock_button_color(rows)

        # -------------------- INLINE EDIT REMARKS --------------------
        def on_double_click(event):
            region = table.identify("region", event.x, event.y)
            if region != "cell":
                return
            col = table.identify_column(event.x)
            row = table.identify_row(event.y)
            if not row or col != "#7":  # only allow editing "Remarks" column (#7)
                return
            item = table.item(row)
            vals = item["values"]
            lid = vals[0]  # Low stock dashboard ID
            current_text = vals[6] or ""
            # Cell bbox
            x, y, w, h = table.bbox(row, col)
            # Create entry overlay
            entry = tk.Entry(table, font=FONT)
            entry.place(x=x, y=y, width=w, height=h)
            entry.insert(0, current_text)
            entry.focus()

            def save_edit(event=None):
                new_text = entry.get()
                entry.destroy()
                # update DB
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                c.execute("UPDATE low_stock_dashboard SET remarks = ?, last_updated = ? WHERE id = ?", (new_text, now, lid))
                conn.commit()
                conn.close()
                # update table
                vals[6] = new_text
                vals[7] = now
                table.item(row, values=vals)
                # update button color
                rows = [table.item(r)["values"] for r in table.get_children()]
                update_low_stock_button_color(rows)

            entry.bind("<Return>", save_edit)
            entry.bind("<FocusOut>", save_edit)  # also save if user clicks away

        table.bind("<Double-1>", on_double_click)
        # -------------------- UPDATE BUTTON COLOR --------------------
        def update_low_stock_button_color(rows):
            missing_remarks = any(not r[6] or str(r[6]).strip() == "" for r in rows)
            if missing_remarks:
                self.btn_lowstock_dash.configure(style="LowStockWarning.TButton")
            else:
                self.btn_lowstock_dash.configure(style="Dark.TButton")

        # -------------------- BUTTONS --------------------
        btns = ttk.Frame(win, style="Dark.TFrame")
        btns.pack(fill="x", padx=12, pady=(6,12))
        ttk.Button(btns, text="Refresh", style="Dark.TButton", command=load_table).pack(side="left", padx=6)
        ttk.Button(btns, text="Export to CSV", style="Dark.TButton", command=lambda: self.export_treeview_to_csv(table, "Low_Stock_Dashboard", parent=win)).pack(side="left", padx=6)
        ttk.Button(btns, text="Close", style="Dark.TButton", command=on_close).pack(side="right", padx=6)
        load_table()

    def clear_filter(self):
        """Clear search filter and reload all data."""
        self.search_var.set("")
        self.load_data()

    def load_storage_locations(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT storage_location FROM materials WHERE storage_location IS NOT NULL AND storage_location != ''")
        locations = [row[0] for row in cursor.fetchall()]
        conn.close()
        self.storage_combobox['values'] = locations

    def load_groupings_dropdown(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM groupings ORDER BY name")
        groupings = cursor.fetchall()
        conn.close()
        self.grouping_map = {name: id for id, name in groupings}
        grouping_names = list(self.grouping_map.keys())
        self.grouping_combobox["values"] = grouping_names

    def get_or_create_grouping_id(self, grouping_name):
        if not grouping_name:
            return None

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id FROM groupings WHERE name=?", (grouping_name,))
            grouping_id = cursor.fetchone()
            if grouping_id:
                return grouping_id[0]
            else:
                cursor.execute("INSERT INTO groupings (name) VALUES (?)", (grouping_name,))
                grouping_id = cursor.lastrowid
                conn.commit()
                return grouping_id
        except Exception as e:
            if DEBUG:
                print(f"Error in get_or_create_grouping_id: {e}")
            return None
        finally:
            conn.close()

    def load_assemblies_map(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM assemblies ORDER BY name")
        rows = cursor.fetchall()
        conn.close()
        self.assemblies_map = {name: id for id, name in rows}

    def _safe_int(self, val, default=0):
        try:
            if val is None:
                return default
            s = str(val).strip()
            if s == "":
                return default
            return int(float(s))
        except Exception:
            return default

    def load_data(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        query = """
            SELECT m.id, m.description, m.part_number, m.model_specs, m.storage_location, m.maintaining_stock, m.quantity_on_hand, m.category, m.project, g.name
            FROM materials m
            LEFT JOIN groupings g ON m.grouping_id = g.id
        """
        params = ()
        st = self.search_var.get().strip()
        if st:
            query += " WHERE m.description LIKE ? OR m.part_number LIKE ?"
            params = (f"%{st}%", f"%{st}%")
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        for idx, row in enumerate(rows):
            ms = self._safe_int(row[5], 0)
            qoh = self._safe_int(row[6], 0)
            tag = 'evenrow' if idx % 2 == 0 else 'oddrow'
            if qoh <= ms:
                tag = 'low'
            wrapped_row = list(row)
            wrapped_row[1] = self.wrap_text(wrapped_row[1], every=48)
            wrapped_row[3] = self.wrap_text(wrapped_row[3], every=15)
            wrapped_row[4] = self.wrap_text(wrapped_row[4], every=20)
            wrapped_row[8] = self.wrap_text(wrapped_row[8], every=20)
            wrapped_row[9] = self.wrap_text(wrapped_row[9], every=14)
            self.tree.insert("", "end", values=wrapped_row, tags=(tag,))
        self.autofit_columns()
        self.load_storage_locations()
        self.load_assemblies_map()
        self.load_groupings_dropdown()

    def sort_treeview(self, col):
        children = list(self.tree.get_children(''))
        try:
            data = [(self.tree.set(item, col), item) for item in children]
            def keyfn(x):
                try:
                    return float(x[0])
                except Exception:
                    return str(x[0]).lower()
            reverse = getattr(self, "_sort_reverse_" + col, False)
            data.sort(key=keyfn, reverse=reverse)
            for index, (_, item) in enumerate(data):
                self.tree.move(item, '', index)
            setattr(self, "_sort_reverse_" + col, not reverse)
            new_heading = ("▲ " if not reverse else "▼ ") + col
            self.tree.heading(col, text=new_heading)
        except Exception:
            pass
            
    def add_item(self):
        grouping_name = self.grouping_var.get().strip()
        grouping_id = None
        if grouping_name:
            grouping_id = self.get_or_create_grouping_id(grouping_name)

        if not self.desc_var.get().strip():
            messagebox.showwarning("Input Error", "Description is required.")
            return

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        try:
            values = (
                self.desc_var.get().strip(),
                self.part_var.get().strip(),
                self.model_var.get().strip(),
                self.loc_var.get().strip(),
                self._safe_int(self.stock_var.get(), 0),
                self._safe_int(self.qty_var.get(), 0),
                self.cat_var.get(),
                self.proj_var.get().strip(),
                grouping_id
            )
            cursor.execute("""
                INSERT INTO materials (description, part_number, model_specs, storage_location, maintaining_stock, quantity_on_hand, category, project, grouping_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, values)
            mat_id = cursor.lastrowid
            conn.commit()
            
            self.update_low_stock_dashboard(mat_id)
            self.sync_all_low_stock()
            self.load_data()
            self.clear_fields()
            
        except sqlite3.IntegrityError as e:
            messagebox.showerror("Database Error", f"Failed to add item. {e}")
        finally:
            conn.close()

    def update_item(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("No selection", "Please select a row to update.")
            return
        
        item_id = self.tree.item(selected)["values"][0]
        grouping_name = self.grouping_var.get().strip()
        grouping_id = None
        if grouping_name:
            grouping_id = self.get_or_create_grouping_id(grouping_name)
            
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        try:
            values = (
                self.desc_var.get().strip(),
                self.part_var.get().strip(),
                self.model_var.get().strip(),
                self.loc_var.get().strip(),
                self._safe_int(self.stock_var.get(), 0),
                self._safe_int(self.qty_var.get(), 0),
                self.cat_var.get(),
                self.proj_var.get().strip(),
                grouping_id,
                item_id
            )
            cursor.execute("""
                UPDATE materials SET description=?, part_number=?, model_specs=?, storage_location=?, maintaining_stock=?, quantity_on_hand=?, category=?, project=?, grouping_id=?
                WHERE id=?
            """, values)
            conn.commit()
            
            self.update_low_stock_dashboard(item_id)
            self.load_data()
            self.clear_fields()

        except sqlite3.IntegrityError as e:
            messagebox.showerror("Database Error", f"Failed to update item. {e}")
        finally:
            conn.close()

    def delete_item(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("No selection", "Please select a row to delete.")
            return
        
        item_id = self.tree.item(selected)["values"][0]
        if messagebox.askyesno("Confirm", "Are you sure you want to delete this item?"):
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM materials WHERE id=?", (item_id,))
            # remove from low stock dashboard as well
            cursor.execute("DELETE FROM low_stock_dashboard WHERE material_id=?", (item_id,))
            conn.commit()
            conn.close()
            self.sync_all_low_stock()
            self.load_data()
            self.clear_fields()

    def on_row_select(self, event):
        selected = self.tree.selection()
        if selected:
            values = self.tree.item(selected)["values"]
            self.desc_var.set(values[1])
            self.part_var.set(values[2])
            self.model_var.set(values[3])
            self.loc_var.set(values[4])
            self.stock_var.set(self._safe_int(values[5], 0))
            self.qty_var.set(self._safe_int(values[6], 0))
            self.cat_var.set(values[7])
            self.proj_var.set(values[8])
            self.grouping_var.set(values[9])

    def clear_fields(self):
        self.desc_var.set("")
        self.part_var.set("")
        self.model_var.set("")
        self.loc_var.set("")
        self.stock_var.set(0)
        self.qty_var.set(0)
        self.proj_var.set("")
        self.category_combobox.set("")
        self.grouping_combobox.set("")
        try:
            self.tree.selection_remove(self.tree.selection())
        except Exception:
            pass

    # ---------- Single withdrawal (existing) ----------
    def open_withdraw_window(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("No selection", "Please select an item to withdraw from.")
            return
        values = self.tree.item(selected)["values"]
        material_id = values[0]
        desc = values[1]
        current_qty = self._safe_int(values[6]) if len(values) > 6 else 0
    
        win = tk.Toplevel(self.root, bg=BACKGROUND_GRAY)
        apply_material_style(win)
        win.title(f"Withdraw: {desc}")
        win.geometry("360x360")
    
        tk.Label(win, text=f"Item: {desc}", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).pack(pady=8)
        tk.Label(win, text=f"Quantity on Hand: {current_qty}", bg=BACKGROUND_GRAY, fg=TEXT_GRAY, font=FONT).pack()
    
        qty_var = tk.IntVar()
        purpose_var = tk.StringVar()
    
        # Withdrawn By (who requested)
        withdrawn_by_var = tk.StringVar()
        # Issued By (logged in user, readonly)
        issued_by_var = tk.StringVar(value=self.current_user.get("name", self.current_user["username"]))
    
        tk.Label(win, text="Quantity to Withdraw:", bg=BACKGROUND_GRAY, fg=TEXT_GRAY, font=FONT).pack(anchor="w", padx=12, pady=(10,0))
        ttk.Entry(win, textvariable=qty_var).pack(fill="x", padx=12)
    
        tk.Label(win, text="Purpose:", bg=BACKGROUND_GRAY, fg=TEXT_GRAY, font=FONT).pack(anchor="w", padx=12, pady=(8,0))
        ttk.Entry(win, textvariable=purpose_var).pack(fill="x", padx=12)
    
        tk.Label(win, text="Withdrawn By:", bg=BACKGROUND_GRAY, fg=TEXT_GRAY, font=FONT).pack(anchor="w", padx=12, pady=(8,0))
        ttk.Entry(win, textvariable=withdrawn_by_var).pack(fill="x", padx=12)
    
        tk.Label(win, text="Issued By:", bg=BACKGROUND_GRAY, fg=TEXT_GRAY, font=FONT).pack(anchor="w", padx=12, pady=(8,0))
        ttk.Entry(win, textvariable=issued_by_var, state="readonly").pack(fill="x", padx=12)
    
        def submit():
            try:
                qty = int(qty_var.get())
            except Exception:
                messagebox.showerror("Invalid", "Please enter a valid number for quantity.")
                return
            if qty <= 0:
                messagebox.showerror("Invalid", "Withdrawal quantity must be > 0.")
                return
            if qty > current_qty:
                messagebox.showerror("Invalid", "Not enough stock.")
                return
    
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT quantity_on_hand, maintaining_stock, description, part_number FROM materials WHERE id = ?", (material_id,))
            current_data = cursor.fetchone()
            if current_data:
                current_qty_db = self._safe_int(current_data[0], 0)
                maintaining_stock_db = self._safe_int(current_data[1], 0)
                description = current_data[2] or desc
                part_number = current_data[3] or ""
                new_qty = current_qty_db - qty
                try:
                    cursor.execute("UPDATE materials SET quantity_on_hand = ? WHERE id = ?", (new_qty, material_id))
                    cursor.execute(
                        "INSERT INTO withdrawals (material_id, quantity, purpose, withdrawn_by, issued_by, date) VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            material_id,
                            qty,
                            purpose_var.get(),
                            withdrawn_by_var.get(),
                            issued_by_var.get(),
                            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        )
                    )
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    conn.close()
                    messagebox.showerror("Database Error", f"Failed to record withdrawal: {e}")
                    return
                finally:
                    conn.close()
    
                # sync low stock
                self.sync_all_low_stock()
                self.check_low_stock_remarks(self.btn_lowstock_dash)
    
                self.load_data()
                win.destroy()
                messagebox.showinfo("Success", "Withdrawal recorded.")
    
                if new_qty <= maintaining_stock_db:
                    subject = f"LOW STOCK ALERT: {description}"
                    body = (
                        f"The following part has reached a low stock level:\n\n"
                        f"Description: {description}\n"
                        f"Part Number: {part_number}\n"
                        f"New Quantity on Hand: {new_qty}\n"
                        f"Maintaining Stock: {maintaining_stock_db}\n\n"
                        f"Please re-order as soon as possible."
                    )
                    send_outlook_email(TO_EMAILS, CC_EMAILS, BCC_EMAILS, subject, body)
            else:
                conn.close()
                messagebox.showerror("Error", "Material not found.")
    
        ttk.Button(win, text="Submit", style="Dark.TButton", command=submit).pack(pady=12)

    # ---------- Receive (existing) ----------
    def open_receive_window(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("No selection", "Please select an item to receive parts for.")
            return
        values = self.tree.item(selected)["values"]
        material_id = values[0]
        desc = values[1]
        current_qty = self._safe_int(values[6]) if len(values) > 6 else 0
    
        win = tk.Toplevel(self.root, bg=BACKGROUND_GRAY)
        apply_material_style(win)
        win.title(f"Receive Parts: {desc}")
        win.geometry("360x240")
    
        tk.Label(win, text=f"Item: {desc}", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).pack(pady=8)
        tk.Label(win, text=f"Quantity on Hand: {current_qty}", bg=BACKGROUND_GRAY, fg=TEXT_GRAY, font=FONT).pack()
    
        qty_var = tk.IntVar()
    
        # Auto-fill Received By with logged user's name
        by_var = tk.StringVar(value=self.current_user.get("name", self.current_user["username"]))
    
        tk.Label(win, text="Quantity to Receive:", bg=BACKGROUND_GRAY, fg=TEXT_GRAY, font=FONT).pack(anchor="w", padx=12, pady=(10,0))
        ttk.Entry(win, textvariable=qty_var).pack(fill="x", padx=12)
    
        tk.Label(win, text="Received By:", bg=BACKGROUND_GRAY, fg=TEXT_GRAY, font=FONT).pack(anchor="w", padx=12, pady=(8,0))
        by_entry = ttk.Entry(win, textvariable=by_var, state="readonly")
        by_entry.pack(fill="x", padx=12)
    
        def submit():
            try:
                qty = int(qty_var.get())
            except Exception:
                messagebox.showerror("Invalid", "Please enter a valid number for quantity.")
                return
            if qty <= 0:
                messagebox.showerror("Invalid", "Received quantity must be > 0.")
                return
    
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "UPDATE materials SET quantity_on_hand = quantity_on_hand + ? WHERE id = ?",
                    (qty, material_id)
                )
                cursor.execute(
                    """INSERT INTO received_parts 
                       (pr_id, po_number, material_id, material_name, quantity, received_by, requestor, date) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        None,
                        None,
                        material_id,
                        desc,
                        qty,
                        by_var.get(),
                        None,
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
                conn.commit()
            except sqlite3.Error as e:
                conn.rollback()
                conn.close()
                messagebox.showerror("Database Error", f"Failed to record receipt: {e}")
                return
            finally:
                conn.close()
    
            # sync low stock
            self.sync_all_low_stock()
            self.check_low_stock_remarks(self.btn_lowstock_dash)
    
            self.load_data()
            win.destroy()
            messagebox.showinfo("Success", "Received parts recorded.")
    
        ttk.Button(win, text="Submit", style="Dark.TButton", command=submit).pack(pady=12)

    # ---------- NEW: Receive filtered by PRs ----------
    def open_receive_from_pr_window(self):
        win = tk.Toplevel(self.root, bg=BACKGROUND_GRAY)
        apply_material_style(win)
        win.title("Receive Parts (with PR)")
        win.geometry("600x260")
    
        form = ttk.Frame(win, style="Dark.TFrame")
        form.pack(fill="x", padx=12, pady=10)
    
        tk.Label(form, text="Material (from open PRs):", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).grid(
            row=0, column=0, sticky="w", padx=(2,8), pady=(2,2)
        )
        mat_var = tk.StringVar()
        mat_cb = ttk.Combobox(form, textvariable=mat_var, style="Dark.TCombobox", width=60)
        mat_cb.grid(row=0, column=1, sticky="ew", pady=(2,2))
    
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT DISTINCT m.id, m.description
            FROM purchase_requests pr
            JOIN materials m ON pr.material_id = m.id
            WHERE pr.status IN ('open','partial') AND pr.quantity_remaining > 0
            ORDER BY m.description
        """)
        mats = c.fetchall()
        conn.close()
    
        choices = [f"{m[0]} - {m[1]}" for m in mats]
        id_from_display = {f"{m[0]} - {m[1]}": m[0] for m in mats}
        mat_cb['values'] = choices
        if choices:
            mat_cb.set(choices[0])
    
        def update_combo_values(event):
            typed = mat_var.get().lower()
            filtered = [item for item in choices if typed in item.lower()]
            mat_cb['values'] = filtered
        mat_cb.bind("<KeyRelease>", update_combo_values)
    
        outstanding_var = tk.StringVar(value="Outstanding: 0")
        tk.Label(form, textvariable=outstanding_var, bg=BACKGROUND_GRAY, fg=TEXT_GRAY, font=FONT).grid(
            row=1, column=1, sticky="w", pady=(0,6)
        )
    
        def refresh_outstanding():
            sel = mat_var.get().strip()
            if not sel or sel not in id_from_display:
                outstanding_var.set("Outstanding: 0")
                return
            mid = id_from_display[sel]
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("""SELECT COALESCE(SUM(quantity_remaining),0)
                         FROM purchase_requests
                         WHERE material_id=? AND status IN ('open','partial')""", (mid,))
            total = c.fetchone()[0] or 0
            conn.close()
            outstanding_var.set(f"Outstanding: {total}")
        mat_cb.bind("<<ComboboxSelected>>", lambda e: refresh_outstanding())
        refresh_outstanding()
    
        tk.Label(form, text="Quantity to Receive:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).grid(
            row=2, column=0, sticky="w", padx=(2,8), pady=(6,2)
        )
        qty_var = tk.IntVar()
        ttk.Entry(form, textvariable=qty_var, style="Dark.TEntry").grid(row=2, column=1, sticky="ew", pady=(6,2))
    
        tk.Label(form, text="Received By:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).grid(
            row=3, column=0, sticky="w", padx=(2,8), pady=(6,2)
        )
        # Auto-fill with current user's name, readonly
        by_var = tk.StringVar(value=self.current_user.get("name", self.current_user["username"]))
        ttk.Entry(form, textvariable=by_var, style="Dark.TEntry", state="readonly").grid(
            row=3, column=1, sticky="ew", pady=(6,2)
        )
    
        def submit():
            sel = mat_var.get().strip()
            if not sel or sel not in id_from_display:
                messagebox.showwarning("Select", "Please select a material from the list.")
                return
            try:
                qty = int(qty_var.get())
            except Exception:
                messagebox.showerror("Invalid", "Please enter a valid number for quantity.")
                return
            if qty <= 0:
                messagebox.showerror("Invalid", "Received quantity must be > 0.")
                return
    
            mid = id_from_display[sel]
            material_name = sel.split(' - ', 1)[1]
    
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            try:
                c.execute("UPDATE materials SET quantity_on_hand = quantity_on_hand + ? WHERE id = ?", (qty, mid))
    
                c.execute("""
                    SELECT id, po_number, requestor, quantity_remaining
                    FROM purchase_requests
                    WHERE material_id=? AND status IN ('open','partial') AND quantity_remaining>0
                    ORDER BY datetime(date_requested) ASC, id ASC
                """, (mid,))
                pr_rows = c.fetchall()
    
                if not pr_rows:
                    messagebox.showwarning("No Open PRs", "No open or partial PRs found for this material.")
                    conn.rollback()
                    conn.close()
                    return
    
                first_pr_id, po_number, requestor, _ = pr_rows[0]
    
                c.execute("""
                    INSERT INTO received_parts (
                        pr_id, po_number, material_id, material_name, quantity, received_by, requestor, date
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    first_pr_id,
                    po_number,
                    mid,
                    material_name,
                    qty,
                    by_var.get(),
                    requestor,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ))
    
                remaining = qty
                for pr_id, _, _, qrem in pr_rows:
                    if remaining <= 0:
                        break
                    take = min(remaining, qrem)
                    new_rem = qrem - take
                    remaining -= take
                    if new_rem == 0:
                        c.execute("UPDATE purchase_requests SET quantity_remaining=?, status='fulfilled', date_closed=? WHERE id=?",
                                  (0, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), pr_id))
                    else:
                        c.execute("UPDATE purchase_requests SET quantity_remaining=?, status='partial' WHERE id=?",
                                  (new_rem, pr_id))
                conn.commit()
            except Exception as e:
                conn.rollback()
                conn.close()
                messagebox.showerror("Error", f"Failed to record receipt: {e}")
                return
            conn.close()
    
            # sync low stock
            self.sync_all_low_stock()
            self.check_low_stock_remarks(self.btn_lowstock_dash)
    
            self.load_data()
            messagebox.showinfo("Success", "Received parts recorded and PRs updated.")
            win.destroy()
    
        btns = ttk.Frame(win, style="Dark.TFrame")
        btns.pack(pady=10)
        ttk.Button(btns, text="Submit", style="Dark.TButton", command=submit).pack(side="left", padx=6)
        ttk.Button(btns, text="Close", style="Dark.TButton", command=win.destroy).pack(side="left", padx=6)

    # ---------- Withdrawals dashboard (existing) ----------
    def open_withdrawal_dashboard(self):
        dash = tk.Toplevel(self.root, bg=BACKGROUND_GRAY)
        apply_material_style(dash)
        dash.title("Withdrawals Dashboard")
        dash.geometry("1000x500")  # slightly wider to fit extra column
    
        filter_frame = ttk.Frame(dash, style="Dark.TFrame")
        filter_frame.pack(fill="x", padx=12, pady=8)
        tk.Label(
            filter_frame,
            text="Search by Description, Purpose, Withdrawn By, Issued By or Date (YYYY-MM-DD):",
            bg=BACKGROUND_GRAY, fg=TEXT_GRAY, font=FONT
        ).pack(side="left", padx=(4,8))
        search = tk.StringVar()
        ttk.Entry(filter_frame, textvariable=search, style="Dark.TEntry", width=30).pack(side="left", padx=4)
        ttk.Button(filter_frame, text="Filter", style="Dark.TButton", command=lambda: load_table()).pack(side="left", padx=6)
    
        table_frame = ttk.Frame(dash, style="Dark.TFrame")
        table_frame.pack(fill="both", expand=True, padx=12, pady=6)
        vsb_dash = ttk.Scrollbar(table_frame, orient="vertical", style="Dark.Vertical.TScrollbar")
        vsb_dash.pack(side="right", fill="y")
    
        # Added Issued By column
        table = ttk.Treeview(
            table_frame,
            columns=("ID", "Material", "Qty", "Purpose", "Withdrawn By", "Issued By", "Date"),
            show="headings",
            yscrollcommand=vsb_dash.set,
            style="Dark.Treeview"
        )
        vsb_dash.config(command=table.yview)
        for col in table["columns"]:
            table.heading(col, text=col)
            table.column(col, width=140, anchor="center")
        table.pack(fill="both", expand=True)
    
        table.tag_configure('evenrow', background=BACKGROUND_GRAY, foreground=TEXT_DARK)
        table.tag_configure('oddrow', background=SURFACE_WHITE, foreground=TEXT_DARK)
    
        def load_table():
            for r in table.get_children():
                table.delete(r)
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            q = """
                SELECT w.id, m.description, w.quantity, w.purpose, w.withdrawn_by, w.issued_by, w.date
                FROM withdrawals w
                JOIN materials m ON w.material_id = m.id
            """
            val = search.get().strip()
            if val:
                like = f"%{val}%"
                # Search by description, purpose, withdrawn_by, issued_by, or date
                q += " WHERE m.description LIKE ? OR w.purpose LIKE ? OR w.withdrawn_by LIKE ? OR w.issued_by LIKE ? OR w.date LIKE ?"
                c.execute(q, (like, like, like, like, like))
            else:
                c.execute(q)
            rows = c.fetchall()
            conn.close()
            for i, r in enumerate(rows):
                tag = 'evenrow' if i % 2 == 0 else 'oddrow'
                r_list = list(r)
                r_list[1] = self.wrap_text(r_list[1], every=48)   # Material
                r_list[3] = self.wrap_text(r_list[3], every=48)   # Purpose
                table.insert("", "end", values=r_list, tags=(tag,))
        btns = ttk.Frame(dash)
        btns.pack(fill="x", padx=12, pady=8)
        ttk.Button(btns, text="Refresh", command=load_table).pack(side="left", padx=6)
        ttk.Button(btns, text="Export to CSV", command=lambda: self.export_treeview_to_csv(table, "Withdrawals_Dashboard", parent=dash)).pack(side="left", padx=6)
        ttk.Button(btns, text="Close", command=dash.destroy).pack(side="right", padx=6)
        load_table()

    # ---------- Received dashboard (existing) ----------
    def open_received_dashboard(self):
        dash = tk.Toplevel(self.root, bg=BACKGROUND_GRAY)
        apply_material_style(dash)
        dash.title("Received Parts Dashboard")
        dash.geometry("1100x500")

        filter_frame = ttk.Frame(dash, style="Dark.TFrame")
        filter_frame.pack(fill="x", padx=12, pady=8)
        tk.Label(filter_frame, text="Search by Description, PO, or Date (YYYY-MM-DD):", bg=BACKGROUND_GRAY, fg=TEXT_GRAY, font=FONT).pack(side="left", padx=(4,8))
        search = tk.StringVar()
        ttk.Entry(filter_frame, textvariable=search, style="Dark.TEntry", width=40).pack(side="left", padx=4)
        ttk.Button(filter_frame, text="Filter", style="Dark.TButton", command=lambda: load_table()).pack(side="left", padx=6)

        table_frame = ttk.Frame(dash, style="Dark.TFrame")
        table_frame.pack(fill="both", expand=True, padx=12, pady=6)
        vsb_dash = ttk.Scrollbar(table_frame, orient="vertical", style="Dark.Vertical.TScrollbar")
        vsb_dash.pack(side="right", fill="y")

        cols = ("ID", "PR ID", "PO Number", "Material", "Qty", "Received By", "Requestor", "Date")
        table = ttk.Treeview(table_frame, columns=cols, show="headings", yscrollcommand=vsb_dash.set, style="Dark.Treeview")
        vsb_dash.config(command=table.yview)

        table.column("ID", width=20, anchor="center")
        table.column("PR ID", width=50, anchor="center")
        table.column("PO Number", width=100, anchor="center")
        table.column("Material", width=200, anchor="w")
        table.column("Qty", width=50, anchor="center")
        table.column("Received By", width=100, anchor="w")
        table.column("Requestor", width=100, anchor="w")
        table.column("Date", width=120, anchor="center")

        for c in cols:
            table.heading(c, text=c)

        table.pack(fill="both", expand=True)

        table.tag_configure('evenrow', background=BACKGROUND_GRAY, foreground=TEXT_DARK)
        table.tag_configure('oddrow', background=SURFACE_WHITE, foreground=TEXT_DARK)

        def load_table():
            for r in table.get_children():
                table.delete(r)
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()

            query = """
                SELECT r.id, r.pr_id, pr.po_number, m.description, r.quantity, r.received_by, pr.requestor, r.date
                FROM received_parts r
                LEFT OUTER JOIN purchase_requests pr ON r.pr_id = pr.id
                JOIN materials m ON r.material_id = m.id
            """
            val = search.get().strip()
            if val:
                query += " WHERE m.description LIKE ? OR r.date LIKE ? OR pr.po_number LIKE ?"
                cursor.execute(query, (f"%{val}%", f"%{val}%", f"%{val}%"))
            else:
                cursor.execute(query)

            rows = cursor.fetchall()
            conn.close()
            for i, r in enumerate(rows):
                tag = 'evenrow' if i % 2 == 0 else 'oddrow'
                r_list = list(r)
                r_list[3] = self.wrap_text(r_list[3], every=40) # Material
                table.insert("", "end", values=r_list, tags=(tag,))
        btns = ttk.Frame(dash)
        btns.pack(fill="x", padx=12, pady=8)
        ttk.Button(btns, text="Refresh", command=load_table).pack(side="left", padx=6)
        ttk.Button(btns, text="Export to CSV", command=lambda: self.export_treeview_to_csv(table, "Received_Parts_Dashboard", parent=dash)).pack(side="left", padx=6)
        ttk.Button(btns, text="Close", command=dash.destroy).pack(side="right", padx=6)
        load_table()

    # ---------- NEW: PR Monitoring ----------
    def open_pr_monitor_window(self):
        win = tk.Toplevel(self.root, bg=BACKGROUND_GRAY)
        apply_material_style(win)
        win.title("Purchase Request (PR) Monitoring")
        win.geometry("1100x560")

        form = ttk.Frame(win, style="Dark.TFrame")
        form.pack(fill="x", padx=12, pady=10)

        tk.Label(form, text="Description:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).grid(row=0, column=0, sticky="w", padx=(2,8))
        desc_var = tk.StringVar()
        desc_cb = ttk.Combobox(form, textvariable=desc_var, style="Dark.TCombobox", width=60)
        desc_cb.grid(row=0, column=1, sticky="ew", pady=2)

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, description FROM materials ORDER BY id ASC")
        mats = c.fetchall()
        conn.close()
        choices = [f"{m[0]} - {m[1]}" for m in mats]
        id_from_display = {f"{m[0]} - {m[1]}": m[0] for m in mats}
        desc_cb['values'] = choices
        if choices:
            desc_cb.set(choices[0])

        def filter_choices(event):
            typed = desc_var.get().lower()
            filtered = [item for item in choices if typed in item.lower()]
            desc_cb['values'] = filtered
        desc_cb.bind("<KeyRelease>", filter_choices)

        tk.Label(form, text="Purpose:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).grid(row=0, column=2, sticky="w", padx=(12,8))
        purpose_var = tk.StringVar()
        ttk.Entry(form, textvariable=purpose_var, style="Dark.TEntry", width=40).grid(row=0, column=3, sticky="ew", pady=2)

        tk.Label(form, text="Quantity:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).grid(row=1, column=0, sticky="w", padx=(2,8))
        qty_var = tk.IntVar(value=1)
        ttk.Entry(form, textvariable=qty_var, style="Dark.TEntry", width=20).grid(row=1, column=1, sticky="w", pady=2)

        tk.Label(form, text="Requestor:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).grid(row=1, column=2, sticky="w", padx=(12,8))
        req_var = tk.StringVar()
        ttk.Entry(form, textvariable=req_var, style="Dark.TEntry", width=40).grid(row=1, column=3, sticky="ew", pady=2)

        tk.Label(form, text="PO Number:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).grid(row=2, column=0, sticky="w", padx=(2,8), pady=2)
        po_var = tk.StringVar()
        ttk.Entry(form, textvariable=po_var, style="Dark.TEntry", width=20).grid(row=2, column=1, sticky="w", pady=2)

        tk.Label(form, text="ETD:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).grid(row=2, column=2, sticky="w", padx=(12,8), pady=2)
        etd_var = tk.StringVar()
        cal = DateEntry(form, selectmode='day', textvariable=etd_var, date_pattern='yyyy-mm-dd')
        cal.grid(row=2, column=3, sticky="ew", pady=2)

        def add_pr():
            sel = desc_var.get().strip()
            po = po_var.get().strip()
            etd = etd_var.get().strip()

            if not sel or sel not in id_from_display:
                messagebox.showwarning("Select", "Select a valid material description.")
                return
            try:
                q = int(qty_var.get())
            except Exception:
                messagebox.showerror("Invalid", "Enter a valid quantity.")
                return
            if q <= 0:
                messagebox.showerror("Invalid", "Quantity must be > 0.")
                return
            mid = id_from_display[sel]
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("""INSERT INTO purchase_requests (material_id, purpose, quantity, quantity_remaining, requestor, status, po_number, date_requested, estimated_delivery_date)
                          VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?)""",
                          (mid, purpose_var.get().strip(), q, q, req_var.get().strip(), po, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), etd))
            conn.commit()
            conn.close()
            load_table()
            messagebox.showinfo("Added", "Purchase Request added.")
            qty_var.set(1)
            purpose_var.set("")
            req_var.set("")
            po_var.set("")
            etd_var.set("")

        ttk.Button(form, text="Add PR", style="Dark.TButton", command=add_pr).grid(row=0, column=4, rowspan=3, padx=(12,0), sticky="ns")

        filter_frame = ttk.Frame(win, style="Dark.TFrame")
        filter_frame.pack(fill="x", padx=12, pady=(6,0))
        tk.Label(filter_frame, text="Search (Description/Requestor/Purpose/Status):", bg=BACKGROUND_GRAY, fg=TEXT_GRAY, font=FONT).pack(side="left")
        search = tk.StringVar()
        ttk.Entry(filter_frame, textvariable=search, style="Dark.TEntry", width=40).pack(side="left", padx=8)
        ttk.Button(filter_frame, text="Filter", style="Dark.TButton", command=lambda: load_table()).pack(side="left", padx=6)

        table_frame = ttk.Frame(win, style="Dark.TFrame")
        table_frame.pack(fill="both", expand=True, padx=12, pady=8)
        vsb = ttk.Scrollbar(table_frame, orient="vertical", style="Dark.Vertical.TScrollbar")
        vsb.pack(side="right", fill="y")
        cols = ("PR ID","Material","Purpose","Quantity","Remaining","Requestor","Status","Requested Date", "Received Date", "PO Number","ETD")
        table = ttk.Treeview(table_frame, columns=cols, show="headings", yscrollcommand=vsb.set, style="Dark.Treeview")
        vsb.config(command=table.yview)

        table.column("PR ID", width=40, anchor="center")
        table.column("Material", width=160, anchor="w")
        table.column("Purpose", width=140, anchor="w")
        table.column("Quantity", width=60, anchor="center")
        table.column("Remaining", width=70, anchor="center")
        table.column("Requestor", width=70, anchor="center")
        table.column("Status", width=50, anchor="center")
        table.column("Requested Date", width=100, anchor="center")
        table.column("Received Date", width=100, anchor="center")
        table.column("PO Number", width=70, anchor="center")
        table.column("ETD", width=100, anchor="center")
        for ccol in cols:
            table.heading(ccol, text=ccol)
        table.pack(fill="both", expand=True)

        table.tag_configure('evenrow', background=BACKGROUND_GRAY, foreground=TEXT_DARK)
        table.tag_configure('oddrow', background=SURFACE_WHITE, foreground=TEXT_DARK)

        def load_table():
            for r in table.get_children():
                table.delete(r)
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            q = """
                SELECT pr.id, m.description, pr.purpose, pr.quantity, pr.quantity_remaining,
                        pr.requestor, pr.status, pr.date_requested, COALESCE(pr.date_closed,''),
                        pr.po_number, pr.estimated_delivery_date
                FROM purchase_requests pr
                JOIN materials m ON pr.material_id = m.id
            """
            val = search.get().strip()
            if val:
                like = f"%{val}%"
                q += " WHERE m.description LIKE ? OR pr.requestor LIKE ? OR pr.purpose LIKE ? OR pr.status LIKE ? OR pr.po_number LIKE ?"
                c.execute(q, (like, like, like, like, like))
            else:
                c.execute(q)
            rows = c.fetchall()
            conn.close()
            for i, r in enumerate(rows):
                tag = 'evenrow' if i % 2 == 0 else 'oddrow'
                r_list = list(r)
                r_list[1] = self.wrap_text(r_list[1], every=48)
                r_list[2] = self.wrap_text(r_list[2], every=48)
                table.insert("", "end", values=r_list, tags=(tag,))

        actions = ttk.Frame(win, style="Dark.TFrame")
        actions.pack(fill="x", padx=12, pady=(0,10))
        def selected_pr_id():
            sel = table.selection()
            if not sel:
                return None
            return table.item(sel)["values"][0]

        def edit_pr():
            pid = selected_pr_id()
            if not pid:
                messagebox.showwarning("Select", "Select a PR to edit.")
                return
            
            # Get current PR data
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("""
                SELECT pr.material_id, m.description, pr.purpose, pr.quantity, pr.quantity_remaining, 
                       pr.requestor, pr.status, pr.po_number, pr.estimated_delivery_date
                FROM purchase_requests pr
                JOIN materials m ON pr.material_id = m.id
                WHERE pr.id = ?
            """, (pid,))
            pr_data = c.fetchone()
            conn.close()
            
            if not pr_data:
                messagebox.showerror("Error", "PR not found.")
                return
            
            mat_id, mat_desc, purpose, qty, qty_rem, requestor, status, po_num, etd = pr_data
            
            # Check if PR is fulfilled - cannot edit
            if status == 'fulfilled':
                messagebox.showwarning("Cannot Edit", "Cannot edit a fulfilled PR. Cancel or delete it instead.")
                return
            
            # Create edit dialog
            edit_win = tk.Toplevel(win, bg=BACKGROUND_GRAY)
            apply_material_style(edit_win)
            edit_win.title(f"Edit PR #{pid}")
            edit_win.geometry("520x400")
            edit_win.transient(win)
            edit_win.grab_set()
            
            edit_form = ttk.Frame(edit_win, style="Dark.TFrame")
            edit_form.pack(fill="both", expand=True, padx=12, pady=10)
            
            # Material (readonly - show current)
            tk.Label(edit_form, text="Material:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).grid(row=0, column=0, sticky="w", padx=(2,8), pady=4)
            tk.Label(edit_form, text=f"{mat_id} - {mat_desc}", bg=BACKGROUND_GRAY, fg=TEXT_GRAY, font=FONT).grid(row=0, column=1, sticky="w", pady=4)
            
            # Purpose
            tk.Label(edit_form, text="Purpose:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).grid(row=1, column=0, sticky="w", padx=(2,8), pady=4)
            edit_purpose_var = tk.StringVar(value=purpose or "")
            ttk.Entry(edit_form, textvariable=edit_purpose_var, style="Dark.TEntry", width=50).grid(row=1, column=1, sticky="ew", pady=4)
            
            # Quantity
            tk.Label(edit_form, text="Quantity:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).grid(row=2, column=0, sticky="w", padx=(2,8), pady=4)
            edit_qty_var = tk.IntVar(value=qty)
            qty_entry = ttk.Entry(edit_form, textvariable=edit_qty_var, style="Dark.TEntry", width=20)
            qty_entry.grid(row=2, column=1, sticky="w", pady=4)
            
            # Show received amount
            received_qty = qty - qty_rem
            tk.Label(edit_form, text=f"(Already received: {received_qty})", bg=BACKGROUND_GRAY, fg=TEXT_GRAY, font=SMALL_FONT).grid(row=2, column=1, sticky="w", padx=(150,0), pady=4)
            
            # Requestor
            tk.Label(edit_form, text="Requestor:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).grid(row=3, column=0, sticky="w", padx=(2,8), pady=4)
            edit_req_var = tk.StringVar(value=requestor or "")
            ttk.Entry(edit_form, textvariable=edit_req_var, style="Dark.TEntry", width=50).grid(row=3, column=1, sticky="ew", pady=4)
            
            # PO Number
            tk.Label(edit_form, text="PO Number:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).grid(row=4, column=0, sticky="w", padx=(2,8), pady=4)
            edit_po_var = tk.StringVar(value=po_num or "")
            ttk.Entry(edit_form, textvariable=edit_po_var, style="Dark.TEntry", width=50).grid(row=4, column=1, sticky="ew", pady=4)
            
            # ETD
            tk.Label(edit_form, text="ETD:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).grid(row=5, column=0, sticky="w", padx=(2,8), pady=4)
            edit_etd_var = tk.StringVar(value=etd or "")
            edit_cal = DateEntry(edit_form, selectmode='day', textvariable=edit_etd_var, date_pattern='yyyy-mm-dd')
            edit_cal.grid(row=5, column=1, sticky="w", pady=4)
            
            # Status info (readonly)
            tk.Label(edit_form, text="Status:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).grid(row=6, column=0, sticky="w", padx=(2,8), pady=4)
            tk.Label(edit_form, text=status, bg=BACKGROUND_GRAY, fg=TEXT_GRAY, font=FONT).grid(row=6, column=1, sticky="w", pady=4)
            
            edit_form.grid_columnconfigure(1, weight=1)
            
            def save_changes():
                try:
                    new_qty = int(edit_qty_var.get())
                except Exception:
                    messagebox.showerror("Invalid", "Enter a valid quantity.")
                    return
                
                # Validate: new quantity must be >= already received
                if new_qty < received_qty:
                    messagebox.showerror("Invalid", f"Cannot set quantity below already received amount ({received_qty}).")
                    return
                
                if new_qty <= 0:
                    messagebox.showerror("Invalid", "Quantity must be > 0.")
                    return
                
                # Calculate new remaining
                new_remaining = new_qty - received_qty
                
                # Update PR
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                try:
                    c.execute("""
                        UPDATE purchase_requests 
                        SET purpose=?, quantity=?, quantity_remaining=?, requestor=?, po_number=?, estimated_delivery_date=?
                        WHERE id=?
                    """, (
                        edit_purpose_var.get().strip(),
                        new_qty,
                        new_remaining,
                        edit_req_var.get().strip(),
                        edit_po_var.get().strip(),
                        edit_etd_var.get().strip(),
                        pid
                    ))
                    conn.commit()
                    messagebox.showinfo("Success", "PR updated successfully.")
                    edit_win.grab_release()
                    edit_win.destroy()
                    load_table()
                except Exception as e:
                    conn.rollback()
                    messagebox.showerror("Error", f"Failed to update PR: {e}")
                finally:
                    conn.close()
            
            def cancel_edit():
                edit_win.grab_release()
                edit_win.destroy()
            
            # Buttons
            btn_frame = tk.Frame(edit_win, bg=BACKGROUND_GRAY)
            btn_frame.pack(fill="x", padx=12, pady=(8,12))
            ttk.Button(btn_frame, text="Save Changes", style="Dark.TButton", command=save_changes).pack(side="left", padx=6)
            ttk.Button(btn_frame, text="Cancel", style="Dark.TButton", command=cancel_edit).pack(side="left", padx=6)

        def mark_fulfilled():
            pid = selected_pr_id()
            if not pid:
                messagebox.showwarning("Select", "Select a PR.")
                return
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE purchase_requests SET quantity_remaining=0, status='fulfilled', date_closed=? WHERE id=?",
                      (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), pid))
            conn.commit()
            conn.close()
            load_table()

        def cancel_pr():
            pid = selected_pr_id()
            if not pid:
                messagebox.showwarning("Select", "Select a PR.")
                return
            if not messagebox.askyesno("Confirm", "Cancel selected PR?"):
                return
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE purchase_requests SET status='cancelled', date_closed=? WHERE id=?",
                      (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), pid))
            conn.commit()
            conn.close()
            load_table()

        def delete_pr():
            pid = selected_pr_id()
            if not pid:
                messagebox.showwarning("Select", "Select a PR.")
                return
            if not messagebox.askyesno("Confirm", "Delete selected PR permanently?"):
                return
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("DELETE FROM purchase_requests WHERE id=?", (pid,))
            conn.commit()
            conn.close()
            load_table()

        ttk.Button(actions, text="Edit PR", style="Dark.TButton", command=edit_pr).pack(side="left", padx=6)
        ttk.Button(actions, text="Mark Fulfilled", style="Dark.TButton", command=mark_fulfilled).pack(side="left", padx=6)
        ttk.Button(actions, text="Cancel PR", style="Dark.TButton", command=cancel_pr).pack(side="left", padx=6)
        ttk.Button(actions, text="Delete PR", style="Dark.TButton", command=delete_pr).pack(side="left", padx=6)
        ttk.Button(actions, text="Refresh", style="Dark.TButton", command=load_table).pack(side="left", padx=6)
        ttk.Button(actions, text="Close", style="Dark.TButton", command=win.destroy).pack(side="right", padx=6)

        load_table()

    # --- Admin user management UI (existing) ---
    def open_manage_users(self):
        if self.current_user['role'] != 'admin':
            messagebox.showwarning("Access Denied", "Only admin users can manage users.")
            return
    
        win = tk.Toplevel(self.root, bg=BACKGROUND_GRAY)
        apply_material_style(win)
        win.title("Manage Users")
        win.geometry("900x520")
    
        left = ttk.Frame(win, style="Dark.TFrame")
        left.pack(side="left", fill="both", expand=True, padx=12, pady=12)
        right = ttk.Frame(win, style="Dark.TFrame", width=260)
        right.pack(side="right", fill="y", padx=10, pady=12)
    
        vsb = ttk.Scrollbar(left, orient="vertical", style="Dark.Vertical.TScrollbar")
        vsb.pack(side="right", fill="y")
    
        # Added "Name" column
        tree = ttk.Treeview(
            left,
            columns=("ID", "Username", "Name", "Role"),
            show="headings",
            yscrollcommand=vsb.set,
            style="Dark.Treeview"
        )
        vsb.config(command=tree.yview)
    
        for col in tree["columns"]:
            tree.heading(col, text=col)
            tree.column(col, width=150, anchor="center")
        tree.pack(fill="both", expand=True)
    
        tree.tag_configure('evenrow', background=BACKGROUND_GRAY, foreground=TEXT_DARK)
        tree.tag_configure('oddrow', background=SURFACE_WHITE, foreground=TEXT_DARK)
    
        def load():
            for r in tree.get_children():
                tree.delete(r)
            for i, row in enumerate(list_users()):  # row = (id, username, name, role)
                tag = 'evenrow' if i % 2 == 0 else 'oddrow'
                tree.insert("", "end", values=row, tags=(tag,))
    
        # --- Right side controls ---
        tk.Label(right, text="Username:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).pack(anchor="w")
        username_var = tk.StringVar()
        ttk.Entry(right, textvariable=username_var, style="Dark.TEntry").pack(fill="x", pady=4)
    
        tk.Label(right, text="Name:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).pack(anchor="w", pady=(6,0))
        name_var = tk.StringVar()
        ttk.Entry(right, textvariable=name_var, style="Dark.TEntry").pack(fill="x", pady=4)
    
        tk.Label(right, text="Password:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).pack(anchor="w", pady=(6,0))
        password_var = tk.StringVar()
        ttk.Entry(right, textvariable=password_var, style="Dark.TEntry", show="*").pack(fill="x", pady=4)
    
        tk.Label(right, text="Role:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).pack(anchor="w", pady=(6,0))
        role_var = tk.StringVar(value="normal")
        role_cb = ttk.Combobox(right, textvariable=role_var, values=["admin", "normal"], state="readonly", style="Dark.TCombobox")
        role_cb.pack(fill="x", pady=4)
    
        def on_add():
            u = username_var.get().strip()
            n = name_var.get().strip()
            p = password_var.get()
            r = role_var.get()
            if not u or not p:
                messagebox.showwarning("Input Error", "Username and password are required.")
                return
            ok, err = create_user(u, n, p, r)
            if ok:
                messagebox.showinfo("User Added", f"User '{u}' created.")
                username_var.set(""); name_var.set(""); password_var.set("")
                load()
            else:
                messagebox.showerror("Error", f"Could not create user: {err}")
    
        def on_delete():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("Select", "Select a user to delete.")
                return
            uid = tree.item(sel)["values"][0]
            uname = tree.item(sel)["values"][1]
            if uid == self.current_user['id']:
                messagebox.showwarning("Action Denied", "You cannot delete the user you're currently logged in as.")
                return
            if messagebox.askyesno("Confirm", f"Delete user '{uname}'?"):
                delete_user(uid)
                load()
    
        def on_reset_pw():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("Select", "Select a user to reset password.")
                return
            uid = tree.item(sel)["values"][0]
            uname = tree.item(sel)["values"][1]
            newpw = simpledialog.askstring("Reset Password", f"Enter new password for {uname}:", show="*")
            if newpw:
                reset_user_password(uid, newpw)
                messagebox.showinfo("Reset", f"Password for {uname} has been reset.")
    
        def on_change_role():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("Select", "Select a user to change role.")
                return
            uid = tree.item(sel)["values"][0]
            uname = tree.item(sel)["values"][1]
            newrole = simpledialog.askstring("Change Role", f"Enter new role for {uname} (admin/normal):")
            if newrole and newrole in ("admin", "normal"):
                if newrole != "admin":
                    users = list_users()
                    admin_count = sum(1 for u in users if u[3] == 'admin')  # role is now index 3
                    selected_role = None
                    for u in users:
                        if u[0] == uid:
                            selected_role = u[3]
                    if selected_role == 'admin' and admin_count <= 1:
                        messagebox.showwarning("Action Denied", "Cannot remove the last admin.")
                        return
                update_user_role(uid, newrole)
                messagebox.showinfo("Role Changed", f"{uname} is now '{newrole}'.")
                load()
            else:
                messagebox.showwarning("Invalid", "Role must be 'admin' or 'normal'.")
    
        ttk.Button(right, text="Add User", style="Dark.TButton", command=on_add).pack(fill="x", pady=(10,4))
        ttk.Button(right, text="Delete User", style="Dark.TButton", command=on_delete).pack(fill="x", pady=4)
        ttk.Button(right, text="Reset Password", style="Dark.TButton", command=on_reset_pw).pack(fill="x", pady=4)
        ttk.Button(right, text="Change Role", style="Dark.TButton", command=on_change_role).pack(fill="x", pady=4)
        ttk.Button(right, text="Close", style="Dark.TButton", command=win.destroy).pack(fill="x", pady=(18,0))
    
        load()

        
    # --- Change password for self (existing) ---
    def change_password_window(self):
        win = tk.Toplevel(self.root, bg=BACKGROUND_GRAY)
        apply_material_style(win)
        win.title("Change Password")
        win.geometry("380x230")

        tk.Label(win, text="Current Password:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).pack(pady=(10,0), padx=10, anchor="w")
        old_var = tk.StringVar()
        ttk.Entry(win, textvariable=old_var, style="Dark.TEntry", show="*").pack(fill="x", padx=12, pady=4)

        tk.Label(win, text="New Password:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).pack(pady=(10,0), padx=10, anchor="w")
        new_var = tk.StringVar()
        ttk.Entry(win, textvariable=new_var, style="Dark.TEntry", show="*").pack(fill="x", padx=12, pady=4)

        tk.Label(win, text="Confirm New Password:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).pack(anchor="w", padx=12, pady=(8,0))
        confirm_var = tk.StringVar()
        ttk.Entry(win, textvariable=confirm_var, style="Dark.TEntry", show="*").pack(fill="x", padx=12, pady=4)

        def submit():
            old = old_var.get(); new = new_var.get(); confirm = confirm_var.get()
            if not old or not new:
                messagebox.showwarning("Input Error", "Please fill all fields.")
                return
            if new != confirm:
                messagebox.showwarning("Mismatch", "New password and confirmation do not match.")
                return
            ok, err = change_own_password(self.current_user['id'], old, new)
            if ok:
                messagebox.showinfo("Success", "Password changed successfully.")
                win.destroy()
            else:
                messagebox.showerror("Error", err)
        ttk.Button(win, text="Change Password", style="Dark.TButton", command=submit).pack(pady=12)

    def logout(self):
        if messagebox.askyesno("Logout", "Are you sure you want to logout?"):
            self.root.destroy()
            launch_login()

    # ----------------- ASSEMBLY MANAGER (ADMIN) -----------------
    def open_assembly_manager(self):
        if self.current_user['role'] != 'admin':
            messagebox.showwarning("Access Denied", "Only admin users can manage assemblies.")
            return

        win = tk.Toplevel(self.root, bg=BACKGROUND_GRAY)
        apply_material_style(win)
        win.title("Assembly Manager")
        win.geometry("1150x570")

        left = ttk.Frame(win, style="Dark.TFrame")
        left.pack(side="left", fill="both", expand=True, padx=12, pady=12)
        right = ttk.Frame(win, style="Dark.TFrame")
        right.pack(side="right", fill="both", expand=True, padx=12, pady=12)

        # Assemblies list
        lbl = tk.Label(left, text="Assemblies", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=HEADER_FONT)
        lbl.pack(anchor="w", pady=(0,8))
        vsb = ttk.Scrollbar(left, orient="vertical", style="Dark.Vertical.TScrollbar")
        vsb.pack(side="right", fill="y")
        tree_assemblies = ttk.Treeview(left, columns=("ID", "Name"), show="headings", yscrollcommand=vsb.set, style="Dark.Treeview")
        vsb.config(command=tree_assemblies.yview)
        tree_assemblies.heading("ID", text="ID")
        tree_assemblies.heading("Name", text="Name")
        tree_assemblies.column("ID", width=10, anchor="center")
        tree_assemblies.column("Name", width=150, anchor="w")
        tree_assemblies.pack(fill="both", expand=True)

        tree_assemblies.tag_configure('evenrow', background=BACKGROUND_GRAY, foreground=TEXT_DARK)
        tree_assemblies.tag_configure('oddrow', background=SURFACE_WHITE, foreground=TEXT_DARK)

        # Right side: parts in assembly
        tk.Label(right, text="Assembly Parts", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).pack(anchor="w")
        vsb2 = ttk.Scrollbar(right, orient="vertical", style="Dark.Vertical.TScrollbar")
        vsb2.pack(side="right", fill="y", pady=(6,0))
        tree_parts = ttk.Treeview(right, columns=("AP ID", "Material ID", "Material", "Qty"), show="headings", yscrollcommand=vsb2.set, style="Dark.Treeview", height=14)
        vsb2.config(command=tree_parts.yview)
        tree_parts.heading("AP ID", text="AP ID")
        tree_parts.heading("Material ID", text="Material ID")
        tree_parts.heading("Material", text="Material")
        tree_parts.heading("Qty", text="Qty")
        tree_parts.column("AP ID", width=60, anchor="center")
        tree_parts.column("Material ID", width=80, anchor="center")
        tree_parts.column("Material", width=160, anchor="w")
        tree_parts.column("Qty", width=60, anchor="center")
        tree_parts.pack(fill="both", pady=(6,8))

        tree_parts.tag_configure('evenrow', background=BACKGROUND_GRAY, foreground=TEXT_DARK)
        tree_parts.tag_configure('oddrow', background=SURFACE_WHITE, foreground=TEXT_DARK)

        # Controls under parts
        btn_frame = tk.Frame(right, bg=BACKGROUND_GRAY)
        btn_frame.pack(fill="x", pady=(6,0))
        ttk.Button(btn_frame, text="New Assembly", style="Dark.TButton", command=lambda: new_assembly()).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Delete Assembly", style="Dark.TButton", command=lambda: delete_assembly()).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Add Part", style="Dark.TButton", command=lambda: add_part_to_assembly()).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Remove Part", style="Dark.TButton", command=lambda: remove_part()).pack(side="left", padx=4)

        # Load assemblies
        def refresh_assemblies():
            for r in tree_assemblies.get_children():
                tree_assemblies.delete(r)
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT id, name FROM assemblies ORDER BY name")
            rows = c.fetchall()
            conn.close()
            for i, r in enumerate(rows):
                tag = 'evenrow' if i % 2 == 0 else 'oddrow'
                tree_assemblies.insert("", "end", values=r, tags=(tag,))
            self.load_assemblies_map()
        refresh_assemblies()

        def refresh_parts(assembly_id):
            for r in tree_parts.get_children():
                tree_parts.delete(r)
            if assembly_id is None:
                return
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("""
                SELECT ap.id, m.id, m.description, ap.quantity_needed
                FROM assembly_parts ap
                JOIN materials m ON ap.material_id = m.id
                WHERE ap.assembly_id = ?
                ORDER BY m.description
            """, (assembly_id,))
            rows = c.fetchall()
            conn.close()
            for i, r in enumerate(rows):
                tag = 'evenrow' if i % 2 == 0 else 'oddrow'
                tree_parts.insert("", "end", values=(r[0], r[1], r[2], r[3]), tags=(tag,))

        def on_select_assembly(event):
            sel = tree_assemblies.selection()
            if not sel:
                refresh_parts(None)
                return
            aid = tree_assemblies.item(sel)["values"][0]
            refresh_parts(aid)
        tree_assemblies.bind("<<TreeviewSelect>>", on_select_assembly)

        def new_assembly():
            name = simpledialog.askstring("New Assembly", "Enter name for the new assembly:")
            if not name or not name.strip():
                return
            name = name.strip()
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            try:
                c.execute("INSERT INTO assemblies (name) VALUES (?)", (name,))
                conn.commit()
                messagebox.showinfo("Added", f"Assembly '{name}' created.")
            except sqlite3.IntegrityError:
                messagebox.showerror("Error", "An assembly with that name already exists.")
            finally:
                conn.close()
            refresh_assemblies()

        def delete_assembly():
            sel = tree_assemblies.selection()
            if not sel:
                messagebox.showwarning("Select", "Select an assembly to delete.")
                return
            aid = tree_assemblies.item(sel)["values"][0]
            aname = tree_assemblies.item(sel)["values"][1]
            if messagebox.askyesno("Confirm", f"Delete assembly '{aname}'? This will also remove its parts."):
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("DELETE FROM assembly_parts WHERE assembly_id = ?", (aid,))
                c.execute("DELETE FROM assemblies WHERE id = ?", (aid,))
                conn.commit()
                conn.close()
                refresh_assemblies()
                refresh_parts(None)

        def add_part_to_assembly():
            sel = tree_assemblies.selection()
            if not sel:
                messagebox.showwarning("Select", "Select an assembly first.")
                return
            aid = tree_assemblies.item(sel)["values"][0]

            # Fetch materials sorted by Material ID
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT id, description, quantity_on_hand FROM materials ORDER BY id")
            mats = c.fetchall()
            conn.close()

            if not mats:
                messagebox.showwarning("No materials", "No materials available to add. Add materials first.")
                return

            # Prepare mapping and choices
            choices = [f"{m[0]} - {m[1]}" for m in mats]
            id_from_display = {f"{m[0]} - {m[1]}": m[0] for m in mats}

            # Dialog to choose material and qty
            dlg = tk.Toplevel(win)
            apply_material_style(dlg)
            dlg.title("Add Part to Assembly")
            dlg.geometry("480x200")
            dlg.transient(win)
            dlg.grab_set()

            tk.Label(dlg, text="Select Material:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).pack(anchor="w", padx=12, pady=(12,0))
            sel_mat_var = tk.StringVar()
            mat_combo = ttk.Combobox(dlg, textvariable=sel_mat_var, values=choices, style="Dark.TCombobox", width=60)
            mat_combo.pack(fill="x", padx=12, pady=(4,6))
            mat_combo.focus()

            # Searchable filter
            def update_combo_values(event):
                typed = sel_mat_var.get().lower()
                filtered = [item for item in choices if typed in item.lower()]
                mat_combo['values'] = filtered
            mat_combo.bind("<KeyRelease>", update_combo_values)

            if choices:
                mat_combo.set(choices[0])

            tk.Label(dlg, text="Quantity Needed:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).pack(anchor="w", padx=12, pady=(6,0))
            qty_var = tk.IntVar(value=1)
            qty_spin = tk.Spinbox(dlg, from_=1, to=1000000, textvariable=qty_var)
            qty_spin.pack(fill="x", padx=12, pady=(4,8))

            def on_add_confirm():
                sel_display = sel_mat_var.get()
                if not sel_display:
                    messagebox.showwarning("Select", "Select a material.")
                    return
                mat_id = id_from_display.get(sel_display)
                try:
                    qty = int(qty_var.get())
                except Exception:
                    messagebox.showerror("Invalid", "Enter a valid quantity.")
                    return
                if qty <= 0:
                    messagebox.showerror("Invalid", "Quantity must be > 0.")
                    return
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                # check if exists -> update, else insert
                c.execute("SELECT id FROM assembly_parts WHERE assembly_id = ? AND material_id = ?", (aid, mat_id))
                existing = c.fetchone()
                if existing:
                    c.execute("UPDATE assembly_parts SET quantity_needed = ? WHERE id = ?", (qty, existing[0]))
                else:
                    c.execute("INSERT INTO assembly_parts (assembly_id, material_id, quantity_needed) VALUES (?, ?, ?)",
                              (aid, mat_id, qty))
                conn.commit()
                conn.close()
                dlg.grab_release()
                dlg.destroy()
                refresh_parts(aid)

            def on_cancel():
                dlg.grab_release()
                dlg.destroy()

            btns = tk.Frame(dlg, bg=BACKGROUND_GRAY)
            btns.pack(fill="x", padx=12, pady=(8,12))
            ttk.Button(btns, text="Add/Update", style="Dark.TButton", command=on_add_confirm).pack(side="left", padx=6)
            ttk.Button(btns, text="Cancel", style="Dark.TButton", command=on_cancel).pack(side="left", padx=6)


        def remove_part():
            sel = tree_parts.selection()
            if not sel:
                messagebox.showwarning("Select", "Select a part to remove.")
                return
            ap_id = tree_parts.item(sel)["values"][0]
            if messagebox.askyesno("Confirm", "Remove selected part from assembly?"):
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("DELETE FROM assembly_parts WHERE id = ?", (ap_id,))
                conn.commit()
                conn.close()
                # refresh
                sel_ass = tree_assemblies.selection()
                if sel_ass:
                    refresh_parts(tree_assemblies.item(sel_ass)["values"][0])
                else:
                    refresh_parts(None)

    # ----------------- WITHDRAW ASSEMBLY UI & LOGIC -----------------
    def open_assembly_withdraw_window(self):
        # select assembly then show its parts and allow withdrawal
        self.load_assemblies_map()
        if not self.assemblies_map:
            messagebox.showwarning("No Assemblies", "No assemblies defined. Ask an admin to create assemblies first.")
            return
        win = tk.Toplevel(self.root, bg=BACKGROUND_GRAY)
        apply_material_style(win)
        win.title("Withdraw Assembly")
        win.geometry("940x480")

        top = ttk.Frame(win, style="Dark.TFrame")
        top.pack(fill="x", padx=12, pady=8)
        tk.Label(top, text="Select Assembly:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).pack(side="left", padx=(4,8))
        assembly_names = sorted(self.assemblies_map.keys())
        sel_var = tk.StringVar()
        assembly_cb = ttk.Combobox(top, textvariable=sel_var, values=assembly_names, state="readonly", style="Dark.TCombobox", width=40)
        assembly_cb.pack(side="left", padx=6)
        assembly_cb.set(assembly_names[0])

        body = ttk.Frame(win, style="Dark.TFrame")
        body.pack(fill="both", expand=True, padx=12, pady=(6,12))

        vsb = ttk.Scrollbar(body, orient="vertical", style="Dark.Vertical.TScrollbar")
        vsb.pack(side="right", fill="y")
        table = ttk.Treeview(body, columns=("Material ID", "Material", "Required Qty", "Qty on Hand"), show="headings", yscrollcommand=vsb.set, style="Dark.Treeview")
        vsb.config(command=table.yview)
        for col in table["columns"]:
            table.heading(col, text=col)
            table.column(col, width=140, anchor="center")
        table.pack(fill="both", expand=True)

        def load_parts_for_selected():
            for r in table.get_children():
                table.delete(r)
            name = sel_var.get().strip()
            if not name:
                return
            aid = self.assemblies_map.get(name)
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("""
                SELECT ap.id, m.id, m.description, ap.quantity_needed, m.quantity_on_hand
                FROM assembly_parts ap
                JOIN materials m ON ap.material_id = m.id
                WHERE ap.assembly_id = ?
                ORDER BY m.description
            """, (aid,))
            rows = c.fetchall()
            conn.close()
            for i, r in enumerate(rows):
                tag = 'evenrow' if i % 2 == 0 else 'oddrow'
                # display material id (r[1]), description (r[2]), needed (r[3]), qoh (r[4])
                table.insert("", "end", values=(r[1], r[2], r[3], r[4]), tags=(tag,))
        load_parts_for_selected()
        assembly_cb.bind("<<ComboboxSelected>>", lambda e: load_parts_for_selected())

        footer = ttk.Frame(win, style="Dark.TFrame")
        footer.pack(fill="x", padx=12, pady=(4,12))
        
        # New: Purpose Entry
        tk.Label(footer, text="Purpose:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).pack(side="left", padx=(4,8))
        purpose_var = tk.StringVar()
        ttk.Entry(footer, textvariable=purpose_var, style="Dark.TEntry", width=30).pack(side="left", padx=(0,8))
        
        # Original: Withdrawn By Entry
        tk.Label(footer, text="Withdrawn By:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).pack(side="left", padx=(4,8))
        by_var = tk.StringVar()
        ttk.Entry(footer, textvariable=by_var, style="Dark.TEntry", width=30).pack(side="left", padx=(0,8))
        
        ttk.Button(footer, text="Check Availability", style="Dark.TButton", command=lambda: check_availability()).pack(side="left", padx=6)
        ttk.Button(footer, text="Withdraw Assembly", style="Dark.TButton", command=lambda: perform_withdraw()).pack(side="right", padx=6)
        def check_availability():
            # highlight rows in table where not enough stock
            insufficient = []
            for iid in table.get_children():
                vals = table.item(iid)["values"]
                try:
                    q_needed = int(vals[2])
                    q_onhand = int(vals[3])
                except Exception:
                    q_needed = 0; q_onhand = 0
                if q_onhand < q_needed:
                    insufficient.append((vals[1], q_needed, q_onhand))
            if insufficient:
                msg = "Insufficient stock for:\n" + "\n".join([f"{m}: need {n}, have {h}" for m,n,h in insufficient])
                messagebox.showerror("Insufficient Stock", msg)
            else:
                messagebox.showinfo("Available", "All parts are available for withdrawal.")

        def perform_withdraw():
            name = sel_var.get().strip()
            if not name:
                messagebox.showwarning("Select", "Select an assembly.")
                return
            aid = self.assemblies_map.get(name)
            by = by_var.get().strip()
            if not by:
                if not messagebox.askyesno("No Withdrawn By", "No 'Withdrawn By' entered. Proceed?"):
                    return
            # gather parts
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("""
                SELECT ap.id, ap.material_id, m.description, ap.quantity_needed, m.quantity_on_hand, m.maintaining_stock, m.part_number
                FROM assembly_parts ap
                JOIN materials m ON ap.material_id = m.id
                WHERE ap.assembly_id = ?
            """, (aid,))
            rows = c.fetchall()
            # check availability first
            insufficient = []
            for r in rows:
                ap_id, mat_id, desc, needed, qoh, maintaining, partnum = r
                if qoh < needed:
                    insufficient.append((desc, needed, qoh))
            if insufficient:
                conn.close()
                msg = "Insufficient stock for:\n" + "\n".join([f"{m}: need {n}, have {h}" for m,n,h in insufficient])
                messagebox.showerror("Insufficient Stock", msg)
                return
            # All available: perform withdrawal in DB
            try:
                for r in rows:
                    ap_id, mat_id, desc, needed, qoh, maintaining, partnum = r
                    new_q = qoh - needed
                    c.execute("UPDATE materials SET quantity_on_hand = ? WHERE id = ?", (new_q, mat_id))
                    #purpose = f"Assembly: {name}"
                    c.execute("INSERT INTO withdrawals (material_id, quantity, purpose, withdrawn_by, date) VALUES (?, ?, ?, ?, ?)",
                              (mat_id, needed, purpose_var.get(), by, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                conn.commit()
                # after commit, check low stock and prepare alerts
                low_alerts = []
                for r in rows:
                    mat_id = r[1]
                    desc = r[2]
                    partnum = r[6] or ""
                    c.execute("SELECT quantity_on_hand, maintaining_stock FROM materials WHERE id = ?", (mat_id,))
                    res = c.fetchone()
                    if res:
                        qoh_new = self._safe_int(res[0], 0)
                        maintaining = self._safe_int(res[1], 0)
                        if qoh_new <= maintaining:
                            low_alerts.append((mat_id, desc, partnum, qoh_new, maintaining))
                # sync low stock for all affected materials
                for la in low_alerts:
                    mat_id = la[0]
                    self.update_low_stock_dashboard(mat_id)
                conn.close()
                self.load_data()
                messagebox.showinfo("Success", f"Assembly '{name}' withdrawn successfully.")
                if low_alerts:
                    subj = f"LOW STOCK ALERTS AFTER ASSEMBLY WITHDRAWAL: {name}"
                    body_lines = []
                    for la in low_alerts:
                        body_lines.append(f"Description: {la[1]}\nPart Number: {la[2]}\nNew QOH: {la[3]}\nMaintaining Stock: {la[4]}\n")
                    body = "The following items have reached or fallen below maintaining stock after assembly withdrawal:\n\n" + "\n".join(body_lines)
                    send_outlook_email(TO_EMAILS, CC_EMAILS, BCC_EMAILS, subj, body)
                win.destroy()
            except Exception as e:
                conn.rollback()
                conn.close()
                messagebox.showerror("Error", f"Failed to perform withdrawal: {e}")

    # ----------- END: Assembly & Withdraw logic -----------

# ----------- Login UI -----------
def launch_login():
    login_root = tk.Tk()
    login_root.title("Login - BMS Inventory System")
    try:
        login_root.geometry("420x260")
        login_root.resizable(False, False)
        login_root.eval('tk::PlaceWindow %s center' % login_root.winfo_pathname(login_root.winfo_id()))
    except Exception:
        pass

    apply_material_style(login_root)

    card = ttk.Frame(login_root, style="Dark.TFrame", padding=16)
    card.place(relx=0.5, rely=0.5, anchor="center")

    tk.Label(card, text="BMS Inventory System Login", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=TITLE_FONT).grid(row=0, column=0, columnspan=2, pady=(0,12))
    tk.Label(card, text="Username:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).grid(row=1, column=0, sticky="w", pady=6)
    username_var = tk.StringVar()
    ttk.Entry(card, textvariable=username_var, style="Dark.TEntry", width=30).grid(row=1, column=1, pady=6, padx=(8,0))

    tk.Label(card, text="Password:", bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=FONT).grid(row=2, column=0, sticky="w", pady=6)
    password_var = tk.StringVar()
    ttk.Entry(card, textvariable=password_var, style="Dark.TEntry", show="*", width=30).grid(row=2, column=1, pady=6, padx=(8,0))

    def attempt_login():
        uname = username_var.get().strip()
        pw = password_var.get()
    
        if not uname or not pw:
            messagebox.showwarning("Input", "Enter username and password.")
            return
    
        row = get_user_by_username(uname)
        if not row:
            messagebox.showerror("Login Failed", "User not found.")
            return
    
        # row now includes 'name'
        uid, username, name, stored_pw, role = row
    
        if verify_password(stored_pw, pw):
            login_root.destroy()
            root = tk.Tk()
    
            # Store name as well
            current_user = {
                'id': uid,
                'username': username,
                'name': name or username,  # fallback to username if name is NULL
                'role': role
            }

            app = InventoryApp(root, current_user)
            root.mainloop()
        else:
            messagebox.showerror("Login Failed", "Incorrect password.")

    def on_quit():
        if messagebox.askyesno("Quit", "Exit application?"):
            login_root.destroy()
            sys.exit(0)
    
    
    btn_frame = tk.Frame(card, bg=BACKGROUND_GRAY)
    btn_frame.grid(row=3, column=0, columnspan=2, pady=(12,0))
    ttk.Button(btn_frame, text="Login", style="Dark.TButton", width=14, command=attempt_login).pack(side="left", padx=6)
    ttk.Button(btn_frame, text="Quit", style="Dark.TButton", width=14, command=on_quit).pack(side="left", padx=6)
    
    if DEBUG:
        tk.Label(card, text="(DEBUG: default admin/admin created on first run)", 
                 bg=BACKGROUND_GRAY, fg=TEXT_DARK, font=SMALL_FONT).grid(row=4, column=0, columnspan=2, pady=(8,0))
    
    login_root.protocol("WM_DELETE_WINDOW", on_quit)
    login_root.mainloop()

# ----------- RUN APP -----------
if __name__ == "__main__":
    init_db()
    launch_login()