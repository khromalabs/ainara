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

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if not os.path.isdir(os.path.join(project_root, "ainara")):
    raise SystemExit(f"{project_root} does not look like the project root (no ainara/)")

nexus_src = os.path.join(project_root, "ainara", "nexus")
nexus_staged_root = os.path.join(project_root, "build", "nexus_staged")
nexus_staged = os.path.join(nexus_staged_root, "ainara", "nexus")
nexus_obfuscated_root = os.path.join(project_root, "build", "nexus_obfuscated")
nexus_obfuscated = os.path.join(nexus_obfuscated_root, "nexus")

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

    # Materialize the ataria tree. In development it is often a symlink to a
    # sibling checkout that lives OUTSIDE project_root; the build container
    # only mounts project_root, so the link would be dangling inside /work.
    # Dereference it into build/ and let the spec read from there.
    ataria_src = os.path.join(nexus_src, "khromalabs", "ataria")
    if os.path.isdir(ataria_src):          # follows the symlink
        os.makedirs(os.path.dirname(ataria_compiled), exist_ok=True)
        shutil.copytree(os.path.realpath(ataria_src), ataria_compiled,
                        symlinks=False)
        print(f"[_obfuscate] Materialized ataria into {ataria_compiled}")

    # Stage the nexus tree (so public edition can strip supporters domains)
    os.makedirs(nexus_staged_root)
    shutil.copytree(nexus_src, nexus_staged, symlinks=False)

    if not supporters:
        ataria_staged = os.path.join(nexus_staged, "khromalabs", "ataria")
        if os.path.islink(ataria_staged) or os.path.exists(ataria_staged):
            if os.path.islink(ataria_staged):
                os.remove(ataria_staged)
            else:
                shutil.rmtree(ataria_staged)

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
    if not os.path.isdir(nexus_obfuscated):
        raise FileNotFoundError(f"PyArmor output not found at {nexus_obfuscated}")

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
    shutil.copytree(nexus_obfuscated, nexus_dest)

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
