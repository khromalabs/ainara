# -*- mode: python ; coding: utf-8 -*-
import os
import importlib
import platform

# Get the project root directory (2 levels up from this spec file)
project_root = os.path.abspath(os.path.join(os.path.dirname(SPECPATH), '..', '..'))

block_cipher = None

# # Create array of package data directories
# package_data_dirs = [
#     ('emoji', 'unicode_codes'),
#     ('normalise', 'data'),
#     ('faster_whisper', 'assets'),
#     ('litellm', 'litellm_core_utils/tokenizers'),
#     ('litellm', 'model_prices_and_context_window_backup.json'),
# ]
#
# # Generate datas array from package data directories
# package_datas = [
#     (os.path.join(os.path.dirname(importlib.util.find_spec(pkg).origin), subdir),
#      f'{pkg}/{subdir}')
#     for pkg, subdir in package_data_dirs
# ]

# New format
package_data_entries = [
    ('emoji', ['unicode_codes']),
    ('normalise', ['data']),
    ('faster_whisper', ['assets']),
    ('litellm', [
        'litellm_core_utils/tokenizers',
        'model_prices_and_context_window_backup.json'
    ]),
]

# Modify the package data collection logic
package_datas = []
for pkg, paths in package_data_entries:
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

a = Analysis(
    [os.path.join(project_root, 'ainara', 'framework', 'pybridge.py')],  # Main entry point for PyBridge
    pathex=[project_root],
    binaries=binaries,
    datas=[
        (os.path.join(project_root, 'ainara/templates'), 'ainara/templates'),
        (os.path.join(project_root, 'ainara/static'), 'ainara/static'),
        (os.path.join(project_root, 'ainara/resources'), 'ainara/resources'),
        *datas,
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
