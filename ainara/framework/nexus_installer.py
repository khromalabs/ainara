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

"""Nexus app remote install — name-addressed bundles (protocol v0).

The user types ``ataria`` (defaults to TLD ``.nexus``) or any host; the
bundle description lives at ``https://<host>/.well-known/nexus-app.json``
and is SELF-SIGNED by the vendor's Solana identity key (``creatorId``,
same canonical-JSON + ed25519 scheme as bundle manifests).

Trust chain (v0):
  TLS (transport) -> doc identity signature (authenticity of the whole
  doc: versions, artifact URLs, hashes) -> artifact sha256 (integrity)
  -> inner manifest identity signature + field match with the doc
  (artifact/doc binding). For license-gated bundles the ultimate anchor
  is on-chain: subscription verification checks the declared collection
  against real NFT ownership, so a spoofed channel cannot produce an
  installable, subscribable app. minisign is intentionally deferred.

The subscriber decides; nothing here phones home. https is enforced for
every non-loopback host (loopback http allowed for tests/dev).
"""

import hashlib
import json
import logging
import platform as pyplatform
import re
import shutil
import sys
import tempfile
import urllib.request
import uuid
import zipfile
from pathlib import Path

from ainara.framework.nexus_licensing import verify_manifest_identity

logger = logging.getLogger(__name__)

DEFAULT_TLD = "nexus"
DOC_PATH = ".well-known/nexus-app.json"
PROTOCOL_VERSION = 1
UNIVERSAL_TAG = "universal"

MAX_DOC_BYTES = 256 * 1024
MAX_ARTIFACT_BYTES = 1024 ** 3  # 1 GiB
DOWNLOAD_CHUNK = 64 * 1024
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 60

HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9-]+)+$")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
LOOPBACK_RE = re.compile(r"^(localhost|127\.0\.0\.1|\[::1\]|::1)$")


class InstallerError(Exception):
    """Installer failure with a machine-readable reason for the UI."""

    def __init__(self, reason: str, message: str = ""):
        self.reason = reason
        super().__init__(message or reason)


def current_platform_tag() -> str:
    """Same convention as ataria pack.py: linux-x86_64 / darwin-arm64 /
    win-amd64 / ..."""
    os_name = {"linux": "linux", "darwin": "darwin", "win32": "win"}.get(
        sys.platform, sys.platform
    )
    arch = pyplatform.machine().lower()
    arch = {"amd64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}.get(
        arch, arch
    )
    return f"{os_name}-{arch}"


def normalize_source(source: str) -> str:
    """'ataria' -> 'ataria.nexus'; dotted input used as-is; an optional
    ``:port`` suffix is preserved (dev/test). Rejects URLs/schemes — the
    UI passes a bare host (it may parse URLs itself)."""
    s = (source or "").strip().lower().rstrip(".")
    if not s or "://" in s or "/" in s:
        raise InstallerError("invalid_source", f"Invalid app source: {source!r}")
    port = ""
    if ":" in s:
        s, _, port = s.rpartition(":")
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            raise InstallerError("invalid_source", f"Invalid port: {port!r}")
        port = f":{port}"
    host = s if "." in s else f"{s}.{DEFAULT_TLD}"
    if not HOST_RE.match(host):
        raise InstallerError("invalid_source", f"Invalid host: {host!r}")
    return f"{host}{port}"


