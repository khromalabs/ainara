#!/bin/bash

# Check if the correct number of arguments is provided
if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <old_version> <new_version>"
    exit 1
fi

old_version=$1
new_version=$2

# Escape dots in the old version for use in agrep
escaped_old_version=$(echo "$old_version" | sed 's/\./\\./g')

# Find files containing the old version and update them
for file in $(bin/agrep "$escaped_old_version" | awk -F: '{print $1}'); do
    replace "$old_version" "$new_version" -- "$file"
done
