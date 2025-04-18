#!/usr/bin/env python3
"""
Batch update source file headers to dual-license notice
"""
import os
from datetime import datetime

HEADER_TEMPLATE = """Ainara AI Companion Framework Project
Copyright (C) {year} Rubén Gómez - khromalabs.org

This file is dual-licensed under:
1. GNU Lesser General Public License v3.0 (LGPL-3.0)
   (See the included LICENSE_LGPL3.txt file or look into
   <https://www.gnu.org/licenses/lgpl-3.0.html> for details)
2. Commercial license
   (Contact: rgomez@khromalabs.org for licensing options)

You may use, distribute and modify this code under the terms of either license.
This notice must be preserved in all copies or substantial portions of the code.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
Lesser General Public License for more details."""


def format_header(header, ext):
    """Format header with proper comment characters per line based on file extension."""
    lines = header.split("\n")
    formatted_lines = []

    if ext in (".py", ".sh"):
        formatted_lines = [f"# {line}" if line else "#" for line in lines]
    elif ext in (".js", ".ts", ".go", ".rs", ".java"):
        formatted_lines = [f"// {line}" if line else "//" for line in lines]
    elif ext == ".md":
        formatted_lines = [
            f"<!-- {line} -->" if line else "<!-- -->" for line in lines
        ]
    elif ext in (".c", ".cpp", ".h", ".hpp", ".css"):
        formatted_lines = (
            ["/*"]
            + [f" * {line}" if line else " *" for line in lines]
            + [" */"]
        )

    return "\n".join(formatted_lines)


# Directories to skip
SKIP_DIRS = [".git", "node_modules", "venv", "__pycache__", "dist", "build"]

# Maximum file size to process (in bytes) - skip files larger than 1MB
MAX_FILE_SIZE = 1024 * 1024


def is_comment_line(line, ext):
    """Check if a line is a comment based on file extension."""
    if ext in (".py", ".sh"):
        return line.lstrip().startswith("#")
    elif ext in (".js", ".ts", ".go", ".rs"):
        return line.lstrip().startswith("//")
    elif ext == ".md":
        return line.lstrip().startswith("<!--")
    elif ext in (".c", ".cpp", ".h", ".hpp", ".css"):
        return (
            line.lstrip().startswith("/*")
            or line.lstrip().startswith("*")
            or line.rstrip().endswith("*/")
        )
    return False


def detect_comment_block(content, ext):
    """Detect the initial comment block in a file."""
    lines = content.splitlines()
    comment_lines = []

    for line in lines:
        stripped = line.lstrip()
        if not stripped:  # Empty line
            if comment_lines:  # Only keep if we're in a comment block
                comment_lines.append(line)
            continue

        if is_comment_line(line, ext):
            comment_lines.append(line)
        else:
            break  # Found non-comment line, stop

    return "\n".join(comment_lines)


def update_file(filepath):
    """Update the license header in a file."""
    ext = os.path.splitext(filepath)[1].lower()
    # Skip files with extensions we don't handle
    if ext not in (
        ".py",
        ".sh",
        ".js",
        ".ts",
        ".go",
        ".rs",
        ".java",
        ".md",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".css",
    ):
        return False

    if os.path.getsize(filepath) > MAX_FILE_SIZE:
        print(f"Skipping large file: {filepath}")
        return False

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        print(f"Skipping binary file: {filepath}")
        return False

    # Check for shebang line
    lines = content.splitlines()
    shebang = lines[0] if lines and lines[0].startswith('#!') else None

    # Detect and remove existing comment block (skip shebang if present)
    start_idx = 1 if shebang else 0
    comment_block = detect_comment_block('\n'.join(lines[start_idx:]), ext)

    # Rebuild content without old header but preserving shebang
    if comment_block:
        remaining_content = '\n'.join(lines[start_idx + len(comment_block.splitlines()):])
    else:
        remaining_content = '\n'.join(lines[start_idx:])

    # Add new header with proper line-by-line commenting
    header = HEADER_TEMPLATE.format(year=datetime.now().year)
    commented_header = format_header(header, ext)

    # Reconstruct content with shebang (if any), new header, and remaining content
    if shebang:
        new_content = f"{shebang}\n{commented_header}\n\n{remaining_content}"
    else:
        new_content = f"{commented_header}\n\n{remaining_content}"

    # Write new content directly (no backup since we're using version control)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_content)

    return True


def main():
    """Main function to update license headers in all files."""
    updated_count = 0
    skipped_count = 0
    error_count = 0

    for root, dirs, files in os.walk("."):
        # Skip directories we don't want to process
        dirs[:] = [
            d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")
        ]

        for file in files:
            if file == "update_headers.py" or file.endswith(".bak"):
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

    print("\nSummary:")
    print(f"  Files updated: {updated_count}")
    print(f"  Files skipped: {skipped_count}")
    print(f"  Errors: {error_count}")


if __name__ == "__main__":
    main()
