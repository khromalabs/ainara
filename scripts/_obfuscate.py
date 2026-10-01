#!/usr/bin/env python3
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

"""Host-side obfuscation stage for the server bundles.

Runs everything that requires the licensed PyArmor installation and the
build secret, on the build host — never inside the manylinux container
(where both are deliberately absent). Produces the trees consumed by
scripts/pyinstaller/servers.spec:

    build/nexus_obfuscated/          PyArmor output + pyarmor_runtime_*/
    build/supporters_obfuscated/     PyArmor output + pyarmor_runtime_*/ (supporters)
    build/supporters_compiled/       final ainara/nexus (+ supporters) trees

Run via scripts/_build.py (which sets POLARIS_EDITION), or directly:
    POLARIS_EDITION=supporters python scripts/_obfuscate.py
"""

import argparse
import os
import secrets
import shutil
import subprocess
import sys
from typing import Optional

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if not os.path.isdir(os.path.join(project_root, "ainara")):
    raise SystemExit(f"{project_root} does not look like the project root (no ainara/)")

nexus_src = os.path.join(project_root, "ainara", "nexus")
nexus_staged_root = os.path.join(project_root, "build", "nexus_staged")
nexus_staged = os.path.join(nexus_staged_root, "ainara", "nexus")
nexus_obfuscated_root = os.path.join(project_root, "build", "nexus_obfuscated")

supporters_src = os.path.join(project_root, "supporters")
supporters_rendered_root = os.path.join(project_root, "build", "supporters_rendered")
supporters_rendered = os.path.join(supporters_rendered_root, "supporters")
supporters_obfuscated_root = os.path.join(project_root, "build", "supporters_obfuscated")
supporters_obfuscated = os.path.join(supporters_obfuscated_root, "supporters")
supporters_compiled_root = os.path.join(project_root, "build", "supporters_compiled")
supporters_compiled = os.path.join(supporters_compiled_root, "supporters")
ataria_compiled_root = os.path.join(project_root, "build", "ataria_compiled")
ataria_compiled = os.path.join(
    ataria_compiled_root, "ainara", "nexus", "khromalabs", "ataria"
)
build_secret_path = os.path.join(project_root, "build", "build_secret.key")

pyarmor_bin = os.path.join(os.path.dirname(sys.executable), "pyarmor")
if sys.platform == "win32":
    pyarmor_bin += ".exe"

pyarmor_common_args = [
    "gen",
    "--recursive",
    "--obf-code", "2",
    "--mix-str",
    "--exclude", "*/test*",
    "--exclude", "*/conftest.py",
    "--exclude", "*/__pycache__",
    "--exclude", "*/generate_",
    "--exclude", "*/.*",
]


def _strip_namespace_inits() -> None:
    """Remove PEP 420 namespace markers from the staged nexus tree.

    No __init__.py may exist at nexus/ level or at vendor level directly
    under it; bundle level and deeper keep theirs. The host repo is
    namespace-native after Stage 1, so this is normally a no-op — it
    guards against stale or symlinked source trees reintroducing the
    markers and breaking the installable-app extraction layout.
    """
    removed = []
    top_init = os.path.join(nexus_staged, "__init__.py")
    if os.path.isfile(top_init):
        os.remove(top_init)
        removed.append(os.path.relpath(top_init, project_root))
    for entry in sorted(os.listdir(nexus_staged)):
        vendor_dir = os.path.join(nexus_staged, entry)
        vendor_init = os.path.join(vendor_dir, "__init__.py")
        if os.path.isdir(vendor_dir) and os.path.isfile(vendor_init):
            os.remove(vendor_init)
            removed.append(os.path.relpath(vendor_init, project_root))
    if removed:
        print(f"[_obfuscate] Stripped namespace __init__.py: {', '.join(removed)}")


ATARIA_PAYLOAD_MARKERS = ("charts", "crypto", "dashboards")
ATARIA_GENERATED_ARTIFACTS = (
    "nexus.json", "providers_registry.json", "skills_metadata.json", "site",
)


def _is_ataria_payload(path: str) -> bool:
    """True if path is the bundle payload itself (not a repo root)."""
    return os.path.isdir(path) and all(
        os.path.isdir(os.path.join(path, d)) for d in ATARIA_PAYLOAD_MARKERS
    )


