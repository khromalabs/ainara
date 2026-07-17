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
import sys
import time
from pathlib import Path
from typing import Tuple

import soundfile as sf
from kokoro_onnx import Kokoro
# import numpy as np  # Enabled for silence padding
from misaki.espeak import EspeakG2P
from pygame import USEREVENT, mixer

from ..config import config
from ..config import get_data_dir
from .base import TTSBackend


class KokoroTTS(TTSBackend):
    """
    Kokoro TTS implementation using ONNX Runtime.
    Follows the resource discovery pattern of PiperTTS.
    """

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)

        # Initialize mixer (Kokoro v1.0 is 24khz)
        mixer.init(frequency=24000)

        # Configuration - check env vars first, then config, then defaults
        self.default_lang = os.environ.get(
            "AINARA_KOKORO_LANG",
            config.get("tts.modules.kokoro.default_lang", "en-us")
        )
        self.default_voice = os.environ.get(
            "AINARA_KOKORO_VOICE",
            config.get("tts.modules.kokoro.default_voice", "af_heart")
        )
        self.default_speed = config.get(
            "tts.modules.kokoro.default_speed", 1.2
        )

        self.logger.info(f"Using default voice: {self.default_voice}")

        # Initialize G2P for phonemization
        self.g2p = EspeakG2P(language=self.default_lang)

        # Define Model Directories
        # 1. User Data Directory (Persistent downloads)
        self.user_models_dir = (
            get_data_dir() / "tts" / "kokoro" / "models"
        )
        # 2. Bundled Resources Directory (App distribution)
        self.bundled_models_dir = (
            self._get_resource_base_dir() / "resources" / "tts" / "models"
        )

        # State
        self.model_path: str = None
        self.voices_path: str = None

        # Run setup
        if not self.setup():
            msg = (
                "Kokoro TTS setup failed. Model files (kokoro-v1.0.onnx,"
                " voices.json) not found in bundled or user directories."
            )
            self.logger.error(msg)
            raise RuntimeError(msg)

        # Initialize Engine
        self.logger.info(
            f"Loading Kokoro ONNX engine from {self.model_path}..."
        )
        try:
            self.engine = Kokoro(self.model_path, self.voices_path)
        except Exception as e:
            self.logger.error(f"Failed to initialize Kokoro: {e}")
            raise

    def _get_resource_base_dir(self) -> Path:
        """Determine the base directory for resources (project root or MEIPASS)."""
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            return Path(sys._MEIPASS)
        else:
            return Path(__file__).parent.parent.parent.parent

    def setup(self) -> bool:
        """
        Locate Kokoro model files.
        """
        self.logger.info("Setting up Kokoro TTS...")

        # We look for v1.0 files specifically
        model_filename = "kokoro-v1.0.onnx"
        voices_filename = "voices-v1.0.bin"

        # Check User Directory first
        u_model = self.user_models_dir / model_filename
        u_voices = self.user_models_dir / voices_filename

        self.logger.info(f"Looking for models in: {u_model}")

        if u_model.exists() and u_voices.exists():
            self.model_path = str(u_model)
            self.voices_path = str(u_voices)
            self.logger.info(
                f"Found Kokoro models in user data: {self.model_path}"
            )
            return True

        # Check Bundled Directory
        b_model = self.bundled_models_dir / model_filename
        b_voices = self.bundled_models_dir / voices_filename

        if b_model.exists() and b_voices.exists():
            self.model_path = str(b_model)
            self.voices_path = str(b_voices)
            self.logger.info(
                f"Found Kokoro models in bundled resources: {self.model_path}"
            )
            return True

        return False

    def speak(self, text: str, lang: str = None, voice: str = None) -> bool:
        try:
            self.stop()

            cleaned_text = self._clean_text(text)
            if not cleaned_text.strip():
                return False
            # Use defaults if not provided
            target_voice = voice or self.default_voice

            # Phonemize text using Misaki G2P
            phonemes, _ = self.g2p(cleaned_text)

            # Generate audio
            samples, sample_rate = self.engine.create(
                phonemes,
                voice=target_voice,
                speed=self.default_speed,
                is_phonemes=True,
            )

            # Save to temp file for pygame playback
            try:
                temp_dir = os.path.dirname(self.model_path)
                test_file = os.path.join(temp_dir, ".test_write")
                with open(test_file, "w") as f:
                    f.write("test")
                os.remove(test_file)
            except (IOError, PermissionError):
                import tempfile

                temp_dir = tempfile.gettempdir()

            temp_wav = os.path.join(
                temp_dir, f"speech_{abs(hash(cleaned_text))}.wav"
            )

            sf.write(temp_wav, samples, sample_rate)

            return self.play_audio(temp_wav)

        except Exception as e:
            self.logger.error(f"Error in Kokoro speak: {e}")
            return False

    def generate_audio(self, text: str) -> Tuple[str, float]:
        try:
            cleaned_text = self._clean_text(text)

            # Phonemize text using Misaki G2P
            phonemes, _ = self.g2p(cleaned_text)

            samples, sample_rate = self.engine.create(
                phonemes,
                voice=self.default_voice,
                speed=self.default_speed,
                is_phonemes=True,
            )

            # Determine temp dir
            try:
                temp_dir = os.path.dirname(self.model_path)
                test_file = os.path.join(temp_dir, ".test_write")
                with open(test_file, "w") as f:
                    f.write("test")
                os.remove(test_file)
            except (IOError, PermissionError):
                import tempfile

                temp_dir = tempfile.gettempdir()

            temp_wav = os.path.join(temp_dir, f"{hash(text)}.wav")

            sf.write(temp_wav, samples, sample_rate)

            duration = len(samples) / sample_rate
            return temp_wav, duration

        except Exception as e:
            self.logger.error(f"Error generating audio: {e}")
            raise

    def play_audio(self, audio_file: str) -> bool:
        try:
            mixer.music.load(audio_file)
            mixer.music.set_endevent(USEREVENT + 1)
            mixer.music.play()

            while mixer.music.get_busy():
                time.sleep(0.1)

            return True
        except Exception as e:
            self.logger.error(f"Error playing audio: {e}")
            return False

    def stop(self) -> bool:
        mixer.music.stop()
        return True
