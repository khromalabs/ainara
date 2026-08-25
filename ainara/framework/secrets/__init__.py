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

from __future__ import annotations

import logging

from ainara.framework.config import config
from . import envelope

logger = logging.getLogger(__name__)

SENSITIVE_KEY_MARKERS = ("api_key", "apikey", "secret", "password", "token")


class SecretVaultError(Exception):
    """Base error for vault failures."""


class SecretVaultUnavailable(SecretVaultError):
    """Keystore is locked, missing, or the backend is not installed."""


class SecretVault:
    """Encrypts/decrypts individual config values using a provider-supplied master key.

    The vault is explicit: callers that need a sensitive value must use
    `get_secret()` / `set_secret()` instead of reading the raw config field.
    `ConfigManager` itself is deliberately left untouched.
    """

    def __init__(self, provider):
        self.provider = provider

    def set_secret(self, path: str, plaintext: str) -> None:
        """Encrypt `plaintext` and write it at the exact config `path`."""
        logger.info(f"Setting secret at path: {path}")
        key = self.provider.get_key()
        blob = envelope.encrypt(plaintext, key, aad=path.encode("utf-8"))
        config.set_exact(path, blob)
        logger.info(f"Successfully set encrypted secret at path: {path}")

    def encrypt(self, path: str, plaintext: str) -> str:
        """Encrypt without touching config; returns the enc:v1 blob."""
        logger.info(f"Encrypting value for path: {path}")
        key = self.provider.get_key()
        return envelope.encrypt(plaintext, key, aad=path.encode("utf-8"))

    def get_secret(self, path: str) -> str:
        """Read config `path` and decrypt the value.

        If the value is still plaintext (e.g. before the first migration),
        a warning is logged and the plaintext is returned unchanged.
        """
        raw = config.get_exact(path)
        if raw is None:
            return None

        if isinstance(raw, str) and envelope.is_encrypted(raw):
            key = self.provider.get_key()
            try:
                return envelope.decrypt(
                    raw, key, aad=path.encode("utf-8")
                )
            except Exception as e:
                raise SecretVaultError(
                    f"Failed to decrypt config value at '{path}': {e}"
                ) from e

        logger.warning(
            "Config value at '%s' is not encrypted. "
            "Run the setup wizard to migrate it into the vault.",
            path,
        )
        return raw

    def is_encrypted(self, path: str) -> bool:
        """Return True if the value at `path` uses the enc:v1 envelope."""
        raw = config.get_exact(path)
        return isinstance(raw, str) and envelope.is_encrypted(raw)

    def migrate_plaintext(self, path: str) -> None:
        """Encrypt an existing plaintext value in place (for the Wizard)."""
        value = config.get_exact(path)
        if value is not None and not self.is_encrypted(path):
            self.set_secret(path, value)

    def migrate_all(self, prefix: str = "apis.") -> list:
        """Encrypt all non-empty sensitive strings under the given dotted prefix.

        Only dict paths are traversed; list-indexed values (e.g.
        ``apis.messaging.email.accounts[].password``) are intentionally skipped
        until ConfigManager supports list paths. Writes the config file once.
        """
        if not prefix.endswith("."):
            prefix += "."

        logger.info(f"Starting SecretVault.migrate_all() with prefix: '{prefix}'")
        migrated = []
        skipped_already_encrypted = []
        skipped_non_sensitive = []
        skipped_empty = []

        def walk(current, path):
            if not isinstance(current, dict):
                return
            for key, value in current.items():
                key_path = f"{path}.{key}" if path else key
                if isinstance(value, dict):
                    walk(value, key_path)
                elif isinstance(value, str):
                    if not key_path.startswith(prefix):
                        continue

                    is_sensitive = any(
                        marker in key.lower()
                        for marker in SENSITIVE_KEY_MARKERS
                    )

                    if not is_sensitive:
                        skipped_non_sensitive.append(key_path)
                        continue

                    if not value:
                        skipped_empty.append(key_path)
                        continue

                    if envelope.is_encrypted(value):
                        skipped_already_encrypted.append(key_path)
                        continue

                    try:
                        master_key = self.provider.get_key()
                        current[key] = envelope.encrypt(
                            value, master_key, aad=key_path.encode("utf-8")
                        )
                        logger.info(f"Encrypted sensitive config key: {key_path}")
                        migrated.append(key_path)
                    except Exception as e:
                        logger.error(f"Failed to encrypt config key '{key_path}': {e}", exc_info=True)
                        raise

        walk(config.config, "")

        logger.info(
            f"Vault migration scan summary: found {len(migrated)} key(s) to encrypt. "
            f"Already encrypted: {len(skipped_already_encrypted)} ({skipped_already_encrypted}), "
            f"Empty sensitive keys: {len(skipped_empty)} ({skipped_empty})"
        )

        if migrated:
            logger.info(f"Saving config with {len(migrated)} newly encrypted secrets.")
            config.save()
        else:
            logger.info("Vault migration finished: no plaintext sensitive keys needed encryption.")
        return migrated


def get_vault() -> SecretVault:
    """Lazy singleton wired to the OS-keystore provider."""
    global _vault
    if _vault is None:
        from .keystore import KeystoreProvider
        _vault = SecretVault(KeystoreProvider())
    return _vault


_vault: SecretVault | None = None
