import os
import platform

def get_user_data_dir(app_name="polaris"):
    """Get the appropriate user data directory for the current platform"""
    system = platform.system()
    if system == "Windows":
        # On Windows, use %LOCALAPPDATA%\app_name
        return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~/AppData/Local")), app_name)
    elif system == "Darwin":  # macOS
        # On macOS, use ~/Library/Application Support/app_name
        return os.path.join(os.path.expanduser("~/Library/Application Support"), app_name)
    else:  # Linux and others
        # On Linux, use ~/.local/state/app_name (for state data)
        return os.path.join(os.path.expanduser("~/.local/state"), app_name)
