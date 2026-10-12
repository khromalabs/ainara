#!/usr/bin/env python3
"""Stage B gate: Nexus licensing seam + manifest identity verification.

Offline (no RPC, no browser). Exercises:

1. Manifest identity (OPEN code): ed25519 sign/verify round-trip via
   solders, tamper detection, missing-field fail-closed.
2. Seam fail-closed: closed core absent -> SubscriptionManager
   unavailable, status/verify/revoke all refuse.
3. Seam delegation: closed core present (real module via
   AINARA_NEXUS_LICENSING_PATH) -> message/issuance/status/revoke work,
   identifiers validated, fail-closed on invalid identities.
"""

import base64
import json
import os
import pathlib
import secrets
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from ainara.framework.nexus_licensing import (  # noqa: E402
    SubscriptionManager,
    canonical_manifest_bytes,
    verify_manifest_identity,
)

LICENSING_ROOT = "/home/ruben/lab/src/ainara_licensing"
WALLET = "9xzW4bYLhMq8fKbVHbB7Yt9E6jLdVmHhVdPzH4CwKq8A"


class FakeStorage:
    def __init__(self):
        self.meta = {}

    def get_metadata(self, key):
        return self.meta.get(key)

    def set_metadata(self, key, value):
        self.meta[key] = value

    def delete_metadata(self, keys):
        for k in keys:
            self.meta.pop(k, None)


def test_identity():
    from solders.keypair import Keypair

    kp = Keypair()
    manifest = {
        "schemaVersion": "1.0",
        "name": "sampleapp",
        "provider": "acme",
        "version": "0.1.0",
        "description": "test",
        "creatorId": str(kp.pubkey()),
        "protection": {"mode": "nft-license", "collection": "COLLMINT"},
    }
    manifest["signature"] = str(
        kp.sign_message(canonical_manifest_bytes(manifest))
    )

    ok, reason = verify_manifest_identity(manifest)
    assert ok, reason
    print("ok  manifest identity: sign -> verify round-trip")

    # canonical form excludes the signature field
    payload = {k: v for k, v in manifest.items() if k != "signature"}
    assert canonical_manifest_bytes(manifest) == json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    print("ok  canonical bytes exclude the signature field")

    # tampered content -> mismatch
    bad = dict(manifest)
    bad["version"] = "9.9.9"
    ok, reason = verify_manifest_identity(bad)
    assert not ok and "mismatch" in reason
    # swapped signature -> mismatch
    other = Keypair()
    bad = dict(manifest)
    bad["signature"] = str(other.sign_message(b"unrelated"))
    ok, reason = verify_manifest_identity(bad)
    assert not ok and "mismatch" in reason
    print("ok  tampered manifest/signature rejected")

    # missing fields -> fail-closed with reasons
    assert not verify_manifest_identity({"name": "x"})[0]
    assert not verify_manifest_identity({"creatorId": str(kp.pubkey())})[0]
    assert not verify_manifest_identity(
        {"creatorId": "not-a-pubkey", "signature": "not-a-sig"}
    )[0]
    print("ok  missing/invalid identity fields fail-closed")


