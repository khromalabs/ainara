# -*- mode: python ; coding: utf-8 -*-
import os
import importlib
import platform
import sys
from PyInstaller.utils.hooks import (
    collect_submodules,
    collect_data_files,
    collect_dynamic_libs,
)

# SPECPATH is injected by PyInstaller and points at scripts/pyinstaller/.
# Reuse it to import the shared exclusion list (scripts/pyinstaller/
# _shadowed_libs.py), so the strip here and the _build.py verifier
# read from a single source.
sys.path.insert(0, SPECPATH)
from _shadowed_libs import SHADOWED_RUNTIME_LIBS

# Fast track to test a server (dist output):
#   1) scripts/_obfuscate.py    (host, licensed PyArmor)
#   2) POLARIS_EDITION=supporters POLARIS_TARGET=orakle \
#          pyinstaller --distpath dist --workpath build/pyi scripts/pyinstaller/servers.spec
# or simply:  scripts/_build.py -e supporters -t orakle

# Get the project root directory (use current working directory as project root)
project_root = os.path.abspath(os.getcwd())

# Sanity check to ensure project_root is correct
if not os.path.exists(os.path.join(project_root, 'ainara')):
    raise ValueError(f"Calculated project_root {project_root} does not contain 'ainara' directory. Ensure the build is run from the project root.")

nexus_obfuscated_root = os.path.join(project_root, 'build', 'nexus_obfuscated')
supporters_obfuscated_root = os.path.join(project_root, 'build', 'supporters_obfuscated')
supporters_compiled_root = os.path.join(project_root, 'build', 'supporters_compiled')
supporters_compiled = os.path.join(supporters_compiled_root, 'supporters')
ataria_compiled = os.path.join(
    project_root, 'build', 'ataria_compiled', 'ainara', 'nexus', 'khromalabs', 'ataria'
)

# Optional single-server build mode.
# Set POLARIS_TARGET=orakle|pybridge|bureau|sentinel to build only that server.
BUILD_TARGET = os.environ.get("POLARIS_TARGET", "all").strip().lower()
if BUILD_TARGET not in ("all", "orakle", "pybridge", "bureau", "sentinel"):
    raise SystemExit(f"Unknown POLARIS_TARGET: {BUILD_TARGET!r}")
print(f"[servers.spec] Build target(s): {BUILD_TARGET}")

# --- Edition & pre-obfuscated artifacts ----------------------------------
# Obfuscation (staging, license-guard injection, PyArmor) runs on the HOST
# via scripts/_obfuscate.py: the licensed PyArmor install and the build
# secret never enter the build container. This spec only consumes that
# output, so it can run inside the manylinux_2_28 container that pins our
# glibc floor.
EDITION = os.environ.get("POLARIS_EDITION", "public").strip().lower()
if EDITION not in ("public", "supporters"):
    raise SystemExit(f"Unknown POLARIS_EDITION: {EDITION!r}")
SUPPORTERS = EDITION == "supporters"
print(f"[servers.spec] Building '{EDITION}' edition")

_required_trees = [
    os.path.join(supporters_compiled_root, 'ainara', 'nexus'),
    ataria_compiled,
]
if SUPPORTERS:
    _required_trees.append(supporters_compiled)
for _tree in _required_trees:
    if not os.path.isdir(_tree):
        raise FileNotFoundError(
            f"{_tree} not found — run scripts/_obfuscate.py first "
            f"(scripts/_build.py runs it automatically)."
        )

block_cipher = None

