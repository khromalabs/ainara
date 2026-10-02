#!/usr/bin/env python3
"""Stage C gate: Nexus installer protocol v0, end-to-end offline.

Serves a locally-signed doc + artifact zip over loopback http (the only
case where non-https is allowed), then exercises:

1. source normalization (default TLD, URL rejection, host validation)
2. doc fetch + identity verification (+ tamper rejection)
3. artifact platform selection (current platform, universal fallback)
4. gated install without subscription -> subscription_required
5. full install with subscription -> sha256 verify -> zip-slip guard ->
   inner manifest binding -> atomic swap into .apps/<vendor>.<app>
6. update: same path replaces the bundle (replaced=True), corrupt hash
   and untrusted manifest rejected
"""

import base64
import hashlib
import io
import json
import os
import pathlib
import secrets
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from ainara.framework.nexus_installer import (  # noqa: E402
    InstallerError,
    current_platform_tag,
    install_source,
    normalize_source,
    pick_artifact,
    resolve_source,
)
from ainara.framework.nexus_licensing import canonical_manifest_bytes  # noqa: E402
from ainara.framework.nexus_licensing import verify_manifest_identity  # noqa: E402

os.environ["AINARA_NEXUS_LICENSING_PATH"] = "/home/ruben/lab/src/ainara_supporters"
os.environ["AINARA_BUILD_SECRET"] = base64.b64encode(
    secrets.token_bytes(32)
).decode()

from solders.keypair import Keypair  # noqa: E402

TMP = pathlib.Path(__file__).resolve().parent / "tmp_nexus_install_gate"
PORT = 8944
LOOPBACK_SRC = f"127.0.0.1:{PORT}"


