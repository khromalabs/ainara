import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Union
import numpy as np
import platform

from ainara.framework.wakeword.base import WakeWordBackend
from ainara.framework.config import ConfigManager

logger = logging.getLogger(__name__)


class OpenWakeWordBackend(WakeWordBackend):
    """
    Wake Word backend using the openWakeWord library.
    Requires: pip install openwakeword
    """

    def __init__(self, config: ConfigManager):
        self.config = config
        self.model = None
        self.chunk_size = 1280  # openWakeWord standard chunk size (80ms @ 16kHz)
        self._has_library = False

        # Define Model Directories
        # 1. User Data Directory (Persistent downloads/custom models)
        self.user_models_dir = Path(self.config.get_default_data_dir()) / "wakeword"

        # 2. Bundled Resources Directory (App distribution)
        self.bundled_models_dir = (
            self._get_resource_base_dir() / "resources" / "stt" / "wakeword"
        )

        try:
            import openwakeword  # noqa: 401
            from openwakeword.model import Model  # noqa: 401
            self._has_library = True
            # Suppress verbose openwakeword logs
            logging.getLogger("openwakeword").setLevel(logging.WARNING)
        except ImportError:
            logger.error("openwakeword library not found. Please install it via pip.")

    def _get_resource_base_dir(self) -> Path:
        """Determine the base directory for resources (project root or MEIPASS)."""
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            return Path(sys._MEIPASS)
        else:
            # ainara/framework/wakeword/openwakeword.py -> root
            return Path(__file__).parent.parent.parent.parent

    def _resolve_model_path(self, model_name: str) -> str:
        """
        Resolve the path to a model file.
        Prioritizes .tflite files in user data, then bundled resources.
        Falls back to the model name string (for built-in models).
        """
        # If the name already has an extension, use it. Otherwise default to .tflite
        if model_name.endswith(".tflite") or model_name.endswith(".onnx"):
            filename = model_name
        else:
            filename = f"{model_name}.tflite"

        # 1. Check User Data Directory
        user_path = self.user_models_dir / filename
        if user_path.exists():
            logger.info(f"Found custom wake word model in user data: {user_path}")
            return str(user_path)

        # 2. Check Bundled Resources
        bundled_path = self.bundled_models_dir / filename
        if bundled_path.exists():
            logger.info(f"Found bundled wake word model: {bundled_path}")
            return str(bundled_path)

        # 3. Fallback to original name (assumes built-in model like 'hey_jarvis')
        return model_name

    def load_model(self, model_names: Optional[List[str]] = None) -> bool:
        if not self._has_library:
            return False

        try:
            import openwakeword
            from openwakeword.model import Model

            # Download default models if they don't exist
            # This is safe to call repeatedly as it checks existence
            try:
                openwakeword.utils.download_models()
            except Exception as e:
                logger.warning(f"Could not auto-download models: {e}")

            # Determine which models to load
            models_to_load = []
            if model_names:
                models_to_load = model_names
            else:
                config_models = self.config.get("wakeword", {}).get("models", [])
                if config_models:
                    models_to_load = config_models
                else:
                    models_to_load = ["aye_nah_rah.onnx"]

            # Resolve paths for custom models
            resolved_models = [self._resolve_model_path(m) for m in models_to_load]

            # Initialize the model
            inference_framework = self.config.get("wakeword", {}).get("inference_framework", "onnx")

            # TODO "vad_threshold" generates error:
            # Error processing wake word chunk: [ONNXRuntimeError] : 2 : INVALID_ARGUMENT : Non-zero status code returned while running If node. Name:'If_25' Status Message: Non-zero status code returned while running Conv node. Name:'Conv_132' Status Message: Invalid input shape: {1}
            # vad_threshold = self.config.get("wakeword", {}).get("vad_threshold", 0.5)
            enable_speex_noise_suppression = self.config.get("wakeword", {}).get("enable_speex_noise_suppression", True)

            logger.info(f"Loading openWakeWord models: {resolved_models} using {inference_framework}")

            params = {
                'wakeword_models': resolved_models,
                'inference_framework': inference_framework,
                # 'vad_threshold': vad_threshold
            }

            # TODO Not compatible with Windows (yet?)
            if platform.system() != 'Windows':
                params['enable_speex_noise_suppression'] = enable_speex_noise_suppression

            self.model = Model(**params)

            return True

        except Exception as e:
            logger.error(f"Failed to load openWakeWord models: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    def process_chunk(self, audio_chunk: Union[bytes, np.ndarray]) -> Dict[str, float]:
        if not self.model:
            logger.debug("process_chunk called but model is None")
            return {}

        try:
            # Convert bytes to numpy if necessary
            if isinstance(audio_chunk, bytes):
                # Assume 16-bit PCM, 16kHz
                audio_data = np.frombuffer(audio_chunk, dtype=np.int16)
            else:
                audio_data = audio_chunk

            # openWakeWord predict() handles buffering internally
            # It returns predictions for the current buffer state
            predictions = self.model.predict(audio_data)

            # logger.debug(f"OpenWakeWord raw predictions: {predictions}")

            # predictions is a dict {model_name: score}
            return predictions

        except Exception as e:
            logger.error(f"Error processing wake word chunk: {e}")
            return {}

    def get_loaded_models(self) -> List[str]:
        if self.model and hasattr(self.model, "models"):
            return list(self.model.models.keys())
        return []
