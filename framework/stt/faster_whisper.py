import logging
import os
from typing import Any, Dict, Optional

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
            "threshold": 0.5,
            "min_speech_duration_ms": 250
        },
        "word_timestamps": False,
        "condition_on_previous_text": False
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
                config["model_size"] = "medium"
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
            from ainara.framework.utils.dependency_checker import \
                DependencyChecker

            stt_deps = DependencyChecker.check_stt_dependencies()

            # Check if CUDA is available
            cuda_available = stt_deps["cuda"]["available"]
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

        # load model on start
        self._load_model()

    def _load_model(self):
        """Load the model if not already loaded"""
        if self.model is None:
            logger.info(f"Loading Faster-Whisper model {self.model_size} (first time)...")
            try:
                from faster_whisper import WhisperModel

                # Based on the GitHub issue #1244, float16 compute_type with CUDA can cause issues
                # Force int8 compute_type when using CUDA to avoid the exclamation marks issue
                if self.device == "cuda" and self.compute_type == "float16":
                    logger.warning("Changing compute_type from float16 to int8_float32 to avoid known issues with CUDA")
                    self.compute_type = "int8_float32"

                logger.info(f"compute_type: {self.compute_type}")

                # Get the cache directory for whisper
                cache_dir = str(config_manager.get_cache_directory("whisper"))
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
                        cache_dir = str(config_manager.get_cache_directory("whisper"))

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
                condition_on_previous_text=self.condition_on_previous_text
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
            logger.info(f"Error transcribing with Faster-Whisper: {e}")
            import traceback

            logger.info(traceback.format_exc())
            return ""

    def listen(self) -> str:
        """
        Record audio and convert to text using Faster-Whisper
        Cross-platform implementation using PyAudio
        """
        try:
            import os
            import tempfile
            import wave

            import pyaudio

            # PyAudio parameters
            FORMAT = pyaudio.paInt16
            CHANNELS = 1
            RATE = 16000
            CHUNK = 1024
            SILENCE_THRESHOLD = 500  # Adjust based on testing

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

                    if amplitude > SILENCE_THRESHOLD:
                        silent_chunks = 0
                        has_speech = True
                    else:
                        silent_chunks += 1

                    # Stop after ~3 seconds of silence if we've detected speech before
                    if has_speech and silent_chunks > RATE / CHUNK * 3:
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