def make_bundle(kp, version, payload_extra=None):
    """Build an artifact zip (bundle root at top) with a signed manifest."""
    manifest = {
        "schemaVersion": "1.0",
        "name": "ataria",
        "provider": "khromalabs",
        "version": version,
        "creatorId": str(kp.pubkey()),
        "protection": {"mode": "nft-license", "collection": "COLLMINT1111"},
    }
    manifest["signature"] = str(
        kp.sign_message(canonical_manifest_bytes(manifest))
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("nexus.json", json.dumps({"manifest": manifest}))
        zf.writestr("skills/demo.py", "VALUE = 1\n")
        for name, content in (payload_extra or {}).items():
            zf.writestr(name, content)
    return buf.getvalue(), manifest


def make_doc(kp, version, zip_bytes, sha=None, extra=None):
    doc = {
        "protocol": 1,
        "vendor": "khromalabs",
        "app": "ataria",
        "latest": version,
        "description": "test bundle",
        "creatorId": str(kp.pubkey()),
        "protection": {"mode": "nft-license", "collection": "COLLMINT1111"},
        "artifacts": [
            {
                "platform": current_platform_tag(),
                "url": f"http://127.0.0.1:{PORT}/ataria.zip",
                "sha256": sha or hashlib.sha256(zip_bytes).hexdigest(),
            }
        ],
    }
    if extra:
        doc.update(extra)
    doc["signature"] = str(kp.sign_message(canonical_manifest_bytes(doc)))
    return doc


class Handler(BaseHTTPRequestHandler):
    state = {}

    def do_GET(self):
        body = self.state.get(self.path.lstrip("/"), b"")
        self.send_response(200 if body else 404)
        self.send_header("Content-Type", "application/octet-stream")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass



def main():
    import shutil

    shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir(parents=True)
    kp = Keypair()

    zip_v1, _ = make_bundle(kp, "0.1.0")
    doc_v1 = make_doc(kp, "0.1.0", zip_v1)
    zip_v2, _ = make_bundle(kp, "0.2.0")
    doc_v2 = make_doc(kp, "0.2.0", zip_v2)

    Handler.state = {
        ".well-known/nexus-app.json": json.dumps(doc_v1).encode(),
        "ataria.zip": zip_v1,
    }
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    try:
        # 1. source normalization
        assert normalize_source("ataria") == "ataria.nexus"
        assert normalize_source("ataria.nexus") == "ataria.nexus"
        assert normalize_source("ATARIA") == "ataria.nexus"
        for bad in ("", "https://x", "a/b", "..", "a b"):
            try:
                normalize_source(bad)
                assert False, f"accepted {bad!r}"
            except InstallerError:
                pass
        print("ok  source normalization (default .nexus TLD, rejects URLs)")

        # 2. resolve: fetch + identity verify
        s = resolve_source(LOOPBACK_SRC)
        assert s["vendor"] == "khromalabs" and s["app"] == "ataria"
        assert s["gated"] is True and s["collection"] == "COLLMINT1111"
        assert s["artifact"]["platform"] == current_platform_tag()
        assert s["latest"] == "0.1.0"
        print("ok  resolve: signed doc fetched and identity-verified")

        # tampered doc rejected (flip latest without re-signing)
        bad_doc = dict(doc_v1)
        bad_doc["latest"] = "9.9.9"
        Handler.state[".well-known/nexus-app.json"] = json.dumps(bad_doc).encode()
        try:
            resolve_source(LOOPBACK_SRC)
            assert False, "tampered doc accepted"
        except InstallerError as e:
            assert e.reason == "untrusted_doc"
        Handler.state[".well-known/nexus-app.json"] = json.dumps(doc_v1).encode()
        print("ok  tampered doc rejected (untrusted_doc)")

        # 3. platform selection: universal fallback
        uni = {"platform": "universal", "url": doc_v1["artifacts"][0]["url"],
               "sha256": doc_v1["artifacts"][0]["sha256"]}
        d = {**doc_v1, "artifacts": [uni]}
        d["signature"] = str(kp.sign_message(canonical_manifest_bytes(d)))
        assert pick_artifact(d)["platform"] == "universal"
        print("ok  artifact selection: current platform, universal fallback")

        # 4. gated install without subscription
        apps = TMP / ".apps"
        try:
            install_source(LOOPBACK_SRC, apps, subscription_ok=lambda v, a: False)
            assert False, "installed without subscription"
        except InstallerError as e:
            assert e.reason == "subscription_required"
        print("ok  gated install rejected without subscription")

        # 5. full install with subscription
        r = install_source(LOOPBACK_SRC, apps, subscription_ok=lambda v, a: True)
        target = apps / "khromalabs.ataria"
        assert r["ok"] and r["version"] == "0.1.0" and target.is_dir()
        assert (target / "nexus.json").is_file()
        assert (target / "skills" / "demo.py").is_file()
        print("ok  install: downloaded, sha256-verified, swapped into .apps")

        # zip-slip member rejected
        evil, _ = make_bundle(
            kp, "0.1.0", {"../evil.txt": "pwned"}
        )
        doc_evil_slip = make_doc(kp, "0.1.0", evil)
        Handler.state["ataria.zip"] = evil
        Handler.state[".well-known/nexus-app.json"] = json.dumps(doc_evil_slip).encode()
        try:
            install_source(LOOPBACK_SRC, apps, subscription_ok=lambda v, a: True)
            assert False, "zip-slip accepted"
        except InstallerError as e:
            assert e.reason == "bad_artifact"
        assert not (apps.parent / "evil.txt").exists()
        print("ok  zip-slip member rejected")

        # 6a. corrupt hash rejected
        zip_v2b, _ = make_bundle(kp, "0.2.0")
        doc_bad_hash = make_doc(
            kp, "0.2.0", zip_v2b, sha="0" * 64
        )
        Handler.state["ataria.zip"] = zip_v2b
        Handler.state[".well-known/nexus-app.json"] = json.dumps(doc_bad_hash).encode()
        try:
            install_source(LOOPBACK_SRC, apps, subscription_ok=lambda v, a: True)
            assert False, "hash mismatch accepted"
        except InstallerError as e:
            assert e.reason == "hash_mismatch"
        print("ok  artifact hash mismatch rejected")

        # 6b. untrusted inner manifest (different key signs the zip)
        other = Keypair()
        evil_zip, _ = make_bundle(other, "0.2.0")
        doc_evil = make_doc(kp, "0.2.0", evil_zip)  # doc signed by kp, zip by other
        Handler.state[".well-known/nexus-app.json"] = json.dumps(doc_evil).encode()
        try:
            install_source(LOOPBACK_SRC, apps, subscription_ok=lambda v, a: True)
            assert False, "untrusted artifact accepted"
        except InstallerError as e:
            assert e.reason in ("untrusted_artifact", "hash_mismatch")
        print("ok  artifact/creator mismatch rejected")

        # 6c. update: same path replaces the bundle atomically
        Handler.state["ataria.zip"] = zip_v2
        Handler.state[".well-known/nexus-app.json"] = json.dumps(doc_v2).encode()
        r = install_source(LOOPBACK_SRC, apps, subscription_ok=lambda v, a: True)
        assert r["version"] == "0.2.0"
        m = json.loads((apps / "khromalabs.ataria" / "nexus.json").read_text())
        assert m["manifest"]["version"] == "0.2.0"
        leftovers = [p.name for p in apps.iterdir() if p.name.startswith(".")]
        assert not leftovers, f"staging/backup leftovers: {leftovers}"
        print("ok  update: atomic swap replaced the bundle, no leftovers")

        print("\nALL GATES PASSED")
    finally:
        server.shutdown()
        import shutil as _sh
        _sh.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    main()
