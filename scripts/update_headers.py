#!/usr/bin/env python3
"""
Batch update source file headers to dual-license notice
"""
import os
import re
from datetime import datetime

HEADER_TEMPLATE = """
Copyright (C) {year} Rubén Gómez - khromalabs.org

This file is part of the Orakle/Polaris project.

This file is dual-licensed under:
1. GNU Lesser General Public License v3.0 only (LGPL-3.0-only)
   (See <https://www.gnu.org/licenses/lgpl-3.0.html> for details)
2. Commercial license 
   (Contact: rgomez@khromalabs.org for licensing options)

You may use, distribute and modify this code under the terms of either license.
This notice must be preserved in all copies or substantial portions of the code.
"""

EXTENSIONS = {
    '.py': '# {header}',
    '.js': '// {header}',
    '.ts': '// {header}',
    '.rs': '// {header}',
    '.go': '// {header}',
    '.sh': '# {header}',
    '.md': '<!-- {header} -->',
    '.c': '/* {header} */',
    '.cpp': '/* {header} */',
    '.h': '/* {header} */',
    '.hpp': '/* {header} */',
    '.css': '/* {header} */',
}

# Directories to skip
SKIP_DIRS = ['.git', 'node_modules', 'venv', '__pycache__', 'dist', 'build']

# Maximum file size to process (in bytes) - skip files larger than 1MB
MAX_FILE_SIZE = 1024 * 1024

def update_file(filepath):
    """Update the license header in a file."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext not in EXTENSIONS:
        return False
    
    # Skip files that are too large
    if os.path.getsize(filepath) > MAX_FILE_SIZE:
        print(f"Skipping large file: {filepath}")
        return False
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        print(f"Skipping binary file: {filepath}")
        return False
        
    # Remove old license headers - more comprehensive pattern
    # This matches common license header patterns including GPL, MIT, Apache, etc.
    license_patterns = [
        r'(#|\/\/|<!--|\/\*)\s*Copyright.*?((GPL|GNU|License|Copyright).*?)\n',
        r'(#|\/\/|<!--|\/\*)\s*This (file|program|code) is.*?((licensed|distributed).*?)\n',
        r'(#|\/\/|<!--|\/\*)\s*Permission is hereby granted.*?\n'
    ]
    
    for pattern in license_patterns:
        content = re.sub(pattern, '', content, flags=re.DOTALL | re.IGNORECASE)
    
    # Add new header
    header = HEADER_TEMPLATE.format(year=datetime.now().year)
    commented_header = EXTENSIONS[ext].format(header=header)
    new_content = f"{commented_header}\n\n{content.lstrip()}"
    
    # Create backup
    backup_path = f"{filepath}.bak"
    with open(backup_path, 'w', encoding='utf-8') as f:
        with open(filepath, 'r', encoding='utf-8') as original:
            f.write(original.read())
    
    # Write updated content
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    return True

def main():
    """Main function to update license headers in all files."""
    updated_count = 0
    skipped_count = 0
    error_count = 0
    
    for root, dirs, files in os.walk('.'):
        # Skip directories we don't want to process
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
        
        for file in files:
            if file == 'update_headers.py' or file.endswith('.bak'):
                continue
                
            filepath = os.path.join(root, file)
            try:
                if update_file(filepath):
                    print(f"Updated: {filepath}")
                    updated_count += 1
                else:
                    skipped_count += 1
            except Exception as e:
                print(f"Error processing {filepath}: {str(e)}")
                error_count += 1
    
    print(f"\nSummary:")
    print(f"  Files updated: {updated_count}")
    print(f"  Files skipped: {skipped_count}")
    print(f"  Errors: {error_count}")
    print("\nBackup files created with .bak extension")

if __name__ == '__main__':
    main()
