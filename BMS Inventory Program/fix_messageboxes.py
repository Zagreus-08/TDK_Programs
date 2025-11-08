"""
Script to replace all messagebox calls with our new helper functions that stay on top.
"""

import re

def fix_messageboxes(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Track changes
    changes = 0
    
    # Replace messagebox.showerror with show_error
    # Pattern: messagebox.showerror("title", "message")
    # Replace with: show_error("title", "message", self.root) or show_error("title", "message", win)
    
    # For methods in InventoryApp class (has self.root)
    pattern1 = r'messagebox\.showerror\('
    if 'def ' in content and 'self' in content:
        # In class methods, add self.root as parent
        new_content = re.sub(
            r'(\s+)messagebox\.showerror\(([^)]+)\)(?!\s*,\s*parent=)',
            r'\1show_error(\2, self.root)',
            content
        )
        changes += len(re.findall(pattern1, content)) - len(re.findall(pattern1, new_content))
        content = new_content
    
    # Replace messagebox.showwarning
    new_content = re.sub(
        r'(\s+)messagebox\.showwarning\(([^)]+)\)(?!\s*,\s*parent=)',
        r'\1show_warning(\2, self.root)',
        content
    )
    changes += len(re.findall(r'messagebox\.showwarning\(', content)) - len(re.findall(r'messagebox\.showwarning\(', new_content))
    content = new_content
    
    # Replace messagebox.showinfo
    new_content = re.sub(
        r'(\s+)messagebox\.showinfo\(([^)]+)\)(?!\s*,\s*parent=)',
        r'\1show_info(\2, self.root)',
        content
    )
    changes += len(re.findall(r'messagebox\.showinfo\(', content)) - len(re.findall(r'messagebox\.showinfo\(', new_content))
    content = new_content
    
    # Replace messagebox.askyesno
    new_content = re.sub(
        r'(\s+)messagebox\.askyesno\(([^)]+)\)(?!\s*,\s*parent=)',
        r'\1ask_yesno(\2, self.root)',
        content
    )
    changes += len(re.findall(r'messagebox\.askyesno\(', content)) - len(re.findall(r'messagebox\.askyesno\(', new_content))
    content = new_content
    
    # Replace simpledialog.askstring
    new_content = re.sub(
        r'(\s+)simpledialog\.askstring\(([^)]+)\)(?!\s*,\s*parent=)',
        r'\1ask_string(\2, parent=self.root)',
        content
    )
    content = new_content
    
    # Fix cases where parent is already specified
    content = re.sub(r'messagebox\.showerror\(([^,]+),\s*([^,]+),\s*parent=([^)]+)\)', r'show_error(\1, \2, \3)', content)
    content = re.sub(r'messagebox\.showwarning\(([^,]+),\s*([^,]+),\s*parent=([^)]+)\)', r'show_warning(\1, \2, \3)', content)
    content = re.sub(r'messagebox\.showinfo\(([^,]+),\s*([^,]+),\s*parent=([^)]+)\)', r'show_info(\1, \2, \3)', content)
    content = re.sub(r'messagebox\.askyesno\(([^,]+),\s*([^,]+),\s*parent=([^)]+)\)', r'ask_yesno(\1, \2, \3)', content)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"Fixed {changes} messagebox calls")
    return changes

if __name__ == "__main__":
    fix_messageboxes("testcopy.py")
    print("Done! Please review the changes.")
