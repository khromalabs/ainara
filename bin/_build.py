#!/usr/bin/env python3
# build/pyinstaller/build.py
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

    required_packages = [
        'pyinstaller',
        'telegram',
        'validators',
        'google-api-python-client',  # Provides googleapiclient
        'tiktoken',
        'litellm',
    ]

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
        print("\nThen run this script again.")
        return False

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
    return True

    print(f"\nBuild complete! Executables are in {os.path.abspath(dist_dir)}")


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
