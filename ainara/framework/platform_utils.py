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

import json
import logging
import os
import platform
from pathlib import Path

logger = logging.getLogger(__name__)

MIGRATION_CHECKED = False

def _get_windows_documents_path():
    """Get the real Documents path on Windows using Windows API"""
    import ctypes.wintypes
    buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
    ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)  # CSIDL_PERSONAL = 5
    return Path(buf.value)


def get_default_config_paths():
    """Get list of default platform-specific configuration file paths"""
    system = platform.system()
    config_paths = []

    if system == "Linux" or system == "Darwin":  # Linux or macOS
        # XDG standard for Linux, similar location for macOS
        config_home = os.environ.get(
            "XDG_CONFIG_HOME", os.path.expanduser("~/.config")
        )
        config_paths.extend([
            Path(config_home) / "ainara/ainara.yaml",
            Path("/etc/ainara/ainara.yaml"),
        ])
    elif system == "Windows":
        # Always use Documents/Ainara/Config on Windows
        docs_path = _get_windows_documents_path()
        config_paths.append(docs_path / "Ainara" / "Config" / "ainara.yaml")
    else:
        # Fallback for other systems
        config_paths.append(Path(os.path.expanduser("~/.ainara/ainara.yaml")))

    # Add current directory as last resort for development environments
    config_paths.append(Path("config/ainara.yaml"))
    return config_paths


def get_default_log_dir():
    """Get default platform-specific log directory path"""
    system = platform.system()

    if system == "Windows":
        docs_path = _get_windows_documents_path()
        return docs_path / "Ainara" / "Logs"
    elif system == "Linux":
        data_home = os.environ.get(
            "XDG_DATA_HOME", os.path.expanduser("~/.local/share")
        )
        return Path(data_home) / "ainara/logs"
    elif system == "Darwin":  # macOS
        return Path(os.path.expanduser("~/Library/Logs/Ainara"))
    else:
        return Path(os.path.expanduser("~/.ainara/logs"))


def get_default_cache_dir():
    """Get default platform-specific cache directory path"""
    system = platform.system()

    if system == "Windows":
        docs_path = _get_windows_documents_path()
        return docs_path / "Ainara" / "Cache"
    elif system == "Linux":
        cache_home = os.environ.get(
            "XDG_CACHE_HOME", os.path.expanduser("~/.cache")
        )
        return Path(cache_home) / "ainara"
    elif system == "Darwin":  # macOS
        return Path(os.path.expanduser("~/Library/Caches/Ainara"))
    else:
        return Path(os.path.expanduser("~/.ainara/cache"))


def get_default_data_dir(app_name="ainara"):
    """Get default platform-specific user data directory path"""
    system = platform.system()

    if system == "Windows":
        docs_path = _get_windows_documents_path()
        return docs_path / "Ainara" / "Data"
    elif system == "Darwin":  # macOS
        return os.path.join(
            os.path.expanduser("~/Library/Application Support"), str(app_name)
        )
    else:  # Linux and others
        return os.path.join(os.path.expanduser("~/.local/state"), str(app_name))


def find_nexus_manifest(start_path: str, max_levels: int = 5) -> dict:
    """
    Finds and parses the nexus.json manifest file by traversing up the directory tree.

    Args:
        start_path: The starting file path to begin the search from.
        max_levels: The maximum number of parent directories to check.

    Returns:
        A dictionary containing the parsed manifest data.

    Raises:
        FileNotFoundError: If nexus.json is not found within the traversal limit.
    """
    current_path = Path(start_path).resolve().parent
    for _ in range(max_levels):
        manifest_path = current_path / "nexus.json"
        if manifest_path.is_file():
            with open(manifest_path, "r") as f:
                return json.load(f)

        if current_path == current_path.parent:  # Reached root
            break
        current_path = current_path.parent

    raise FileNotFoundError(
        f"Could not find nexus.json within {max_levels} levels "
        f"up from {start_path}"
    )
