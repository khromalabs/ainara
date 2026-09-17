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

"""Verify that no ELF file in a built bundle requires glibc newer than a floor.

Regression guard for the "version `GLIBC_X.Y' not found" class of failure:
inspects the versioned symbol requirements (what readelf --version-info
prints) of every bundled .so and server executable and exits non-zero if
any of them exceeds the floor.

Usage:
    python scripts/_audit_glibc.py dist [floor]     # floor default: 2.35
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

SERVER_EXES = {"orakle", "pybridge", "bureau", "sentinel"}
GLIBC_RE = re.compile(r"GLIBC_(\d+(?:\.\d+)+)")


def parse_version(s: str):
    return tuple(int(p) for p in s.split("."))


def elf_candidates(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file() and (
            path.name in SERVER_EXES or path.suffix == ".so" or ".so." in path.name
        ):
            yield path


def max_glibc(path: Path):
    proc = subprocess.run(
        ["readelf", "--version-info", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    versions = [parse_version(m) for m in GLIBC_RE.findall(proc.stdout)]
    return max(versions) if versions else None


def main():
    if shutil.which("readelf") is None:
        raise SystemExit("readelf not found — install binutils (or run inside the manylinux image)")

    root = Path(sys.argv[1] if len(sys.argv) > 1 else "dist")
    floor = parse_version(sys.argv[2]) if len(sys.argv) > 2 else parse_version("2.35")
    if not root.is_dir():
        raise SystemExit(f"{root} is not a directory")

    ceiling = None
    offenders = []
    checked = 0
    for path in elf_candidates(root):
        v = max_glibc(path)
        if v is None:
            continue
        checked += 1
        ceiling = v if ceiling is None else max(ceiling, v)
        if v > floor:
            offenders.append((v, path))

    fmt = lambda v: "GLIBC_" + ".".join(map(str, v))
    print(f"[audit] ELF files with GLIBC requirements: {checked}")
    print(f"[audit] glibc ceiling: {fmt(ceiling) if ceiling else 'none'} (floor {fmt(floor)})")
    if offenders:
        offenders.sort(reverse=True)
        print(f"[audit] FAIL — {len(offenders)} file(s) exceed the floor:")
        for v, p in offenders[:20]:
            print(f"    {fmt(v)}  {p}")
        sys.exit(1)
    print("[audit] OK")


if __name__ == "__main__":
    main()
