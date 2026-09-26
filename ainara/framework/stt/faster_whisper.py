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
import math
import os
import platform
# import subprocess
from collections import deque
from typing import Any, Dict, Optional

from huggingface_hub import hf_hub_download
from huggingface_hub.utils import HfHubHTTPError

from ainara.framework.config import ConfigManager
from ainara.framework.stt.base import STTBackend

logger = logging.getLogger(__name__)

# logging.getLogger("faster_whisper").setLevel(logging.DEBUG)

config_manager = ConfigManager()

ALLOW_GPU = False


def get_optimal_whisper_config():
    """
    Determine optimal faster-whisper configuration based on available hardware.
    Returns a dict with recommended configuration parameters.
    """
    config = {
        "model_size": "small",
        "device": "cpu",
        "compute_type": "int8",
        "beam_size": 5,
        "best_of": 5,
        "patience": 1.0,
        "length_penalty": 1.0,
        "vad_filter": True,
        "vad_parameters": {
            "min_silence_duration_ms": 500,
            "threshold": 0.4,
            "min_speech_duration_ms": 250,
        },
        "word_timestamps": False,
        "condition_on_previous_text": False,
        "initial_prompt": "Ainara is a personal AI assistant.",
    }

    # Helper to detect CUDA VRAM without torch
    def get_cuda_vram_gb():
        # TODO Disabled, better use the DependencyChecker module
        return 0
        # try:
        #     output = subprocess.check_output(
        #         [
        #             "nvidia-smi",
        #             "--query-gpu=memory.total",
        #             "--format=csv,noheader,nounits",
        #         ],
        #         encoding="utf-8",
        #     )
        #     # Output is like "8192\n" (in MB). Take the first GPU.
        #     return float(output.strip().split("\n")[0]) / 1024
        # except Exception:
        #     return 0.0

    vram_gb = get_cuda_vram_gb()

    # 1. CUDA Detection
    if vram_gb > 0 and ALLOW_GPU:
        logger.info(f"Detected NVIDIA GPU with {vram_gb:.1f}GB VRAM")

        if vram_gb >= 8:
            config["model_size"] = "large-v3"
            config["beam_size"] = 5
            config["best_of"] = 5
        elif vram_gb >= 4:
            config["model_size"] = "small"
            config["beam_size"] = 4
            config["best_of"] = 4
        elif vram_gb >= 2:
            config["model_size"] = "base"
            config["beam_size"] = 3
            config["best_of"] = 3
            config["vad_parameters"]["threshold"] = 0.6
        else:
            config["model_size"] = "tiny"
            config["beam_size"] = 2
            config["best_of"] = 2
            config["vad_parameters"]["threshold"] = 0.7

        config["device"] = "cuda"
        # Use float16 on Windows to avoid silent failures, int8_float32 on Linux
        if platform.system() == "Windows":
            config["compute_type"] = "float16"
        else:
            config["compute_type"] = "int8_float32"

    # 2. Apple Silicon Detection
    elif platform.system() == "Darwin" and platform.machine() == "arm64":
        logger.info("Detected Apple Silicon (ARM64)")
        # CTranslate2 runs on CPU for Mac, but optimized
        config["model_size"] = "small"
        config["device"] = "cpu"
        config["compute_type"] = "float16"  # Supported on ARM64 CPU
        config["beam_size"] = 4

    # 3. CPU Fallback
    else:
        try:
            import psutil

            ram_gb = psutil.virtual_memory().total / 1e9
            cpu_count = psutil.cpu_count(logical=False) or 2

            logger.info(
                f"Using CPU with {ram_gb:.1f}GB RAM, {cpu_count} cores"
            )

            if ram_gb >= 16 and cpu_count >= 8:
                config["model_size"] = "small"
                config["beam_size"] = 4
                config["best_of"] = 4
            elif ram_gb >= 8 and cpu_count >= 4:
                config["model_size"] = "base"
                config["beam_size"] = 3
                config["best_of"] = 3
            else:
                config["model_size"] = "tiny"
                config["beam_size"] = 2
                config["best_of"] = 2
                config["vad_parameters"]["threshold"] = 0.7

            config["cpu_threads"] = cpu_count
        except ImportError:
            logger.warning("psutil not found, using conservative defaults")
            config["model_size"] = "base"
            config["beam_size"] = 3
            config["best_of"] = 3

        config["device"] = "cpu"
        config["compute_type"] = "int8"

    logger.info(
        f"Selected configuration: model_size={config['model_size']}, "
        f"device={config['device']}, "
        f"beam_size={config['beam_size']}"
    )

    return config


