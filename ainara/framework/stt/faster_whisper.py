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
import os
import platform
from typing import Any, Dict, Optional

from huggingface_hub import hf_hub_download
from huggingface_hub.utils import HfHubHTTPError

from ainara.framework.config import ConfigManager
from ainara.framework.stt.base import STTBackend

logger = logging.getLogger(__name__)

# logging.getLogger("faster_whisper").setLevel(logging.DEBUG)

config_manager = ConfigManager()


def get_optimal_whisper_config():
    """
    Determine optimal faster-whisper configuration based on available hardware.
    Returns a dict with recommended configuration parameters.
    """
    config = {
        "model_size": "small",
        "device": "cpu",
        "compute_type": "int8_float32",
        "beam_size": 5,
        "vad_filter": True,
        "vad_parameters": {
            "min_silence_duration_ms": 500,
            "threshold": 0.4,  # Lowered for better sensitivity
            "min_speech_duration_ms": 250
        },
        "word_timestamps": False,
        "condition_on_previous_text": False,
        # Add a prompt to help recognize specific words
        "initial_prompt": "Ainara is a personal AI assistant."
    }

    try:
        import torch

        # Check if CUDA is available
        if torch.cuda.is_available():
            # Get GPU info
            gpu_name = torch.cuda.get_device_name(0)
            vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9

            logger.info(f"Detected GPU: {gpu_name} with {vram_gb:.1f}GB VRAM")

            # Adjust model size based on VRAM
            if vram_gb >= 8:  # High-end GPUs
                # Can use larger models with good performance
                config["model_size"] = "large-v3"
                config["beam_size"] = 5
            elif vram_gb >= 4:  # Mid-range GPUs like GTX 1650 Ti
                # Balance between speed and accuracy
                config["model_size"] = "small"
                config["beam_size"] = 4
            elif vram_gb >= 2:  # Entry-level GPUs
                # Optimize for speed
                config["model_size"] = "base"
                config["beam_size"] = 3
                # More aggressive VAD for speed
                config["vad_parameters"]["threshold"] = 0.6
            else:  # Low VRAM GPUs
                # Highly optimized for limited resources
                config["model_size"] = "tiny"
                config["beam_size"] = 2
                config["vad_parameters"]["threshold"] = 0.7

            # Always use int8_float32 with CUDA to avoid the exclamation marks issue
            config["device"] = "cuda"
            # Use float16 on Windows to avoid silent failures
            if platform.system() == "Windows":
                config["compute_type"] = "float16"
            else:
                config["compute_type"] = "int8_float32"

        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            # Apple Silicon optimization
            logger.info("Detected Apple Silicon GPU")
            config["model_size"] = "small"
            config["device"] = "mps"
            config["compute_type"] = "float16"
            config["beam_size"] = 4

        else:
            # CPU optimization
            import psutil
            ram_gb = psutil.virtual_memory().total / 1e9
            cpu_count = psutil.cpu_count(logical=False) or 2

            logger.info(f"Using CPU with {ram_gb:.1f}GB RAM, {cpu_count} cores")

            # Adjust based on available RAM and CPU cores
            if ram_gb >= 16 and cpu_count >= 8:
                # High-end desktop/server
                config["model_size"] = "small"
                config["beam_size"] = 4
            elif ram_gb >= 8 and cpu_count >= 4:
                # Mid-range system
                config["model_size"] = "base"
                config["beam_size"] = 3
            else:
                # Low-end system
                config["model_size"] = "tiny"
                config["beam_size"] = 2
                # More aggressive VAD for speed
                config["vad_parameters"]["threshold"] = 0.7

            config["device"] = "cpu"
            config["compute_type"] = "int8"
            config["cpu_threads"] = cpu_count

    except ImportError:
        # Fallback to conservative defaults if torch/psutil not available
        logger.info("Could not detect hardware capabilities, using conservative defaults")
        config["model_size"] = "base"
        config["device"] = "cpu"
        config["compute_type"] = "int8"
        config["beam_size"] = 3

    logger.info(f"Selected configuration: model_size={config['model_size']}, "
                f"device={config['device']}, "
                f"beam_size={config['beam_size']}")

    return config


