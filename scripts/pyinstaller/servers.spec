# -*- mode: python ; coding: utf-8 -*-
import os
import sys
import importlib
import platform
from PyInstaller.utils.hooks import collect_submodules

# Get the project root directory (use current working directory as project root)
project_root = os.path.abspath(os.getcwd())

# Sanity check to ensure project_root is correct
if not os.path.exists(os.path.join(project_root, 'ainara')):
    raise ValueError(f"Calculated project_root {project_root} does not contain 'ainara' directory. Ensure the build is run from the project root.")

block_cipher = None

# Create array of package data entries
package_data_entries = [
    ('emoji', ['unicode_codes']),
    ('normalise', ['data']),
    ('faster_whisper', ['assets']),
    ('litellm', [
        'litellm_core_utils/tokenizers',
        'model_prices_and_context_window_backup.json'
    ]),
    ('en_core_web_sm', ['.']),
]

# Generate datas array from package data directories
package_datas = []
for pkg, paths in package_data_entries:
    try:
        pkg_dir = os.path.dirname(importlib.util.find_spec(pkg).origin)
        for rel_path in paths:
            src_path = os.path.join(pkg_dir, rel_path)
            # Handle individual files
            if os.path.isfile(src_path):
                package_datas.append(
                    (src_path, os.path.dirname(f'{pkg}/{rel_path}')),
                )
            # Handle directories
            elif os.path.isdir(src_path):
                package_datas.append(
                    (src_path, f'{pkg}/{rel_path}'),
                )
    except (ImportError, AttributeError):
        print(f"Warning: Package {pkg} not found, skipping")

# Add platform-specific binaries and TTS models
binaries = []
datas = []

# Add TTS models
tts_models_dir = os.path.join(project_root, 'resources/tts/models')
if os.path.exists(tts_models_dir):
    datas.append((tts_models_dir, 'resources/tts/models'))

# Add platform-specific binaries
system = platform.system()
arch = platform.machine().lower()

if system == "Windows":
    # Add Windows-specific binaries
    piper_bin_dir = os.path.join(project_root, 'resources/bin/windows')
    if os.path.exists(piper_bin_dir):
        binaries.append((piper_bin_dir, 'resources/bin/windows'))
elif system == "Darwin":  # macOS
    # Add macOS-specific binaries with architecture awareness
    if arch == "arm64":
        # ARM64 (Apple Silicon) binaries
        piper_bin_dir = os.path.join(project_root, 'resources/bin/macos/aarch64')
        if os.path.exists(piper_bin_dir):
            binaries.append((piper_bin_dir, 'resources/bin/macos/aarch64'))
        else:
            raise ValueError(f"Expected Piper bin dir {piper_bin_dir} not found")
    else:
        # Intel binaries
        piper_bin_dir = os.path.join(project_root, 'resources/bin/macos/x64')
        if os.path.exists(piper_bin_dir):
            binaries.append((piper_bin_dir, 'resources/bin/macos/x64'))
        else:
            raise ValueError(f"Expected Piper bin dir {piper_bin_dir} not found")
else:  # Linux
    # Add Linux-specific binaries
    piper_bin_dir = os.path.join(project_root, 'resources/bin/linux')
    if os.path.exists(piper_bin_dir):
        binaries.append((piper_bin_dir, 'resources/bin/linux'))

# Common data files for both executables
common_datas = [
    (os.path.join(project_root, 'ainara/framework'), 'ainara/framework'),
    (os.path.join(project_root, 'ainara/__init__.py'), 'ainara/__init__.py'),
    (os.path.join(project_root, 'ainara/templates'), 'ainara/templates'),
    (os.path.join(project_root, 'resources'), 'resources'),
    *datas,
    *package_datas
]

# Common hidden imports for both executables
common_imports = [
    # Core functionality
    'flask',
    'flask_cors',
    'requests',
    'aiohttp',
    'asgiref',
    'tiktoken_ext.openai_public',
    'tiktoken_ext',
    'yaml',
    'json',
    'numpy',
    'pyperclip',
    'newsapi_python',

    # LangChain related
    'langchain',
    'langchain.llms',
    'langchain.chains',
    'langchain.embeddings',
    'langchain.vectorstores',
    'langchain.text_splitter',
    'langchain.document_loaders',
    'langchain_community',
    'langchain_community.vectorstores',
    'langchain_community.embeddings',

    # Audio processing
    'faster_whisper',
    'sounddevice',
    'soundfile',
    'pygame',

    # Additional dependencies
    'telegram',
    'validators',
    'googleapiclient',
    'googleapiclient.discovery',
    'tiktoken',

    # ML/AI related
    'transformers',
    'sentence_transformers',
    'torch',
    'chromadb',
    'litellm',

    # Search engines
    'newsapi_python',
    'newspaper',
    'tweepy',

    # Text processing
    'nltk',
    'textblob',
    'emoji',
    'normalise', # Text normalization
    'spacy', # NLTK and Spacy for text processing
    'en_core_web_sm', # Default English model for Spacy

    # Framework modules
    'ainara.framework',
    'ainara.framework.llm',
    'ainara.framework.matcher',
    'ainara.framework.storage',
    'ainara.framework.documents',
    'ainara.framework.stt',
    'ainara.framework.stt.faster_whisper',
    'ainara.framework.stt.whisper',
    'ainara.framework.tts',
]

