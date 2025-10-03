import tkinter as tk
from tkinter import ttk, messagebox
import time, random, os, csv
from datetime import datetime
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

LOGS_DIR = "logs"

class FlowMeterApp:
    def __init__(self, root):
        self.root = root# Remove title bar
        self.root.attributes("-fullscreen", True)    # Adjust for Raspberry Pi screen
        self.root.configure(bg="#f0f0f0")

        self.current_month = None
        self.job = None
        self.running = True

        # Layout
        self.root.columnconfigure(0, weight=1)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        # --- LEFT SIDE ---
        left_frame = ttk.Frame(root)
        left_frame.grid(row=0, column=0, padx=8, pady=8, sticky="nsew")

        # Live data
        frame_live = ttk.LabelFrame(left_frame, text=" Live Monitoring ")
        frame_live.pack(fill="x", padx=5, pady=5)

        self.flow_var = tk.StringVar(value="0.00")
        self.total_var = tk.StringVar(value="0.000")
        self.temp_var = tk.StringVar(value="25.0")
        self.batt_var = tk.StringVar(value="100% (Good)")

        ttk.Label(frame_live, text="Flow Rate (SLPM):", font=("Arial", 13)).grid(row=0, column=0, sticky="w", pady=2)
        ttk.Label(frame_live, textvariable=self.flow_var, font=("Arial", 16, "bold"), foreground="blue").grid(row=0, column=1, sticky="e", pady=2)
        ttk.Label(frame_live, text="Total Flow (NCM):", font=("Arial", 13)).grid(row=1, column=0, sticky="w", pady=2)
        ttk.Label(frame_live, textvariable=self.total_var, font=("Arial", 16, "bold"), foreground="green").grid(row=1, column=1, sticky="e", pady=2)
        ttk.Label(frame_live, text="Temperature (°C):", font=("Arial", 13)).grid(row=2, column=0, sticky="w", pady=2)
        ttk.Label(frame_live, textvariable=self.temp_var, font=("Arial", 16, "bold"), foreground="red").grid(row=2, column=1, sticky="e", pady=2)
        ttk.Label(frame_live, text="Battery:", font=("Arial", 13)).grid(row=3, column=0, sticky="w", pady=2)
        ttk.Label(frame_live, textvariable=self.batt_var, font=("Arial", 16, "bold"), foreground="purple").grid(row=3, column=1, sticky="e", pady=2)

        # Graph
        frame_graph = ttk.LabelFrame(left_frame, text=" Real-Time Flow Graph ")
        frame_graph.pack(fill="both", expand=True, padx=5, pady=5)
        self.fig, self.ax = plt.subplots(figsize=(4.5, 3.5))
        self.canvas = FigureCanvasTkAgg(self.fig, master=frame_graph)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # --- RIGHT SIDE ---
        frame_browser = ttk.LabelFrame(root, text=" Data Logs Browser ")
        frame_browser.grid(row=0, column=1, padx=8, pady=8, sticky="nsew")
        frame_browser.rowconfigure(2, weight=1)
        frame_browser.columnconfigure(0, weight=1)
        frame_browser.columnconfigure(1, weight=1)

        self.month_list = tk.Listbox(frame_browser, height=6)
        self.month_list.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        self.month_list.bind("<<ListboxSelect>>", self.load_days)

        self.day_list = tk.Listbox(frame_browser, height=6)
        self.day_list.grid(row=0, column=1, padx=5, pady=5, sticky="nsew")

        btn_frame = ttk.Frame(frame_browser)
        btn_frame.grid(row=1, column=0, columnspan=2, pady=5)
        ttk.Button(btn_frame, text="Load Day", command=self.show_day).grid(row=0, column=0, padx=5)
        ttk.Button(btn_frame, text="Load Month", command=self.show_month).grid(row=0, column=1, padx=5)
        ttk.Button(btn_frame, text="Exit", command=self.stop).grid(row=0, column=2, padx=5)

        self.tree = ttk.Treeview(frame_browser, columns=("Time", "Flow", "Total", "Temp", "Battery"), show="headings", height=15)
        for col in self.tree["columns"]:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=110, anchor="center")
        self.tree.grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky="nsew")
        scrollbar = ttk.Scrollbar(frame_browser, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.grid(row=2, column=2, sticky="ns")

        # State
        self.total_flow = 0.0
        self.battery = 100.0
        self.last_temp_update = time.time()
        self.temp = 25.0

        # Start
        self.update_data()
        self.load_months()
        self.update_live_graph()

    # ---------------------- Logging ----------------------
    def get_log_file(self):
        today = datetime.now().strftime("%Y-%m-%d")
        month_folder = datetime.now().strftime("%Y-%m")
        folder = os.path.join(LOGS_DIR, month_folder)
        os.makedirs(folder, exist_ok=True)
        file_path = os.path.join(folder, f"{today}.csv")
        if not os.path.exists(file_path):
            with open(file_path, "w", newline="") as f:
                csv.writer(f).writerow(["Timestamp", "Flow (SLPM)", "Total Flow (NCM)", "Temperature (°C)", "Battery"])
        return file_path

    def log_data(self, flow, total, temp, batt_text):
        with open(self.get_log_file(), "a", newline="") as f:
            csv.writer(f).writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), f"{flow:.2f}", f"{total:.3f}", f"{temp:.1f}", batt_text])

    # ---------------------- Live Data ----------------------
    def update_data(self):
        if not self.running: return
        flow = round(random.uniform(0.5, 20.0), 2)
        self.total_flow += flow * 0.001
        self.battery = max(0, self.battery - random.uniform(0.001, 0.003))
        batt_text = f"{self.battery:.0f}% (Good)" if self.battery > 50 else (f"{self.battery:.0f}% (Low)" if self.battery > 20 else f"{self.battery:.0f}% (Replace!)")
        if time.time() - self.last_temp_update > 5:
            self.temp = round(random.uniform(20, 30), 1)
            self.last_temp_update = time.time()

        self.flow_var.set(f"{flow:.2f}")
        self.total_var.set(f"{self.total_flow:.3f}")
        self.temp_var.set(f"{self.temp:.1f}")
        self.batt_var.set(batt_text)
        self.log_data(flow, self.total_flow, self.temp, batt_text)

        self.job = self.root.after(1000, self.update_data)

    # ---------------------- Graph Update ----------------------
    def update_live_graph(self):
        try:
            file_path = self.get_log_file()
            if not os.path.exists(file_path): return
            times, flows = [], []
            with open(file_path, "r") as f:
                reader = csv.reader(f)
                next(reader, None)
                for row in reader:
                    try:
                        t = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
                        times.append(t.replace(minute=0, second=0, microsecond=0))
                        flows.append(float(row[1]))
                    except: continue
            hourly = {}
            for t, f in zip(times, flows):
                hourly.setdefault(t, []).append(f)
            hourly_times = sorted(hourly.keys())
            hourly_avg = [sum(v)/len(v) for v in hourly.values()]

            self.ax.clear()
            if hourly_times:
                self.ax.plot(hourly_times, hourly_avg, marker="o", color="blue", linewidth=2)
                self.ax.set_title("Live Hourly Flow (Today)")
                self.ax.set_xlabel("Time")
                self.ax.set_ylabel("Avg Flow (SLPM)")
                self.ax.tick_params(axis="x", rotation=30, labelsize=8)
            else:
                self.ax.text(0.5, 0.5, "No data yet", ha="center", va="center")
            self.fig.tight_layout()
            self.canvas.draw()
        except Exception as e:
            print("Graph error:", e)
        self.root.after(60000, self.update_live_graph)
                
    # ---------------------- Logs Browser ----------------------
    def load_months(self, event=None):
        if not os.path.exists(LOGS_DIR): return
        self.month_list.delete(0, tk.END)
        for m in sorted(os.listdir(LOGS_DIR)):
            self.month_list.insert(tk.END, m)

    def load_days(self, event=None):
        sel = self.month_list.curselection()
        if not sel: return
        self.current_month = self.month_list.get(sel[0])
        folder = os.path.join(LOGS_DIR, self.current_month)
        self.day_list.delete(0, tk.END)
        for d in sorted(os.listdir(folder)):
            self.day_list.insert(tk.END, d)

    def show_day(self):
        if not self.current_month:
            messagebox.showinfo("Info", "Please select a month first.")
            return

        sel_day = self.day_list.curselection()
        if not sel_day:
            messagebox.showinfo("Info", "Please select a day from the list before loading.")
            return

        day = self.day_list.get(sel_day[0])
        file_path = os.path.join(LOGS_DIR, self.current_month, day)

        if not os.path.exists(file_path):
            messagebox.showerror("Error", f"Log file not found: {file_path}")
            return

        self.load_csv_day(file_path, f"Day {day}")


    def show_month(self):
        if not self.month_list.curselection():
            messagebox.showinfo("Info", "Please select a month.")
            return

        self.current_month = self.month_list.get(self.month_list.curselection()[0])
        folder = os.path.join(LOGS_DIR, self.current_month)
        if not os.path.exists(folder):
            messagebox.showerror("Error", f"No folder found: {folder}")
            return

        files = sorted([os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".csv")])
        if not files:
            messagebox.showinfo("Info", f"No CSV files found for {self.current_month}.")
            return

        # Summarize per day
        days, avg_flows, total_flows = [], [], []
        for file_path in files:
            flows, totals = [], []
            with open(file_path, "r") as f:
                reader = csv.reader(f)
                headers = next(reader, None)
                for row in reader:
                    if row:
                        flows.append(float(row[1]))
                        totals.append(float(row[2]))
            if flows and totals:
                day_str = os.path.basename(file_path).replace(".csv", "")
                day_dt = datetime.strptime(day_str, "%Y-%m-%d")
                days.append(day_dt)
                avg_flows.append(sum(flows) / len(flows))
                total_flows.append(max(totals))

        if not days:
            messagebox.showinfo("Info", "No valid data for this month.")
            return

        days, avg_flows, total_flows = zip(*sorted(zip(days, avg_flows, total_flows)))

        # Fill table
        for row in self.tree.get_children():
            self.tree.delete(row)
        for d, af, tf in zip(days, avg_flows, total_flows):
            self.tree.insert("", tk.END, values=(d.strftime("%Y-%m-%d"), f"{af:.2f}", f"{tf:.3f}", "-", "-"))

        # Graph
        self.ax.clear()
        self.ax.bar(days, total_flows, color="lightgreen", label="Total Flow (NCM)")
        self.ax.plot(days, avg_flows, color="blue", marker="o", label="Avg Flow (SLPM)", linewidth=2)
        self.ax.set_title(f"Monthly Summary - {self.current_month}")
        self.ax.set_xlabel("Day")
        self.ax.set_ylabel("Flow")
        self.ax.tick_params(axis="x", rotation=45, labelsize=8)
        self.ax.legend()
        self.fig.autofmt_xdate()
        self.fig.tight_layout()
        self.canvas.draw()


    def load_csv_day(self, file_path, label):
        for r in self.tree.get_children(): self.tree.delete(r)
        times, flows = [], []
        with open(file_path, "r") as f:
            reader = csv.reader(f); next(reader, None)
            for row in reader:
                self.tree.insert("", tk.END, values=row)
                try:
                    times.append(datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S"))
                    flows.append(float(row[1]))
                except: continue
        hourly = {}
        for t, f in zip(times, flows):
            hourly.setdefault(t.replace(minute=0, second=0, microsecond=0), []).append(f)
        ht, hf = zip(*sorted(hourly.items()))
        hf_avg = [sum(v)/len(v) for v in hf]

        self.ax.clear()
        self.ax.plot(ht, hf_avg, marker="o", color="blue")
        self.ax.set_title(label)
        self.ax.tick_params(axis="x", rotation=30, labelsize=8)
        self.fig.tight_layout()
        self.canvas.draw()

    # ---------------------- Stop ----------------------
    def stop(self):
        """Completely stop the app and exit."""
        self.running = False
        try:
            if self.job:
                self.root.after_cancel(self.job)
                self.job = None
        except Exception:
            pass

        try:
            self.root.quit()       
            self.root.destroy()    
            os._exit(0)            
        except Exception:
            os._exit(0)


# --- RUN ---
if __name__ == "__main__":
    root = tk.Tk()
    app = FlowMeterApp(root)
    root.mainloop()
