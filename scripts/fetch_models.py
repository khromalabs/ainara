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

"""Download runtime model files required to boot the backend services.

The Kokoro TTS model files are large (~354 MB total) and are NOT part
of the git repository (resources/ is gitignored). A fresh clone without
them cannot boot PyBridge, since create_tts_backend() hard-requires the
Kokoro backend. This script fetches them into the bundled resources
directory, mirroring what packaged builds ship.

Idempotent: files already present with the expected sha256 are skipped.

Usage:
    python3 scripts/fetch_models.py [--dest DIR] [--force]

Downloads (kokoro-onnx v1.0 GitHub release):
    kokoro-v1.0.onnx   (~325 MB)
    voices-v1.0.bin    (~28 MB)
"""

import argparse
import hashlib
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# kokoro-onnx v1.0, from https://github.com/thewh1teagle/kokoro-onnx/releases
FILES = {
    "kokoro-v1.0.onnx": {
        "url": (
            "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
            "model-files-v1.0/kokoro-v1.0.onnx"
        ),
        "sha256": "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5",
        "size": 325_532_387,
    },
    "voices-v1.0.bin": {
        "url": (
            "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
            "model-files-v1.0/voices-v1.0.bin"
        ),
        "sha256": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
        "size": 28_214_398,
    },
}


def log(msg: str) -> None:
    print(f"[fetch-models] {msg}", flush=True)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, dest: Path, expected_size: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        dir=dest.parent, prefix=dest.name, suffix=".part", delete=False
    ) as tmp:
        tmp_path = Path(tmp.name)

    try:
        last_reported = -1
        with urllib.request.urlopen(url) as response, open(tmp_path, "wb") as out:
            total = int(response.headers.get("Content-Length", expected_size))
            fetched = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                fetched += len(chunk)
                mb = fetched // (1024 * 1024)
                if mb != last_reported and mb % 25 == 0:
                    log(f"  {dest.name}: {mb} MB"
                        + (f" / {total // (1024 * 1024)} MB" if total else ""))
                    last_reported = mb
        shutil.move(str(tmp_path), str(dest))
    finally:
        tmp_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch runtime model files (Kokoro TTS)."
    )
    parser.add_argument(
        "--dest",
        default=str(REPO_ROOT / "resources" / "tts" / "models"),
        help="Target directory (default: resources/tts/models).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if files are already present and valid.",
    )
    args = parser.parse_args()

    dest_dir = Path(args.dest)
    failed = False

    for name, meta in FILES.items():
        target = dest_dir / name
        if not args.force and target.exists():
            log(f"Verifying existing {name} ...")
            if sha256_of(target) == meta["sha256"]:
                log(f"{name} already present — skipping")
                continue
            log(f"{name} present but sha256 mismatch — re-downloading")

        log(f"Downloading {name} ({meta['size'] // (1024 * 1024)} MB) ...")
        try:
            download(meta["url"], target, meta["size"])
        except Exception as e:
            log(f"ERROR: failed to download {name}: {e}")
            failed = True
            continue

        actual = sha256_of(target)
        if actual != meta["sha256"]:
            log(
                f"ERROR: {name} sha256 mismatch\n"
                f"  expected {meta['sha256']}\n"
                f"  actual   {actual}"
            )
            target.unlink(missing_ok=True)
            failed = True
        else:
            log(f"{name} OK (sha256 verified)")

    if failed:
        sys.exit(1)
    log("All model files ready.")


if __name__ == "__main__":
    main()
