# -*- mode: python ; coding: utf-8 -*-
import os
import importlib

# Get the project root directory (2 levels up from this spec file)
project_root = os.path.abspath(os.path.join(os.path.dirname(SPECPATH), '..', '..'))

block_cipher = None

# Create array of package data directories
package_data_dirs = [
    ('emoji', 'unicode_codes'),
    ('normalise', 'data'),
    ('faster_whisper', 'assets'),
    ('litellm', 'litellm_core_utils/tokenizers'),
]

# Generate datas array from package data directories
package_datas = [
    (os.path.join(os.path.dirname(importlib.util.find_spec(pkg).origin), subdir),
     f'{pkg}/{subdir}')
    for pkg, subdir in package_data_dirs
]

a = Analysis(
    [os.path.join(project_root, 'ainara', 'framework', 'pybridge.py')],  # Main entry point for PyBridge
    pathex=[project_root],
    binaries=[],
    datas=[
        (os.path.join(project_root, 'ainara/templates'), 'ainara/templates'),
        (os.path.join(project_root, 'ainara/static'), 'ainara/static'),
        (os.path.join(project_root, 'ainara/config'), 'ainara/config'),
        *package_datas
    ],
    hiddenimports=[
        # Core functionality
        'flask',
        'flask_cors',
        'requests',
        'aiohttp',
        'asgiref',
        # Add these hidden imports for tiktoken
        'tiktoken_ext.openai_public',
        'tiktoken_ext',
        'flask_cors',
        'requests',
        'yaml',
        'json',
        'numpy',

        # Audio processing
        'faster_whisper',
        'sounddevice',
        'soundfile',
        'pygame',

        # LLM related
        'litellm',

        # Text processing
        'nltk',
        'emoji',

        # Framework modules
        'framework.llm',
        'framework.matcher',
        'framework.storage',
        'framework.documents',

        # Framework modules
        'framework.stt',
        'framework.stt.faster_whisper',
        'framework.stt.whisper',
        'framework.tts',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='pybridge',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='pybridge',
)
