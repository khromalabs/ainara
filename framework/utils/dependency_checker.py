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
    def check_cuda_availability() -> Tuple[bool, Optional[str], List[str]]:
        """
        Check if CUDA is available and which version

        Returns:
            Tuple of (is_available, version, missing_libraries)
        """
        missing_libs = []

        # Check for torch
        torch_available, torch_version = (
            DependencyChecker.check_python_package("torch")
        )
        if not torch_available:
            missing_libs.append("torch")
            return False, None, missing_libs

        # Check for CUDA availability through torch
        try:
            import torch

            if torch.cuda.is_available():
                cuda_version = torch.version.cuda

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

                return len(missing_libs) == 0, cuda_version, missing_libs
            else:
                return False, None, ["CUDA driver"]
        except Exception as e:
            logger.warning(f"Error checking CUDA: {e}")
            return False, None, ["CUDA runtime"]

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
        cuda_available, cuda_version, missing_cuda_libs = (
            DependencyChecker.check_cuda_availability()
        )
        results["cuda"]["available"] = cuda_available
        results["cuda"]["version"] = cuda_version
        results["cuda"]["missing"] = missing_cuda_libs

        return results

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