# Add all the transformers models to common imports
common_imports += collect_submodules('transformers.models')

# Orakle-specific data and imports
orakle_datas = [
    (os.path.join(project_root, 'ainara/orakle'), 'ainara/orakle'),
]

orakle_imports = [
    'ainara.orakle.skills',
    'ainara.orakle.skills.crypto',
    'ainara.orakle.skills.finance',
    'ainara.orakle.skills.messaging',
    'ainara.orakle.skills.search',
    'ainara.orakle.skills.sentiment',
    'ainara.orakle.skills.system',
    'ainara.orakle.skills.tools',
]

# PyBridge-specific data and imports
pybridge_datas = []

pybridge_imports = []

# Create a runtime hook to help with imports
with open(os.path.join(SPECPATH, 'runtime_hook.py'), 'w') as f:
    f.write("""
import os
import sys
import logging
import platform

# Set up logging to a file
# Use a writable location for logs
# --- Platform-specific log directory ---
home_dir = os.path.expanduser('~')
app_name = 'ainara'
log_dir = '' # Initialize log_dir

system = platform.system()
if system == "Windows":
    appdata = os.getenv('APPDATA')
    if appdata:
        log_dir = os.path.join(appdata, app_name, 'logs')
    else: # Fallback if APPDATA isn't set (unlikely)
        log_dir = os.path.join(home_dir, '.' + app_name, 'logs')
elif system == "Darwin": # macOS
    log_dir = os.path.join(home_dir, 'Library', 'Application Support', app_name, 'logs')
else: # Linux and other Unix-like
    log_dir = os.path.join(home_dir, '.' + app_name, 'logs')

# Ensure the directory exists
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
""")

# Analysis for Orakle
a_orakle = Analysis(
    [os.path.join(project_root, 'ainara/orakle', 'server.py')],
    pathex=[project_root],
    binaries=binaries,
    datas=[*common_datas, *orakle_datas],
    hiddenimports=[*common_imports, *orakle_imports],
    hookspath=[os.path.join(project_root, 'scripts', 'pyinstaller', 'hooks')],
    hooksconfig={},
    runtime_hooks=[os.path.join(SPECPATH, 'runtime_hook.py')],
    #module_collection_mode={
    #    'transformers': 'py',
    #},
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=True,
)

# Analysis for PyBridge
a_pybridge = Analysis(
    [os.path.join(project_root, 'ainara/framework', 'pybridge.py')],
    pathex=[project_root],
    binaries=binaries,
    datas=[*common_datas, *pybridge_datas],
    hiddenimports=[*common_imports, *pybridge_imports],
    hookspath=[os.path.join(project_root, 'scripts', 'pyinstaller', 'hooks')],
    hooksconfig={},
    runtime_hooks=[os.path.join(SPECPATH, 'runtime_hook.py')],
    #module_collection_mode={
    #    'transformers': 'py',
    #},
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=True,
)

# MERGE statement to combine the analyses
MERGE(
    (a_orakle, 'orakle', 'orakle'),
    (a_pybridge, 'pybridge', 'pybridge')
)

# PYZ for Orakle
pyz_orakle = PYZ(a_orakle.pure, a_orakle.zipped_data, cipher=block_cipher)

# PYZ for PyBridge
pyz_pybridge = PYZ(a_pybridge.pure, a_pybridge.zipped_data, cipher=block_cipher)

# EXE for Orakle
exe_orakle = EXE(
    pyz_orakle,
    a_orakle.scripts,
    [],
    exclude_binaries=True,
    name='orakle',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

# EXE for PyBridge
exe_pybridge = EXE(
    pyz_pybridge,
    a_pybridge.scripts,
    [],
    exclude_binaries=True,
    name='pybridge',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

# COLLECT to create the final bundle with both executables
coll = COLLECT(
    exe_orakle,
    a_orakle.binaries,
    a_orakle.zipfiles,
    a_orakle.datas,
    exe_pybridge,
    a_pybridge.binaries,
    a_pybridge.zipfiles,
    a_pybridge.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='servers',
)
