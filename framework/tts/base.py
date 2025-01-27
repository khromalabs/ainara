from abc import ABC, abstractmethod
import logging
import subprocess
from typing import Optional, Tuple


class TTSBackend(ABC):
    """Abstract base class for Text-to-Speech backends"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    @abstractmethod
    def speak(self, text: str) -> bool:
        """Convert text to speech

        Args:
            text: The text to convert to speech

        Returns:
            bool: True if successful, False otherwise
        """
        pass

    @abstractmethod
    def stop(self) -> bool:
        """Stop current speech

        Returns:
            bool: True if successful, False otherwise
        """
        pass

    @abstractmethod
    def generate_audio(self, text: str) -> Tuple[str, float]:
        """Generate audio file for text and return its path and duration

        Args:
            text: The text to convert to speech

        Returns:
            Tuple[str, float]: Path to generated audio file and its duration in seconds
        """
        pass

    @abstractmethod
    def play_audio(self, audio_file: str) -> bool:
        """Play audio file asynchronously

        Args:
            audio_file: Path to audio file to play

        Returns:
            bool: True if playback started successfully, False otherwise
        """
        pass
