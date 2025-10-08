#!/bin/bash

# Check arguments
if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <old_version> <new_version>"
    exit 1
fi

old_version=$1
new_version=$2

# Escape dots for regex
escaped_old_version=$(echo "$old_version" | sed 's/\./\\./g')

# Convert version to tuple format (eg 0 . 3 . 0 -> 0 , 3 , 1)
old_tuple=$(echo "$old_version" | tr '.' ', ')
new_tuple=$(echo "$new_version" | tr '.' ', ')

# Grep for both dot-separated and comma-separated versions
old_tuple_grep=$(echo "$old_version" | tr '.' ',')

# Find and update files
for file in $( (scripts/agrep "$escaped_old_version"; scripts/agrep "$old_tuple_grep") | awk -F: '{print $1}' | sort -u); do
    # Handle different version formats based on file type
    case "$file" in
        *__init__.py)
            replace "$old_version" "$new_version" -- "$file"
            # Handle tuples with or without spaces
            old_tuple_regex=$(echo "$old_version" | sed 's/\./, */g')
            sed -i -E "s/\($old_tuple_regex\)/($new_tuple)/" "$file"
            ;;
        pyproject.toml)
            replace "version = \"$old_version\"" "version = \"$new_version\"" -- "$file"
            ;;
        *package.json*)
            replace "\"version\": \"$old_version\"" "\"version\": \"$new_version\"" -- "$file"
            ;;
        *splash.html)
            replace ">Version $old_version<" ">Version $new_version<" -- "$file"
            ;;
        *setup.js)
            replace "'setup.version', '$old_version'" "'setup.version', '$new_version'" -- "$file"
            ;;
        *)
            echo "Warning: Unhandled file with version string: $file"
            ;;
    esac
done


# Handle virtual environment
VENV_PATH="venv"
if [ -z "$VIRTUAL_ENV" ]; then
    if [ -f "$VENV_PATH/bin/activate" ]; then
        echo "Activating virtual environment..."
        source "$VENV_PATH/bin/activate"
    else
        echo "Virtual environment not found at $VENV_PATH"
        echo "To complete update, manually activate venv and run:"
        echo "  pip uninstall ainara && pip install -e ."
        exit 1
    fi
fi

# Refresh the editable installation
echo "Updating editable installation..."
pip uninstall -y ainara
pip install -e .
