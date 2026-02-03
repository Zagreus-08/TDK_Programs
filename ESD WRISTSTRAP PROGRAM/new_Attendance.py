import sqlite3
import win32com.client
import datetime
import psutil
import time
import json
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import io
import tempfile
import os
import traceback

# --- Constants ---
DB_PATH = r"\\phlsvr08\BMS Data\BMS_Database\ESD_Checker\ESDChecker.db"
EMPLOYEES_JSON_PATH = r"\\phlsvr08\BMS Data\BMS_Database\ESD_Checker\employees.json"

EMAIL_RECIPIENTS_JSON = r"C:\Users\a493353\Desktop\Lans Galos\Raspberry Pi Program\ESD WRISTSTRAP PROGRAM\email_recipients.json"

# Debug: when True, saves generated PNG to this path for manual inspection
DEBUG_SAVE_PNG = False
DEBUG_SAVE_PATH = r"C:\Temp\esd_chart_debug.png"

recipient_emails = []
cc_emails = []
bcc_emails = []
admin_email = ''

# --------------------------------------------------
# Email Recipients Loader
# --------------------------------------------------
def load_email_recipients():
    global recipient_emails, cc_emails, bcc_emails, admin_email
    try:
        with open(EMAIL_RECIPIENTS_JSON, 'r') as f:
            email_data = json.load(f)

        recipient_emails = email_data.get('recipient_emails', [])
        cc_emails = email_data.get('cc_emails', [])
        bcc_emails = email_data.get('bcc_emails', [])
        admin_email = '; '.join(email_data.get('admin_emails', []))

        print("Email recipients loaded successfully.")
    except Exception as e:
        print(f"Failed to load email recipients: {e}")
        sys.exit()

# --------------------------------------------------
# Outlook Detection (Classic + New Outlook)
# --------------------------------------------------
def is_outlook_running():
    """
    Detects if the New Outlook app (olk.exe) is currently open.
    """
    for proc in psutil.process_iter(['name']):
        try:
            # 'olk.exe' is the process name for New Outlook
            if proc.info['name'] and proc.info['name'].lower() == "olk.exe":
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False

# --------------------------------------------------
# Email Functions & ESD Chart Utilities
# --------------------------------------------------
def send_error_email(error_message, context=''):
    if not admin_email:
        return
    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)
        mail.Subject = f'[ERROR] Attendance Script Failed - {datetime.datetime.now():%B %d, %Y}'
        mail.HTMLBody = f"""
        <html><body style="font-family:Tahoma;">
        <p><b>Context:</b> {context}</p>
        <pre>{error_message}</pre>
        </body></html>
        """
        mail.To = admin_email
        mail.Importance = 2
        mail.Send()
    except Exception as e:
        print(f"Failed to send error email: {e}")


