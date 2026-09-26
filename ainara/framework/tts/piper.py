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
from pathlib import Path
from typing import Generator, List, Optional, Tuple

import soundfile as sf
from pygame import USEREVENT, mixer

from ..config import config
from .base import TTSBackend


class PiperTTS(TTSBackend):
    """Piper implementation of TTS backend"""

    def __init__(self):
        """Initialize piper backend"""
        self._current_process: Optional[subprocess.Popen] = None

        mixer.init(frequency=22050)

        # Create temp directory for audio files
        self.temp_dir = tempfile.mkdtemp(prefix="piper_tts_")

        # Initialize logging
        self.logger = logging.getLogger(__name__)
        self.logger.debug("PiperTTS initialization started")

        # Load Configuration
        self.default_voice_name = config.get(
            "tts.modules.piper.default_voice", "en_US-amy-medium"
        )
        self.default_options = config.get(
            "tts.modules.piper.default_options",
            "--output_raw --length_scale 1.0",
        ).split()
        self.language_config = config.get("tts.modules.piper.languages", {})

        # Define Model Directories
        # 1. User Data Directory (Persistent downloads)
        self.user_models_dir = (
            Path(config.get_default_data_dir()) / "tts" / "piper" / "models"
        )
        # 2. Bundled Resources Directory (App distribution)
        self.bundled_models_dir = (
            self._get_resource_base_dir() / "resources" / "tts" / "models"
        )

        # State
        self.binary: Optional[str] = None
        self.default_model_path: Optional[str] = None

        # Run setup
        if not self.setup():
            self.logger.error("Piper TTS setup failed")
            raise RuntimeError(
                "Failed to set up Piper TTS. Check logs for details."
            )

        self.logger.debug("Initialized PiperTTS with:")
        self.logger.debug(f"Binary: {self.binary}")
        self.logger.debug(f"Default Voice: {self.default_voice_name}")
        self.logger.debug(f"Default Model Path: {self.default_model_path}")

    def _get_resource_base_dir(self) -> Path:
        """Determine the base directory for resources (project root or MEIPASS)."""
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            return Path(sys._MEIPASS)
        else:
            return Path(__file__).parent.parent.parent.parent

    def _find_piper_binary(self) -> str:
        """Find piper binary in bundled resources or common locations"""
        configured_binary = config.get("tts.modules.piper.binary_path", "auto")
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

        msg_error = (
            "Could not find piper binary. Please install piper or specify the"
            " path in config."
        )
        self.logger.error(msg_error)
        raise RuntimeError(msg_error)

    def _get_voice_path(self, voice_name: str) -> Optional[str]:
        """
        Locate a voice model file in user data or bundled resources.

        Args:
            voice_name: The name of the voice (e.g., 'en_US-amy-medium')

        Returns:
            str: Path to the .onnx file if found, None otherwise.
        """
        # 1. Check User Data Directory
        user_path = self.user_models_dir / f"{voice_name}.onnx"
        if user_path.exists():
            return str(user_path)

        # 2. Check Bundled Resources
        bundled_path = self.bundled_models_dir / f"{voice_name}.onnx"
        if bundled_path.exists():
            return str(bundled_path)

        return None

    def setup(self) -> bool:
        """
        Validate and set up Piper TTS requirements.
        """
        try:
            self.logger.info("Setting up Piper TTS...")

            # Step 1: Ensure Piper binary is available
            try:
                self.binary = self._find_piper_binary()
            except RuntimeError:
                return False

            # Step 2: Ensure Default Voice is available
            self.default_model_path = self._get_voice_path(
                self.default_voice_name
            )

            if not self.default_model_path:
                self.logger.error(
                    f"Default voice model '{self.default_voice_name}' not"
                    " found in bundled or user directories."
                )
                return False

            # Step 3: Verify Piper works
            try:
                self._check_dependencies()
                self.logger.info("Piper TTS setup completed successfully")
                return True
            except RuntimeError as e:
                self.logger.error(f"Piper dependency check failed: {e}")
                return False

        except Exception as e:
            self.logger.error(f"Unexpected error during Piper setup: {e}")
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
            subprocess.run(
                [self.binary, "--help"], capture_output=True, check=True
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            self.logger.error(f"Command check failed: {str(e)}")
            raise RuntimeError("Piper binary check failed.")

    def _resolve_voice_params(self, text: str) -> Tuple[str, List[str]]:
        """
        Determine the appropriate model and options for the given text.

        Looks up configuration based on configured lang. Falls back to default
        voice if specific language voice is missing or not configured.

        Args:
            text: The text to be spoken.

        Returns:
            Tuple[str, List[str]]: (model_path, options_list)
        """
        lang = config.get("stt.language", "en")
        model_path = None
        options = self.default_options

        # Check if we have a configuration for this language
        if lang in self.language_config:
            lang_conf = self.language_config[lang]
            voice_name = lang_conf.get("voice")

            if voice_name:
                found_path = self._get_voice_path(voice_name)
                if found_path:
                    model_path = found_path
                    # Override options if specified for this language
                    if "options" in lang_conf:
                        options = lang_conf["options"].split()
                else:
                    self.logger.warning(
                        f"Configured voice '{voice_name}' for language"
                        f" '{lang}' not found. Falling back to default."
                    )

        # Fallback to default if no specific model found
        if not model_path:
            model_path = self.default_model_path

        return model_path, options

    def _print_synchronized(self, text: str, duration: float) -> None:
        """Print text synchronized with audio playback"""
        if not text:
            return

        char_delay = duration / len(text)
        for char in text:
            sys.stdout.write(char)
            sys.stdout.flush()
            time.sleep(char_delay)
        sys.stdout.write("\n")
        sys.stdout.flush()

    def speak_sync(
        self, text: str
    ) -> Generator[Tuple[str, float], None, None]:
        """Stream text to speech with precise timing"""
        phrases = self._split_into_phrases(text)

        for phrase in phrases:
            phrase = phrase.strip()
            if not phrase:
                continue

            try:
                # Resolve model and options for this specific phrase
                model_path, options = self._resolve_voice_params(phrase)

                temp_wav = os.path.join(
                    self.temp_dir, f"speech_{abs(hash(phrase))}.wav"
                )

                piper_cmd = (
                    [self.binary, "--model", model_path]
                    + options
                    + ["--output_file", temp_wav]
                )

                cleaned_phrase = self._clean_text(phrase).encode("utf-8")

                process = subprocess.Popen(
                    piper_cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=False,
                )

                _, stderr = process.communicate(input=cleaned_phrase)

                if process.returncode != 0:
                    stderr_text = stderr.decode("utf-8") if stderr else ""
                    self.logger.error(f"Piper failed: {stderr_text}")
                    continue

                mixer.music.load(temp_wav)
                mixer.music.play()

                start_time = time.time()
                while mixer.music.get_busy():
                    time.sleep(0.1)
                actual_duration = time.time() - start_time

                yield phrase, actual_duration
                time.sleep(0.2)

            except Exception as e:
                self.logger.error(f"Speech error: {e}")
                continue

    def speak(self, text: str) -> bool:
        """Convert text to speech using piper with pygame for audio playback"""
        try:
            self.stop()

            # Resolve model and options
            model_path, options = self._resolve_voice_params(text)

            temp_wav = os.path.join(
                self.temp_dir, f"speech_{abs(hash(text))}.wav"
            )

            piper_cmd = (
                [self.binary, "--model", model_path]
                + options
                + ["--output_file", temp_wav]
            )

            cleaned_text = self._clean_text(text).encode("utf-8")

            process = subprocess.Popen(
                piper_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
            )

            _, stderr = process.communicate(input=cleaned_text)

            if process.returncode != 0:
                stderr_text = stderr.decode("utf-8") if stderr else ""
                self.logger.error(f"Piper failed: {stderr_text}")
                return False

            try:
                mixer.music.load(temp_wav)
                mixer.music.play()
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
        """Split text into natural phrases/sentences"""
        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        splits = re.split(r"([.!?]\s+|\n\n+)", text)
        phrases = []
        for i in range(0, len(splits) - 1, 2):
            if i + 1 < len(splits):
                phrases.append(splits[i] + splits[i + 1])
            else:
                phrases.append(splits[i])
        return [p.strip() for p in phrases if p.strip()]

    def stop(self) -> bool:
        """Stop current speech and audio playback"""
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
        """Generate audio file for text and return its path and duration"""
        try:
            # Resolve model and options
            model_path, options = self._resolve_voice_params(text)

            temp_file = os.path.join(self.temp_dir, f"{hash(text)}.wav")

            piper_cmd = (
                [self.binary, "--model", model_path]
                + options
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

            with sf.SoundFile(temp_file) as f:
                duration = len(f) / f.samplerate

            return temp_file, duration

        except Exception as e:
            self.logger.error(f"Error generating audio: {e}")
            raise

    def play_audio(self, audio_file: str) -> bool:
        """Play audio file and return when playback actually starts"""
        try:
            mixer.music.load(audio_file)
            mixer.music.set_endevent(USEREVENT + 1)
            mixer.music.play()
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
