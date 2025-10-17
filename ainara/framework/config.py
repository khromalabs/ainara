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
# import logging
import os
import shutil
import sys
from pathlib import Path
# import traceback
import yaml
import json
from jsonschema import Draft7Validator

from ainara.framework.platform_utils import (
    get_default_cache_dir,
    get_default_config_paths,
    get_default_data_dir,
    get_default_log_dir,
)


class ConfigManager:
    """Manages application configuration following platform-specific standards"""

    def __init__(self):
        self.config = {}
        self.config_file_path = None
        self.last_modified_time = 0
        self.validation_errors = []
        self.initial_config_valid = True
        self.load_config()

    def _get_config_paths(self):
        """Get platform-specific configuration paths"""
        # First check environment variable
        env_config_path = os.environ.get("AINARA_CONFIG")
        if env_config_path:
            return [Path(env_config_path)]

        # Determine OS-specific config locations
        config_paths = get_default_config_paths()

        return config_paths

    def _get_default_config_path(self):
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

    def _get_schema_path(self):
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
            print("INFO: Configuration file has changed won't update")
            dry_run = True

        default_path = self._get_default_config_path()

        if not default_path:
            print("ERROR: Default configuration template not found.")
            print("Ainara cannot start without a configuration file.")
            print(
                "Please ensure the file 'resources/ainara.yaml.defaults'"
                " exists."
            )
            sys.exit(1)

        # Ensure the directory exists
        target_dir = os.path.dirname(target_path)
        os.makedirs(target_dir, exist_ok=True)

        if not dry_run:
            # Copy the default config
            shutil.copy(default_path, target_path)
            print(f"Created new configuration file at: {target_path}")

        return target_path

    def load_config(self, force=False):
        """Load config from appropriate location or create from defaults

        Args:
            force: If True, forces reload even if file hasn't changed
        """
        config_paths = self._get_config_paths()

        # Try to load from existing config file
        for config_path in config_paths:
            if config_path.exists():
                try:
                    if self.config and not force and not self.needs_load():
                        print("Avoiding configuration reload")
                        return  # File hasn't changed since last load

                    with open(config_path) as f:
                        user_config = yaml.safe_load(f) or {}

                    # --- Validate Configuration ---
                    schema_path = self._get_schema_path()
                    if not schema_path:
                        print("WARNING: Schema not found, skipping validation.")
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
                            print("ERROR: Configuration validation failed. Attempting to restore invalid sections from defaults.")
                            for error in self.validation_errors:
                                print(f" - {error}")

                            default_path = self._get_default_config_path()
                            if not default_path:
                                print("ERROR: Default configuration not found. Re-creating entire configuration file.")
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
                            print(f"Configuration automatically corrected and saved to: {config_path}")
                        else:
                            self.config = user_config
                    # --- End Validation ---

                    self.config_file_path = config_path
                    self.last_modified_time = os.path.getmtime(config_path)
                    print(f"Configuration loaded from: {config_path}")

                    # Set up log directory in config
                    if "logging" not in self.config:
                        self.config["logging"] = {}
                    if "directory" not in self.config["logging"]:
                        self.config["logging"]["directory"] = str(
                            self._get_log_directory()
                        )

                    # Set up cache directory in config
                    if "cache" not in self.config:
                        self.config["cache"] = {}
                    if "directory" not in self.config["cache"]:
                        self.config["cache"]["directory"] = str(
                            self._get_cache_directory()
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
                            self._get_data_directory()
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

                    # Force correct orakle server URL (temporary enforcement)
                    if "orakle" in self.config and "servers" in self.config["orakle"]:
                        self.config["orakle"]["servers"] = ["http://127.0.0.1:8100"]

                    return
                except Exception as e:
                    print(
                        f"Error loading configuration from {config_path}: {e}"
                    )
                    # trace = traceback.print_exc()
                    # print(f"Traceback: {trace}")

        # If we get here, no config file was found - create one
        # Use the first path from the OS-specific list (skip env var path)
        default_config_location = self._get_config_paths()[0]
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
                self._get_log_directory()
            )

    def get(self, key_path: str, default=None):
        """Get a config value using dot notation"""
        # Check if the config file has been modified and reload if necessary
        if self.needs_load():
            print("INFO: Configuration file has changed, reloading.")
            self.load_config()

        keys = key_path.split(".")
        value = self.config

        for key in keys:
            try:
                value = value[key]
            except (KeyError, TypeError):
                return default

        return value

    def save(self):
        """Save current configuration back to file"""
        if not self.config_file_path:
            raise ValueError("No configuration file path set")

        with open(self.config_file_path, "w") as f:
            yaml.dump(self.config, f, default_flow_style=False)
            print(f"Configuration saved to: {self.config_file_path}")
        self.last_modified_time = os.path.getmtime(self.config_file_path)

    def update_config(self, new_config, save=True):
        """Update configuration with new values"""

        if self.needs_load():
            print("INFO: Configuration file has changed, reloading.")
            self.load_config()
            return True

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

    def _get_log_directory(self):
        """Get log directory based on platform defaults (private method)"""
        # First check environment variable
        env_log_path = os.environ.get("AINARA_LOGS")
        if env_log_path:
            log_dir = Path(os.path.expanduser(env_log_path))
            os.makedirs(log_dir, exist_ok=True)
            return log_dir

        log_dir = get_default_log_dir()

        # Ensure the directory exists
        os.makedirs(log_dir, exist_ok=True)
        return log_dir

    def _get_cache_directory(self):
        """Get cache directory based on platform defaults

        Args:
            subdirectory: Optional subdirectory within the cache directory

        Returns:
            Path object for the cache directory
        """
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

        cache_dir = get_default_cache_dir()

        # Ensure the directory exists
        os.makedirs(cache_dir, exist_ok=True)
        return cache_dir

    def _get_data_directory(self, app_name="ainara"):
        """Get the appropriate user data directory for the current platform"""
        return get_default_data_dir(app_name)

    def get_subdir(self, directory, subdirectory):
        """Returns a subdirectory ensuring it exists"""
        full_path = os.path.join(str(self.get(directory)), str(subdirectory))
        os.makedirs(full_path, exist_ok=True)
        return str(full_path)

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
            print("INFO: Configuration file has changed, reloading.")
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
