"""
Simple SQLite editor for ESD wrist and footwear readings.

Usage: run this script on the same machine that can access the DB path configured
in `new_Attendance copy.py` (the DB path is used by default). The GUI allows
viewing, filtering, adding, editing, and deleting records in the `esd_data` table.

This script uses only the Python standard library and `tkinter`.
"""
import os
import sqlite3
import datetime
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

# Default DB path - match the one used in the attendance script
DB_PATH = r"\\phlsvr08\BMS Data\BMS_Database\ESD_Checker\ESDChecker.db"


def open_conn(path=DB_PATH):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Database not found: {path}")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def detect_columns(conn):
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(esd_data)")
    cols = [r[1] for r in cur.fetchall()]
    return cols


class ESDEditor(tk.Tk):
    def __init__(self, db_path=DB_PATH):
        super().__init__()
        self.title('ESD DB Editor')
        self.geometry('1000x600')
        self.db_path = db_path

        try:
            self.conn = open_conn(self.db_path)
        except Exception as e:
            messagebox.showerror('DB Error', str(e))
            self.destroy()
            return

        self.cols = detect_columns(self.conn)

        # UI
        top = ttk.Frame(self)
        top.pack(fill='x', padx=8, pady=6)

        ttk.Label(top, text='Filter name:').pack(side='left')
        self.filter_name = tk.Entry(top)
        self.filter_name.pack(side='left', padx=4)

        ttk.Label(top, text='From (YYYY-MM-DD):').pack(side='left', padx=8)
        self.filter_from = tk.Entry(top, width=12)
        self.filter_from.pack(side='left')

        ttk.Label(top, text='To (YYYY-MM-DD):').pack(side='left', padx=8)
        self.filter_to = tk.Entry(top, width=12)
        self.filter_to.pack(side='left')

        ttk.Button(top, text='Refresh', command=self.refresh).pack(side='left', padx=6)
        ttk.Button(top, text='Add Row', command=self.add_row).pack(side='left', padx=6)
        ttk.Button(top, text='Edit Selected', command=self.edit_selected).pack(side='left', padx=6)
        ttk.Button(top, text='Delete Selected', command=self.delete_selected).pack(side='left', padx=6)

        # Treeview
        cols = self.cols if self.cols else ['id', 'timestamp', 'emp_name', 'wrist', 'shoe']
        self.tree = ttk.Treeview(self, columns=cols, show='headings')
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=120, anchor='center')
        self.tree.pack(fill='both', expand=True, padx=8, pady=6)

        self.status = ttk.Label(self, text='Ready')
        self.status.pack(fill='x')

        self.refresh()

    def refresh(self):
        for r in self.tree.get_children():
            self.tree.delete(r)

        q = "SELECT * FROM esd_data"
        params = []
        w = []
        name = self.filter_name.get().strip()
        if name:
            # search anywhere in name
            w.append("emp_name LIKE ?")
            params.append(f"%{name}%")

        date_from = self.filter_from.get().strip()
        date_to = self.filter_to.get().strip()
        # Guess timestamp column name
        ts_col = None
        for c in self.cols:
            if 'time' in c.lower() or 'date' in c.lower():
                ts_col = c
                break

        if date_from and ts_col:
            w.append(f"DATE({ts_col}) >= ?")
            params.append(date_from)
        if date_to and ts_col:
            w.append(f"DATE({ts_col}) <= ?")
            params.append(date_to)

        if w:
            q += " WHERE " + " AND ".join(w)

        q += " ORDER BY "+ (ts_col or 'rowid') + " DESC LIMIT 1000"

        cur = self.conn.cursor()
        try:
            cur.execute(q, params)
        except Exception as e:
            messagebox.showerror('Query Error', str(e))
            return

        rows = cur.fetchall()
        for row in rows:
            vals = [row[c] if c in row.keys() else '' for c in self.tree['columns']]
            self.tree.insert('', 'end', values=vals)

        self.status.config(text=f'Showing {len(rows)} rows (limited to 1000)')

    def add_row(self):
        editor = RowEditor(self, self.cols)
        self.wait_window(editor)
        if getattr(editor, 'saved', False):
            data = editor.values
            # Build insert
            keys = [k for k in data.keys()]
            placeholders = ','.join('?' for _ in keys)
            q = f"INSERT INTO esd_data ({', '.join(keys)}) VALUES ({placeholders})"
            try:
                cur = self.conn.cursor()
                cur.execute(q, [data[k] for k in keys])
                self.conn.commit()
                self.refresh()
            except Exception as e:
                messagebox.showerror('Insert Error', str(e))

    def edit_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo('Edit', 'No row selected')
            return
        vals = self.tree.item(sel[0])['values']
        colnames = list(self.tree['columns'])
        current = dict(zip(colnames, vals))
        editor = RowEditor(self, self.cols, current)
        self.wait_window(editor)
        if getattr(editor, 'saved', False):
            data = editor.values
            # Determine primary key for update - prefer 'id' or 'rowid'
            pk = None
            for p in ('id', 'rowid'):
                if p in colnames:
                    pk = p
                    break
            if not pk:
                messagebox.showerror('Update Error', 'No primary key column found (id or rowid)')
                return
            if not current.get(pk):
                messagebox.showerror('Update Error', f'Selected row has no {pk} value')
                return
            set_clause = ', '.join(f"{k} = ?" for k in data.keys())
            q = f"UPDATE esd_data SET {set_clause} WHERE {pk} = ?"
            try:
                cur = self.conn.cursor()
                cur.execute(q, [data[k] for k in data.keys()] + [current[pk]])
                self.conn.commit()
                self.refresh()
            except Exception as e:
                messagebox.showerror('Update Error', str(e))

    def delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo('Delete', 'No row selected')
            return
        if not messagebox.askyesno('Delete', 'Delete selected rows?'):
            return
        colnames = list(self.tree['columns'])
        pk = None
        for p in ('id', 'rowid'):
            if p in colnames:
                pk = p
                break
        if not pk:
            messagebox.showerror('Delete Error', 'No primary key column found (id or rowid)')
            return
        cur = self.conn.cursor()
        try:
            for i in sel:
                vals = self.tree.item(i)['values']
                current = dict(zip(colnames, vals))
                cur.execute(f"DELETE FROM esd_data WHERE {pk} = ?", (current[pk],))
            self.conn.commit()
            self.refresh()
        except Exception as e:
            messagebox.showerror('Delete Error', str(e))


