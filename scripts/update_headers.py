#!/usr/bin/env python3
"""
Batch update source file headers to dual-license notice
"""
import os
import re
from datetime import datetime

HEADER_TEMPLATE = """Copyright (C) {year} Rubén Gómez - khromalabs.org
This file is dual-licensed under:
1. GNU Lesser General Public License v3.0 only (LGPL-3.0-only)
2. Commercial license (contact rgomez@khromalabs.org)
You may use this file under the terms of either license.
"""

EXTENSIONS = {
    '.py': '# {header}',
    '.js': '// {header}',
    '.ts': '// {header}',
    '.rs': '// {header}',
    '.go': '// {header}',
    '.rs': '// {header}',
    '.sh': '# {header}',
    '.md': '<!-- {header} -->',
}

def update_file(filepath):
    ext = os.path.splitext(filepath)[1].lower()
    if ext not in EXTENSIONS:
        return False
    
    with open(filepath, 'r+') as f:
        content = f.read()
        
        # Remove old GPL notices
        content = re.sub(r'(#|\/\/|<!--)\s*Copyright.*GPL.*?\n', '', content, flags=re.DOTALL)
        
        # Add new header
        header = HEADER_TEMPLATE.format(year=datetime.now().year)
        commented_header = EXTENSIONS[ext].format(header=header)
        new_content = f"{commented_header}\n\n{content.lstrip()}"
        
        f.seek(0)
        f.write(new_content)
        f.truncate()
    
    return True

def main():
    for root, _, files in os.walk('.'):
        for file in files:
            if file == 'update_headers.py':
                continue
            filepath = os.path.join(root, file)
            try:
                if update_file(filepath):
                    print(f"Updated: {filepath}")
            except Exception as e:
                print(f"Error processing {filepath}: {str(e)}")

if __name__ == '__main__':
    main()
