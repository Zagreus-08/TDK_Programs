#!/usr/bin/env python3
"""
Apply dialog fixes to make all messageboxes stay on top.
This script replaces messagebox calls with our custom helper functions.
"""

import re

def apply_fixes():
    import os
    script_dir = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(script_dir, 'testcopy.py')
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    
    # Replace patterns - handle both with and without parent parameter
    replacements = [
        # Already has parent parameter - just change function name
        (r'messagebox\.showerror\(([^,]+),\s*([^,]+),\s*parent=([^)]+)\)', r'show_error(\1, \2, \3)'),
        (r'messagebox\.showwarning\(([^,]+),\s*([^,]+),\s*parent=([^)]+)\)', r'show_warning(\1, \2, \3)'),
        (r'messagebox\.showinfo\(([^,]+),\s*([^,]+),\s*parent=([^)]+)\)', r'show_info(\1, \2, \3)'),
        (r'messagebox\.askyesno\(([^,]+),\s*([^,]+),\s*parent=([^)]+)\)', r'ask_yesno(\1, \2, \3)'),
        
        # No parent parameter - add self.root (for class methods)
        (r'messagebox\.showerror\(([^,]+),\s*f?"[^"]*"[^)]*\)(?!\s*,\s*parent)', r'show_error(\1, self.root)'),
        (r'messagebox\.showwarning\(([^,]+),\s*f?"[^"]*"[^)]*\)(?!\s*,\s*parent)', r'show_warning(\1, self.root)'),
        (r'messagebox\.showinfo\(([^,]+),\s*f?"[^"]*"[^)]*\)(?!\s*,\s*parent)', r'show_info(\1, self.root)'),
        (r'messagebox\.askyesno\(([^,]+),\s*f?"[^"]*"[^)]*\)(?!\s*,\s*parent)', r'ask_yesno(\1, self.root)'),
        
        # simpledialog.askstring
        (r'simpledialog\.askstring\(([^,]+),\s*([^,]+),\s*show=([^)]+)\)', r'ask_string(\1, \2, parent=self.root, show=\3)'),
        (r'simpledialog\.askstring\(([^,]+),\s*([^,]+)\)(?!\s*,\s*parent)', r'ask_string(\1, \2, parent=self.root)'),
    ]
    
    for pattern, replacement in replacements:
        content = re.sub(pattern, replacement, content)
    
    # Count changes
    changes = len(re.findall(r'messagebox\.(showerror|showwarning|showinfo|askyesno)', original_content))
    remaining = len(re.findall(r'messagebox\.(showerror|showwarning|showinfo|askyesno)', content))
    
    print(f"Original messagebox calls: {changes}")
    print(f"Remaining messagebox calls: {remaining}")
    print(f"Converted: {changes - remaining}")
    
    # Write back
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("\nDone! File updated.")

if __name__ == "__main__":
    apply_fixes()