def _resolve_ataria_source() -> Optional[str]:
    """Resolve the ataria payload source, mirroring discovery precedence.

    Order (first payload-shaped hit wins):
      1. nexus.dev_apps['ataria'] — repo root or payload directly (runtime
         truth; the dev checkout also carries the gitignored generated
         artifacts the PyInstaller spec requires).
      2. Host bundle path via realpath — legacy payload-pointing symlink
         or real payload dir.
      3. Host submodule mount's nested payload
         (<mount>/ainara/nexus/khromalabs/ataria) — fresh clones.
    Never returns a repo ROOT: builds must not ingest plans/, _scripts/,
    docs/ or a nested duplicate payload (note §11).
    """
    from ainara.framework.config import config

    candidates = []  # (label, path)

    dev_root = (config.get("nexus.dev_apps") or {}).get("ataria")
    if dev_root:
        dev_root = os.path.abspath(os.path.expanduser(str(dev_root)))
        candidates.append(("nexus.dev_apps (payload)", dev_root))
        candidates.append(("nexus.dev_apps (nested payload)", os.path.join(
            dev_root, "ainara", "nexus", "khromalabs", "ataria")))

    host_bundle = os.path.join(nexus_src, "khromalabs", "ataria")
    candidates.append(("host bundle (realpath)", os.path.realpath(host_bundle)))
    candidates.append(("host bundle (nested payload)", os.path.join(
        host_bundle, "ainara", "nexus", "khromalabs", "ataria")))

    for label, path in candidates:
        if _is_ataria_payload(path):
            print(f"[_obfuscate] ataria source: {label} -> {path}")
            return path
    return None


