#!/usr/bin/env python3
# scripts/prepare_tiktoken.py

import os
import sys
import hashlib
import requests
import shutil

def download_encoding_file(url, output_path):
    """Download a tiktoken encoding file"""
    print(f"Downloading {url} to {output_path}...")
    response = requests.get(url)
    if response.status_code == 200:
        with open(output_path, 'wb') as f:
            f.write(response.content)
        print(f"Successfully downloaded {url} to {output_path}")
        return True
    else:
        print(f"Failed to download: {response.status_code}")
        return False

def prepare_tiktoken():
    """Download and prepare tiktoken encoding files"""
    # Create directory for tiktoken files
    tiktoken_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'ainara', 'tiktoken_files')
    os.makedirs(tiktoken_dir, exist_ok=True)
    
    # URL for cl100k_base encoding
    url = "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"
    
    # Calculate the hash (this is what tiktoken uses to look up the file)
    cache_key = hashlib.sha1(url.encode()).hexdigest()
    output_path = os.path.join(tiktoken_dir, cache_key)
    
    # Download the file
    if download_encoding_file(url, output_path):
        print(f"Tiktoken encoding file prepared at: {output_path}")
        print(f"Hash: {cache_key}")
        return True
    return False

if __name__ == "__main__":
    success = prepare_tiktoken()
    sys.exit(0 if success else 1)