def test_fail_closed():
    """Closed core absent -> SubscriptionManager unavailable, all calls
    refuse. Simulates a machine without the closed core via a meta-path
    blocker (a source venv may legitimately have the wheel installed)."""
    import subprocess
    repo = pathlib.Path(__file__).resolve().parents[1]
    env = {
        k: v for k, v in os.environ.items()
        if k != "AINARA_NEXUS_LICENSING_PATH"
    }
    env["PYTHONPATH"] = str(repo)
    probe = r"""
import importlib.abc
import sys


class _BlockCore(importlib.abc.MetaPathFinder):
    # Simulate a machine without the closed core.
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "nexuslicensing" or fullname.startswith("nexuslicensing."):
            raise ModuleNotFoundError("blocked (test)", name=fullname)
        return None


sys.meta_path.insert(0, _BlockCore())


class FakeStorage:
    def __init__(self):
        self.meta = {}

    def get_metadata(self, key):
        return self.meta.get(key)

    def set_metadata(self, key, value):
        self.meta[key] = value

    def delete_metadata(self, keys):
        for k in keys:
            self.meta.pop(k, None)


from ainara.framework.nexus_licensing import SubscriptionManager
mgr = SubscriptionManager(FakeStorage())
assert mgr.available is False
assert mgr.subscription_message("a", "b") is None
assert mgr.get_status("a", "b") == {
    "subscribed": False,
    "reason": "licensing_unavailable",
    "vendor": "a",
    "app": "b",
}
ok, msg, info = mgr.verify_subscription(
    "a", "b", {}, None, "9xzW4bYLhMq8fKbVHbB7Yt9E6jLdVmHhVdPzH4CwKq8A", [1], "m"
)
assert ok is False and info is None and "unavailable" in msg.lower()
assert mgr.revoke("a", "b") is False
assert mgr.protection_targets({"collection": " C "}, "CR") == ("C", "CR")
print("PROBE-OK")
"""
    r = subprocess.run(
        [sys.executable, "-c", probe], env=env,
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0 and "PROBE-OK" in r.stdout, (
        "fail-closed seam broken\n" + r.stdout[-800:] + r.stderr[-800:]
    )
    print("ok  closed core absent -> fail-closed across the seam")


def test_crash_resilience():
    """Core found but broken (no build secret) -> manager degrades to
    fail-closed; Pybridge startup must never crash on licensing.

    Runs in a subprocess whose sys.path puts a deliberately BROKEN
    checkout (package copied alone, no build/) AHEAD of everything else,
    so the resolution order itself is exercised: a machine with the
    wheel installed must still be able to test the broken-core path.
    """
    import shutil
    import subprocess
    import tempfile
    repo = pathlib.Path(__file__).resolve().parents[1]
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="nexuslic_broken_"))
    shutil.copytree(
        pathlib.Path(LICENSING_ROOT) / "nexuslicensing",
        tmp / "nexuslicensing",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    env = {k: v for k, v in os.environ.items() if k != "AINARA_BUILD_SECRET"}
    env["AINARA_NEXUS_LICENSING_PATH"] = str(tmp)
    env["PYTHONPATH"] = os.pathsep.join([str(tmp), str(repo)])
    probe = r"""
import sys


class FakeStorage:
    def __init__(self):
        self.meta = {}

    def get_metadata(self, key):
        return self.meta.get(key)

    def set_metadata(self, key, value):
        self.meta[key] = value

    def delete_metadata(self, keys):
        for k in keys:
            self.meta.pop(k, None)


import nexuslicensing
assert nexuslicensing.__file__.startswith(sys.path[0]), (
    "broken checkout must shadow any installed core: "
    + nexuslicensing.__file__)
try:
    import nexuslicensing.auth_core  # noqa: F401 — must raise (no secret)
    raise SystemExit("broken checkout unexpectedly resolved its secret")
except RuntimeError:
    pass

from ainara.framework.nexus_licensing import SubscriptionManager
mgr = SubscriptionManager(FakeStorage())
assert mgr.available is False, "broken core must degrade, not raise"
ok, msg, info = mgr.verify_subscription(
    "a", "b", {}, None, "9xzW4bYLhMq8fKbVHbB7Yt9E6jLdVmHhVdPzH4CwKq8A", [1], "m"
)
assert ok is False and info is None
print("PROBE-OK")
"""
    try:
        r = subprocess.run(
            [sys.executable, "-c", probe], env=env,
            capture_output=True, text=True, timeout=120,
        )
        assert r.returncode == 0 and "PROBE-OK" in r.stdout, (
            "broken core must degrade, not raise\n"
            + r.stdout[-800:] + r.stderr[-800:]
        )
        print("ok  core present but broken -> fail-closed, no startup crash")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_delegation():
    os.environ["AINARA_NEXUS_LICENSING_PATH"] = LICENSING_ROOT
    os.environ["AINARA_BUILD_SECRET"] = base64.b64encode(
        secrets.token_bytes(32)
    ).decode()
    mgr = SubscriptionManager(FakeStorage())
    assert mgr.available, "closed core should load from the dev checkout"

    # canonical message + identifier validation
    assert mgr.subscription_message("Acme", "Sampleapp") == (
        "Authorize Ainara Nexus subscription: acme/sampleapp"
    )
    try:
        mgr.subscription_message("bad vendor", "app")
        assert False, "invalid identifier accepted"
    except ValueError:
        pass
    print("ok  closed core loaded: canonical message + validation")

    # issuance delegation (RPC + ed25519 stubbed as in the core suite)
    core_mod = sys.modules["nexuslicensing.auth_core"]

    class _FakeSigObj:
        def verify(self, pubkey, msg):
            return True

    class _FakeSignature:
        @staticmethod
        def from_bytes(b):
            return _FakeSigObj()

    real_sig = core_mod.Signature
    core_mod.Signature = _FakeSignature
    mgr._core._execute_rpc_check = lambda wallet, c, cr: True
    try:
        ok, msg, info = mgr.verify_subscription(
            "acme", "sampleapp",
            {"mode": "nft-license", "collection": "COLLMINT"},
            "CREATORKEY",
            WALLET, [1] * 64,
            "Authorize Ainara Nexus subscription: acme/sampleapp",
        )
        assert ok, msg
        assert info["code"] and info["expires_at"] and info["wallet"] == WALLET

        st = mgr.get_status("acme", "sampleapp")
        assert st["subscribed"] is True and st["code"] == info["code"]
        assert st["mode"] == "nft-license"

        assert mgr.revoke("acme", "sampleapp") is True
        st = mgr.get_status("acme", "sampleapp")
        assert st["subscribed"] is False and st["reason"] == "no_subscription"
        print("ok  issuance/status/revoke delegate to the closed core")
    finally:
        core_mod.Signature = real_sig

    print("\nALL GATES PASSED")


if __name__ == "__main__":
    test_identity()
    test_fail_closed()
    test_crash_resilience()
    test_delegation()