# Create array of package data entries
package_data_entries = [
    ('emoji', ['unicode_codes']),
    # ('normalise', ['data']),
    ('faster_whisper', ['assets']),
    # ('litellm', [
    #     'litellm_core_utils/tokenizers',
    #     'model_prices_and_context_window_backup.json'
    #     'containers/endpoints.json'
    # ]),
    ('en_core_web_sm', ['.']),
    ('openwakeword', ['.']),
    ('trafilatura', ['.'])
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
    'chroma-hnswlib',
    # 'numpy',
    'litellm',
    'kokoro_onnx',
    'language_tags',
    'espeakng_loader',
    'pyarmor_runtime',
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

# Add STT wakeword models
wakeword_models_dir = os.path.join(project_root, 'resources/stt/wakeword')
if os.path.exists(wakeword_models_dir):
    datas.append((wakeword_models_dir, 'resources/stt/wakeword'))

system = platform.system()

# Piper binaries are no longer bundled (the app uses Kokoro); only the
# espeakng fix below remains platform-specific.
if system == "Linux":
    # Fix for kokoro-onnx/espeakng_loader on Linux: ensure libespeak-ng.so is bundled
    try:
        spec = importlib.util.find_spec('espeakng_loader')
        if spec and spec.origin:
            pkg_dir = os.path.dirname(spec.origin)
            so_path = os.path.join(pkg_dir, 'libespeak-ng.so')
            if os.path.exists(so_path):
                datas.append((so_path, 'espeakng_loader'))
    except Exception as e:
        print(f"Warning: Could not add libespeak-ng.so: {e}")

# Define platform-specific excludes for packages that should not be bundled
# on certain operating systems, even if they are present in the environment.
platform_excludes = []
# Never let modulegraph collect the PLAIN supporters source (it lives at
# <root>/supporters with the __BUILD_SECRET__ placeholder). Supporters
# ships the obfuscated tree via datas; public ships nothing.
platform_excludes.append('supporters')
if system == "Windows":
    platform_excludes.append('uvloop')
    platform_excludes.append('triton')


# Common data files for both executables
common_datas = [
    (os.path.join(project_root, 'ainara/framework'), 'ainara/framework'),
    (os.path.join(project_root, 'ainara/__init__.py'), 'ainara/__init__.py'),
    (os.path.join(project_root, 'ainara/templates'), 'ainara/templates'),
    (os.path.join(project_root, 'resources'), 'resources'),
    (os.path.join(ataria_compiled, 'nexus.json'), 'ainara/nexus/khromalabs/ataria'),
    (os.path.join(ataria_compiled, 'providers_registry.json'), 'ainara/nexus/khromalabs/ataria'),
    (os.path.join(ataria_compiled, 'skills_metadata.json'), 'ainara/nexus/khromalabs/ataria'),
    (os.path.join(ataria_compiled, 'site'), 'ainara/nexus/khromalabs/ataria/site'),
    *datas,
    *package_datas,
    *datas_from_hooks
]

# The obfuscated trees contain a per-build runtime like pyarmor_runtime_*
# PyInstaller must ship that directory at the top level of _internal so 
#`from pyarmor_runtime_XXXX import ...` can resolve.
for _root in (nexus_obfuscated_root, supporters_obfuscated_root):
    if not os.path.isdir(_root):
        continue
    for _entry in os.listdir(_root):
        if _entry.startswith("pyarmor_runtime") and os.path.isdir(os.path.join(_root, _entry)):
            common_datas.append((os.path.join(_root, _entry), _entry))

# Obfuscated nexus tree ships to ALL servers (validated above). In the
# public edition the tree simply lacks the supporters domains.
common_datas.append(
    (os.path.join(supporters_compiled_root, 'ainara', 'nexus'), 'ainara/nexus')
)

if SUPPORTERS:
    if not os.path.isdir(supporters_compiled):
        raise FileNotFoundError("Supporters build requires the obfuscated supporters package")
    common_datas.append((supporters_compiled, 'supporters'))

# Common hidden imports for both executables
common_imports = [
    # Core functionality
    'flask',
    'flask_cors',
    'aiohttp',
    'asgiref',
    'tiktoken_ext.openai_public',
    'tiktoken_ext',
    'PyYAML', # The package name for 'yaml'
    'json',
    # 'numpy',
    'pyperclip',
    'fastembed',

    # LLM Backends
    'litellm',
    'ollama',

    # Audio processing
    'av',
    'faster_whisper',
    'sounddevice',
    'soundfile',
    'pygame',
    'kokoro_onnx',
    'misaki',
    'language_tags',
    'espeakng_loader',
    'openwakeword'

    # ML/AI related
    # 'transformers',
    'tokenizers',
    # ChromaDB and its full set of dependencies.
    # Even for local/in-process usage, it can dynamically import many of these.
    'chromadb',
    'hnswlib',      # Import name for chroma-hnswlib
    # The following are hidden imports for ChromaDB needed for PyInstaller
    # due to its dynamic loading. This prevents a series of ModuleNotFoundErrors.
    # See: https://github.com/chroma-core/chroma/issues/4092
    'chromadb.telemetry.product.posthog',
    'chromadb.api.segment',
    'chromadb.db.impl.sqlite',
    'chromadb.segment.impl.manager.local',
    'chromadb.segment.impl.metadata.sqlite',
    'chromadb.execution.executor.local',
    'chromadb.quota.simple_quota_enforcer',
    'analytics',  # A dependency of posthog, sometimes missed by PyInstaller
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
    'pycountry',
    'tree_sitter',
    'tree_sitter_javascript',
    'tree_sitter_python',
    'pyarmor_runtime',

    # Dependencies for MCP
    'mcp',

    # Search engines
    'newsapi_python',
    'tweepy',
    'trafilatura',

    # Text processing
    'lxml_html_clean',
    'nltk',
    'textblob',
    'emoji',
    # 'normalise', # Text normalization
    'spacy', # NLTK and Spacy for text processing
    'en_core_web_sm', # Default English model for Spacy

    # System utilities
    'psutil',
    'setproctitle',
    'apscheduler',
    'keyring',

    # Communications
    'aioimaplib',
    'aiosmtplib',
    # 'telethon',

    # Additional dependencies
    'validators',
    'googleapiclient',
    'googleapiclient.discovery',
    'tiktoken',
    'ccxt',
    'ccxt.async_support',
    'sympy',

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
# common_imports += collect_submodules('transformers')
common_imports += collect_submodules('chromadb')

if SUPPORTERS:
    # The supporters.auth_core module is shipped as data/obfuscated and is
    # never analyzed by PyInstaller, so its imports are not discovered.
    # Force-include the Solana stack (including the native solders binary).
    common_imports += collect_submodules('solana')
    common_imports += collect_submodules('solders')
    binaries += collect_dynamic_libs('solana')
    binaries += collect_dynamic_libs('solders')
# # Add all opentelemetry modules, a complex dependency of chromadb
# common_imports += collect_submodules('opentelemetry')
# collect_submodules('sentence_transformers')
# common_imports += collect_submodules('numpy')
# common_imports += collect_submodules('litellm')

# Orakle-specific data and imports
orakle_datas = [
    (os.path.join(project_root, 'ainara/orakle'), 'ainara/orakle'),
]

orakle_imports = [
    'ainara.orakle.skills',
    'ainara.orakle.skills.finance',
    'ainara.orakle.skills.html',
    'ainara.orakle.skills.inference',
    'ainara.orakle.skills.messaging',
    'ainara.orakle.skills.search',
    'ainara.orakle.skills.system',
    'ainara.orakle.skills.tools',
    # 'ainara.orakle.skills.sentiment',
    # 'ainara.orakle.skills.crypto',
]

# PyBridge-specific data and imports
pybridge_datas = []
pybridge_imports = []

# Bureau-specific data and imports
bureau_datas = []
bureau_imports = []

# Sentinel data and imports
sentinel_datas = []
sentinel_imports = []

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

## --- Set up a reliable cache directory for transformers ---
## Priority: TRANSFORMERS_CACHE > AINARA_CACHE > Ainara platform default.
## If TRANSFORMERS_CACHE is already set, we respect it and do nothing.
#if 'TRANSFORMERS_CACHE' not in os.environ:
#    cache_dir_str = os.environ.get("AINARA_CACHE")
#    if cache_dir_str:
#        cache_dir = Path(os.path.expanduser(cache_dir_str))
#    else:
#        cache_dir = config.get_default_cache_dir()
#
#    transformers_cache_dir = cache_dir / 'transformers'
#    os.makedirs(transformers_cache_dir, exist_ok=True)
#
#    # Set the environment variable for huggingface libraries
#    os.environ['TRANSFORMERS_CACHE'] = str(transformers_cache_dir)
#    logger.info(f"Set TRANSFORMERS_CACHE to: {os.environ['TRANSFORMERS_CACHE']}")
#else:
#    logger.info(f"TRANSFORMERS_CACHE already set to: {os.environ['TRANSFORMERS_CACHE']}. Hook will not override it.")

logger.info("--- PyInstaller Runtime Hook End ---")
""")

_target_configs = {
    "orakle": {
        "entry": os.path.join(project_root, 'ainara/orakle', 'server.py'),
        "datas": [*common_datas, *orakle_datas],
        "imports": [*common_imports, *orakle_imports],
    },
    "pybridge": {
        "entry": os.path.join(project_root, 'ainara/framework', 'pybridge.py'),
        "datas": [*common_datas, *pybridge_datas],
        "imports": [*common_imports, *pybridge_imports],
    },
    "bureau": {
        "entry": os.path.join(project_root, 'ainara/bureau', 'server.py'),
        "datas": [*common_datas, *bureau_datas],
        "imports": [*common_imports, *bureau_imports],
    },
    "sentinel": {
        "entry": os.path.join(project_root, 'scripts', 'scheduler.py'),
        "datas": [*common_datas, *sentinel_datas],
        "imports": [*common_imports, *sentinel_imports],
    },
}

build_targets = ["orakle", "pybridge", "bureau", "sentinel"] if BUILD_TARGET == "all" else [BUILD_TARGET]

# First pass: create all Analysis objects so MERGE can run before PYZ.
analyses = {}
for target in build_targets:
    cfg = _target_configs[target]
    analyses[target] = Analysis(
        [cfg["entry"]],
        pathex=[project_root],
        binaries=binaries,
        datas=cfg["datas"],
        hiddenimports=cfg["imports"],
        hookspath=[os.path.join(project_root, 'scripts', 'pyinstaller', 'hooks')],
        hooksconfig={},
        runtime_hooks=[os.path.join(SPECPATH, 'runtime_hook.py')],
        excludes=platform_excludes,
        win_no_prefer_redirects=False,
        win_private_assemblies=False,
        cipher=block_cipher,
        noarchive=True,
    )

# Strip toolchain runtimes on Linux before MERGE propagates the TOC.
# They would shadow the host's (usually newer) libstdc++/libgcc_s and
# break system libs the app pulls in at runtime (libjack, libportaudio).
if system == "Linux":
    for target in build_targets:
        analyses[target].binaries = [
            b for b in analyses[target].binaries
            if os.path.basename(b[0]) not in SHADOWED_RUNTIME_LIBS
        ]

if BUILD_TARGET == "all":
    MERGE(
        (analyses["orakle"], "orakle", "orakle"),
        (analyses["pybridge"], "pybridge", "pybridge"),
        (analyses["bureau"], "bureau", "bureau"),
        (analyses["sentinel"], "sentinel", "sentinel"),
    )

# Second pass: PYZ/EXE after merge.
pyzs = {}
exes = {}
for target in build_targets:
    pyzs[target] = PYZ(analyses[target].pure, analyses[target].zipped_data, cipher=block_cipher)
    exes[target] = EXE(
        pyzs[target],
        analyses[target].scripts,
        [],
        exclude_binaries=True,
        name=target,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=True,
    )

# Final collect: one combined bundle for "all", otherwise a single-server bundle.
if BUILD_TARGET == "all":
    coll = COLLECT(
        exes["orakle"], analyses["orakle"].binaries, analyses["orakle"].zipfiles, analyses["orakle"].datas,
        exes["pybridge"], analyses["pybridge"].binaries, analyses["pybridge"].zipfiles, analyses["pybridge"].datas,
        exes["bureau"], analyses["bureau"].binaries, analyses["bureau"].zipfiles, analyses["bureau"].datas,
        exes["sentinel"], analyses["sentinel"].binaries, analyses["sentinel"].zipfiles, analyses["sentinel"].datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name='servers',
    )
else:
    target = BUILD_TARGET
    coll = COLLECT(
        exes[target],
        analyses[target].binaries,
        analyses[target].zipfiles,
        analyses[target].datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name=target,
    )