def obfuscate(edition: str) -> None:
    supporters = edition == "supporters"
    print(f"[_obfuscate] Edition: {edition}")

    if not os.path.isdir(nexus_src):
        raise FileNotFoundError(f"{nexus_src} not found")

    if shutil.which(pyarmor_bin) is None:
        raise SystemExit(
            f"pyarmor not found next to {sys.executable}. The licensed "
            "PyArmor install must live in the interpreter that runs this "
            "script (host only — never inside the build container)."
        )

    # Clean previous artifacts
    for d in [
        nexus_staged_root,
        nexus_obfuscated_root,
        supporters_rendered_root,
        supporters_obfuscated_root,
        supporters_compiled_root,
        ataria_compiled_root,
    ]:
        if os.path.exists(d):
            shutil.rmtree(d)

    # Build secret is only needed for supporters edition
    build_secret = None
    if supporters:
        os.makedirs(os.path.dirname(build_secret_path), exist_ok=True)
        if not os.path.exists(build_secret_path):
            with open(build_secret_path, "wb") as f:
                f.write(secrets.token_bytes(32))
        with open(build_secret_path, "rb") as f:
            build_secret = f.read()
        if len(build_secret) < 32:
            raise ValueError(
                f"{build_secret_path} is corrupt (<32 bytes). Delete it to "
                "regenerate — NOTE: this invalidates all existing tokens."
            )

    # Materialize the ataria PAYLOAD into build/ so the (containerized) spec
    # can read it. Resolution precedence mirrors discovery (note §11).
    ataria_source = _resolve_ataria_source()
    if ataria_source is None:
        raise FileNotFoundError(
            "No usable ataria payload found. Set nexus.dev_apps['ataria'] to "
            "the dev checkout, or materialize the payload at "
            f"{os.path.join(nexus_src, 'khromalabs', 'ataria')} (charts/, "
            "crypto/, dashboards/ must sit directly inside it)."
        )
    missing = [
        name for name in ATARIA_GENERATED_ARTIFACTS
        if not os.path.exists(os.path.join(ataria_source, name))
    ]
    if missing:
        raise FileNotFoundError(
            f"ataria payload {ataria_source} is missing generated artifacts: "
            f"{missing}. Regenerate (generate_registries.py with "
            "cwd=<payload>; 'mkdocs build --site-dir <payload>/site' from the "
            "repo root) or point nexus.dev_apps at the dev checkout."
        )
    os.makedirs(os.path.dirname(ataria_compiled), exist_ok=True)
    shutil.copytree(
        ataria_source,
        ataria_compiled,
        symlinks=False,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
    )
    print(f"[_obfuscate] Materialized ataria into {ataria_compiled}")

    # Stage the nexus tree (so public edition can strip supporters domains)
    os.makedirs(nexus_staged_root)
    shutil.copytree(nexus_src, nexus_staged, symlinks=False)
    _strip_namespace_inits()

    # Whatever the host bundle entry is (symlink, real dir, submodule mount),
    # the staged tree must contain ONLY the resolved payload — never repo
    # junk (plans/, _scripts/, docs/) or a nested duplicate payload. The
    # staged copy is only needed for the supporters obfuscation pass.
    ataria_staged = os.path.join(nexus_staged, "khromalabs", "ataria")
    if os.path.islink(ataria_staged):
        os.remove(ataria_staged)
    elif os.path.exists(ataria_staged):
        shutil.rmtree(ataria_staged)
    if supporters:
        shutil.copytree(
            ataria_source,
            ataria_staged,
            symlinks=False,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
        )

    # Render the closed-source supporters package with the real build secret,
    # then inject license guards into the staged nexus tree.
    if supporters:
        os.makedirs(supporters_rendered_root)
        shutil.copytree(supporters_src, supporters_rendered, symlinks=False)
        auth_core_path = os.path.join(supporters_rendered, "auth_core.py")
        with open(auth_core_path, encoding="utf-8") as f:
            rendered = f.read()
        if "__BUILD_SECRET__" not in rendered:
            raise ValueError("auth_core.py: __BUILD_SECRET__ placeholder not found")
        rendered = rendered.replace("__BUILD_SECRET__", repr(build_secret))
        with open(auth_core_path, "w", encoding="utf-8") as f:
            f.write(rendered)

        subprocess.run(
            [
                sys.executable,
                os.path.join(project_root, "supporters", "inject_license_guards.py"),
                "--tree", nexus_staged_root,
                "--auth-core", os.path.join(supporters_src, "auth_core.py"),
                "--secret-file", build_secret_path,
            ],
            check=True,
            cwd=project_root,
        )

    # Obfuscate the staged nexus tree
    subprocess.run(
        [pyarmor_bin, *pyarmor_common_args, "-O", nexus_obfuscated_root, nexus_staged],
        check=True,
        cwd=project_root,
    )
    # PyArmor 9 mirrors a regular package's basename under -O
    # (nexus_obfuscated/nexus/...), but a namespace-package input — no
    # __init__.py at the input root, our Stage-1 layout — is written with
    # its contents directly under the -O root. Normalize both shapes.
    wrapped = os.path.join(nexus_obfuscated_root, "nexus")
    if os.path.isdir(wrapped):
        nexus_output_dir = wrapped
    elif os.path.isdir(nexus_obfuscated_root):
        nexus_output_dir = nexus_obfuscated_root
    else:
        raise FileNotFoundError(
            f"PyArmor output not found under {nexus_obfuscated_root}"
        )

    # Obfuscate the rendered supporters package
    supporters_obfuscated_dir = None
    if supporters:
        subprocess.run(
            [pyarmor_bin, *pyarmor_common_args, "-O", supporters_obfuscated_root, supporters_rendered],
            check=True,
            cwd=project_root,
        )
        supporters_obfuscated_dir = os.path.join(supporters_obfuscated_root, "supporters")
        if not os.path.isdir(supporters_obfuscated_dir):
            raise FileNotFoundError(
                f"Supporters obfuscation output missing: {supporters_obfuscated_dir}"
            )

    # Assemble the final compiled tree used by the PyInstaller datas
    os.makedirs(supporters_compiled_root, exist_ok=True)
    nexus_dest = os.path.join(supporters_compiled_root, "ainara", "nexus")
    os.makedirs(os.path.dirname(nexus_dest), exist_ok=True)
    # pyarmor_runtime_* siblings live at the -O root and ship separately
    # (spec collects them to _internal root); never leak into ainara/nexus.
    shutil.copytree(
        nexus_output_dir,
        nexus_dest,
        ignore=shutil.ignore_patterns("pyarmor_runtime_*"),
    )

    shipped = [f for _, _, files in os.walk(nexus_dest)
               for f in files if f.endswith(".py")]
    if not shipped:
        print("[_obfuscate] shipped 0 obfuscated scripts (empty nexus tree)")
        if supporters:
            raise FileNotFoundError(
                "supporters edition: compiled nexus tree is empty — "
                "staging lost the bundles; aborting"
            )

    if supporters:
        shutil.copytree(supporters_obfuscated_dir, supporters_compiled)

    print(f"[_obfuscate] Artifacts ready under {supporters_compiled_root}")


def main():
    parser = argparse.ArgumentParser(
        description="Host-side obfuscation stage (licensed PyArmor)."
    )
    parser.add_argument(
        "-e", "--edition",
        choices=["public", "supporters"],
        default=None,
        help="Distribution edition (defaults to POLARIS_EDITION).",
    )
    args = parser.parse_args()

    edition = args.edition or os.environ.get("POLARIS_EDITION")
    if edition not in ("public", "supporters"):
        parser.error("edition is required (-e/--edition or POLARIS_EDITION)")
    os.environ["POLARIS_EDITION"] = edition
    obfuscate(edition)


if __name__ == "__main__":
    main()
