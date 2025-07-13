#!/usr/bin/env python3
# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
#
# This file is dual-licensed under:
# 1. GNU Lesser General Public License v3.0 (LGPL-3.0)
#    (See the included LICENSE_LGPL3.txt file or look into
#    <https://www.gnu.org/licenses/lgpl-3.0.html> for details)
# 2. Commercial license
#    (Contact: rgomez@khromalabs.org for licensing options)
#
# You may use, distribute and modify this code under the terms of either license.
# This notice must be preserved in all copies or substantial portions of the code.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.

import argparse
import os
import shutil
import subprocess
import sys

try:
    import pkg_resources
    HAVE_PKG_RESOURCES = True
except ImportError:
    HAVE_PKG_RESOURCES = False


def run_command(cmd):
    """Run a command and print its output"""
    print(f"Running: {' '.join(cmd)}")
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )

    # Print output in real-time
    for line in process.stdout:
        print(line, end="")

    process.wait()
    if process.returncode != 0:
        print(f"Error: Command failed with exit code {process.returncode}")
        sys.exit(1)


def check_dependencies():
    """Check if all required dependencies are installed"""
    if not HAVE_PKG_RESOURCES:
        print("Warning: pkg_resources not available, skipping dependency check")
        return True

    print("\n=== Reading dependencies from requirements.txt... ===")
    try:
        with open('requirements.txt', 'r') as f:
            lines = f.readlines()
        
        required_packages = []
        for line in lines:
            line = line.strip()
            # Ignore comments, blank lines, and special flags
            if not line or line.startswith('#') or line.startswith('--'):
                continue
            # Strip version specifiers and extras (e.g., "mcp[cli]==1.7.1" -> "mcp")
            package_name = line.split('==')[0].split('>=')[0].split('<=')[0].split('@')[0].split('[')[0].strip()
            required_packages.append(package_name)
    except FileNotFoundError:
        print("Error: requirements.txt not found. Cannot check dependencies.")
        return False

    print("\n=== Checking for required packages... ===")
    missing = []
    for package in required_packages:
        try:
            pkg_resources.get_distribution(package)
        except pkg_resources.DistributionNotFound:
            missing.append(package)

    if missing:
        print("\n=== Missing dependencies detected ===")
        print("The following packages are required but not installed:")
        for package in missing:
            print(f"  - {package}")
        print("\nPlease install them using:")
        print(f"  pip install {' '.join(missing)}")
        print("\nAdditionally, ensure the Spacy model is downloaded:")
        print("  python -m spacy download en_core_web_sm")
        print("\nThen run this script again.")
        return False

    print("All required packages are installed.")
    return True


def build_executables(force=False):
    """Build both Orakle and PyBridge executables"""
    # Check dependencies first
    if not check_dependencies():
        return False

    # Get paths to spec files
    servers_spec = os.path.join("scripts", "pyinstaller", "servers.spec")

    # Create a combined distribution directory
    dist_dir = "dist/"
    os.makedirs(dist_dir, exist_ok=True)

    # Clean up build and dist directories if force is True
    if force:
        print("\n=== Cleaning up build and dist directories ===\n")
        if os.path.exists("build"):
            shutil.rmtree("build")
        if os.path.exists(dist_dir):
            shutil.rmtree(dist_dir)

    # Build servers if requested (joined build with shared libraries)
    servers_dist_path = os.path.join(dist_dir, "servers")
    if (
        force
        or not os.path.exists(servers_dist_path)
        or not os.listdir(servers_dist_path)
    ):
        print("\n=== Building joined servers ===\n")
        run_command(["pyinstaller", servers_spec, "--clean"])
        print("\n=== Joined servers build complete ===\n")
    else:
        print("\n=== Skipping joined servers build (already exists) ===\n")
        print("Use --force to rebuild anyway")

    print(f"\nBuild complete! Executables are in {os.path.abspath(dist_dir)}")
    return True


if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Build Orakle and/or PyBridge executables"
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force rebuild even if executables already exist",
    )
    args = parser.parse_args()

    build_executables(force=args.force)
