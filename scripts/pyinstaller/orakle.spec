# -*- mode: python ; coding: utf-8 -*-
import os
import sys
import tiktoken
import importlib

# Get the project root directory (2 levels up from this spec file)
project_root = os.path.abspath(os.path.join(os.path.dirname(SPECPATH), '..', '..'))

block_cipher = None

# Create array of package data directories
package_data_dirs = [
    ('litellm', 'litellm_core_utils/tokenizers'),
]

# Generate datas array from package data directories
package_datas = [
    (os.path.join(os.path.dirname(importlib.util.find_spec(pkg).origin), subdir),
     f'{pkg}/{subdir}')
    for pkg, subdir in package_data_dirs
]

a = Analysis(
    [os.path.join(project_root, 'ainara/orakle', 'server.py')],  # Main entry point for Orakle
    pathex=[project_root],
    binaries=[],
    datas=[
        (os.path.join(project_root, 'ainara/framework'), 'ainara/framework'),
        (os.path.join(project_root, 'ainara/orakle'), 'ainara/orakle'),
        (os.path.join(project_root, 'ainara/templates'), 'ainara/templates'),
        (os.path.join(project_root, 'ainara/static'), 'ainara/static'),
        (os.path.join(project_root, 'ainara/__init__.py'), 'ainara/__init__.py'),
        *package_datas
    ],
    hiddenimports=[
        # Core functionality
        'flask',
        # Add these hidden imports for tiktoken
        'tiktoken_ext.openai_public',
        'tiktoken_ext',
        'flask_cors',
        'requests',
        'yaml',
        'json',
        'numpy',
        'pyperclip',

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

        # Additional dependencies for skills
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
        'framework.llm',
        'framework.matcher',
        'framework.storage',
        'framework.documents',

        # Add explicit imports for all skill modules
        'orakle.skills',
        'orakle.skills.crypto',
        'orakle.skills.finance',
        'orakle.skills.messaging',
        'orakle.skills.search',
        'orakle.skills.sentiment',
        'orakle.skills.system',
        'orakle.skills.tools',
    ],
    hookspath=[os.path.join(project_root, 'ainara/scripts', 'pyinstaller', 'hooks')],
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
    name='orakle',
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
    name='orakle',
)
