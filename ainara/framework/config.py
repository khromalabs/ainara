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

import copy
import inspect
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
# import traceback
import yaml
import json
import platform
from jsonschema import Draft7Validator
from typing import Optional

logger = logging.getLogger(__name__)

_NEXUS_MODULE_PREFIXES = [
    ("ainara.nexus", "skills.nexus"),
]

def register_nexus_root(module_prefix: str, config_prefix: str):
    """Register an external Nexus package root."""
    _NEXUS_MODULE_PREFIXES.append((module_prefix, config_prefix))
    _NEXUS_MODULE_PREFIXES.sort(key=lambda p: len(p[0]), reverse=True)

def nexus_prefix_from_module_name(module_name: str) -> str:
    """Return the config prefix for a Nexus module, or '' if not in Nexus."""
    for module_prefix, config_prefix in _NEXUS_MODULE_PREFIXES:
        if module_name == module_prefix or module_name.startswith(module_prefix + "."):
            rel = module_name[len(module_prefix):]
            return config_prefix + rel if rel else config_prefix
    return ""

def _get_caller_nexus_prefix() -> str:
    """Walk the stack to find the first Nexus module and derive its prefix."""
    frame = inspect.currentframe()
    try:
        # skip _get_caller_nexus_prefix and the calling method (get/set)
        frame = frame.f_back.f_back
        while frame:
            module_name = frame.f_globals.get("__name__", "")
            prefix = nexus_prefix_from_module_name(module_name)
            if prefix:
                return prefix
            frame = frame.f_back
        return ""
    finally:
        del frame


