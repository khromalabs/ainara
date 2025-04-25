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

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class STTBackend(ABC):
    """Abstract base class for Speech-to-Text backends"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize STT backend with configuration

        Args:
            config: Dictionary containing STT configuration parameters
                   Should match structure defined in orakle.yaml
        """
        self.config = config or {}

    @abstractmethod
    def listen(self) -> str:
        """Record audio and convert to text"""
        pass

    @abstractmethod
    def transcribe_file(self, audio_file: str) -> str:
        """Transcribe an existing audio file to text"""
        pass