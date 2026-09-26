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
from typing import Any, Dict

from .base import TTSBackend

logger = logging.getLogger(__name__)


def create_tts_backend(tts_config: Dict[str, Any] = None) -> TTSBackend:
    """
    Factory function to create a TTS backend based on configuration.
    Uses lazy loading to avoid importing heavy dependencies (like torch)
    unless the specific backend is requested.
    """
    if tts_config is None:
        tts_config = {}

    # Piper is the default option
    # backend_name = tts_config.get("selected_module", "piper").lower()
    backend_name = "kokoro"
    logger.info(f"Initializing TTS backend: {backend_name}")

    try:
        if backend_name == "coqui":
            from .coqui import CoquiTTS

            return CoquiTTS()

        elif backend_name == "elevenlabs":
            from .elevenlabs import ElevenLabsTTS

            return ElevenLabsTTS()

        elif backend_name == "macos":
            from .macos import MacOSTTS

            return MacOSTTS()

        elif backend_name == "kokoro":
            from .kokoro import KokoroTTS

            return KokoroTTS()

        elif backend_name == "remote":
            from .remote import RemoteTTS

            return RemoteTTS()

        elif backend_name == "piper":
            from .piper import PiperTTS

            return PiperTTS()

        else:
            logger.warning(
                f"Unknown TTS backend '{backend_name}'. Falling back to Piper."
            )
            from .piper import PiperTTS

            return PiperTTS()

    except Exception as e:
        logger.error(f"Failed to initialize TTS backend '{backend_name}': {e}")

        # # Fallback safety net
        # if backend_name != "piper":
        #     logger.info("Attempting to fall back to PiperTTS...")
        #     try:
        #         from .piper import PiperTTS
        #
        #         return PiperTTS()
        #     except Exception as fallback_error:
        #         logger.critical(
        #             f"Fallback to PiperTTS failed: {fallback_error}"
        #         )
        #         raise e
        raise e
