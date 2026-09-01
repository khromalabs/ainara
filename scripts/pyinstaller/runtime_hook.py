
import os
import sys
import logging
from pathlib import Path

# It's crucial to add the bundled 'ainara' package to the path
# so we can import our own utilities.
# sys._MEIPASS is the root of the bundled app.
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    sys.path.insert(0, sys._MEIPASS)

from ainara.framework.config import config

# --- Set up logging to a file ---
# Use a writable location for logs, respecting environment variables first.
log_dir_str = os.environ.get("AINARA_LOGS")
if log_dir_str:
    log_dir = Path(os.path.expanduser(log_dir_str))
else:
    log_dir = config.get_default_log_dir()

os.makedirs(log_dir, exist_ok=True)
log_file = log_dir / 'pyinstaller_debug.log'

logging.basicConfig(
    filename=str(log_file),
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('PyInstallerDebug')

# Log system information
logger.info("--- PyInstaller Runtime Hook Start ---")
logger.info(f"Python executable: {sys.executable}")
logger.info(f"Working directory: {os.getcwd()}")
logger.info(f"sys.path: {sys.path}")
logger.info(f"Log directory: {log_dir}")

# # --- Set up a reliable cache directory for transformers ---
# # Priority: TRANSFORMERS_CACHE > AINARA_CACHE > Ainara platform default.
# # If TRANSFORMERS_CACHE is already set, we respect it and do nothing.
# if 'TRANSFORMERS_CACHE' not in os.environ:
#     cache_dir_str = os.environ.get("AINARA_CACHE")
#     if cache_dir_str:
#         cache_dir = Path(os.path.expanduser(cache_dir_str))
#     else:
#         cache_dir = config.get_default_cache_dir()
#
#     transformers_cache_dir = cache_dir / 'transformers'
#     os.makedirs(transformers_cache_dir, exist_ok=True)
#
#     # Set the environment variable for huggingface libraries
#     os.environ['TRANSFORMERS_CACHE'] = str(transformers_cache_dir)
#     logger.info(f"Set TRANSFORMERS_CACHE to: {os.environ['TRANSFORMERS_CACHE']}")
# else:
#     logger.info(f"TRANSFORMERS_CACHE already set to: {os.environ['TRANSFORMERS_CACHE']}. Hook will not override it.")
#
# logger.info("--- PyInstaller Runtime Hook End ---")
