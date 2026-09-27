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

"""Deterministic key derivation from a Solana wallet signature.

Used only during setup/recovery, never on app start. The derived key is
cached in the OS keystore, so day-to-day use never asks for a signature.
"""

from __future__ import annotations

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class WalletKeyDerivation:
    """Derives the same 32-byte master key whenever the same wallet signs the same message."""

    # Dedicated message — intentionally different from the login message in auth.py
    MESSAGE = "Ainara Secure Storage Key Derivation v1"

    @staticmethod
    def derive_signature(signature_bytes: bytes, wallet_address: str) -> bytes:
        """Turn the 64-byte Ed25519 signature into the master key."""
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=wallet_address.encode("utf-8"),
            info=b"ainara-vault-v1",
        )
        return hkdf.derive(signature_bytes)

    @staticmethod
    def verify_signature(
        wallet_address: str, signature_bytes: bytes, message: str = None
    ) -> bool:
        """Return True if the wallet signed the given message."""
        from solders.pubkey import Pubkey
        from solders.signature import Signature

        try:
            pubkey = Pubkey.from_string(wallet_address)
            msg_bytes = (message or WalletKeyDerivation.MESSAGE).encode("utf-8")
            sig = Signature.from_bytes(signature_bytes)
            return sig.verify(pubkey, msg_bytes)
        except Exception:
            return False

    @staticmethod
    def request_signature(wallet_address: str) -> bytes:
        """Placeholder for the Electron wallet adapter.

        The Wizard will:
        1. Present the MESSAGE
        2. Get the user's wallet signature
        3. Pass the raw 64 bytes to derive_signature()
        """
        raise NotImplementedError(
            "Wallet signature request must be wired to the Electron/Pybridge adapter."
        )
