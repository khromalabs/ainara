# -*- mode: python ; coding: utf-8 -*-
import os
import sys
import importlib
import platform
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

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
    ('newspaper', ['.']),
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

# Collect data files for complex packages using PyInstaller's utility.
# This is more robust than manually specifying paths.
datas_from_hooks = []
packages_to_collect_data_from = [
    'chromadb',
    'onnxruntime',
    'tokenizers',
    'chroma-hnswlib'
]

# Define rules for platform-specific data files that need special handling.
# This is more modular than if/else blocks scattered in the script.
# - collection_name: The name used in packages_to_collect_data_from.
# - pkg_name: The actual importable package name to find the path.
# - dest_path: The target path and filename inside the bundle.
# - os: A list of platforms this rule applies to (e.g., ['Windows', 'Darwin']). Use None for all.
platform_specific_data_rules = [
    {
        'collection_name': 'chroma-hnswlib',
        'pkg_name': 'hnswlib',
        'dest_path': os.path.join('hnswlib', 'hnswlib.pyd'),
        'os': ['Windows'] # Note: For macOS, you'd likely need a separate rule with a '.so' dest_path.
    },
]

# Process the platform-specific rules
for rule in platform_specific_data_rules:
    # A rule applies if its 'os' key is not set (None) or if the current platform is in its 'os' list.
    applies = rule.get('os') is None or platform.system() in rule.get('os', [])
    if applies and rule['collection_name'] in packages_to_collect_data_from:
        try:
            spec = importlib.util.find_spec(rule['pkg_name'])
            if spec and spec.origin:
                datas_from_hooks.append((spec.origin, rule['dest_path']))
                # Remove from the standard collection list to avoid duplication
                packages_to_collect_data_from.remove(rule['collection_name'])
        except (ImportError, AttributeError):
            print(f"Warning: Could not apply rule for {rule['pkg_name']}, skipping.")

# Collect data files for the remaining packages using PyInstaller's utility.
for pkg_name in packages_to_collect_data_from:
    try:
        datas_from_hooks.extend(collect_data_files(pkg_name))
    except Exception as e:
        print(f"Warning: Could not collect data files for {pkg_name}: {e}")

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

# Define platform-specific excludes for packages that should not be bundled
# on certain operating systems, even if they are present in the environment.
platform_excludes = []
if system == "Windows":
    platform_excludes.append('uvloop')
    platform_excludes.append('triton')

# Common data files for both executables
common_datas = [
    (os.path.join(project_root, 'ainara/framework'), 'ainara/framework'),
    (os.path.join(project_root, 'ainara/__init__.py'), 'ainara/__init__.py'),
    (os.path.join(project_root, 'ainara/templates'), 'ainara/templates'),
    (os.path.join(project_root, 'resources'), 'resources'),
    *datas,
    *package_datas,
    *datas_from_hooks
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
    'PyYAML', # The package name for 'yaml'
    'json',
    'numpy',
    'pyperclip',
    'feedparser',
    'tldextract',

    # LLM Backends
    'litellm',
    'ollama',

    # Audio processing
    'av',
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
    'tokenizers',
    'sentence_transformers',
    'torch',
    # ChromaDB and its full set of dependencies.
    # Even for local/in-process usage, it can dynamically import many of these.
    'chromadb',
    'hnswlib',      # Import name for chroma-hnswlib
    'pydantic',
    'tenacity',
    'overrides',
    'onnxruntime',
    'onnxruntime.capi.onnxruntime_internal',
    'fastapi',
    'uvicorn',
    'posthog',
    'pypika',       # Import name for PyPika
    'tqdm',
    'importlib_resources',
    'grpcio',
    'bcrypt',
    'kubernetes',
    'mmh3',
    'orjson',
    'typer',
    'rich',
    'httpx',

    # Dependencies for MCP
    'mcp',

    # Search engines
    'newsapi_python',
    'newspaper3k', # The package name for 'newspaper'
    'tweepy',

    # Text processing
    'lxml_html_clean',
    'nltk',
    'textblob',
    'emoji',
    'normalise', # Text normalization
    'spacy', # NLTK and Spacy for text processing
    'en_core_web_sm', # Default English model for Spacy

    # Framework modules
    'ainara.framework',
    # System utilities
    'psutil',
    'setproctitle',

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
common_imports += collect_submodules('transformers')
common_imports += collect_submodules('chromadb')
# Add all opentelemetry modules, a complex dependency of chromadb
common_imports += collect_submodules('opentelemetry')
collect_submodules('sentence_transformers')

# Orakle-specific data and imports
orakle_datas = [
    (os.path.join(project_root, 'ainara/orakle'), 'ainara/orakle'),
]

orakle_imports = [
    'ainara.orakle.skills',
    'ainara.orakle.skills.crypto',
    'ainara.orakle.skills.finance',
    'ainara.orakle.skills.html',
    'ainara.orakle.skills.inference',
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
from pathlib import Path

# It's crucial to add the bundled 'ainara' package to the path
# so we can import our own utilities.
# sys._MEIPASS is the root of the bundled app.
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    sys.path.insert(0, sys._MEIPASS)

from ainara.framework.platform_utils import get_default_log_dir, get_default_cache_dir

# --- Set up logging to a file ---
# Use a writable location for logs, respecting environment variables first.
log_dir_str = os.environ.get("AINARA_LOGS")
if log_dir_str:
    log_dir = Path(os.path.expanduser(log_dir_str))
else:
    log_dir = get_default_log_dir()

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

# --- Set up a reliable cache directory for transformers ---
# Priority: TRANSFORMERS_CACHE > AINARA_CACHE > Ainara platform default.
# If TRANSFORMERS_CACHE is already set, we respect it and do nothing.
if 'TRANSFORMERS_CACHE' not in os.environ:
    cache_dir_str = os.environ.get("AINARA_CACHE")
    if cache_dir_str:
        cache_dir = Path(os.path.expanduser(cache_dir_str))
    else:
        cache_dir = get_default_cache_dir()

    transformers_cache_dir = cache_dir / 'transformers'
    os.makedirs(transformers_cache_dir, exist_ok=True)

    # Set the environment variable for huggingface libraries
    os.environ['TRANSFORMERS_CACHE'] = str(transformers_cache_dir)
    logger.info(f"Set TRANSFORMERS_CACHE to: {os.environ['TRANSFORMERS_CACHE']}")
else:
    logger.info(f"TRANSFORMERS_CACHE already set to: {os.environ['TRANSFORMERS_CACHE']}. Hook will not override it.")

logger.info("--- PyInstaller Runtime Hook End ---")
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
    excludes=platform_excludes,
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
    excludes=platform_excludes,
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