def _http_get(url: str, max_bytes: int):
    scheme = urllib.request.urlparse(url).scheme
    host = urllib.request.urlparse(url).hostname or ""
    if scheme != "https" and not LOOPBACK_RE.match(host):
        raise InstallerError("insecure_transport", f"Refusing non-https URL: {url}")
    req = urllib.request.Request(
        url, headers={"User-Agent": "ainara-nexus-installer/0.1"}
    )
    try:
        resp = urllib.request.urlopen(
            req, timeout=CONNECT_TIMEOUT
        )  # nosec - scheme enforced above
        chunks, total = [], 0
        while True:
            chunk = resp.read(DOWNLOAD_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise InstallerError("too_large", f"Response exceeds cap: {url}")
            chunks.append(chunk)
        return b"".join(chunks)
    except InstallerError:
        raise
    except urllib.error.HTTPError as e:
        reason = "not_found" if e.code == 404 else "network"
        raise InstallerError(reason, f"Fetch failed: {url} ({e})") from e
    except Exception as e:
        raise InstallerError("network", f"Fetch failed: {url} ({e})") from e


def _validate_doc(doc) -> dict:
    if not isinstance(doc, dict):
        raise InstallerError("bad_doc", "Document is not an object")
    if doc.get("protocol") != PROTOCOL_VERSION:
        raise InstallerError(
            "bad_doc", f"Unsupported protocol: {doc.get('protocol')!r}"
        )
    for field in ("vendor", "app", "latest", "creatorId", "signature"):
        if not isinstance(doc.get(field), str) or not doc[field].strip():
            raise InstallerError("bad_doc", f"Missing doc field: {field}")
    if not NAME_RE.match(doc["vendor"].strip().lower()) or not NAME_RE.match(
        doc["app"].strip().lower()
    ):
        raise InstallerError("bad_doc", "Invalid vendor/app in doc")
    artifacts = doc.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise InstallerError("bad_doc", "No artifacts in doc")
    for art in artifacts:
        if not isinstance(art, dict) or not all(
            isinstance(art.get(k), str) and art.get(k)
            for k in ("platform", "url", "sha256")
        ):
            raise InstallerError("bad_doc", "Malformed artifact entry")
    return doc


def fetch_doc(source: str) -> dict:
    """Fetch, validate and identity-verify the bundle doc. Returns the doc
    (with its signature field intact). Loopback hosts use http (dev/test
    allowance); everything else is https-only."""
    host = normalize_source(source)
    scheme = "http" if LOOPBACK_RE.match(host.rsplit(":", 1)[0]) else "https"
    raw = _http_get(f"{scheme}://{host}/{DOC_PATH}", MAX_DOC_BYTES)
    try:
        doc = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise InstallerError("bad_doc", f"Document is not valid JSON: {e}") from e
    _validate_doc(doc)
    ok, reason = verify_manifest_identity(doc)
    if not ok:
        raise InstallerError(
            "untrusted_doc", f"Bundle doc failed identity verification: {reason}"
        )
    return doc


def pick_artifact(doc: dict) -> dict:
    """Current platform first, then universal."""
    tag = current_platform_tag()
    artifacts = doc["artifacts"]
    for art in artifacts:
        if art["platform"] == tag:
            return art
    for art in artifacts:
        if art["platform"] == UNIVERSAL_TAG:
            return art
    raise InstallerError(
        "no_artifact",
        f"No artifact for this platform ({tag}) and no universal build",
    )


def _summary(doc: dict) -> dict:
    protection = doc.get("protection") or {}
    gated = protection.get("mode") == "nft-license"
    return {
        "vendor": doc["vendor"].strip().lower(),
        "app": doc["app"].strip().lower(),
        "latest": doc["latest"].strip(),
        "description": doc.get("description") or "",
        "creatorId": doc["creatorId"].strip(),
        "gated": gated,
        "protection": protection.get("mode") or "open",
        "collection": (protection.get("collection") or "").strip() or None,
    }


def resolve_source(source: str) -> dict:
    """Fetch + verify the doc and return the UI summary (no download)."""
    host = normalize_source(source)
    doc = fetch_doc(host)
    summary = _summary(doc)
    summary["source_host"] = host
    artifact = pick_artifact(doc)
    summary["artifact"] = {
        "platform": artifact["platform"],
        "url": artifact["url"],
        "sha256": artifact["sha256"],
    }
    summary["artifacts"] = [
        {"platform": a["platform"]} for a in doc["artifacts"]
    ]
    return summary


def _safe_extract(zip_path: Path, dest: Path):
    """Extract with zip-slip and size guards. The artifact root IS the
    bundle root (D2): members land directly in dest."""
    total = 0
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename
            if name.startswith("/") or "\\" in name or ":" in name:
                raise InstallerError("bad_artifact", f"Unsafe zip member: {name!r}")
            parts = name.split("/")
            if any(p == ".." for p in parts):
                raise InstallerError("bad_artifact", f"Unsafe zip member: {name!r}")
            total += info.file_size
            if total > MAX_ARTIFACT_BYTES:
                raise InstallerError("too_large", "Artifact exceeds size cap")
        zf.extractall(dest)


def _atomic_swap(staging: Path, target: Path):
    """Replace target with staging; never leaves a partial install."""
    backup = target.parent / f".old-{uuid.uuid4().hex}"
    replaced = False
    if target.exists():
        target.rename(backup)
        replaced = True
    try:
        staging.rename(target)
    except Exception:
        if replaced:
            backup.rename(target)
        raise
    if replaced:
        shutil.rmtree(backup, ignore_errors=True)


def uninstall_app(apps_dir, vendor: str, app: str) -> dict:
    """Remove an installed bundle. The subscription token is kept: a
    reinstall does not need to re-subscribe."""
    vendor = (vendor or "").strip().lower()
    app = (app or "").strip().lower()
    if not NAME_RE.match(vendor) or not NAME_RE.match(app):
        raise InstallerError("invalid_source", f"Invalid bundle id: {vendor}/{app}")
    apps_dir = Path(apps_dir)
    target = apps_dir / f"{vendor}.{app}"
    # path safety: only ever remove inside .apps/, and only bundle-shaped dirs
    if apps_dir.resolve() not in target.resolve().parents:
        raise InstallerError("invalid_source", "Refusing to remove outside .apps")
    if not target.is_dir() or not (target / "nexus.json").is_file():
        raise InstallerError("not_installed", f"{vendor}/{app} is not installed")
    shutil.rmtree(target)
    logger.info(f"Nexus app uninstalled: {vendor}/{app} ({target})")
    return {"ok": True, "vendor": vendor, "app": app}


def install_source(source: str, apps_dir, subscription_ok=None) -> dict:
    """Full install: fetch doc -> gate check -> download -> verify ->
    extract -> verify inner manifest -> atomic swap. ``subscription_ok``
    is called for gated bundles as ``subscription_ok(vendor, app)``."""
    doc = fetch_doc(source)
    summary = _summary(doc)
    vendor, app = summary["vendor"], summary["app"]

    if summary["gated"]:
        if not (callable(subscription_ok) and subscription_ok(vendor, app)):
            raise InstallerError(
                "subscription_required",
                "This Nexus App requires an active subscription",
            )

    artifact = pick_artifact(doc)

    apps_dir = Path(apps_dir)
    apps_dir.mkdir(parents=True, exist_ok=True)

    # Download to a temp file, verifying sha256 while streaming
    blob = _http_get(artifact["url"], MAX_ARTIFACT_BYTES)
    digest = hashlib.sha256(blob).hexdigest()
    if digest != artifact["sha256"].strip().lower():
        raise InstallerError("hash_mismatch", "Artifact sha256 mismatch")
    tmp_zip = apps_dir.parent / f".dl-{uuid.uuid4().hex}"
    tmp_zip.write_bytes(blob)

    staging = apps_dir / f".staging-{uuid.uuid4().hex}"
    try:
        try:
            _safe_extract(tmp_zip, staging)
        except zipfile.BadZipFile as e:
            raise InstallerError("bad_artifact", f"Corrupt artifact: {e}") from e

        manifest_path = staging / "nexus.json"
        if not manifest_path.is_file():
            raise InstallerError("bad_artifact", "Artifact has no nexus.json")
        from ainara.framework.nexus_apps import read_manifest

        manifest = read_manifest(manifest_path)
        if not manifest:
            raise InstallerError("bad_artifact", "Artifact manifest unreadable")

        # Artifact/doc binding
        ok, reason = verify_manifest_identity(manifest)
        if not ok:
            raise InstallerError(
                "untrusted_artifact",
                f"Artifact manifest failed identity verification: {reason}",
            )
        if (
            manifest.get("provider", "").strip().lower() != vendor
            or manifest.get("name", "").strip().lower() != app
            or (manifest.get("creatorId") or "").strip() != summary["creatorId"]
            or (manifest.get("protection") or {}).get("mode")
            != (doc.get("protection") or {}).get("mode")
        ):
            raise InstallerError(
                "untrusted_artifact",
                "Artifact identity does not match the bundle doc",
            )

        target = apps_dir / f"{vendor}.{app}"
        _atomic_swap(staging, target)
        logger.info(
            f"Nexus app installed: {vendor}/{app} {summary['latest']} -> {target}"
        )
        return {
            "ok": True,
            "vendor": vendor,
            "app": app,
            "version": summary["latest"],
            "path": str(target),
        }
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        tmp_zip.unlink(missing_ok=True)
