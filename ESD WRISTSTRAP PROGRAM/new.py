import psutil
 
def check_outlook_running():
    classic_outlook = False
    new_outlook = False
    detected_processes = []
 
    for proc in psutil.process_iter(['name', 'cmdline']):
        try:
            name = proc.info['name']
            cmdline = " ".join(proc.info['cmdline'] or [])
 
            # Classic Outlook
            if name and name.lower() == "outlook.exe":
                classic_outlook = True
                detected_processes.append("Classic Outlook (OUTLOOK.EXE)")
 
            # New Outlook indicators
            if name and name.lower() in ("olk.exe", "msedgewebview2.exe"):
                if "outlook" in cmdline.lower():
                    new_outlook = True
                    detected_processes.append(f"New Outlook ({name})")
 
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
 
    return classic_outlook, new_outlook, detected_processes
 
 
if __name__ == "__main__":
    classic, new, details = check_outlook_running()
 
    if classic or new:
        print("✅ Outlook is running")
        for d in set(details):
            print(" -", d)
    else:
        print("❌ Outlook is NOT running")