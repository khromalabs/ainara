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

import importlib
import logging
import platform
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class DependencyChecker:
    """Utility class to check for system and Python dependencies"""

    @staticmethod
    def detect_nvidia_gpus() -> Tuple[bool, List[Dict[str, str]]]:
        """
        Detect NVIDIA GPUs in the system regardless of driver installation

        Returns:
            tuple: (has_nvidia_gpu, gpu_list)
        """
        gpus = []
        has_nvidia = False

        try:
            if sys.platform == 'win32':
                # Windows detection using WMI
                result = subprocess.run(
                    ['wmic', 'path', 'win32_VideoController', 'get', 'name,PNPDeviceID,AdapterRAM,DriverVersion'],
                    capture_output=True, text=True, check=False
                )

                if result.returncode == 0:
                    lines = [line.strip() for line in result.stdout.split('\n') if line.strip()]
                    # Skip the header line
                    for line in lines[1:]:
                        parts = line.split()
                        if not parts:
                            continue

                        # Join all parts except the last few which are the other properties
                        name = ' '.join(parts[:-3]) if len(parts) > 3 else ' '.join(parts)

                        if 'nvidia' in name.lower():
                            has_nvidia = True
                            # Try to extract more details if available
                            try:
                                # Get more detailed info using nvidia-smi if available
                                detailed_info = subprocess.run(
                                    ['nvidia-smi', '--query-gpu=name,driver_version,memory.total', '--format=csv,noheader'],
                                    capture_output=True, text=True, check=False
                                )
                                if detailed_info.returncode == 0:
                                    for gpu_line in detailed_info.stdout.strip().split('\n'):
                                        if gpu_line.strip():
                                            gpu_parts = gpu_line.split(',')
                                            gpus.append({
                                                'name': gpu_parts[0].strip(),
                                                'driver_version': gpu_parts[1].strip() if len(gpu_parts) > 1 else 'Unknown',
                                                'memory': gpu_parts[2].strip() if len(gpu_parts) > 2 else 'Unknown'
                                            })
                                else:
                                    # nvidia-smi failed, use basic info from wmic
                                    gpus.append({
                                        'name': name,
                                        'driver_version': 'Not installed or unknown',
                                        'memory': 'Unknown'
                                    })
                            except Exception as e:
                                # nvidia-smi not available, use basic info
                                gpus.append({
                                    'name': name,
                                    'driver_version': 'Not installed or unknown',
                                    'memory': 'Unknown'
                                })
            elif sys.platform == 'linux':
                # Linux detection using lspci
                try:
                    result = subprocess.run(
                        ['lspci', '-nn'],
                        capture_output=True, text=True, check=False
                    )

                    if result.returncode == 0:
                        for line in result.stdout.split('\n'):
                            if 'NVIDIA' in line or 'nvidia' in line.lower():
                                has_nvidia = True
                                # Extract the device name
                                name = line.split(':')[-1].strip()

                                # Try to get more details with nvidia-smi
                                try:
                                    detailed_info = subprocess.run(
                                        ['nvidia-smi', '--query-gpu=name,driver_version,memory.total', '--format=csv,noheader'],
                                        capture_output=True, text=True, check=False
                                    )
                                    if detailed_info.returncode == 0:
                                        for gpu_line in detailed_info.stdout.strip().split('\n'):
                                            if gpu_line.strip():
                                                gpu_parts = gpu_line.split(',')
                                                gpus.append({
                                                    'name': gpu_parts[0].strip(),
                                                    'driver_version': gpu_parts[1].strip() if len(gpu_parts) > 1 else 'Unknown',
                                                    'memory': gpu_parts[2].strip() if len(gpu_parts) > 2 else 'Unknown'
                                                })
                                    else:
                                        # nvidia-smi failed, use basic info
                                        gpus.append({
                                            'name': name,
                                            'driver_version': 'Not installed or unknown',
                                            'memory': 'Unknown'
                                        })
                                except Exception:
                                    # nvidia-smi not available
                                    gpus.append({
                                        'name': name,
                                        'driver_version': 'Not installed or unknown',
                                        'memory': 'Unknown'
                                    })
                except Exception as e:
                    logger.debug(f"Error using lspci to detect GPUs: {e}")

                    # Fallback to checking for nvidia-smi directly
                    try:
                        result = subprocess.run(
                            ['nvidia-smi', '--query-gpu=name,driver_version,memory.total', '--format=csv,noheader'],
                            capture_output=True, text=True, check=False
                        )
                        if result.returncode == 0:
                            has_nvidia = True
                            for gpu_line in result.stdout.strip().split('\n'):
                                if gpu_line.strip():
                                    gpu_parts = gpu_line.split(',')
                                    gpus.append({
                                        'name': gpu_parts[0].strip(),
                                        'driver_version': gpu_parts[1].strip() if len(gpu_parts) > 1 else 'Unknown',
                                        'memory': gpu_parts[2].strip() if len(gpu_parts) > 2 else 'Unknown'
                                    })
                    except Exception:
                        pass

            elif sys.platform == 'darwin':
                # macOS detection - NVIDIA GPUs are rare on Macs, but check anyway
                try:
                    result = subprocess.run(
                        ['system_profiler', 'SPDisplaysDataType'],
                        capture_output=True, text=True, check=False
                    )

                    if result.returncode == 0:
                        for line in result.stdout.split('\n'):
                            if 'NVIDIA' in line:
                                has_nvidia = True
                                gpus.append({
                                    'name': line.strip(),
                                    'driver_version': 'macOS integrated',
                                    'memory': 'Unknown'
                                })
                except Exception as e:
                    logger.debug(f"Error detecting GPUs on macOS: {e}")

        except Exception as e:
            logger.error(f"Error detecting NVIDIA GPUs: {e}")

        return has_nvidia, gpus

    @staticmethod
    def check_python_package(package_name: str) -> Tuple[bool, Optional[str]]:
        """
        Check if a Python package is installed

        Args:
            package_name: Name of the package to check

        Returns:
            Tuple of (is_available, version)
        """
        try:
            module = importlib.import_module(package_name)
            version = getattr(module, "__version__", "unknown")
            return True, version
        except ImportError:
            return False, None

    @staticmethod
    def check_system_library(library_name: str) -> bool:
        """
        Check if a system library is available

        Args:
            library_name: Name of the library to check (without lib prefix or extension)

        Returns:
            True if the library is available, False otherwise
        """
        system = platform.system()

        if system == "Linux":
            # Check using ldconfig on Linux
            try:
                result = subprocess.run(
                    ["ldconfig", "-p"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                return f"lib{library_name}.so" in result.stdout
            except (subprocess.SubprocessError, FileNotFoundError):
                # Try using ldd on the Python binary as fallback
                try:
                    python_path = sys.executable
                    result = subprocess.run(
                        ["ldd", python_path],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    return f"lib{library_name}.so" in result.stdout
                except (subprocess.SubprocessError, FileNotFoundError):
                    return False

        elif system == "Darwin":  # macOS
            # Check using otool on macOS
            try:
                python_path = sys.executable
                result = subprocess.run(
                    ["otool", "-L", python_path],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                return f"lib{library_name}" in result.stdout
            except (subprocess.SubprocessError, FileNotFoundError):
                return False

        elif system == "Windows":
            # Check using where on Windows
            try:
                result = subprocess.run(
                    ["where", f"{library_name}.dll"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                return result.returncode == 0
            except (subprocess.SubprocessError, FileNotFoundError):
                return False

        return False

    @staticmethod
    def check_cuda_availability() -> Tuple[bool, Optional[str], List[str], Dict]:
        """
        Enhanced check if CUDA is available and which version

        Returns:
            Tuple of (is_available, version, missing_libraries, details)
        """
        missing_libs = []
        details = {
            "has_nvidia_hardware": False,
            "gpu_list": [],
            "platform": sys.platform,
            "cuda_version": None,
            "cudnn_version": None,
            "pytorch_cuda_available": False,
            "driver_issue": False
        }

        # First detect if NVIDIA hardware is present
        has_nvidia_gpu, gpu_list = DependencyChecker.detect_nvidia_gpus()
        details["has_nvidia_hardware"] = has_nvidia_gpu
        details["gpu_list"] = gpu_list

        # Check for torch
        torch_available, torch_version = (
            DependencyChecker.check_python_package("torch")
        )
        if not torch_available:
            missing_libs.append("torch")
            return False, None, missing_libs, details

        # Check for CUDA availability through torch
        try:
            import torch

            details["pytorch_cuda_available"] = torch.cuda.is_available()

            if torch.cuda.is_available():
                cuda_version = torch.version.cuda
                details["cuda_version"] = cuda_version

                # Get GPU info for logging
                gpu_name = "Unknown"
                gpu_memory = "Unknown"
                try:
                    if torch.cuda.device_count() > 0:
                        device_props = torch.cuda.get_device_properties(0)
                        gpu_name = device_props.name
                        gpu_memory = f"{device_props.total_memory / (1024**3):.1f}GB"
                        logger.info(f"Detected GPU: {gpu_name} with {gpu_memory} VRAM")

                        # Add to details
                        details["device_count"] = torch.cuda.device_count()
                        details["current_device"] = torch.cuda.current_device()
                        details["device_name"] = gpu_name
                        details["memory_allocated"] = f"{torch.cuda.memory_allocated(0)/1024**3:.2f} GB"
                        details["memory_reserved"] = f"{torch.cuda.memory_reserved(0)/1024**3:.2f} GB"
                        details["max_memory"] = gpu_memory
                except Exception as e:
                    logger.warning(f"Error getting GPU info: {e}")

                # Try to get cuDNN version if available
                try:
                    from torch.backends import cudnn
                    if cudnn.is_available():
                        details["cudnn_version"] = cudnn.version()
                except Exception:
                    pass

                # On Windows, we'll trust torch.cuda.is_available() and not check for system libraries
                # as the DLLs are typically bundled with PyTorch or in the system PATH
                if platform.system() == "Windows":
                    return True, cuda_version, [], details

                # For Linux and macOS, perform additional checks
                # Check for cuDNN
                cudnn_available = DependencyChecker.check_system_library(
                    "cudnn"
                )
                if not cudnn_available:
                    missing_libs.append("cudnn")

                # Check for other CUDA libraries
                cuda_libs = [
                    "cublas",
                    "cufft",
                    "curand",
                    "cusolver",
                    "cusparse",
                ]
                for lib in cuda_libs:
                    if not DependencyChecker.check_system_library(lib):
                        missing_libs.append(lib)

                # Even if we're missing some libs, if torch.cuda.is_available() is True,
                # we'll consider CUDA available but log the missing libs
                if missing_libs:
                    logger.warning(f"CUDA available but missing libraries: {', '.join(missing_libs)}")
                return True, cuda_version, missing_libs, details
            else:
                # Hardware detected but CUDA not available - likely a driver issue
                if has_nvidia_gpu:
                    details["driver_issue"] = True

                    # Try to get more specific error information
                    try:
                        # Force CUDA initialization to get error message
                        torch.cuda.init()
                    except Exception as e:
                        error_msg = str(e)
                        details["error_message"] = error_msg

                        if "Found no NVIDIA driver" in error_msg:
                            missing_libs.append("NVIDIA driver")
                        elif "library not found" in error_msg.lower():
                            missing_libs.append("CUDA libraries")
                        else:
                            missing_libs.append("CUDA runtime")
                else:
                    missing_libs.append("NVIDIA GPU")

                return False, None, missing_libs, details
        except Exception as e:
            logger.warning(f"Error checking CUDA: {e}")
            details["error_message"] = str(e)
            missing_libs.append("CUDA runtime")
            return False, None, missing_libs, details

    @staticmethod
    def check_stt_dependencies() -> Dict[str, Dict]:
        """
        Check dependencies for STT functionality

        Returns:
            Dictionary with dependency status
        """
        results = {
            "whisper": {"available": False, "version": None, "missing": []},
            "faster_whisper": {
                "available": False,
                "version": None,
                "missing": [],
            },
            "cuda": {"available": False, "version": None, "missing": []},
        }

        # Check for whisper
        whisper_available, whisper_version = (
            DependencyChecker.check_python_package("openai-whisper")
        )
        results["whisper"]["available"] = whisper_available
        results["whisper"]["version"] = whisper_version
        if not whisper_available:
            results["whisper"]["missing"].append("openai-whisper")

        # Check for faster_whisper
        faster_whisper_available, faster_whisper_version = (
            DependencyChecker.check_python_package("faster_whisper")
        )
        results["faster_whisper"]["available"] = faster_whisper_available
        results["faster_whisper"]["version"] = faster_whisper_version
        if not faster_whisper_available:
            results["faster_whisper"]["missing"].append("faster_whisper")

        # Check for CUDA
        cuda_available, cuda_version, missing_cuda_libs, cuda_details = (
            DependencyChecker.check_cuda_availability()
        )
        results["cuda"]["available"] = cuda_available
        results["cuda"]["version"] = cuda_version
        results["cuda"]["missing"] = missing_cuda_libs
        results["cuda"]["details"] = cuda_details
        results["cuda"]["has_nvidia_hardware"] = cuda_details["has_nvidia_hardware"]
        results["cuda"]["gpu_list"] = cuda_details["gpu_list"]

        return results

    @staticmethod
    def get_acceleration_recommendation() -> Dict:
        """
        Get platform-specific recommendations for hardware acceleration

        Returns:
            dict: Recommendations for the current platform
        """
        cuda_available, cuda_version, missing_libs, details = DependencyChecker.check_cuda_availability()

        recommendations = {
            "cuda_available": cuda_available,
            "has_nvidia_hardware": details["has_nvidia_hardware"],
            "platform": sys.platform,
            "gpu_list": details["gpu_list"],
            "action_needed": not cuda_available and details["has_nvidia_hardware"],
        }

        # Add platform-specific recommendations
        if sys.platform == 'win32':
            if details["has_nvidia_hardware"] and not cuda_available:
                recommendations["action"] = "install_drivers"
                recommendations["instructions"] = [
                    "Download and install NVIDIA drivers from https://www.nvidia.com/Download/index.aspx",
                    "For best performance, also install CUDA Toolkit from https://developer.nvidia.com/cuda-downloads"
                ]
                recommendations["urls"] = {
                    "drivers": "https://www.nvidia.com/Download/index.aspx",
                    "cuda": "https://developer.nvidia.com/cuda-downloads"
                }
            elif not details["has_nvidia_hardware"]:
                recommendations["action"] = "none"
                recommendations["instructions"] = [
                    "No NVIDIA GPU detected. Speech recognition will use CPU, which may be slower."
                ]
            else:
                recommendations["action"] = "none"
                recommendations["instructions"] = [
                    "CUDA is properly configured. Speech recognition will use GPU acceleration."
                ]
        elif sys.platform == 'linux':
            if details["has_nvidia_hardware"] and not cuda_available:
                recommendations["action"] = "install_drivers"
                recommendations["instructions"] = [
                    "Install NVIDIA drivers using your distribution's package manager",
                    "For Ubuntu: sudo apt install nvidia-driver-XXX cuda",
                    "For other distributions, check your package manager"
                ]
            elif not details["has_nvidia_hardware"]:
                recommendations["action"] = "none"
                recommendations["instructions"] = [
                    "No NVIDIA GPU detected. Speech recognition will use CPU, which may be slower."
                ]
            else:
                recommendations["action"] = "none"
                recommendations["instructions"] = [
                    "CUDA is properly configured. Speech recognition will use GPU acceleration."
                ]
        elif sys.platform == 'darwin':
            recommendations["action"] = "none"
            recommendations["instructions"] = [
                "macOS uses Metal for GPU acceleration, not CUDA",
                "No action needed for Apple Silicon Macs"
            ]

        return recommendations

    @staticmethod
    def print_stt_dependency_report():
        """Print a report of STT dependencies"""
        results = DependencyChecker.check_stt_dependencies()

        logger.info("=== STT Dependency Report ===")

        # Whisper
        if results["whisper"]["available"]:
            logger.info(
                "✅ Whisper: Available (version"
                f" {results['whisper']['version']})"
            )
        # else:
        #     logger.info("❌ Whisper: Not available")
        #     logger.info("   To install: pip install openai-whisper")

        # Faster Whisper
        if results["faster_whisper"]["available"]:
            logger.info(
                "✅ Faster Whisper: Available (version"
                f" {results['faster_whisper']['version']})"
            )
        # else:
        #     logger.info("❌ Faster Whisper: Not available")
        #     logger.info("   To install: pip install faster-whisper")

        # CUDA
        if results["cuda"]["available"]:
            logger.info(
                f"✅ CUDA: Available (version {results['cuda']['version']})"
            )

            # Check if we're on Windows and add a note about potential issues
            if platform.system() == "Windows" and results["faster_whisper"]["available"]:
                logger.info(
                    "   Note: On Windows, if STT fails silently with CUDA, try setting"
                    " 'compute_type' to 'float16' or 'float32' in your STT configuration"
                )
        elif results["cuda"]["has_nvidia_hardware"]:
            logger.warning(
                "⚠️ NVIDIA GPU detected but CUDA is not available. Check driver installation."
            )

            # Log detected GPUs
            for gpu in results["cuda"]["gpu_list"]:
                logger.info(f"   Detected GPU: {gpu['name']} (Driver: {gpu['driver_version']})")

            # Platform-specific advice
            if platform.system() == "Windows":
                logger.info(
                    "   On Windows, download and install drivers from: "
                    "https://www.nvidia.com/Download/index.aspx"
                )
        else:
            # if results["cuda"]["missing"]:
            #     logger.info(
            #         "❌ CUDA: Missing dependencies:"
            #         f" {', '.join(results['cuda']['missing'])}"
            #     )
            #
            #     # Provide platform-specific installation instructions
            #     system = platform.system()
            #     if system == "Linux":
            #         try:
            #             import distro
            #
            #             distro_name = distro.name()
            #         except ImportError:
            #             distro_name = "Unknown Linux"
            #
            #         if "Ubuntu" in distro_name or "Debian" in distro_name:
            #             logger.info("   To install CUDA on Ubuntu/Debian:")
            #             logger.info(
            #                 "   sudo apt install nvidia-cuda-toolkit libcudnn8"
            #             )
            #         elif "Arch" in distro_name:
            #             logger.info("   To install CUDA on Arch Linux:")
            #             logger.info("   sudo pacman -S cuda cudnn")
            #         elif (
            #             "Fedora" in distro_name
            #             or "CentOS" in distro_name
            #             or "Red Hat" in distro_name
            #         ):
            #             logger.info("   To install CUDA on Fedora/RHEL:")
            #             logger.info("   sudo dnf install cuda cudnn")
            #     elif system == "Windows":
            #         logger.info("   To install CUDA on Windows:")
            #         logger.info(
            #             "   Download and install from"
            #             " https://developer.nvidia.com/cuda-downloads"
            #         )
            #     elif system == "Darwin":
            #         logger.info(
            #             "   CUDA is not supported on macOS, but MPS"
            #             " acceleration may be available"
            #         )
            # else:
            #     logger.info("❌ CUDA: Not available")

            logger.info(
                "   STT will fall back to CPU mode (slower but still"
                " functional)"
            )

        logger.info("=============================")

        return results