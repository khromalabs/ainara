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

"""Pure AES-256-GCM envelope for config values.

Format: enc:v1:<base64-nonce>:<base64-ciphertext>:<base64-tag>
No I/O here — keeps this module trivially unit-testable.
"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


_PREFIX = "enc:v1:"


def is_encrypted(payload: str) -> bool:
    """Return True if the payload looks like an enc:v1 envelope."""
    return isinstance(payload, str) and payload.startswith(_PREFIX)


def encrypt(plaintext: str, key: bytes, aad: bytes = b"") -> str:
    """Encrypt `plaintext` into an enc:v1 string.

    `aad` should be the config path (e.g. ``b"apis.cryptoexchanges.hyperliquid.secret"``)
    so a blob cannot be moved from one field to another.
    """
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(
        nonce, plaintext.encode("utf-8"), aad
    )
    ciphertext, tag = ct[:-16], ct[-16:]

    encoded = ":".join(
        base64.urlsafe_b64encode(x).decode("ascii")
        for x in (nonce, ciphertext, tag)
    )
    return _PREFIX + encoded


def decrypt(payload: str, key: bytes, aad: bytes = b"") -> str:
    """Decrypt an enc:v1 string back to plaintext."""
    if not is_encrypted(payload):
        raise ValueError("Not an encrypted payload")

    body = payload[len(_PREFIX):]
    parts = body.split(":")
    if len(parts) != 3:
        raise ValueError("Invalid enc:v1 envelope")

    nonce_b64, ciphertext_b64, tag_b64 = parts
    nonce = base64.urlsafe_b64decode(nonce_b64)
    ciphertext = base64.urlsafe_b64decode(ciphertext_b64)
    tag = base64.urlsafe_b64decode(tag_b64)

    plaintext = AESGCM(key).decrypt(
        nonce, ciphertext + tag, aad
    )
    return plaintext.decode("utf-8")