class FasterWhisperSTT(STTBackend):
    """Faster-Whisper implementation of STT backend"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)

        # Check dependencies first
        try:
            from ainara.framework.dependency_checker import \
                DependencyChecker

            stt_deps = DependencyChecker.check_stt_dependencies()

            # Check if CUDA is available
            cuda_available = stt_deps["cuda"]["available"]

            # # Double-check CUDA availability directly with torch on Windows
            # if not cuda_available and platform.system() == "Windows":
            #     try:
            #         import torch
            #         if torch.cuda.is_available():
            #             cuda_available = True
            #             logger.info("CUDA detected directly through torch on Windows")
            #     except ImportError:
            #         pass
        except ImportError:
            # Dependency checker not available, assume CUDA is not available
            cuda_available = False
            logger.info(
                "Dependency checker not available, assuming CUDA is not"
                " available"
            )

        # Get configuration from user or config file
        config_manager = ConfigManager()
        user_model_size = config_manager.get("stt.modules.faster_whisper.model_size", None)
        user_device = config_manager.get("stt.modules.faster_whisper.device", None)
        user_compute_type = config_manager.get("stt.modules.faster_whisper.compute_type", None)

        # Get optimal configuration based on hardware
        optimal_config = get_optimal_whisper_config()

        # Use user config if provided, otherwise use optimal config
        self.model_size = user_model_size or optimal_config.get("model_size", "small")

        # TODO Fix CUDA dependencies error
        # By not force CPU mode on Linux regardless of other settings
        if platform.system() == "Linux":
            self.device = "cpu"
            self.compute_type = "int8"
            logger.info("Forcing CPU mode on Linux to avoid potential library issues.")
        elif platform.system() == "Darwin":  # macOS
            self.device = "cpu"
            self.compute_type = "int8"  # Optimal for CPU
            logger.info(
                "Forcing CPU mode on macOS (Darwin) as MPS is not supported by CTranslate2 (a faster-whisper dependency)."
            )
        else:
            self.device = user_device or optimal_config.get("device", "cpu")
            self.compute_type = user_compute_type or optimal_config.get("compute_type", "int8")

        # If CUDA is not available but device is set to cuda, force CPU mode
        if not cuda_available and self.device == "cuda":
            logger.info(
                "CUDA dependencies not available. Forcing CPU mode for"
                " Faster-Whisper."
            )
            self.device = "cpu"
            self.compute_type = "int8"

        # Store transcription parameters
        self.beam_size = optimal_config.get("beam_size", 5)
        self.vad_filter = optimal_config.get("vad_filter", True)
        self.vad_parameters = optimal_config.get("vad_parameters", {
            "min_silence_duration_ms": 500,
            "threshold": 0.5,
            "min_speech_duration_ms": 250
        })
        self.word_timestamps = optimal_config.get("word_timestamps", False)
        self.condition_on_previous_text = optimal_config.get("condition_on_previous_text", False)
        self.initial_prompt = config_manager.get(
            "stt.modules.faster_whisper.initial_prompt",
            optimal_config.get("initial_prompt")
        )
        # VAD parameters for the listen() method
        self.silence_threshold = config_manager.get(
            "stt.modules.faster_whisper.silence_threshold", 500
        )
        self.silence_duration_s = config_manager.get(
            "stt.modules.faster_whisper.silence_duration_s", 2
        )

        # If using CPU, set number of threads
        if self.device == "cpu":
            self.num_workers = optimal_config.get("cpu_threads", os.cpu_count() or 4)
            logger.info(f"Using {self.num_workers} CPU threads for Faster-Whisper")
        else:
            self.num_workers = 1

        # Log the configuration
        logger.info(
            f"Initializing Faster-Whisper with model={self.model_size}, "
            f"device={self.device}, compute_type={self.compute_type}, "
            f"beam_size={self.beam_size}"
        )
        self.model = None

    def _load_model(self):
        """Load the model if not already loaded"""
        if self.model is None:
            logger.info(f"Loading Faster-Whisper model {self.model_size} (first time)...")
            try:
                from faster_whisper import WhisperModel

                # Based on the GitHub issue #1244, float16 compute_type with CUDA can cause issues
                # On Windows, prefer float16 with CUDA to avoid silent failures
                if self.device == "cuda":
                    if platform.system() == "Windows":
                        if self.compute_type != "float16" and self.compute_type != "float32":
                            logger.warning("On Windows with CUDA, changing compute_type to float16 to avoid silent failures")
                            self.compute_type = "float16"
                    else:
                        # On other platforms, use int8_float32 with CUDA
                        if self.compute_type == "float16":
                            logger.warning("Changing compute_type from float16 to int8_float32 to avoid known issues with CUDA")
                            self.compute_type = "int8_float32"

                logger.info(f"compute_type: {self.compute_type}")

                # Get the cache directory for whisper
                cache_dir = config_manager.get_subdir(
                    "cache.directory",
                    "whisper"
                )

                logger.info(f"Using cache directory: {cache_dir}")

                # Prepare kwargs based on device
                model_kwargs = {
                    "model_size_or_path": self.model_size,
                    "device": self.device,
                    "compute_type": self.compute_type,
                    "download_root": cache_dir,
                }

                # Only add cpu_threads for CPU device
                if self.device == "cpu":
                    model_kwargs["cpu_threads"] = self.num_workers

                logger.info(f"Loading model with device={self.device}, compute_type={self.compute_type}")
                self.model = WhisperModel(**model_kwargs)

                logger.info(f"Faster-Whisper model {self.model_size} loaded successfully")
            except Exception as e:
                logger.info(f"Error loading Faster-Whisper model: {e}")
                import traceback
                logger.info(traceback.format_exc())  # Print full traceback

                # If CUDA failed, try falling back to CPU
                if self.device == "cuda":
                    logger.warning("CUDA loading failed, falling back to CPU")
                    try:
                        self.device = "cpu"
                        self.compute_type = "int8"
                        logger.info(f"Retrying with device={self.device}, compute_type={self.compute_type}")

                        # Get the cache directory for whisper
                        cache_dir = config_manager.get_subdir(
                            "cache.directory",
                            "whisper"
                        )

                        self.model = WhisperModel(
                            self.model_size,
                            device="cpu",
                            compute_type="int8",
                            download_root=cache_dir,
                            cpu_threads=self.num_workers
                        )
                        logger.info("Successfully loaded model with CPU fallback")
                    except Exception as cpu_error:
                        logger.error(f"CPU fallback also failed: {cpu_error}")
                        raise
                else:
                    raise
        else:
            logger.info("Using already loaded Faster-Whisper model (cached)")

    def transcribe_file(self, audio_file: str) -> str:
        """Transcribe an audio file using Faster-Whisper"""

        if not self.model:
            self._load_model()

        # logger.info("transcribe_file 1")
        try:
            # logger.info("transcribe_file 2")

            # Transcribe the audio with the optimized parameters
            segments, info = self.model.transcribe(
                audio_file,
                beam_size=self.beam_size,
                language="en",  # Force English language
                vad_filter=self.vad_filter,
                vad_parameters=self.vad_parameters,
                word_timestamps=self.word_timestamps,
                condition_on_previous_text=self.condition_on_previous_text,
                initial_prompt=self.initial_prompt
            )

            # Combine all segments into a single transcript
            transcript = " ".join(segment.text for segment in segments)

            logger.info(
                f"Detected language: {info.language} with probability"
                f" {info.language_probability:.2f}"
            )
            logger.info(f"Transcription result: {transcript}")
            # logger.info("transcribe_file 3")

            return transcript
        except Exception as e:
            # logger.info("transcribe_file 4")
            logger.error(f"Error transcribing with Faster-Whisper: {e}")
            import traceback

            logger.error(traceback.format_exc())

            # Try to provide more helpful error information
            if "CUDA" in str(e) or "GPU" in str(e):
                logger.error("This appears to be a CUDA-related error. Try setting 'compute_type' to 'float16' in your config.")
            elif "out of memory" in str(e).lower():
                logger.error("GPU memory error. Try using a smaller model or setting 'device' to 'cpu' in your config.")
            return ""

    def listen(self) -> str:
        """
        Record audio and convert to text using Faster-Whisper
        Cross-platform implementation using PyAudio
        """
        try:

            if not self.model:
                self._load_model()

            import os
            import tempfile
            import wave

            import pyaudio

            # PyAudio parameters
            FORMAT = pyaudio.paInt16
            CHANNELS = 1
            RATE = 16000
            CHUNK = 1024

            # Create a temporary file for the recording
            fd, temp_file = tempfile.mkstemp(suffix=".wav")
            os.close(fd)

            try:
                audio = pyaudio.PyAudio()
                stream = audio.open(
                    format=FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    input=True,
                    frames_per_buffer=CHUNK,
                )

                logger.info(
                    "Recording... Speak now (will auto-stop after silence)"
                )

                frames = []
                silent_chunks = 0
                has_speech = False

                # Record until we detect speech followed by silence
                while True:
                    data = stream.read(CHUNK)
                    frames.append(data)

                    # Simple silence detection
                    amplitude = max(
                        abs(
                            int.from_bytes(
                                data[i: i + 2],
                                byteorder="little",
                                signed=True,
                            )
                        )
                        for i in range(0, len(data), 2)
                    )

                    if amplitude > self.silence_threshold:
                        silent_chunks = 0
                        has_speech = True
                    else:
                        silent_chunks += 1

                    # Stop after N seconds of silence if we've detected speech before
                    if has_speech and silent_chunks > RATE / CHUNK * self.silence_duration_s:
                        break

                    # Also stop if recording gets too long (30 seconds)
                    if len(frames) > RATE / CHUNK * 30:
                        break

                logger.info("Recording stopped, transcribing...")

                # Stop and close the stream
                stream.stop_stream()
                stream.close()
                audio.terminate()

                # Save the recorded audio to the temporary file
                with wave.open(temp_file, "wb") as wf:
                    wf.setnchannels(CHANNELS)
                    wf.setsampwidth(audio.get_sample_size(FORMAT))
                    wf.setframerate(RATE)
                    wf.writeframes(b"".join(frames))

                # Transcribe the recorded audio
                transcript = self.transcribe_file(temp_file)
                return transcript

            finally:
                # Clean up the temporary file
                if os.path.exists(temp_file):
                    os.remove(temp_file)

        except Exception as e:
            logger.info(f"Error in Faster-Whisper listen: {e}")
            return ""

    def check_model(self) -> Dict[str, Any]:
        """Check if Whisper models are available locally."""
        try:
            cache_dir = config_manager.get_subdir("cache.directory", "whisper")
            model_path = hf_hub_download(
                repo_id=f"guillaumekln/faster-whisper-{self.model_size}",
                filename="model.bin",
                cache_dir=cache_dir,
                local_files_only=True,
            )
            return {
                "initialized": True,
                "message": f"Whisper {self.model_size} model is available",
                "path": model_path,
            }
        except HfHubHTTPError:
            # This exception is raised when the file is not found in the cache with local_files_only=True
            return {
                "initialized": False,
                "message": f"Whisper {self.model_size} model is not available",
            }
        except Exception as e:
            logger.error(f"Error checking Whisper models: {e}")
            return {
                "initialized": False,
                "message": f"Error checking Whisper models: {str(e)}",
            }

    def setup_model(self) -> Dict[str, Any]:
        """Download and setup whisper models."""
        try:
            logger.info(f"Downloading Faster-Whisper {self.model_size} model...")
            cache_dir = config_manager.get_subdir("cache.directory", "whisper")
            model_path = hf_hub_download(
                repo_id=f"guillaumekln/faster-whisper-{self.model_size}",
                filename="model.bin",
                cache_dir=cache_dir,
            )
            logger.info(
                f"Faster-Whisper {self.model_size} model downloaded to {model_path}"
            )
            return {
                "success": True,
                "message": f"Whisper {self.model_size} model downloaded successfully",
                "path": model_path,
            }
        except Exception as e:
            logger.error(f"Error downloading whisper model: {e}")
            return {
                "success": False,
                "message": f"Error downloading whisper model: {str(e)}",
            }