def _get_esd_data(days=31):
    """Fetches ESD wrist and footwear readings for the last `days` days from DB.
    Returns (dates, wrist_by_emp, shoe_by_emp, skipped_count) or None on failure.
    """
    try:
        def _safe_float(x):
            if x is None:
                return None
            if isinstance(x, (int, float)):
                return float(x)
            s = str(x).strip()
            if not s:
                return None
            if s.lower() in ('n/a', 'na', 'none', '-', 'nan', 'inf'):
                return None
            try:
                return float(s)
            except Exception:
                return None

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(esd_data)")
        cols = [r[1] for r in cursor.fetchall()]

        timestamp_col = 'timestamp' if 'timestamp' in cols else next((c for c in cols if 'time' in c.lower()), None)
        name_col = 'emp_name' if 'emp_name' in cols else next((c for c in cols if 'name' in c.lower()), None)

        wrist_col = next((c for c in cols if 'wrist' in c.lower()), None)
        shoe_col = next((c for c in cols if 'shoe' in c.lower() or 'footwear' in c.lower()), None)

        start_date = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime('%Y-%m-%d')

        dates_set = set()
        wrist = {}
        shoe = {}
        skipped = 0

        if wrist_col and shoe_col and timestamp_col and name_col:
            cursor.execute(f"SELECT DATE({timestamp_col}) as dt, {name_col}, {wrist_col}, {shoe_col} FROM esd_data WHERE DATE({timestamp_col}) >= ?", (start_date,))
            rows = cursor.fetchall()
            for dt, name, wv, sv in rows:
                dates_set.add(dt)
                fv = _safe_float(wv)
                if fv is not None:
                    wrist.setdefault((name, dt), []).append(fv)
                else:
                    if wv is not None:
                        skipped += 1
                fv2 = _safe_float(sv)
                if fv2 is not None:
                    shoe.setdefault((name, dt), []).append(fv2)
                else:
                    if sv is not None:
                        skipped += 1
        else:
            # Try alternative format: test_type / value
            val_col = next((c for c in cols if c.lower() in ('value', 'reading', 'resistance') or 'value' in c.lower()), None)
            type_col = next((c for c in cols if 'test' in c.lower() or 'type' in c.lower() or 'measurement' in c.lower()), None)
            if val_col and type_col and timestamp_col and name_col:
                cursor.execute(f"SELECT DATE({timestamp_col}) as dt, {name_col}, {type_col}, {val_col} FROM esd_data WHERE DATE({timestamp_col}) >= ?", (start_date,))
                rows = cursor.fetchall()
                for dt, name, ttype, val in rows:
                    dates_set.add(dt)
                    fval = _safe_float(val)
                    if fval is None:
                        if val is not None:
                            skipped += 1
                        continue
                    if ttype and 'wrist' in str(ttype).lower():
                        wrist.setdefault((name, dt), []).append(fval)
                    elif ttype and ('shoe' in str(ttype).lower() or 'footwear' in str(ttype).lower() or 'shoe' in str(ttype).lower()):
                        shoe.setdefault((name, dt), []).append(fval)
            else:
                conn.close()
                return None

        # Average grouped readings and build per-employee dicts
        wrist_by_emp = {}
        shoe_by_emp = {}

        for (name, dt), vals in wrist.items():
            wrist_by_emp.setdefault(name, {})[dt] = sum(vals) / len(vals)
        for (name, dt), vals in shoe.items():
            shoe_by_emp.setdefault(name, {})[dt] = sum(vals) / len(vals)

        dates = sorted(dates_set)
        conn.close()
        return dates, wrist_by_emp, shoe_by_emp, skipped
    except Exception:
        send_error_email(traceback.format_exc(), "Getting ESD data")
        return None