class FasterWhisperSTT(STTBackend):
    """Faster-Whisper implementation of STT backend"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)

        # Get optimal configuration based on hardware (now torch-free)
        optimal_config = get_optimal_whisper_config()

        # Determine if CUDA is effectively available based on the detection
        cuda_available = optimal_config["device"] == "cuda"

        # Get configuration from user or config file
        config_manager = ConfigManager()
        user_model_size = config_manager.get(
            "stt.modules.faster_whisper.model_size", None
        )
        user_device = config_manager.get(
            "stt.modules.faster_whisper.device", None
        )
        user_compute_type = config_manager.get(
            "stt.modules.faster_whisper.compute_type", None
        )

        # Use user config if provided, otherwise use optimal config
        self.model_size = user_model_size or optimal_config.get(
            "model_size", "small"
        )

        # Platform specific overrides
        if platform.system() == "Linux" and not cuda_available:
            self.device = "cpu"
            self.compute_type = "int8"
        elif platform.system() == "Darwin":  # macOS
            self.device = "cpu"
            self.compute_type = (
                "int8"
                if optimal_config["compute_type"] != "float16"
                else "float16"
            )
        else:
            self.device = user_device or optimal_config.get("device", "cpu")
            self.compute_type = user_compute_type or optimal_config.get(
                "compute_type", "int8"
            )

        # If CUDA is not available but device is set to cuda, force CPU mode
        if not cuda_available and self.device == "cuda":
            logger.info("CUDA not detected via nvidia-smi. Forcing CPU mode.")
            self.device = "cpu"
            self.compute_type = "int8"

        # Store transcription parameters
        self.beam_size = optimal_config.get("beam_size", 5)
        self.best_of = optimal_config.get("best_of", 5)  # [NEW]
        self.patience = optimal_config.get("patience", 1.0)  # [NEW]
        self.length_penalty = optimal_config.get(
            "length_penalty", 1.0
        )  # [NEW]
        self.vad_filter = optimal_config.get("vad_filter", True)
        self.vad_parameters = optimal_config.get(
            "vad_parameters",
            {
                "min_silence_duration_ms": 500,
                "threshold": 0.5,
                "min_speech_duration_ms": 250,
            },
        )
        self.word_timestamps = optimal_config.get("word_timestamps", False)
        self.condition_on_previous_text = optimal_config.get(
            "condition_on_previous_text", False
        )
        self.initial_prompt = config_manager.get(
            "stt.modules.faster_whisper.initial_prompt",
            optimal_config.get("initial_prompt"),
        )

        # Load hotwords and repository configuration
        self.hotwords = config_manager.get(
            "stt.modules.faster_whisper.hotwords", []
        )

        # Default to Systran (official) instead of guillaumekln
        repo_prefix = config_manager.get(
            "stt.modules.faster_whisper.repo_prefix", "Systran/faster-whisper-"
        )
        self.repo_id = f"{repo_prefix}{self.model_size}"

        # VAD parameters for the listen() method
        self.silence_threshold = config_manager.get(
            "stt.modules.faster_whisper.silence_threshold", 500
        )
        self.silence_duration_s = config_manager.get(
            "stt.modules.faster_whisper.silence_duration_s", 2
        )

        # If using CPU, set number of threads
        if self.device == "cpu":
            self.num_workers = optimal_config.get(
                "cpu_threads", os.cpu_count() or 4
            )
            logger.info(
                f"Using {self.num_workers} CPU threads for Faster-Whisper"
            )
        else:
            self.num_workers = 1

        # Context buffer for previous user inputs
        self.context_buffer = deque(maxlen=3)

        # Log the configuration
        logger.info(
            f"Initializing Faster-Whisper with model={self.model_size}, "
            f"device={self.device}, compute_type={self.compute_type}, "
            f"beam_size={self.beam_size}, best_of={self.best_of}"
        )
        self.model = None
        self.language = config_manager.get("stt.language", None)

    def load_model(self):
        """Load the model if not already loaded"""
        if self.model is None:
            logger.info(
                f"Loading Faster-Whisper model {self.model_size} (first"
                " time)..."
            )
            try:
                from faster_whisper import WhisperModel

                # Based on the GitHub issue #1244, float16 compute_type with CUDA can cause issues
                # On Windows, prefer float16 with CUDA to avoid silent failures
                if self.device == "cuda":
                    if platform.system() == "Windows":
                        if (
                            self.compute_type != "float16"
                            and self.compute_type != "float32"
                        ):
                            logger.warning(
                                "On Windows with CUDA, changing compute_type"
                                " to float16 to avoid silent failures"
                            )
                            self.compute_type = "float16"
                    else:
                        # On other platforms, use int8_float32 with CUDA
                        if self.compute_type == "float16":
                            logger.warning(
                                "Changing compute_type from float16 to"
                                " int8_float32 to avoid known issues with CUDA"
                            )
                            self.compute_type = "int8_float32"

                logger.info(f"compute_type: {self.compute_type}")

                # Get the cache directory for whisper
                cache_dir = config_manager.get_subdir(
                    "cache.directory", "whisper"
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

                logger.info(
                    f"Loading model with device={self.device},"
                    f" compute_type={self.compute_type}"
                )
                self.model = WhisperModel(**model_kwargs)

                logger.info(
                    f"Faster-Whisper model {self.model_size} loaded"
                    " successfully"
                )
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
                        logger.info(
                            f"Retrying with device={self.device},"
                            f" compute_type={self.compute_type}"
                        )

                        # Get the cache directory for whisper
                        cache_dir = config_manager.get_subdir(
                            "cache.directory", "whisper"
                        )

                        self.model = WhisperModel(
                            self.model_size,
                            device="cpu",
                            compute_type="int8",
                            download_root=cache_dir,
                            cpu_threads=self.num_workers,
                        )
                        logger.info(
                            "Successfully loaded model with CPU fallback"
                        )
                    except Exception as cpu_error:
                        logger.error(f"CPU fallback also failed: {cpu_error}")
                        raise
                else:
                    raise
        else:
            logger.info("Using already loaded Faster-Whisper model (cached)")

    def reset_context(self):
        """Clear the internal context buffer"""
        self.context_buffer.clear()

    def _get_dynamic_prompt(self) -> str:
        """
        Combine base prompt with recent context.
        Enforces a safe character limit (800 chars) to stay within Whisper's 224-token limit.
        Prioritizes recent messages and ensures words are not cut in half.
        """
        # Safety limit (approx 200 tokens)
        MAX_CHARS = 800

        base_prompt = self.initial_prompt or ""
        # Reserve space for base prompt + 1 space separator
        current_len = len(base_prompt) + 1 if base_prompt else 0

        if not self.context_buffer:
            return base_prompt

        # We build the context list backwards (newest first) to prioritize recent context
        collected_parts = []

        # Iterate in reverse (Newest -> Oldest)
        for msg in reversed(self.context_buffer):
            # Calculate remaining budget, accounting for a separator (e.g., ". ")
            available = MAX_CHARS - current_len

            # If we have less than 10 chars left, it's not worth adding a fragment
            if available < 10:
                break

            if len(msg) + 2 <= available:
                # Case 1: The whole message fits
                collected_parts.append(msg)
                current_len += len(msg) + 2  # +2 for ". "
            else:
                # Case 2: It doesn't fit, we need to truncate.
                # We take the END of the message (the most recent part of that sentence)
                # that fits in the available space.
                candidate_chunk = msg[-available:]

                # Find the first space to avoid cutting a word in the middle.
                # We search from the left of this chunk.
                first_space = candidate_chunk.find(" ")

                if (
                    first_space != -1
                    and first_space < len(candidate_chunk) - 1
                ):
                    # Cut from the space onwards to ensure a clean start
                    safe_chunk = candidate_chunk[first_space + 1:]
                    collected_parts.append(safe_chunk)

                # We hit the limit, so we stop processing older messages
                break

        # Reverse back to chronological order (Oldest -> Newest)
        history_text = ". ".join(reversed(collected_parts))

        if base_prompt:
            return f"{base_prompt} {history_text}"

        return history_text

    def transcribe_file(self, audio_file: str) -> Any:
        """Transcribe an audio file using Faster-Whisper"""

        if not self.model:
            self.load_model()

        # logger.info("transcribe_file 1")
        try:
            # logger.info("transcribe_file 2")

            # [MODIFIED] Generate prompt including context
            current_prompt = self._get_dynamic_prompt()

            # Transcribe the audio with the optimized parameters
            segments, info = self.model.transcribe(
                audio_file,
                beam_size=self.beam_size,
                best_of=self.best_of,  # [NEW]
                patience=self.patience,  # [NEW]
                length_penalty=self.length_penalty,  # [NEW]
                # None enables language autodetection
                language=None if self.language is None else self.language,
                vad_filter=self.vad_filter,
                vad_parameters=self.vad_parameters,
                word_timestamps=self.word_timestamps,
                condition_on_previous_text=self.condition_on_previous_text,
                initial_prompt=current_prompt,  # [MODIFIED] Use dynamic prompt
                hotwords=self.hotwords,  # [NEW] Add hotwords support
            )

            # [MODIFIED] Process segments to extract text and calculate confidence
            text_segments = []
            min_confidence = 1.0  # Start at 100%

            for segment in segments:
                text_segments.append(segment.text)
                # Convert log probability to linear probability (0.0 to 1.0)
                segment_confidence = math.exp(segment.avg_logprob)
                # Track the lowest confidence segment (the "weakest link")
                if segment_confidence < min_confidence:
                    min_confidence = segment_confidence

            transcript = " ".join(text_segments)

            # [NEW] Update context buffer with the new result
            if transcript.strip():
                self.context_buffer.append(transcript.strip())

            logger.info(
                f"Detected language: {info.language} with probability"
                f" {info.language_probability:.2f}"
            )
            logger.info(f"Transcription result: {transcript} (Confidence: {min_confidence:.2f})")
            # logger.info("transcribe_file 3")

            # Return dictionary with metadata instead of just string
            return {
                "text": transcript,
                "confidence": min_confidence,
                "language": info.language
            }
        except Exception as e:
            # logger.info("transcribe_file 4")
            logger.error(f"Error transcribing with Faster-Whisper: {e}")
            import traceback

            logger.error(traceback.format_exc())

            # Try to provide more helpful error information
            if "CUDA" in str(e) or "GPU" in str(e):
                logger.error(
                    "This appears to be a CUDA-related error. Try setting"
                    " 'compute_type' to 'float16' in your config."
                )
            elif "out of memory" in str(e).lower():
                logger.error(
                    "GPU memory error. Try using a smaller model or setting"
                    " 'device' to 'cpu' in your config."
                )
            return {"text": "", "confidence": 0.0}

    def listen(self) -> str:
        """
        Record audio and convert to text using Faster-Whisper
        Cross-platform implementation using PyAudio with Numpy optimization
        """
        try:
            if not self.model:
                self.load_model()

            import os
            import tempfile
            import wave

            import pyaudio

            # Try importing numpy for faster processing
            try:
                import numpy as np

                HAS_NUMPY = True
            except ImportError:
                HAS_NUMPY = False
                logger.warning(
                    "Numpy not found. Using slower pure-Python silence"
                    " detection."
                )

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

                    # Calculate amplitude
                    if HAS_NUMPY:
                        # Optimized Numpy calculation
                        audio_chunk = np.frombuffer(data, dtype=np.int16)
                        amplitude = np.max(np.abs(audio_chunk))
                    else:
                        # Fallback: Simple silence detection (slower)
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
                    if (
                        has_speech
                        and silent_chunks
                        > RATE / CHUNK * self.silence_duration_s
                    ):
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
                result = self.transcribe_file(temp_file)

                # [MODIFIED] Handle dictionary return type
                if isinstance(result, dict):
                    return result.get("text", "")
                return str(result)

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
                repo_id=self.repo_id,  # [MODIFIED] Use dynamic repo_id
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
            logger.info(
                f"Downloading Faster-Whisper {self.model_size} model..."
            )
            cache_dir = config_manager.get_subdir("cache.directory", "whisper")
            model_path = hf_hub_download(
                repo_id=self.repo_id,  # [MODIFIED] Use dynamic repo_id
                filename="model.bin",
                cache_dir=cache_dir,
            )
            logger.info(
                f"Faster-Whisper {self.model_size} model downloaded to"
                f" {model_path}"
            )
            return {
                "success": True,
                "message": (
                    f"Whisper {self.model_size} model downloaded successfully"
                ),
                "path": model_path,
            }
        except Exception as e:
            logger.error(f"Error downloading whisper model: {e}")
            return {
                "success": False,
                "message": f"Error downloading whisper model: {str(e)}",
            }
