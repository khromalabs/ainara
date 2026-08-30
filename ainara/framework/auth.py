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

import logging

logger = logging.getLogger(__name__)


class AuthManager:
    """Thin adapter. All verification logic (NFT ownership, token signing,
    machine binding) lives in supporters.auth_core (closed, obfuscated).
    Absent module => public mode."""

    def __init__(self, storage_backend):
        self.storage = storage_backend
        self._core = None
        try:
            from supporters.auth_core import PremiumAuthCore
            self._core = PremiumAuthCore(storage_backend)
        except Exception as e:
            logger.info(f"Premium module unavailable ({e}); running in public mode.")

    def get_portal_html(self):
        if self._core:
            return self._core.get_portal_html()
        return "<html><body><p>Licensing unavailable in public mode.</p></body></html>"

    def is_authorized(self):
        if self._core:
            return self._core.is_authorized()
        return {"authorized": True, "mode": "public"}

    def verify_and_login(self, wallet_address, signature_arr, message_text):
        if self._core:
            return self._core.verify_and_login(
                wallet_address, signature_arr, message_text
            )
        return False, "Licensing module not available"