class ConfigManager:
    """Manages application configuration following platform-specific standards"""

    def __init__(self):
        self.config = {}
        self.config_file_path = None
        self.last_modified_time = 0
        self.validation_errors = []
        self.initial_config_valid = True
        self.load_config()

    def _get_windows_saved_games_path(self):
        """Get the Saved Games path on Windows using PowerShell."""
        try:
            result = subprocess.run(
                ['powershell', '-Command', "[Environment]::GetFolderPath('SavedGames')"],
                capture_output=True, text=True, check=True
            )
            return Path(result.stdout.strip())
        except Exception:
            # Fallback to default if PowerShell fails
            return Path(os.path.expanduser('~/Saved Games'))

    def get_default_config_paths(self):
        """Get list of default platform-specific configuration file paths"""
        # First check environment variable
        env_config_path = os.environ.get("AINARA_CONFIG")
        if env_config_path:
            return [Path(env_config_path)]

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
            # Always use Saved Games\Ainara\Config on Windows
            saved_games = self._get_windows_saved_games_path()
            config_paths.append(saved_games / "Ainara" / "Config" / "ainara.yaml")
        else:
            # Fallback for other systems
            config_paths.append(Path(os.path.expanduser("~/.ainara/ainara.yaml")))

        # Add current directory as last resort for development environments
        config_paths.append(Path("config/ainara.yaml"))
        return config_paths

    def get_default_log_dir(self):
        """Get default platform-specific log directory path"""

        # First check environment variable
        env_log_path = os.environ.get("AINARA_LOGS")
        if env_log_path:
            log_dir = Path(os.path.expanduser(env_log_path))
            os.makedirs(log_dir, exist_ok=True)
            return log_dir

        system = platform.system()

        if system == "Windows":
            saved_games = self._get_windows_saved_games_path()
            log_dir = saved_games / "Ainara" / "Logs"
        elif system == "Linux":
            data_home = os.environ.get(
                "XDG_DATA_HOME", os.path.expanduser("~/.local/share")
            )
            log_dir = Path(data_home) / "ainara/logs"
        elif system == "Darwin":  # macOS
            log_dir = Path(os.path.expanduser("~/Library/Logs/Ainara"))
        else:
            log_dir = Path(os.path.expanduser("~/.ainara/logs"))

        # Ensure the directory exists
        os.makedirs(log_dir, exist_ok=True)
        return log_dir

    def get_default_cache_dir(self):
        """Get default platform-specific cache directory path"""
        # First check environment variable
        env_cache_path = os.environ.get("AINARA_CACHE")
        if env_cache_path:
            cache_dir = Path(os.path.expanduser(env_cache_path))
            os.makedirs(cache_dir, exist_ok=True)
            return cache_dir

        # Check if user has specified a cache directory in config
        if "cache" in self.config and "directory" in self.config["cache"]:
            user_cache_dir = self.config["cache"]["directory"]
            cache_dir = Path(os.path.expanduser(user_cache_dir))
            os.makedirs(cache_dir, exist_ok=True)
            return cache_dir

        system = platform.system()
        if system == "Windows":
            saved_games = self._get_windows_saved_games_path()
            cache_dir = saved_games / "Ainara" / "Cache"
        elif system == "Linux":
            cache_home = os.environ.get(
                "XDG_CACHE_HOME", os.path.expanduser("~/.cache")
            )
            cache_dir = Path(cache_home) / "ainara"
        elif system == "Darwin":  # macOS
            cache_dir = Path(os.path.expanduser("~/Library/Caches/Ainara"))
        else:
            cache_dir = Path(os.path.expanduser("~/.ainara/cache"))

        # Ensure the directory exists
        os.makedirs(cache_dir, exist_ok=True)
        return cache_dir

    # -------------------------------------------------------------------------
    # KNOWN ISSUE & FUTURE MIGRATION PLAN (Issue #1.7 / #7)
    # -------------------------------------------------------------------------
    # MIGRATION COMPLETED (v0.11): On Windows, the default data location is
    # now the Saved Games folder (FOLDERID_SavedGames). The migration from
    # the old Documents\Ainara location (and from legacy AppData paths) is
    # handled automatically at startup by the Electron layer. The Python
    # ConfigManager now reads/writes config files from
    # Saved Games\Ainara\Config. Old folders are renamed to
    # *.old.migrated_to_savedgames for user inspection.
    # -------------------------------------------------------------------------
    def get_default_data_dir(self, app_name="ainara"):
        """Get default platform-specific user data directory path"""
        system = platform.system()

        if system == "Windows":
            saved_games = self._get_windows_saved_games_path()
            data_dir = saved_games / "Ainara" / "Data"
        elif system == "Darwin":  # macOS
            data_dir = os.path.join(
                os.path.expanduser("~/Library/Application Support"), str(app_name)
            )
        else:  # Linux and others
            data_dir = os.path.join(os.path.expanduser("~/.local/state"), str(app_name))

        # Ensure the directory exists
        os.makedirs(data_dir, exist_ok=True)
        return data_dir

    def _get_config_template_path(self):
        """Get the path to the default configuration template"""
        # Look for defaults in several possible locations
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            path = Path(sys._MEIPASS + "/resources/ainara.yaml.defaults")
            if path.exists():
                return path

        possible_paths = [
            Path("resources/ainara.yaml.defaults"),  # Project root
            Path("../resources/ainara.yaml.defaults"),  # Project root
            Path(__file__).parent.parent
            / "resources/ainara.yaml.defaults",  # Relative to this file
            Path(
                "/usr/share/ainara/ainara.yaml.defaults"
            ),  # System-wide installation
        ]

        for path in possible_paths:
            if path.exists():
                return path

        return None

    def _get_config_schema_path(self):
        """Get the path to the configuration schema"""
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            path = Path(sys._MEIPASS + "/resources/config.schema.json")
            if path.exists():
                return path

        possible_paths = [
            Path("resources/config.schema.json"),  # Project root
            Path("../resources/config.schema.json"),  # Project root
            Path(__file__).parent.parent
            / "resources/config.schema.json",  # Relative to this file
            Path(
                "/usr/share/ainara/config.schema.json"
            ),  # System-wide installation
        ]

        for path in possible_paths:
            if path.exists():
                return path

        return None

    def create_default_config(self, target_path):
        """Create a new configuration file from defaults"""
        dry_run = False

        if self.needs_load():
            logger.info("INFO: Configuration file has changed won't update")
            dry_run = True

        default_path = self._get_config_template_path()

        if not default_path:
            logger.info("ERROR: Default configuration template not found.")
            logger.info("Ainara cannot start without a configuration file.")
            logger.info(
                "Please ensure the file 'resources/ainara.yaml.defaults'"
                " exists."
            )
            sys.exit(1)

        # Ensure the directory exists
        target_dir = os.path.dirname(target_path)
        os.makedirs(target_dir, exist_ok=True)

        if not dry_run:
            # backup previous config if exists
            if os.path.isfile(target_path):
                shutil.copy(target_path, f"{target_path}.bak")
            # Copy the default config
            shutil.copy(default_path, target_path)
            logger.info(f"Created new configuration file at: {target_path}")

        return target_path

    def load_config(self, force=False):
        """Load config from appropriate location or create from defaults

        Args:
            force: If True, forces reload even if file hasn't changed
        """
        config_paths = self.get_default_config_paths()

        # Try to load from existing config file
        for config_path in config_paths:
            if config_path.exists():
                try:
                    if self.config and not force and not self.needs_load():
                        logger.info("Avoiding configuration reload")
                        return  # File hasn't changed since last load

                    with open(config_path) as f:
                        user_config = yaml.safe_load(f) or {}

                    # --- Validate Configuration ---
                    schema_path = self._get_config_schema_path()
                    if not schema_path:
                        logger.info("WARNING: Schema not found, skipping validation.")
                        self.config = user_config
                    else:
                        with open(schema_path) as f:
                            schema = json.load(f)
                        validator = Draft7Validator(schema)
                        errors = sorted(
                            validator.iter_errors(user_config),
                            key=lambda e: e.path,
                        )

                        if errors:
                            self.initial_config_valid = False
                            self.validation_errors = [
                                f"{'.'.join(map(str, e.path)) or 'root'}: {e.message}"
                                for e in errors
                            ]
                            logger.info("ERROR: Configuration validation failed. Attempting to restore invalid sections from defaults.")
                            for error in self.validation_errors:
                                logger.info(f" - {error}")

                            default_path = self._get_config_template_path()
                            if not default_path:
                                logger.info("ERROR: Default configuration not found. Re-creating entire configuration file.")
                                self.create_default_config(config_path)
                                with open(config_path) as f:
                                    self.config = yaml.safe_load(f) or {}
                                return

                            with open(default_path) as f:
                                default_config = yaml.safe_load(f) or {}

                            corrected_config = copy.deepcopy(user_config)

                            def get_nested(d, path):
                                for key in path:
                                    d = d[key]
                                return d

                            def set_nested(d, path, value):
                                for key in path[:-1]:
                                    d = d.setdefault(key, {})
                                d[path[-1]] = value

                            for e in {tuple(e.path) for e in errors}:
                                path = list(e)
                                if not path:
                                    corrected_config = default_config
                                    break
                                try:
                                    default_value = get_nested(default_config, path)
                                    set_nested(corrected_config, path, default_value)
                                except (KeyError, IndexError):
                                    continue

                            self.config = corrected_config
                            with open(config_path, "w") as f:
                                yaml.dump(self.config, f, default_flow_style=False)
                            logger.info(f"Configuration automatically corrected and saved to: {config_path}")
                        else:
                            self.config = user_config
                    # --- End Validation ---

                    self.config_file_path = config_path
                    self.last_modified_time = os.path.getmtime(config_path)
                    logger.info(f"Configuration loaded from: {config_path}")

                    # Set up log directory in config
                    if "logging" not in self.config:
                        self.config["logging"] = {}
                    if "directory" not in self.config["logging"]:
                        self.config["logging"]["directory"] = str(
                            self.get_default_log_dir()
                        )

                    # Set up cache directory in config
                    if "cache" not in self.config:
                        self.config["cache"] = {}
                    if "directory" not in self.config["cache"]:
                        self.config["cache"]["directory"] = str(
                            self.get_default_cache_dir()
                        )

                    # Set up sentence_transformers cache directory
                    cache_dir = Path(self.config["cache"]["directory"])
                    st_home = (
                        self.config["cache"].get("sentence_transformers_home")
                        or cache_dir / "transformers"
                    )
                    st_home = Path(os.path.expanduser(str(st_home)))
                    os.makedirs(st_home, exist_ok=True)
                    os.environ["SENTENCE_TRANSFORMERS_HOME"] = str(st_home)
                    self.config["cache"]["sentence_transformers_home"] = str(st_home)

                    # Set up data directory in config
                    if "data" not in self.config:
                        self.config["data"] = {}
                    if "directory" not in self.config["data"]:
                        self.config["data"]["directory"] = str(
                            self.get_default_data_dir()
                        )

                    # Set up backup configuration with defaults if not present
                    if "backup" not in self.config:
                        self.config["backup"] = {}
                    if "enabled" not in self.config["backup"]:
                        self.config["backup"]["enabled"] = False
                    if "directory" not in self.config["backup"]:
                        self.config["backup"]["directory"] = ""
                    if "interval_hours" not in self.config["backup"]:
                        self.config["backup"]["interval_hours"] = 24
                    if "versions_to_keep" not in self.config["backup"]:
                        self.config["backup"]["versions_to_keep"] = 7
                    if "password" not in self.config["backup"]:
                        self.config["backup"]["password"] = ""

                    # Set up user skills configuration with defaults
                    if "user_skills" not in self.config:
                        self.config["user_skills"] = {}
                    if "enabled" not in self.config["user_skills"]:
                        self.config["user_skills"]["enabled"] = False

                    # Force correct orakle server URL (temporary enforcement)
                    if "orakle" in self.config and "servers" in self.config["orakle"]:
                        self.config["orakle"]["servers"] = ["http://127.0.0.1:8100"]

                    return
                except Exception as e:
                    logger.info(
                        f"Error loading configuration from {config_path}: {e}"
                    )
                    # trace = traceback.logger.info_exc()
                    # logger.info(f"Traceback: {trace}")

        # If we get here, no config file was found - create one
        # Use the first path from the OS-specific list (skip env var path)
        default_config_location = self.get_default_config_paths()[0]

        self.config_file_path = self.create_default_config(
            default_config_location
        )

        # Now load the newly created config
        with open(self.config_file_path) as f:
            self.config = yaml.safe_load(f) or {}

        # Set up log directory in config
        if "logging" not in self.config:
            self.config["logging"] = {}
        if "directory" not in self.config["logging"]:
            self.config["logging"]["directory"] = str(
                self.get_default_log_dir()
            )

    def _get_unscoped(self, key_path, default=None):
        keys = key_path.split(".")
        value = self.config
        for key in keys:
            try:
                value = value[key]
            except (KeyError, TypeError):
                return default
        return value

    def _set_unscoped(self, key_path: str, value):
        parts = key_path.split(".")
        current = self.config
        for part in parts[:-1]:
            if not isinstance(current, dict):
                raise TypeError(f"Config path '{key_path}' traverses a non-dict.")
            current = current.setdefault(part, {})
        if not isinstance(current, dict):
            raise TypeError(f"Config path '{key_path}' traverses a non-dict.")
        current[parts[-1]] = value

    def get_exact(self, key_path: str, default=None):
        """Get a config value using exact dot notation without Nexus prefixing."""
        if self.needs_load():
            logger.info("INFO: Configuration file has changed, reloading.")
            self.load_config()
        return self._get_unscoped(key_path, default)

    def set_exact(self, key_path: str, value):
        """Set a config value using exact dot notation without Nexus prefixing."""
        if self.needs_load():
            self.load_config()

        self._set_unscoped(key_path, value)
        self.save()

    def get(
        self,
        key_path: str,
        default=None,
        schema=None,
        *,
        description: Optional[str] = None,
    ):
        """Get a config value using dot notation."""
        if self.needs_load():
            logger.info("INFO: Configuration file has changed, reloading.")
            self.load_config()

        # Global API namespace (legacy "API" wizard step): never auto-prefix
        if key_path.startswith("apis."):
            return self._get_unscoped(key_path, default)

        prefix = _get_caller_nexus_prefix()
        if prefix:
            raise ValueError(
                "config.get() cannot be used from Nexus modules for scoped keys. "
                "Use self.properties for values declared in _PROPERTIES, or "
                "config.get_exact(full_key) for explicit shared access."
            )

        return self._get_unscoped(key_path, default)

    def set(self, key_path: str, value):
        """Set a config value using dot notation."""
        if self.needs_load():
            self.load_config()

        if key_path.startswith("apis."):
            self._set_unscoped(key_path, value)
            self.save()
            return

        prefix = _get_caller_nexus_prefix()
        if prefix:
            raise ValueError(
                "config.set() cannot be used from Nexus modules for scoped keys. "
                "Use config.set_exact(full_key) for explicit full-key access."
            )

        self._set_unscoped(key_path, value)
        self.save()

    def save(self):
        """Save current configuration back to file"""
        if not self.config_file_path:
            raise ValueError("No configuration file path set")

        # backup previous config if exists
        if os.path.isfile(self.config_file_path):
            shutil.copy(self.config_file_path, f"{self.config_file_path}.bak")

        with open(self.config_file_path, "w") as f:
            # backup original file
            yaml.dump(self.config, f, default_flow_style=False)
            logger.info(f"Configuration saved to: {self.config_file_path}")
        self.last_modified_time = os.path.getmtime(self.config_file_path)

    def update_config(self, new_config, save=True):
        """Update configuration with new values"""

        if self.needs_load():
            logger.info("INFO: Configuration file has changed, reloading.")
            self.load_config()
            return True

        prefix = _get_caller_nexus_prefix()
        if prefix:
            raise ValueError(
                "update_config() is not available inside Nexus scopes; "
                "use set() instead."
            )

        # Recursively update the configuration
        def update_dict(target, source):
            # Update existing keys and add new ones from source
            for key, value in source.items():
                if (
                    isinstance(value, dict)
                    and key in target
                    and isinstance(target[key], dict)
                ):
                    update_dict(target[key], value)  # Recurse for nested dicts
                else:
                    target[key] = value  # Add new key or update existing one

            # Remove keys from target that are not in source
            keys_to_remove = [key for key in target if key not in source]
            for key in keys_to_remove:
                del target[key]

        update_dict(self.config, new_config)
        if save:
            self.save()
        return True

    def get_safe_config(self):
        """Return a copy of the config with sensitive information masked"""
        # Create a deep copy to avoid modifying the original
        safe_config = copy.deepcopy(self.config)

        # Mask sensitive information like API keys
        def mask_sensitive_values(
            obj,
            sensitive_keys=[
                "api_key",
                "apiKey",
                "secret",
                "password",
                "token",
            ],
        ):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if isinstance(value, (dict, list)):
                        mask_sensitive_values(value, sensitive_keys)
                    elif (
                        any(
                            sensitive_key in key.lower()
                            for sensitive_key in sensitive_keys
                        )
                        and value
                    ):
                        # Mask the value but preserve a hint of its existence
                        if isinstance(value, str) and len(value) > 4:
                            obj[key] = (
                                value[:2] + "*" * (len(value) - 4) + value[-2:]
                            )
                        else:
                            obj[key] = "****"
            elif isinstance(obj, list):
                for item in obj:
                    if isinstance(item, (dict, list)):
                        mask_sensitive_values(item, sensitive_keys)

        mask_sensitive_values(safe_config)
        return safe_config

    def get_subdir(self, directory, subdirectory):
        """Returns a subdirectory ensuring it exists"""
        full_path = os.path.join(str(self._get_unscoped(directory)), str(subdirectory))
        os.makedirs(full_path, exist_ok=True)
        return str(full_path)

    def get_nexus_base_path(self) -> Path:
        """Return the absolute path to the Nexus bundles/plugins base directory."""
        custom = self._get_unscoped("nexus.path")
        if custom:
            return Path(custom)
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            return Path(sys._MEIPASS) / "ainara" / "nexus"
        # Development fallback: config.py is in ainara/framework/ → one level up is ainara/
        return Path(__file__).resolve().parents[1] / "nexus"

    def needs_load(self):
        """Check if the config file has been modified since last load"""
        if not self.config_file_path or not os.path.exists(self.config_file_path):
            return False
        return os.path.getmtime(self.config_file_path) > self.last_modified_time

    def validate_config(self, config_data):
        """Basic validation of configuration data"""
        # This is a simple validation - in a real implementation, you might want to use
        # a more formal schema validation

        if self.needs_load():
            logger.info("INFO: Configuration file has changed, reloading.")
            self.load_config()

        result = {"valid": True, "errors": []}

        # Check for required top-level sections
        required_sections = ["llm", "stt"]
        for section in required_sections:
            if section not in config_data and section in self.config:
                result["valid"] = False
                result["errors"].append(f"Missing required section: {section}")

        # Additional validation could be added here

        return result


# Global config instance
config = ConfigManager()
