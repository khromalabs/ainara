
import os
import sys
import logging

# Set up logging to a file
# Use a writable location for logs
home_dir = os.path.expanduser('~')
log_dir = os.path.join(home_dir, '.polaris', 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'pyinstaller_debug.log')

logging.basicConfig(
    filename=log_file,
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('PyInstallerDebug')

# Log system information
logger.info(f"Python executable: {sys.executable}")
logger.info(f"Working directory: {os.getcwd()}")
logger.info(f"sys.path: {sys.path}")

# Add the directory containing the executable to sys.path
sys.path.insert(0, os.path.dirname(sys.executable))

# Add the parent directory of the executable to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(sys.executable)))
