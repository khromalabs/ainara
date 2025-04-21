# -*- mode: python ; coding: utf-8 -*-
import os
import sys
import importlib
import platform

# Get the project root directory (2 levels up from this spec file)
project_root = os.path.abspath(os.path.join(os.path.dirname(SPECPATH), '..', '..'))

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
if system == "Windows":
    # Add Windows-specific binaries
    piper_bin_dir = os.path.join(project_root, 'resources/bin/windows')
    if os.path.exists(piper_bin_dir):
        binaries.append((piper_bin_dir, 'resources/bin/windows'))
elif system == "Darwin":  # macOS
    # Add macOS-specific binaries
    piper_bin_dir = os.path.join(project_root, 'resources/bin/macos')
    if os.path.exists(piper_bin_dir):
        binaries.append((piper_bin_dir, 'resources/bin/macos'))
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
    (os.path.join(project_root, 'ainara/resources'), 'ainara/resources'),
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
    'normalise',

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
""")

# Analysis for Orakle
a_orakle = Analysis(
    [os.path.join(project_root, 'ainara/orakle', 'server.py')],
    pathex=[project_root],
    binaries=binaries,
    datas=[*common_datas, *orakle_datas],
    hiddenimports=[*common_imports, *orakle_imports],
    hookspath=[os.path.join(project_root, 'ainara/scripts', 'pyinstaller', 'hooks')],
    hooksconfig={},
    runtime_hooks=[os.path.join(SPECPATH, 'runtime_hook.py')],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Analysis for PyBridge
a_pybridge = Analysis(
    [os.path.join(project_root, 'ainara/framework', 'pybridge.py')],
    pathex=[project_root],
    binaries=binaries,
    datas=[*common_datas, *pybridge_datas],
    hiddenimports=[*common_imports, *pybridge_imports],
    hookspath=[os.path.join(project_root, 'ainara/scripts', 'pyinstaller', 'hooks')],
    hooksconfig={},
    runtime_hooks=[os.path.join(SPECPATH, 'runtime_hook.py')],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
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
    strip=True,
    upx=False,
    console=False,
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
    strip=True,
    upx=False,
    console=False,
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
    strip=True,
    upx=False,
    upx_exclude=[],
    name='servers',
)
