#!/usr/bin/env python3
# build/pyinstaller/build.py
import argparse
import os
import shutil
import subprocess
import sys
import time

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


def build_executables(targets=None, force=False):
    """Build both Orakle and PyBridge executables"""
    # Check dependencies first
    if not check_dependencies():
        return False

    # Get paths to spec files
    orakle_spec = os.path.join("scripts", "pyinstaller", "orakle.spec")
    pybridge_spec = os.path.join("scripts", "pyinstaller", "pybridge.spec")

    # Create a combined distribution directory
    dist_dir = "dist/"
    os.makedirs(dist_dir, exist_ok=True)

    # Clean up build and dist directories for specific targets if force is True
    if force:
        print("\n=== Cleaning up build and dist directories ===\n")
        if not targets:  # If no targets specified, clean everything
            if os.path.exists("build"):
                shutil.rmtree("build")
            if os.path.exists(dist_dir):
                shutil.rmtree(dist_dir)
        else:  # Only clean specified targets
            if "orakle" in targets:
                orakle_build = os.path.join("build", "orakle")
                if os.path.exists(orakle_build):
                    shutil.rmtree(orakle_build)
                orakle_dist = os.path.join(dist_dir, "orakle")
                if os.path.exists(orakle_dist):
                    shutil.rmtree(orakle_dist)
            if "pybridge" in targets:
                pybridge_build = os.path.join("build", "pybridge")
                if os.path.exists(pybridge_build):
                    shutil.rmtree(pybridge_build)
                pybridge_dist = os.path.join(dist_dir, "pybridge")
                if os.path.exists(pybridge_dist):
                    shutil.rmtree(pybridge_dist)

    # Set default targets if none specified
    if not targets:
        targets = ["orakle", "pybridge"]

    # Build Orakle if requested
    if "orakle" in targets:
        orakle_dist_path = os.path.join(dist_dir, "orakle")
        if (
            force
            or not os.path.exists(orakle_dist_path)
            or not os.listdir(orakle_dist_path)
        ):
            print("\n=== Building Orakle ===\n")
            print(f"\n=== Cleaning {orakle_dist_path} ===\n")
            # If the directory exists, remove it first to avoid copy errors
            if os.path.exists(orakle_dist_path):
                shutil.rmtree(orakle_dist_path)
            run_command(["pyinstaller", orakle_spec, "--clean"])
            print("\n=== Waiting briefly for file handles to release (Windows Antivirus fix) ===\n")
            time.sleep(15)
            # Copy the executable to the combined directory
            print("\n=== Copying Orakle to combined distribution ===\n")
            try:
                shutil.copytree("dist/orakle", orakle_dist_path)
            except Exception as e:
                print(f"Error copying Orakle files: {str(e)}")
                # Continue anyway as the build might have succeeded

        else:
            print("\n=== Skipping Orakle build (already exists) ===\n")
            print("Use --force to rebuild anyway")

    # Build PyBridge if requested
    if "pybridge" in targets:
        pybridge_dist_path = os.path.join(dist_dir, "pybridge")
        if (
            force
            or not os.path.exists(pybridge_dist_path)
            or not os.listdir(pybridge_dist_path)
        ):
            print("\n=== Building PyBridge ===\n")
            print(f"\n=== Cleaning {pybridge_dist_path} ===\n")
            # If the directory exists, remove it first to avoid copy errors
            if os.path.exists(pybridge_dist_path):
                shutil.rmtree(pybridge_dist_path)
            run_command(["pyinstaller", pybridge_spec, "--clean"])
            print("\n=== Waiting briefly for file handles to release (Windows Antivirus fix) ===\n")
            time.sleep(15)
            # Copy the executable to the combined directory
            print("\n=== Copying PyBridge to combined distribution ===\n")
            try:
                shutil.copytree("dist/pybridge", pybridge_dist_path)
            except Exception as e:
                print(f"Error copying PyBridge files: {str(e)}")
                # Continue anyway as the build might have succeeded

        else:
            print("\n=== Skipping PyBridge build (already exists) ===\n")
            print("Use --force to rebuild anyway")

    print(f"\nBuild complete! Executables are in {os.path.abspath(dist_dir)}")
    # print("\nDirectory structure:")
    # for root, dirs, files in os.walk(dist_dir):
    #     level = root.replace(dist_dir, "").count(os.sep)
    #     indent = " " * 4 * level
    #     print(f"{indent}{os.path.basename(root)}/")
    #     sub_indent = " " * 4 * (level + 1)
    #     for f in files[
    #         :5
    #     ]:  # Show only first 5 files per directory to avoid clutter
    #         print(f"{sub_indent}{f}")
    #     if len(files) > 5:
    #         print(f"{sub_indent}... ({len(files) - 5} more files)")


if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Build Orakle and/or PyBridge executables"
    )
    parser.add_argument(
        "--target",
        choices=["orakle", "pybridge", "all"],
        default="all",
        help="Specify which executable to build (default: all)",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force rebuild even if executables already exist",
    )
    args = parser.parse_args()

    # Determine which targets to build
    targets = []
    if args.target == "all":
        targets = ["orakle", "pybridge"]
    else:
        targets = [args.target]

    # # Check if PyInstaller is installed
    # try:
    #     import PyInstaller
    # except ImportError:
    #     print("PyInstaller is not installed. Installing...")
    #     run_command([sys.executable, "-m", "pip", "install", "pyinstaller"])

    build_executables(targets=targets, force=args.force)
