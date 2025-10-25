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
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Generator, Optional, Tuple

import soundfile as sf
from pygame import USEREVENT, mixer

from ..config import config
from .base import TTSBackend


class PiperTTS(TTSBackend):
    """Piper implementation of TTS backend"""

    # Default voices with their file names and URLs
    DEFAULT_VOICES = {
        "en_US-amy-medium": {
            "model": "en_US-amy-medium.onnx",
            "url": (
                "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium/en_US-amy-medium.onnx?download=true"
            ),
            "config_url": (
                "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium/en_US-amy-medium.onnx.json?download=true"
            ),
        },
        "en_US-lessac-medium": {
            "model": "en_US-lessac-medium.onnx",
            "url": (
                "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx?download=true"
            ),
            "config_url": (
                "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json?download=true"
            ),
        },
        "en_GB-alba-medium": {
            "model": "en_GB-alba-medium.onnx",
            "url": (
                "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/alba/medium/en_GB-alba-medium.onnx?download=true"
            ),
            "config_url": (
                "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/alba/medium/en_GB-alba-medium.onnx.json?download=true"
            ),
        },
        "es_ES-mls_10246-medium": {
            "model": "es_ES-mls_10246-medium.onnx",
            "url": (
                "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/es/es_ES/mls_10246/medium/es_ES-mls_10246-medium.onnx?download=true"
            ),
            "config_url": (
                "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/es/es_ES/mls_10246/medium/es_ES-mls_10246-medium.onnx.json?download=true"
            ),
        },
        "fr_FR-siwis-medium": {
            "model": "fr_FR-siwis-medium.onnx",
            "url": (
                "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx?download=true"
            ),
            "config_url": (
                "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx.json?download=true"
            ),
        },
        "de_DE-thorsten-medium": {
            "model": "de_DE-thorsten-medium.onnx",
            "url": (
                "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/de/de_DE/thorsten/medium/de_DE-thorsten-medium.onnx?download=true"
            ),
            "config_url": (
                "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/de/de_DE/thorsten/medium/de_DE-thorsten-medium.onnx.json?download=true"
            ),
        },
    }

    def __init__(self):
        """Initialize piper backend"""
        self._current_process: Optional[subprocess.Popen] = None

        # # Initialize pygame mixer for audio playback with platform-specific settings
        # if platform.system() == 'Darwin':
        #     mixer.pre_init(
        #         frequency=22050,
        #         buffer=4096,
        #         allowedchanges=0
        #     )
        mixer.init(frequency=22050)

        # Create temp directory for audio files
        self.temp_dir = tempfile.mkdtemp(prefix="piper_tts_")

        # Initialize logging
        self.logger = logging.getLogger(__name__)
        self.logger.debug("PiperTTS initialization started")

        # Get model directory and voice name from config
        self.voice = config.get("tts.modules.piper.voice", "en_US-amy-medium")
        self.model_dir = self._get_model_directory()
        self.options = config.get(
            "tts.modules.piper.options", "--output_raw --length_scale 0.7"
        ).split()

        # Run setup to ensure binary and models are available
        if not self.setup():
            self.logger.error("Piper TTS setup failed")
            raise RuntimeError(
                "Failed to set up Piper TTS. Check logs for details."
            )

        self.logger.debug("Initialized PiperTTS with:")
        self.logger.debug(f"Binary: {self.binary}")
        self.logger.debug(f"Voice: {self.voice}")
        self.logger.debug(f"Model: {self.model}")
        self.logger.debug(f"Model directory: {self.model_dir}")
        self.logger.debug(f"Options: {self.options}")

    def _get_resource_base_dir(self) -> Path:
        """Determine the base directory for resources (project root or MEIPASS)."""
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            # Running as a bundled app (PyInstaller)
            return Path(sys._MEIPASS)
        else:
            # Running from source
            # __file__ -> tts -> framework -> ainara -> project_root
            return Path(__file__).parent.parent.parent.parent

    def _find_piper_binary(self) -> str:
        """Find piper binary in bundled resources or common locations"""
        configured_binary = config.get("tts.modules.piper.binary", "auto")
        if configured_binary != "auto" and os.path.exists(configured_binary):
            return configured_binary

        resource_base_dir = self._get_resource_base_dir()
        system = platform.system()

        if system == "Windows":
            bundled_path = (
                resource_base_dir / "resources/bin/windows/piper/piper.exe"
            )
        elif system == "Darwin":  # macOS
            mac_arch = self._get_macos_architecture()
            bundled_path = (
                resource_base_dir
                / f"resources/bin/macos/{mac_arch}/piper/piper"
            )
        else:  # Linux
            bundled_path = (
                resource_base_dir / "resources/bin/linux/piper/piper"
            )

        if "bundled_path" in locals() and bundled_path.exists():
            self.logger.info(f"Using bundled Piper binary: {bundled_path}")
            return str(bundled_path)

        # If we get here, we couldn't find piper
        msg_error = (
            "Could not find piper binary. Please install piper or specify the"
            " path in config."
        )
        self.logger.error(msg_error)
        raise RuntimeError(msg_error)

    def _get_model_directory(self) -> str:
        """Get the directory for storing TTS models"""
        configured_dir = config.get("tts.modules.piper.model_dir", "auto")
        if configured_dir != "auto":
            model_dir = os.path.expanduser(configured_dir)
            os.makedirs(model_dir, exist_ok=True)
            return model_dir

        # Check for bundled models relative to resource base dir
        resource_base_dir = self._get_resource_base_dir()
        bundled_model_dir = resource_base_dir / "resources" / "tts" / "models"

        if bundled_model_dir.is_dir():
            self.logger.info(
                f"Using bundled model directory: {bundled_model_dir}"
            )
            return str(bundled_model_dir)

        # Use standard XDG data directory for other platforms
        user_data_dir = config.get("data.directory")
        model_dir = os.path.join(user_data_dir, "tts", "models")
        os.makedirs(model_dir, exist_ok=True)
        self.logger.info(f"Using standard model directory: {model_dir}")
        return model_dir

    def _get_or_download_model(self) -> str:
        """Get the path to the voice model, downloading it if necessary"""
        voice_name = self.voice

        # Check if it's a full path to a model file
        if os.path.exists(os.path.expanduser(voice_name)):
            return os.path.expanduser(voice_name)

        # Check if it's one of our known voices
        if voice_name in self.DEFAULT_VOICES:
            voice_info = self.DEFAULT_VOICES[voice_name]
            model_filename = voice_info["model"]
            model_path = os.path.join(self.model_dir, model_filename)

            # Check if model exists, download if not
            if not os.path.exists(model_path):
                self._download_model(voice_name, model_path)

            # Check for config file - Piper expects the config file to be named exactly like the model file but with .json extension
            json_path = (
                model_path + ".json"
            )  # Piper expects model.onnx.json, not model.json
            if not os.path.exists(json_path):
                self._download_model_config(voice_name, json_path)

            return model_path

        # If we get here, we don't know this voice
        self.logger.error(f"Unknown voice model: {voice_name}")
        raise ValueError(
            f"Unknown voice model: {voice_name}. Please use one of:"
            f" {', '.join(self.DEFAULT_VOICES.keys())}"
        )

    def _download_model(self, voice_name: str, model_path: str) -> None:
        """Download a voice model from the repository"""
        voice_info = self.DEFAULT_VOICES[voice_name]
        model_url = voice_info["url"]

        self.logger.info(
            f"Downloading voice model {voice_name} from {model_url}"
        )
        print(
            f"Downloading voice model {voice_name}... This may take a few"
            " minutes."
        )

        try:
            # Download with progress reporting
            def report_progress(block_num, block_size, total_size):
                downloaded = block_num * block_size
                percent = min(100, int(downloaded * 100 / total_size))
                sys.stdout.write(
                    f"\rDownloading: {percent}% [{downloaded} / {total_size}]"
                )
                sys.stdout.flush()

            urllib.request.urlretrieve(
                model_url, model_path, reporthook=report_progress
            )
            print("\nDownload complete!")
        except Exception as e:
            self.logger.error(f"Failed to download voice model: {e}")
            if os.path.exists(model_path):
                os.remove(model_path)
            raise RuntimeError(f"Failed to download voice model: {e}")

    def _download_model_config(
        self, voice_name: str, config_path: str
    ) -> None:
        """Download the JSON config file for a voice model"""
        voice_info = self.DEFAULT_VOICES[voice_name]
        config_url = voice_info["config_url"]

        self.logger.info(f"Downloading voice config from {config_url}")

        try:
            first_error = None
            # First try the URL as provided
            try:
                urllib.request.urlretrieve(config_url, config_path)
                return
            except Exception as e:
                first_error = e
                self.logger.warning(
                    f"First attempt to download config failed: {e}"
                )

            # If that fails, try with an extra .json extension (seen in some URLs)
            try:
                alternate_url = f"{config_url}.json"
                self.logger.info(f"Trying alternate URL: {alternate_url}")
                urllib.request.urlretrieve(alternate_url, config_path)
                return
            except Exception as second_error:
                self.logger.warning(
                    f"Second attempt to download config failed: {second_error}"
                )

            # If both attempts fail, raise the original error
            if first_error:
                raise first_error
        except Exception as e:
            self.logger.warning(f"Failed to download voice config: {e}")
            self.logger.warning(
                "This is not critical, Piper can work without the config file"
            )

    def setup(self) -> bool:
        """
        Validate and set up Piper TTS requirements.

        This function checks if the Piper binary and voice models are available,
        and downloads them if needed.

        Returns:
            bool: True if setup was successful, False otherwise
        """
        try:
            self.logger.info("Setting up Piper TTS...")

            # Step 1: Ensure Piper binary is available
            try:
                self.binary = self._find_piper_binary()
                self.logger.info(f"Using Piper binary: {self.binary}")
            except RuntimeError:
                # Binary not found, try to download it
                self.logger.info(
                    "Piper binary not found"
                )
                return False

            # Step 2: Ensure voice model is available
            try:
                self.model = self._get_or_download_model()
                self.logger.info(f"Using voice model: {self.model}")
            except (ValueError, RuntimeError) as e:
                self.logger.error(f"Failed to set up voice model: {e}")
                return False

            # Step 3: Verify Piper works by running a simple test
            try:
                self._check_dependencies()
                self.logger.info("Piper TTS setup completed successfully")
                return True
            except RuntimeError as e:
                self.logger.error(f"Piper dependency check failed: {e}")
                return False

        except Exception as e:
            self.logger.error(f"Unexpected error during Piper setup: {e}")
            import traceback

            self.logger.error(traceback.format_exc())
            return False

    def _get_macos_architecture(self) -> str:
        """Get macOS architecture and return appropriate string"""
        process = subprocess.run(
            ["uname", "-m"], capture_output=True, text=True
        )
        arch = process.stdout.strip().lower()
        if arch == "arm64":
            return "aarch64"
        return "x64"

    def _check_dependencies(self) -> None:
        """Check if required commands are available"""
        try:
            self.logger.debug(f"Checking piper binary: {self.binary}")

            # Check if piper works
            subprocess.run(
                [self.binary, "--help"], capture_output=True, check=True
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            self.logger.error(f"Command check failed: {str(e)}")
            raise RuntimeError(
                "Required commands not found. Please install piper and audio"
                " playback utilities"
            )

    def _print_synchronized(self, text: str, duration: float) -> None:
        """Print text synchronized with audio playback

        Args:
            text: Text to print
            duration: Duration in seconds to complete printing
        """
        if not text:
            return

        # Calculate delay between each character
        char_delay = duration / len(text)

        # Print each character with calculated delay
        for char in text:
            sys.stdout.write(char)
            sys.stdout.flush()
            time.sleep(char_delay)
        sys.stdout.write("\n")
        sys.stdout.flush()

    def speak_sync(
        self, text: str
    ) -> Generator[Tuple[str, float], None, None]:
        """Stream text to speech with precise timing

        Args:
            text: The text to convert to speech

        Yields:
            Tuple[str, float]: Each phrase and its duration in seconds
        """
        self.logger.debug("speak_sync called with text length: %d", len(text))
        phrases = self._split_into_phrases(text)

        for phrase in phrases:
            phrase = phrase.strip()
            if not phrase:
                continue

            try:
                self.logger.debug(
                    "Processing phrase: %s",
                    phrase[:50] + "..." if len(phrase) > 50 else phrase,
                )

                # Generate audio file
                temp_wav = os.path.join(
                    self.temp_dir, f"speech_{abs(hash(phrase))}.wav"
                )

                # Generate speech using piper with direct WAV output
                piper_cmd = [
                    self.binary,
                    "--model",
                    self.model,
                    "--output_file",
                    temp_wav,
                ]

                self.logger.debug(
                    f"Running piper command: {' '.join(piper_cmd)}"
                )

                # Clean and write the text to piper
                cleaned_phrase = self._clean_text(phrase).encode("utf-8")

                # Run piper to generate the WAV file
                process = subprocess.Popen(
                    piper_cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=False,
                )

                _, stderr = process.communicate(input=cleaned_phrase)
                stderr_text = stderr.decode("utf-8") if stderr else ""

                if process.returncode != 0:
                    self.logger.error(
                        f"Piper failed with return code {process.returncode}"
                    )
                    self.logger.error(f"Piper stderr: {stderr_text}")
                    raise RuntimeError(f"Piper failed: {stderr_text}")

                # Play the WAV file using pygame
                mixer.music.load(temp_wav)
                mixer.music.play()

                # Wait for audio playback to complete and track the actual duration
                start_time = time.time()
                while mixer.music.get_busy():
                    time.sleep(0.1)
                actual_duration = time.time() - start_time

                # Yield for any external processing
                yield phrase, actual_duration

                # Small pause between phrases
                time.sleep(0.2)

            except Exception as e:
                self.logger.error(f"Speech error: {e}")
                continue

    def speak(self, text: str) -> bool:
        """Convert text to speech using piper with pygame for audio playback

        Args:
            text: The text to convert to speech

        Returns:
            bool: True if successful, False otherwise
        """
        self.logger.debug(f"speak() called with text: {text[:50]}...")

        try:
            # Stop any current speech
            self.stop()

            # Create a temporary WAV file
            temp_wav = os.path.join(
                self.temp_dir, f"speech_{abs(hash(text))}.wav"
            )

            # Generate speech using piper with direct WAV output
            piper_cmd = [
                self.binary,
                "--model",
                self.model,
                "--output_file",
                temp_wav,
            ]

            # Clean the text
            cleaned_text = self._clean_text(text).encode("utf-8")

            # Run piper to generate the WAV file
            process = subprocess.Popen(
                piper_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
            )

            _, stderr = process.communicate(input=cleaned_text)
            stderr_text = stderr.decode("utf-8") if stderr else ""

            if process.returncode != 0:
                self.logger.error(
                    f"Piper failed with return code {process.returncode}"
                )
                self.logger.error(f"Piper stderr: {stderr_text}")
                return False

            # Play the WAV file using pygame
            try:
                mixer.music.load(temp_wav)
                mixer.music.play()

                # Wait for playback to complete
                while mixer.music.get_busy():
                    time.sleep(0.1)

                return True
            except Exception as e:
                self.logger.error(f"Error playing audio with pygame: {e}")
                return False

        except Exception as e:
            self.logger.error(f"Error in speak: {e}")
            return False

    def _split_into_phrases(self, text: str) -> list[str]:
        """Split text into natural phrases/sentences

        Args:
            text: Text to split

        Returns:
            list[str]: List of phrases
        """
        # Remove code blocks as we don't want to speak those
        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)

        # Split on sentence endings and other natural breaks
        splits = re.split(r"([.!?]\s+|\n\n+)", text)

        # Recombine splits with their punctuation
        phrases = []
        for i in range(0, len(splits) - 1, 2):
            if i + 1 < len(splits):
                phrases.append(splits[i] + splits[i + 1])
            else:
                phrases.append(splits[i])

        return [p.strip() for p in phrases if p.strip()]

    def stop(self) -> bool:
        """Stop current speech and audio playback

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if self._current_process:
                self._current_process.terminate()
                self._current_process = None
            mixer.stop()
            mixer.music.stop()
            return True
        except Exception as e:
            self.logger.error(f"Error stopping playback: {e}")
            return False

    def generate_audio(self, text: str) -> Tuple[str, float]:
        """Generate audio file for text and return its path and duration

        Args:
            text: The text to convert to speech

        Returns:
            Tuple[str, float]: Path to generated audio file and its duration
            in seconds
        """
        try:
            # Create temporary WAV file
            temp_file = os.path.join(self.temp_dir, f"{hash(text)}.wav")

            # Generate speech using piper
            piper_cmd = (
                [self.binary, "--model", self.model]
                + self.options
                + ["--output_file", temp_file]
            )

            process = subprocess.Popen(
                piper_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
            )

            cleaned_text = self._clean_text(text).encode("utf-8")
            _, stderr = process.communicate(input=cleaned_text)

            if process.returncode != 0:
                stderr_text = stderr.decode("utf-8") if stderr else ""
                self.logger.error(f"Piper failed: {stderr_text}")
                raise RuntimeError(f"Piper failed: {stderr_text}")

            # Get audio duration using soundfile
            with sf.SoundFile(temp_file) as f:
                duration = len(f) / f.samplerate

            return temp_file, duration

        except Exception as e:
            self.logger.error(f"Error generating audio: {e}")
            raise

    def play_audio(self, audio_file: str) -> bool:
        """Play audio file and return when playback actually starts

        Args:
            audio_file: Path to audio file to play

        Returns:
            bool: True if playback started successfully, False otherwise
        """
        try:
            mixer.music.load(audio_file)
            # Set up an event to be triggered when playback starts
            mixer.music.set_endevent(USEREVENT + 1)
            mixer.music.play()

            # Wait for playback to actually start
            # This ensures synchronization with text display
            while not mixer.music.get_busy():
                time.sleep(0.001)
            return True
        except Exception as e:
            self.logger.error(f"Error playing audio: {e}")
            return False

    def __del__(self):
        """Cleanup temp files on deletion"""
        try:
            shutil.rmtree(self.temp_dir)
        except Exception as e:
            self.logger.error(f"Error cleaning up temp directory: {e}")