class RowEditor(tk.Toplevel):
    def __init__(self, parent, cols, data=None):
        super().__init__(parent)
        self.transient(parent)
        self.grab_set()
        self.title('Row Editor')
        self.geometry('480x380')
        self.cols = cols
        self.values = {}
        frm = ttk.Frame(self)
        frm.pack(fill='both', expand=True, padx=8, pady=8)

        # Build inputs for common columns
        common = ['timestamp', 'emp_name', 'wrist', 'shoe']
        self.inputs = {}
        row = 0
        for c in (common + [x for x in cols if x not in common]):
            ttk.Label(frm, text=c).grid(row=row, column=0, sticky='w', pady=4)
            e = ttk.Entry(frm, width=40)
            e.grid(row=row, column=1, sticky='w')
            val = ''
            if data and c in data:
                val = data[c]
            e.insert(0, '' if val is None else str(val))
            self.inputs[c] = e
            row += 1

        btnf = ttk.Frame(self)
        btnf.pack(fill='x', pady=8)
        ttk.Button(btnf, text='Save', command=self.save).pack(side='left', padx=6)
        ttk.Button(btnf, text='Cancel', command=self.cancel).pack(side='left')

    def save(self):
        for k, w in self.inputs.items():
            self.values[k] = w.get().strip() or None
        # ensure timestamp exists
        if 'timestamp' in self.values and not self.values['timestamp']:
            self.values['timestamp'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.saved = True
        self.destroy()

    def cancel(self):
        self.saved = False
        self.destroy()


def main():
    app = ESDEditor()
    app.mainloop()


if __name__ == '__main__':
    main()
