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

"""Nexus bundle subscription licensing (open seam).

Two independent pieces live here:

1. :class:`SubscriptionManager` — the LGPL adapter in front of the closed
   licensing core (``nexuslicensing.auth_core.NexusSubscriptionCore``,
   obfuscated, shipped inside the Polaris build; source of truth lives in
   the closed tooling checkout). The closed module is imported
   OPTIONALLY: with the Supporters Edition retired there is a single open
   Polaris edition and therefore NO "public mode" fallback — when the
   core is absent the manager is unavailable and license-gated bundles
   are fail-closed (they cannot subscribe). Open bundles never consult
   this manager.

   Set ``AINARA_NEXUS_LICENSING_PATH`` to the closed tooling checkout
   root for source runs (the packaged build ships the compiled package
   on sys.path).

2. :func:`verify_manifest_identity` — OPEN bundle-authenticity check
   (ed25519 via solders, already a dependency). The bundle author signs
   the canonical form of the manifest with the key whose public address
   is ``manifest.creatorId``; the signature travels in
   ``manifest.signature`` (base58). This binds the declared identity to
   a Solana key the vendor controls, preventing spoofed app releases
   (someone else shipping a bundle claiming ``khromalabs/ataria``).
   Surfaced by the runtime today; intended to become MANDATORY for every
   bundle at install time.
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

DEV_LICENSING_PATH_ENV = "AINARA_NEXUS_LICENSING_PATH"

# Canonical manifest signature field (inside the 'manifest' object).
MANIFEST_SIGNATURE_FIELD = "signature"


# ----------------------------------------------------------------------
# Manifest identity (open code; nothing secret)
# ----------------------------------------------------------------------

def canonical_manifest_bytes(manifest: dict) -> bytes:
    """Canonical serialization signed/verified for identity purposes:
    every 'manifest' key except the signature field, JSON with sorted
    keys and compact separators, UTF-8."""
    payload = {k: v for k, v in manifest.items()
               if k != MANIFEST_SIGNATURE_FIELD}
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def verify_manifest_identity(manifest: dict) -> Tuple[bool, str]:
    """Verify the manifest's ed25519 identity signature against its own
    ``creatorId``. Returns ``(verified, reason)``; fail-closed on any
    malformed input. Best-effort import of solders: if the Solana stack
    is not installed the identity cannot be verified (reported as such)."""
    creator = (manifest.get("creatorId") or "").strip()
    signature = (manifest.get(MANIFEST_SIGNATURE_FIELD) or "").strip()
    if not creator:
        return False, "missing creatorId"
    if not signature:
        return False, "missing signature"

    try:
        from solders.pubkey import Pubkey
        from solders.signature import Signature
    except ImportError:
        return False, "solders not installed; identity unverifiable"

    try:
        pubkey = Pubkey.from_string(creator)
        sig = Signature.from_string(signature)
    except Exception as e:
        return False, f"invalid creatorId or signature encoding: {e}"

    try:
        if sig.verify(pubkey, canonical_manifest_bytes(manifest)):
            return True, "verified"
        return False, "signature mismatch"
    except Exception as e:
        return False, f"verification error: {e}"


# ----------------------------------------------------------------------
# Subscription manager (thin adapter over the closed core)
# ----------------------------------------------------------------------

def _import_core():
    """Locate and import NexusSubscriptionCore, or return None.

    Order: normal import path (packaged builds ship the compiled
    ``nexuslicensing`` package), then the dev checkout pointed at by
    ``AINARA_NEXUS_LICENSING_PATH``."""
    try:
        from nexuslicensing.auth_core import NexusSubscriptionCore
        return NexusSubscriptionCore
    except ImportError:
        pass

    dev_root = os.environ.get(DEV_LICENSING_PATH_ENV, "").strip()
    if dev_root:
        root = Path(dev_root).expanduser().resolve()
        if root.is_dir() and str(root) not in sys.path:
            sys.path.insert(0, str(root))
        try:
            from nexuslicensing.auth_core import NexusSubscriptionCore
            return NexusSubscriptionCore
        except ImportError as e:
            logger.warning(
                f"{DEV_LICENSING_PATH_ENV}={dev_root} did not yield the "
                f"nexuslicensing package: {e}"
            )
    return None


class SubscriptionManager:
    """Fail-closed adapter over the closed subscription core.

    Gated bundles get issuance/status/revocation only when the compiled
    licensing backend is present. All methods raise ValueError for
    invalid bundle identifiers (normalized charset contract) — callers
    translate that into HTTP 400.
    """

    def __init__(self, storage_backend):
        self.storage = storage_backend
        try:
            core_cls = _import_core()
            self._core = core_cls(storage_backend) if core_cls else None
        except Exception as e:
            # The core loads its build secret at import time; a missing or
            # broken setup must degrade to fail-closed, never take down
            # Pybridge startup.
            logger.error(
                f"Nexus licensing core failed to load: {e} — running "
                "fail-closed (gated bundles cannot subscribe)."
            )
            self._core = None
        if self._core is None:
            logger.warning(
                "Nexus licensing backend unavailable — license-gated "
                "bundles cannot subscribe (fail-closed)."
            )
        else:
            logger.info("Nexus licensing backend loaded.")

    @property
    def available(self) -> bool:
        return self._core is not None

    @staticmethod
    def protection_targets(protection, creator_id: str = None):
        """(collection, creator) from a manifest ``protection`` block;
        ``creator`` falls back to the manifest ``creatorId``. Kept in
        sync with the core's identical helper (trivial derivation, needed
        here even when the closed module is absent)."""
        protection = protection or {}
        collection = (protection.get("collection") or "").strip() or None
        creator = (protection.get("creator") or creator_id or "").strip() or None
        return collection, creator

    def subscription_message(self, vendor: str, app: str) -> Optional[str]:
        """Canonical sign message for a bundle, or None when the backend
        is unavailable. Raises ValueError on invalid identifiers."""
        if not self._core:
            return None
        return self._core.subscription_message(vendor, app)

    def verify_subscription(
        self,
        vendor: str,
        app: str,
        protection,
        creator_id: str,
        wallet_address: str,
        signature_arr,
        message_text: str,
    ):
        """Returns ``(success, message, info_or_None)``. Fail-closed when
        the backend is absent."""
        if not self._core:
            return False, "Licensing backend unavailable", None
        collection, creator = self.protection_targets(protection, creator_id)
        return self._core.verify_subscription(
            vendor, app, collection, creator,
            wallet_address, signature_arr, message_text,
        )

    def get_status(self, vendor: str, app: str) -> dict:
        if not self._core:
            return {
                "subscribed": False,
                "reason": "licensing_unavailable",
                "vendor": vendor,
                "app": app,
            }
        return self._core.get_subscription_status(vendor, app)

    def revoke(self, vendor: str, app: str) -> bool:
        if not self._core:
            return False
        return self._core.revoke_subscription(vendor, app)
