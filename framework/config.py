import copy
# import logging
import os
import platform
import shutil
import sys
from pathlib import Path

import yaml


class ConfigManager:
    """Manages application configuration following platform-specific standards"""

    def __init__(self):
        self.config = {}
        self.config_file_path = None
        self.load_config()

    def get_config_paths(self):
        """Get platform-specific configuration paths"""
        # First check environment variable
        env_config_path = os.environ.get("AINARA_CONFIG")
        if env_config_path:
            return [Path(env_config_path)]

        # Determine OS-specific config locations
        system = platform.system()
        config_paths = []

        if system == "Linux" or system == "Darwin":  # Linux or macOS
            # XDG standard for Linux, similar location for macOS
            config_home = os.environ.get(
                "XDG_CONFIG_HOME", os.path.expanduser("~/.config")
            )
            config_paths = [
                Path(config_home) / "ainara/ainara.yaml",
                Path("/etc/ainara/ainara.yaml"),
            ]
        elif system == "Windows":
            # Windows standard locations
            appdata = os.environ.get(
                "APPDATA", os.path.expanduser("~/AppData/Roaming")
            )
            config_paths = [
                Path(appdata) / "Ainara/ainara.yaml",
            ]
        else:
            # Fallback for other systems
            config_paths = [
                Path(os.path.expanduser("~/.ainara/ainara.yaml")),
            ]

        # Add current directory as last resort for development environments
        config_paths.append(Path("config/ainara.yaml"))

        return config_paths

    def get_default_config_path(self):
        """Get the path to the default configuration template"""
        # Look for defaults in several possible locations
        possible_paths = [
            Path("resources/ainara.yaml.defaults"),  # Project root
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

    def create_default_config(self, target_path):
        """Create a new configuration file from defaults"""
        default_path = self.get_default_config_path()

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

        # Copy the default config
        shutil.copy(default_path, target_path)
        print(f"Created new configuration file at: {target_path}")

        return target_path

    def load_config(self):
        """Load config from appropriate location or create from defaults"""
        config_paths = self.get_config_paths()

        # Try to load from existing config file
        for config_path in config_paths:
            if config_path.exists():
                try:
                    with open(config_path) as f:
                        self.config = yaml.safe_load(f) or {}
                    self.config_file_path = config_path
                    print(f"Configuration loaded from: {config_path}")
                    
                    # Set up log directory in config
                    if "logging" not in self.config:
                        self.config["logging"] = {}
                    if "directory" not in self.config["logging"]:
                        self.config["logging"]["directory"] = str(self._get_log_directory())
                    
                    return
                except Exception as e:
                    print(
                        f"Error loading configuration from {config_path}: {e}"
                    )
                    # Continue to next path

        # If we get here, no config file was found - create one
        # Use the first path from the OS-specific list (skip env var path)
        default_config_location = self.get_config_paths()[0]
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
            self.config["logging"]["directory"] = str(self._get_log_directory())

    def get(self, key_path: str, default=None):
        """Get a config value using dot notation"""
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

    def update_config(self, new_config, save=True):
        """Update configuration with new values"""

        # Recursively update the configuration
        def update_dict(target, source):
            for key, value in source.items():
                if (
                    isinstance(value, dict)
                    and key in target
                    and isinstance(target[key], dict)
                ):
                    update_dict(target[key], value)
                else:
                    target[key] = value

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

        # Determine OS-specific log locations
        system = platform.system()
        
        if system == "Linux":
            # XDG standard for Linux
            data_home = os.environ.get(
                "XDG_DATA_HOME", os.path.expanduser("~/.local/share")
            )
            log_dir = Path(data_home) / "ainara/logs"
        elif system == "Darwin":  # macOS
            log_dir = Path(os.path.expanduser("~/Library/Logs/Ainara"))
        elif system == "Windows":
            # Windows standard locations
            localappdata = os.environ.get(
                "LOCALAPPDATA", os.path.expanduser("~/AppData/Local")
            )
            log_dir = Path(localappdata) / "Ainara/logs"
        else:
            # Fallback for other systems
            log_dir = Path(os.path.expanduser("~/.ainara/logs"))
        
        # Ensure the directory exists
        os.makedirs(log_dir, exist_ok=True)
        return log_dir

    def validate_config(self, config_data):
        """Basic validation of configuration data"""
        # This is a simple validation - in a real implementation, you might want to use
        # a more formal schema validation

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
