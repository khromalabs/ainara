# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
#
# This file is dual-licensed under:
# 1. GNU Lesser General Public License v3.0 (LGPL-3.0)
#    (See the included LICENSE_LGPL3.txt file or look into
#    <https://www.gnu.org/licenses/lgpl-3.0.html> for details)
# 2. Commercial license
#    (Contact: rgomez@khromalabs.org for licensing options)
#
# You may use, distribute and modify this code under the terms of either license.
# This notice must be preserved in all copies or substantial portions of the code.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.

"""Nexus app helpers: payload resolution and namespace registration.

Stdlib-only by design: this module is imported by the runtime
(capabilities/nexus.py), the config manager, and by OUT-OF-PROCESS dev
tooling (each app repo's generate_registries.py / docs_hook.py), which must not
pull Flask or other framework dependencies.

Layout contract (Stage 3a):

- An **app repo** (dev checkout, git submodule) carries the shippable
  bundle in a ``payload/`` subdirectory; everything else in the repo is
  dev material and never ships.
- An **installed app** (extracted pack artifact) has the bundle contents
  at its top level (artifact root == bundle root).
- The Python namespace ``ainara.nexus.<vendor>.<bundle>`` is DERIVED from
  the manifest (``provider`` + ``name``), never from on-disk nesting: the
  runtime registers the payload directory as that package via
  :func:`register_bundle_namespace`.
"""

import importlib
import importlib.util
import json
import logging
import sys
import types
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

BUNDLE_PAYLOAD_DIR = "payload"
BUNDLE_MANIFEST = "nexus.json"


def read_manifest(manifest_path) -> Optional[dict]:
    """Parse a nexus.json manifest; return its 'manifest' object or None."""
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"Cannot read Nexus manifest {manifest_path}: {e}")
        return None
    manifest = data.get("manifest")
    if not isinstance(manifest, dict):
        logger.warning(f"Nexus manifest {manifest_path} has no 'manifest' object")
        return None
    return manifest


def resolve_app_payload(root) -> Optional[Tuple[str, str, Path]]:
    """Resolve an app root to ``(vendor, bundle, payload_dir)``.

    Accepted shapes (first match wins):

    1. Dev repo:  ``<root>/payload/nexus.json``  -> bundle is ``payload/``.
    2. Installed: ``<root>/nexus.json``          -> root IS the bundle
       (the installer extracts the artifact, whose root == bundle root).

    Returns None when neither shape matches or the manifest lacks
    'provider'/'name' — identity is manifest-derived, never
    directory-derived, so a vendor-less manifest is unusable.
    """
    root = Path(root)
    payload = root / BUNDLE_PAYLOAD_DIR
    manifest_path = payload / BUNDLE_MANIFEST
    if manifest_path.is_file():
        payload_dir = payload
    else:
        manifest_path = root / BUNDLE_MANIFEST
        if not manifest_path.is_file():
            return None
        payload_dir = root
    manifest = read_manifest(manifest_path)
    if not manifest:
        return None
    vendor = manifest.get("provider")
    bundle = manifest.get("name")
    if not vendor or not bundle:
        logger.warning(
            f"Nexus manifest {manifest_path} lacks 'provider'/'name' — skipping"
        )
        return None
    return str(vendor), str(bundle), payload_dir


def register_bundle_namespace(payload_dir, vendor: str, bundle: str) -> bool:
    """Register ``payload_dir`` as the package ``ainara.nexus.<vendor>.<bundle>``.

    App-shaped roots have no physical ``ainara/nexus/<vendor>/<bundle>``
    tree on disk, so skill imports (``from ainara.nexus.<vendor>.<bundle>.
    crypto... import ...``) only resolve after this registration. The
    intermediate ``ainara.nexus`` and ``ainara.nexus.<vendor>`` namespace
    packages are created on demand as pure in-memory namespaces.

    Idempotent and first-wins: if the module name is already registered
    (e.g. by a higher-precedence root), the existing registration is kept
    and False is returned. Callers must therefore resolve bundle ownership
    (first-wins dedup) BEFORE calling this.

    Raises on failure so callers never proceed with half-registered
    bundles (skill imports would fail noisily anyway).
    """
    payload_dir = Path(payload_dir)
    name = f"ainara.nexus.{vendor}.{bundle}"
    if name in sys.modules:
        return False

    # Ensure the host 'ainara' package is importable (runtime, frozen build,
    # or a sys.path entry provided by out-of-process dev tooling).
    importlib.import_module("ainara")

    # Build/look up the namespace chain.
    parent = sys.modules["ainara"]
    for part in ("nexus", vendor):
        modname = f"{parent.__name__}.{part}"
        if modname in sys.modules:
            parent = sys.modules[modname]
            continue
        ns = types.ModuleType(modname)
        ns.__path__ = []
        ns.__package__ = modname
        sys.modules[modname] = ns
        setattr(parent, part, ns)
        parent = ns

    init_py = payload_dir / "__init__.py"
    if init_py.is_file():
        spec = importlib.util.spec_from_file_location(
            name, str(init_py), submodule_search_locations=[str(payload_dir)]
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception:
            del sys.modules[name]
            raise
    else:
        # Bundle without a bundle-level __init__.py: register as a pure
        # namespace package pointing at the payload.
        mod = types.ModuleType(name)
        mod.__path__ = [str(payload_dir)]
        mod.__package__ = name
        sys.modules[name] = mod
    setattr(parent, bundle, mod)

    importlib.invalidate_caches()
    logger.info(
        f"Registered Nexus bundle namespace '{name}' -> {payload_dir}"
    )
    return True