def _create_esd_plot_image(dates, wrist_by_emp, shoe_by_emp):
    """Creates a PNG image (bytes) of two rows of small multiple charts (4 columns each)
    to match the reference style: each row is split into 4 week-like clusters with a combined legend.
    """
    try:
        if not dates:
            return None

        import matplotlib.dates as mdates

        # Convert date strings to datetime objects
        try:
            date_objs = [datetime.datetime.strptime(d, '%Y-%m-%d') for d in dates]
        except Exception:
            date_objs = dates

        # Determine number of columns (four clusters) and split dates
        cols = 4
        n = len(date_objs)
        # Split indices into roughly equal chunks
        chunk_sizes = [(n // cols) + (1 if i < (n % cols) else 0) for i in range(cols)]
        indices = []
        start = 0
        for sz in chunk_sizes:
            indices.append((start, start + sz))
            start += sz

        fig, axs = plt.subplots(2, cols, figsize=(14, 9), sharey='row')
        # leave default figure facecolor

        BASELINE = 1.0
        UCL_WRIST = 5
        UCL_SHOE = 10

        # Find y-limits across all wrist and shoe values to keep consistent scaling per row
        all_wrist_vals = [v for s in wrist_by_emp.values() for v in s.values()]
        all_shoe_vals = [v for s in shoe_by_emp.values() for v in s.values()]
        def compute_ylim(vals, ucl):
            try:
                if vals:
                    ymax = max(max(vals), ucl) * 1.08
                    return (0, ymax)
            except Exception:
                pass
            return (0, ucl * 1.2)

        wrist_ylim = compute_ylim(all_wrist_vals, UCL_WRIST)
        shoe_ylim = compute_ylim(all_shoe_vals, UCL_SHOE)

        # Plot wrist row (row 0)
        wrist_handles = {}
        for col_idx, (sidx, eidx) in enumerate(indices):
            ax = axs[0, col_idx]
            seg_dates = date_objs[sidx:eidx]
            seg_labels = dates[sidx:eidx]
            for name, series in sorted(wrist_by_emp.items()):
                y_seg = [series.get(d, float('nan')) for d in seg_labels]
                # Draw faint baseline where missing
                isnan = [not (v == v) for v in y_seg]
                startm = None
                for i, miss in enumerate(isnan):
                    if miss and startm is None:
                        startm = i
                    if not miss and startm is not None:
                        ax.plot(seg_dates[startm:i], [BASELINE] * (i - startm), color='#e0e0e0', linewidth=0.6, zorder=0)
                        startm = None
                if startm is not None:
                    ax.plot(seg_dates[startm:len(seg_dates)], [BASELINE] * (len(seg_dates) - startm), color='#e0e0e0', linewidth=0.6, zorder=0)

                # plot actual data with NaNs preserved so lines break
                line, = ax.plot(seg_dates, y_seg, marker='o', markersize=3, linewidth=0.8, zorder=5) if any(not (v != v) for v in y_seg) else (None,)
                if line is not None:
                    wrist_handles.setdefault(name, line)

            # UCL and formatting
            ax.axhline(UCL_WRIST, color='red', linewidth=2.0, zorder=11)
            ax.set_ylim(wrist_ylim)
            ax.grid(True, linestyle='--', alpha=0.4)
            ax.set_axisbelow(True)
            ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, max(1, (eidx - sidx) // 3))))
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d-%b'))
            for lbl in ax.get_xticklabels():
                lbl.set_rotation(45); lbl.set_ha('right')
            if col_idx != 0:
                ax.set_ylabel('')
            else:
                ax.set_ylabel('Ohms')

        axs[0, 0].set_title('ESD WRIST STRAP MONITORING', fontweight='bold')

        # Plot shoe row (row 1)
        shoe_handles = {}
        for col_idx, (sidx, eidx) in enumerate(indices):
            ax = axs[1, col_idx]
            seg_dates = date_objs[sidx:eidx]
            seg_labels = dates[sidx:eidx]
            for name, series in sorted(shoe_by_emp.items()):
                y_seg = [series.get(d, float('nan')) for d in seg_labels]
                # baseline
                isnan = [not (v == v) for v in y_seg]
                startm = None
                for i, miss in enumerate(isnan):
                    if miss and startm is None:
                        startm = i
                    if not miss and startm is not None:
                        ax.plot(seg_dates[startm:i], [BASELINE] * (i - startm), color='#e0e0e0', linewidth=0.6, zorder=0)
                        startm = None
                if startm is not None:
                    ax.plot(seg_dates[startm:len(seg_dates)], [BASELINE] * (len(seg_dates) - startm), color='#e0e0e0', linewidth=0.6, zorder=0)

                line, = ax.plot(seg_dates, y_seg, marker='o', markersize=3, linewidth=0.8, zorder=5) if any(not (v != v) for v in y_seg) else (None,)
                if line is not None:
                    shoe_handles.setdefault(name, line)

            ax.axhline(UCL_SHOE, color='red', linewidth=2.0, zorder=11)
            ax.set_ylim(shoe_ylim)
            ax.grid(True, linestyle='--', alpha=0.4)
            ax.set_axisbelow(True)
            ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, max(1, (eidx - sidx) // 3))))
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d-%b'))
            for lbl in ax.get_xticklabels():
                lbl.set_rotation(45); lbl.set_ha('right')

        axs[1, 0].set_title('ESD FOOTWEAR MONITORING', fontweight='bold')

        # Build legend from handles
        combined_handles = []
        combined_labels = []
        added = set()
        for d in (wrist_handles, shoe_handles):
            for n, h in d.items():
                if h is not None and n not in added:
                    combined_handles.append(h)
                    combined_labels.append(n)
                    added.add(n)
        # Add UCL legend entry (create a proxy Line2D)
        import matplotlib.lines as mlines
        ucl_line = mlines.Line2D([], [], color='red', linewidth=2)
        combined_handles.append(ucl_line)
        combined_labels.append('UCL')

        if combined_handles:
            fig.legend(combined_handles, combined_labels, loc='lower center', ncol=6, fontsize='small', frameon=False)
            plt.subplots_adjust(bottom=0.2, hspace=0.6)
        else:
            plt.subplots_adjust(bottom=0.12, hspace=0.6)

        buf = io.BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight', dpi=140)
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception:
        send_error_email(traceback.format_exc(), "Creating ESD plot")
        return None


def _create_esd_plot_images(dates, wrist_by_emp, shoe_by_emp):
    """Return (wrist_png_bytes, shoe_png_bytes) as two separate single-row images."""
    try:
        BASELINE = 1.0
        import matplotlib.dates as mdates
        import numpy as np

        # normalize dates from data
        try:
            date_objs = [datetime.datetime.strptime(d, '%Y-%m-%d') for d in dates]
        except Exception:
            date_objs = dates
        
        if len(date_objs) == 0:
            return None, None

        # Get the last date and create a full calendar month (last 31 days)
        end_date = max(date_objs)
        start_date = end_date - datetime.timedelta(days=30)  # 31 days total including end_date
        
        # Create ALL calendar dates for the month (including weekends/no-data days)
        all_calendar_dates = []
        current = start_date
        while current <= end_date:
            all_calendar_dates.append(current)
            current += datetime.timedelta(days=1)
        
        # Group calendar dates by week (Monday-Sunday)
        weeks = {}
        for dt in all_calendar_dates:
            year, week_num, weekday = dt.isocalendar()
            week_key = (year, week_num)
            if week_key not in weeks:
                weeks[week_key] = []
            weeks[week_key].append(dt)
        
        sorted_weeks = sorted(weeks.keys())
        week_groups = [weeks[wk] for wk in sorted_weeks]
        
        if len(week_groups) == 0:
            return None, None

        def make_row_image(data_by_emp, title, ucl, base_ylim):
            # Create figure with more height for legend spacing
            fig, ax = plt.subplots(1, 1, figsize=(18, 4.8))
            fig.patch.set_facecolor('white')
            ax.set_facecolor('white')
            
            handles = {}
            
            # Create a large color palette for unique colors per employee
            import matplotlib.cm as cm
            num_employees = len(data_by_emp)
            # Use tab20 + tab20b + tab20c for up to 60 distinct colors
            if num_employees <= 20:
                colors = plt.cm.tab20(np.linspace(0, 1, 20))
            elif num_employees <= 40:
                colors1 = plt.cm.tab20(np.linspace(0, 1, 20))
                colors2 = plt.cm.tab20b(np.linspace(0, 1, 20))
                colors = np.vstack([colors1, colors2])
            else:
                colors1 = plt.cm.tab20(np.linspace(0, 1, 20))
                colors2 = plt.cm.tab20b(np.linspace(0, 1, 20))
                colors3 = plt.cm.tab20c(np.linspace(0, 1, 20))
                colors = np.vstack([colors1, colors2, colors3])
            
            # Assign colors to employees
            employee_colors = {}
            for idx, name in enumerate(sorted(data_by_emp.keys())):
                employee_colors[name] = colors[idx % len(colors)]
            
            # Create x-positions for ALL calendar dates (no gaps between weeks)
            x_positions = []
            x_labels = []
            x_dates_map = {}  # map date object to x position
            current_x = 0
            week_boundaries = []
            
            for week_idx, week_dates in enumerate(week_groups):
                if week_idx > 0:
                    # Mark boundary but don't add gap
                    week_boundaries.append(current_x - 0.5)
                
                for dt in week_dates:
                    x_dates_map[dt] = current_x
                    x_positions.append(current_x)
                    x_labels.append(dt.strftime('%d-%b-%y'))
                    current_x += 1
            
            # Plot baseline (very light gray)
            ax.axhline(BASELINE, color='#f0f0f0', linewidth=1.0, zorder=0)
            
            # Plot each employee's data - separate lines per week
            for name, series in sorted(data_by_emp.items()):
                emp_color = employee_colors[name]
                # Plot each week separately to avoid connecting across gaps
                for week_dates in week_groups:
                    week_x = []
                    week_y = []
                    for dt in week_dates:
                        date_str = dt.strftime('%Y-%m-%d')
                        val = series.get(date_str, None)
                        if val is not None:
                            week_x.append(x_dates_map[dt])
                            week_y.append(val)
                        else:
                            # Include None/NaN for missing data to create gaps in lines
                            week_x.append(x_dates_map[dt])
                            week_y.append(np.nan)
                    
                    # Plot this week's data (NaN will create gaps) with assigned color
                    if len(week_x) > 0:
                        line, = ax.plot(week_x, week_y, marker='o', markersize=3.5, 
                                       linewidth=1.0, alpha=0.9, zorder=5, color=emp_color)
                        # Only store handle once per employee
                        if name not in handles:
                            handles[name] = line
            
            # Draw vertical separators between weeks (subtle)
            for boundary_x in week_boundaries:
                ax.axvline(boundary_x, color='#d0d0d0', linewidth=1.0, 
                          linestyle='--', alpha=0.6, zorder=1)
            
            # Configure axes
            ax.set_ylim(base_ylim)
            ax.yaxis.grid(True, linestyle='--', alpha=0.4, linewidth=0.5)
            ax.xaxis.grid(False)
            ax.set_axisbelow(True)
            
            # Set x-axis with proper limits
            ax.set_xlim(-0.8, max(x_positions) + 0.8)
            ax.set_xticks(x_positions)
            ax.set_xticklabels(x_labels, rotation=45, ha='right', fontsize=8)
            
            # Style spines
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.spines['bottom'].set_linewidth(0.8)
            ax.spines['left'].set_linewidth(0.8)
            
            # Draw UCL line across entire plot (thick red line)
            ax.axhline(ucl, color='red', linewidth=2.8, zorder=10, alpha=0.95)
            
            # Title at top
            ax.set_title(title, fontweight='bold', fontsize=13, pad=15)
            
            # Adjust layout to give more space for legend below
            plt.subplots_adjust(top=0.92, bottom=0.38, left=0.06, right=0.98)
            
            # Build legend with proper spacing
            import matplotlib.lines as mlines
            combined_handles = []
            combined_labels = []
            
            # Sort employees alphabetically for consistent legend
            for n in sorted(handles.keys()):
                combined_handles.append(handles[n])
                combined_labels.append(n)
            
            # Add UCL to legend
            ucl_line = mlines.Line2D([], [], color='red', linewidth=2.5)
            combined_handles.append(ucl_line)
            combined_labels.append('UCL')
            
            # Place legend below with more spacing
            if combined_handles:
                legend = fig.legend(combined_handles, combined_labels, 
                          loc='lower center', 
                          bbox_to_anchor=(0.5, -0.02),
                          ncol=7, 
                          fontsize=8,
                          frameon=False,
                          columnspacing=1.5,
                          handletextpad=0.5)
            
            # Save with high DPI for quality
            buf = io.BytesIO()
            fig.savefig(buf, format='png', bbox_inches='tight', dpi=200, facecolor='white')
            plt.close(fig)
            buf.seek(0)
            return buf.read()

        # Compute y-limits
        all_wrist_vals = [v for s in wrist_by_emp.values() for v in s.values()]
        all_shoe_vals = [v for s in shoe_by_emp.values() for v in s.values()]
        
        def compute_ylim(vals, ucl):
            try:
                if vals:
                    ymax = max(max(vals), ucl) * 1.1
                    return (0, ymax)
            except Exception:
                pass
            return (0, ucl * 1.2)

        wrist_img = make_row_image(wrist_by_emp, 'ESD WRIST STRAP MONITORING', 5, compute_ylim(all_wrist_vals, 5))
        shoe_img = make_row_image(shoe_by_emp, 'ESD FOOTWEAR MONITORING', 10, compute_ylim(all_shoe_vals, 10))
        
        # Debug save
        try:
            if globals().get('DEBUG_SAVE_PNG'):
                base = globals().get('DEBUG_SAVE_PATH', r"C:\Temp\esd_chart_debug.png")
                try:
                    with open(base.replace('.png', '_wrist.png'), 'wb') as f:
                        if wrist_img:
                            f.write(wrist_img)
                except Exception:
                    pass
                try:
                    with open(base.replace('.png', '_shoe.png'), 'wb') as f:
                        if shoe_img:
                            f.write(shoe_img)
                except Exception:
                    pass
        except Exception:
            pass
        return wrist_img, shoe_img
    except Exception:
        send_error_email(traceback.format_exc(), 'Creating ESD plot images')
        return None, None


def _attach_inline_image(mail, img_bytes, cid_name):
    """Attach PNG bytes to mail and set attachment MAPI properties so it can be displayed inline via cid:cid_name."""
    try:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
        tmp.write(img_bytes)
        tmp.close()
        # Attach by value and give a filename
        attachment = mail.Attachments.Add(tmp.name, 1, 0, os.path.basename(tmp.name))
        pa = attachment.PropertyAccessor
        try:
            # PR_ATTACH_CONTENT_ID
            pa.SetProperty("http://schemas.microsoft.com/mapi/proptag/0x3712001F", cid_name)
            # PR_ATTACH_CONTENT_LOCATION - sometimes helpful for inline images
            pa.SetProperty("http://schemas.microsoft.com/mapi/proptag/0x3713001F", f"cid:{cid_name}")
            # PR_ATTACH_MIME_TAG
            pa.SetProperty("http://schemas.microsoft.com/mapi/proptag/0x370E001F", "image/png")
        except Exception:
            send_error_email(traceback.format_exc(), "Setting attachment properties")
        # Save the mail item so Outlook persists the properties
        try:
            mail.Save()
        except Exception:
            pass
        return tmp.name
        return tmp.name
    except Exception:
        send_error_email(traceback.format_exc(), "Attaching inline image")
        return None


def send_absentee_email(absentees):
    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)
    display_date = datetime.datetime.now().strftime("%B %d, %Y")

    # Build the text part of the email
    body_text = f"""
    <p>The following personnel <b>did not enter the Production Area / perform ESD Wrist and Shoe Testing</b> on {display_date}:</p>
    <ul>
    {''.join(f'<li>{name}</li>' for name in absentees)}
    </ul>
    """

    # Try to fetch data and create charts (wrist and shoe separate)
    chart_html = ""
    tmp_files = []
    esd = _get_esd_data(days=31)
    if esd:
        dates, wrist_by_emp, shoe_by_emp, skipped = esd
        wrist_img, shoe_img = _create_esd_plot_images(dates, wrist_by_emp, shoe_by_emp)
        if wrist_img:
            tmp = _attach_inline_image(mail, wrist_img, 'esd_wrist')
            if tmp:
                tmp_files.append(tmp)
                chart_html += '<p><b>ESD Wrist Monitoring (last 31 days):</b></p>\n<img src="cid:esd_wrist" style="max-width:100%;height:auto;" />'
        if shoe_img:
            tmp2 = _attach_inline_image(mail, shoe_img, 'esd_shoe')
            if tmp2:
                tmp_files.append(tmp2)
                chart_html += '<p><b>ESD Footwear Monitoring (last 31 days):</b></p>\n<img src="cid:esd_shoe" style="max-width:100%;height:auto;" />'
        if skipped:
            chart_html += f"\n<p style='font-size:smaller;color:#666;'><em>Note: {skipped} non-numeric readings were skipped when plotting.</em></p>"
    html = f"""
    <html><body style="font-family:Tahoma;">{body_text}{chart_html}</body></html>
    """

    mail.Subject = f'Attendance Alert: No ESD Test on {display_date}'
    mail.HTMLBody = html
    mail.To = '; '.join(recipient_emails)
    if cc_emails:
        mail.CC = '; '.join(cc_emails)
    if bcc_emails:
        mail.BCC = '; '.join(bcc_emails)
    mail.Importance = 2
    mail.Send()

    # Cleanup temp files
    for f in tmp_files:
        try:
            os.unlink(f)
        except Exception:
            pass


def send_no_absentee_email():
    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)
    display_date = datetime.datetime.now().strftime("%B %d, %Y")

    text = f"<p>All personnel entered the Production Area and performed ESD Wrist and Shoe Testing on {display_date}.</p>"

    chart_html = ""
    tmp_files = []
    esd = _get_esd_data(days=31)
    if esd:
        dates, wrist_by_emp, shoe_by_emp, skipped = esd
        wrist_img, shoe_img = _create_esd_plot_images(dates, wrist_by_emp, shoe_by_emp)
        if wrist_img:
            tmp = _attach_inline_image(mail, wrist_img, 'esd_wrist')
            if tmp:
                tmp_files.append(tmp)
                chart_html += '<p><b>ESD Wrist Monitoring (last 31 days):</b></p>\n<img src="cid:esd_wrist" style="max-width:100%;height:auto;" />'
        if shoe_img:
            tmp2 = _attach_inline_image(mail, shoe_img, 'esd_shoe')
            if tmp2:
                tmp_files.append(tmp2)
                chart_html += '<p><b>ESD Footwear Monitoring (last 31 days):</b></p>\n<img src="cid:esd_shoe" style="max-width:100%;height:auto;" />'
        if skipped:
            chart_html += f"\n<p style='font-size:smaller;color:#666;'><em>Note: {skipped} non-numeric readings were skipped when plotting.</em></p>"
    mail.Subject = f'Attendance Notice: All Present on {display_date}'
    mail.HTMLBody = f"<html><body style='font-family:Tahoma;'>{text}{chart_html}</body></html>"
    mail.To = '; '.join(recipient_emails)
    if cc_emails:
        mail.CC = '; '.join(cc_emails)
    if bcc_emails:
        mail.BCC = '; '.join(bcc_emails)
    mail.Importance = 2
    mail.Send()

    # Cleanup temp files
    for f in tmp_files:
        try:
            os.unlink(f)
        except Exception:
            pass

# --------------------------------------------------
# Attendance Logic
# --------------------------------------------------
def load_employee_names(json_path):
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
        return list(data.values()) if isinstance(data, dict) else []
    except Exception as e:
        send_error_email(e, "Loading employee names")
        return []

def check_attendance_and_send_alert():
    names_to_check = load_employee_names(EMPLOYEES_JSON_PATH)
    if not names_to_check:
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        today = datetime.datetime.now().strftime("%Y-%m-%d")

        cursor.execute(
            "SELECT DISTINCT emp_name FROM esd_data WHERE DATE(timestamp) = ?",
            (today,)
        )

        present = {row[0] for row in cursor.fetchall()}
        absentees = [name for name in names_to_check if name not in present]

        if absentees:
            send_absentee_email(absentees)
        else:
            send_no_absentee_email()

        conn.close()
    except Exception as e:
        send_error_email(e, "Checking attendance DB")

# --------------------------------------------------
# Main Loop
# --------------------------------------------------
if __name__ == "__main__":
    load_email_recipients()
    print("Waiting for Outlook (Classic or New) to start...")

    while True:
        if is_outlook_running():
            print("Outlook detected. Running attendance check.")
            check_attendance_and_send_alert()
            break
        time.sleep(5)
