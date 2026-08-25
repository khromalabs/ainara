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

"""OS keystore-backed KeyProvider using the `keyring` package.

Optional dependency flag follows the same pattern as auth.py/SOLANA_AVAILABLE.
"""

from __future__ import annotations

import base64
import logging

try:
    import keyring

    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False

from . import SecretVaultUnavailable

logger = logging.getLogger(__name__)


class KeystoreProvider:
    """Stores the 32-byte master key as one password in the OS keyring."""

    SERVICE = "ainara"
    USERNAME = "vault-master-key"

    def is_available(self) -> bool:
        """Check that keyring is installed and the backend is usable."""
        if not KEYRING_AVAILABLE:
            logger.warning("Keystore unavailable: 'keyring' package is not installed.")
            return False
        try:
            kr = keyring.get_keyring()
            logger.info(f"Keystore provider checking backend: {type(kr).__name__} (priority: {getattr(kr, 'priority', 'unknown')})")
            return True
        except Exception as e:
            logger.warning(f"Keystore unavailable: failed to get keyring backend: {e}")
            return False

    def get_key(self) -> bytes:
        """Return the master key or raise SecretVaultUnavailable."""
        if not KEYRING_AVAILABLE:
            logger.error("Attempted to get master key, but 'keyring' package is not installed.")
            raise SecretVaultUnavailable(
                "keyring package is not installed."
            )

        logger.info(f"Fetching master key from keyring (service='{self.SERVICE}', username='{self.USERNAME}').")
        try:
            raw = keyring.get_password(self.SERVICE, self.USERNAME)
        except Exception as e:
            logger.error(f"Error accessing OS keyring to retrieve master key: {e}")
            raise SecretVaultUnavailable(f"Error reading from OS keyring: {e}") from e

        if not raw:
            logger.warning("Master key not found in OS keyring.")
            raise SecretVaultUnavailable(
                "Master key not found in OS keyring. "
                "Run the setup wizard in a desktop session."
            )
        logger.info("Successfully retrieved and decoded master key from OS keyring.")
        return base64.b64decode(raw)

    def set_key(self, key: bytes) -> None:
        """Store the master key in the OS keyring."""
        if not KEYRING_AVAILABLE:
            logger.error("Attempted to set master key, but 'keyring' package is not installed.")
            raise SecretVaultUnavailable(
                "keyring package is not installed."
            )
        logger.info(f"Storing master key ({len(key)} bytes) in OS keyring (service='{self.SERVICE}', username='{self.USERNAME}').")
        try:
            keyring.set_password(
                self.SERVICE,
                self.USERNAME,
                base64.b64encode(key).decode("ascii"),
            )
            logger.info("Successfully stored master key in OS keyring.")
        except Exception as e:
            logger.error(f"Failed to store master key in OS keyring: {e}")
            raise SecretVaultUnavailable(f"Failed to store key in OS keyring: {e}") from e

    def delete_key(self) -> None:
        """Remove the master key from the keyring."""
        if not KEYRING_AVAILABLE:
            logger.error("Attempted to delete master key, but 'keyring' package is not installed.")
            raise SecretVaultUnavailable(
                "keyring package is not installed."
            )
        logger.info(f"Deleting master key from OS keyring (service='{self.SERVICE}', username='{self.USERNAME}').")
        try:
            keyring.delete_password(self.SERVICE, self.USERNAME)
            logger.info("Successfully deleted master key from OS keyring.")
        except Exception as e:
            logger.error(f"Failed to delete master key from OS keyring: {e}")
            raise SecretVaultUnavailable(f"Failed to delete key from OS keyring: {e}") from e
