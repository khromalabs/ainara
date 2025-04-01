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
