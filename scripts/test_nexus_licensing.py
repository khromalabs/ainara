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

LICENSING_ROOT = "/home/ruben/lab/src/ainara_supporters"
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
        "name": "ataria",
        "provider": "khromalabs",
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
    saved = os.environ.pop("AINARA_NEXUS_LICENSING_PATH", None)
    try:
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
            "a", "b", {}, None, WALLET, [1], "m"
        )
        assert ok is False and info is None and "unavailable" in msg.lower()
        assert mgr.revoke("a", "b") is False
        # open bundles: targets derivation still works locally
        assert mgr.protection_targets({"collection": " C "}, "CR") == ("C", "CR")
        print("ok  closed core absent -> fail-closed across the seam")
    finally:
        if saved is not None:
            os.environ["AINARA_NEXUS_LICENSING_PATH"] = saved


def test_delegation():
    os.environ["AINARA_NEXUS_LICENSING_PATH"] = LICENSING_ROOT
    os.environ["AINARA_BUILD_SECRET"] = base64.b64encode(
        secrets.token_bytes(32)
    ).decode()
    mgr = SubscriptionManager(FakeStorage())
    assert mgr.available, "closed core should load from the dev checkout"

    # canonical message + identifier validation
    assert mgr.subscription_message("Khromalabs", "Ataria") == (
        "Authorize Ainara Nexus subscription: khromalabs/ataria"
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
            "khromalabs", "ataria",
            {"mode": "nft-license", "collection": "COLLMINT"},
            "CREATORKEY",
            WALLET, [1] * 64,
            "Authorize Ainara Nexus subscription: khromalabs/ataria",
        )
        assert ok, msg
        assert info["code"] and info["expires_at"] and info["wallet"] == WALLET

        st = mgr.get_status("khromalabs", "ataria")
        assert st["subscribed"] is True and st["code"] == info["code"]
        assert st["mode"] == "nft-license"

        assert mgr.revoke("khromalabs", "ataria") is True
        st = mgr.get_status("khromalabs", "ataria")
        assert st["subscribed"] is False and st["reason"] == "no_subscription"
        print("ok  issuance/status/revoke delegate to the closed core")
    finally:
        core_mod.Signature = real_sig

    print("\nALL GATES PASSED")


if __name__ == "__main__":
    test_identity()
    test_fail_closed()
    test_delegation()
