from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Union
import numpy as np

class WakeWordBackend(ABC):
    """Abstract base class for Wake Word detection backends"""

    @abstractmethod
    def load_model(self, model_names: Optional[List[str]] = None) -> bool:
        """
        Load the wake word models.

        Args:
            model_names: List of model names or paths to load.
                         If None, loads defaults based on implementation.

        Returns:
            bool: True if successful, False otherwise.
        """
        pass

    @abstractmethod
    def process_chunk(self, audio_chunk: Union[bytes, np.ndarray]) -> Dict[str, float]:
        """
        Process a chunk of audio and return confidence scores.

        Args:
            audio_chunk: Audio data. Can be raw bytes (int16 PCM) or numpy array.

        Returns:
            Dict[str, float]: Dictionary mapping model names to confidence scores (0.0 - 1.0).
        """
        pass

    @abstractmethod
    def get_loaded_models(self) -> List[str]:
        """Return list of loaded model names"""
        pass
