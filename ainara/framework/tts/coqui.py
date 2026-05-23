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
import shutil
import tempfile
import time
from typing import Tuple

import soundfile as sf
import torch
from langdetect import LangDetectException, detect
from pygame import USEREVENT, mixer
from TTS.api import TTS

from ..config import config
from .base import TTSBackend


class CoquiTTS(TTSBackend):
    """Coqui TTS implementation (YourTTS/XTTS)"""

    def __init__(self):
        """Initialize Coqui TTS backend"""
        super().__init__()
        self.logger = logging.getLogger(__name__)

        # Initialize pygame mixer
        mixer.init(frequency=22050)
        self.temp_dir = tempfile.mkdtemp(prefix="coqui_tts_")

        # Load configuration
        self.model_name = config.get(
            "tts.modules.coqui.model_name",
            "tts_models/multilingual/multi-dataset/your_tts",
        )
        self.use_cuda = config.get("tts.modules.coqui.use_cuda", False)
        self.speaker_wav = config.get(
            "tts.modules.coqui.speaker_wav", "resources/tts/samples/default.wav"
        )

        # Validate speaker reference
        if not os.path.exists(self.speaker_wav):
            # Try to resolve relative to project root if not absolute
            root_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "../../../")
            )
            alt_path = os.path.join(root_path, self.speaker_wav)
            if os.path.exists(alt_path):
                self.speaker_wav = alt_path
            else:
                self.logger.warning(
                    f"Reference voice file not found at {self.speaker_wav}. "
                    "Voice cloning will fail."
                )

        # Initialize Model
        self.logger.info(f"Loading Coqui TTS model: {self.model_name}")
        device = (
            "cuda" if self.use_cuda and torch.cuda.is_available() else "cpu"
        )
        self.logger.info(f"Coqui TTS running on: {device}")

        self.tts = TTS(model_name=self.model_name, progress_bar=False).to(
            device
        )

    def _detect_language(self, text: str) -> str:
        """Detect language code from text"""
        try:
            lang = detect(text)
            # YourTTS supports: en, es, fr, pt
            # XTTS supports many more
            # We assume the model handles the code or we might need mapping here
            self.logger.debug(f"Detected language: {lang}")
            return lang
        except LangDetectException:
            self.logger.warning(
                "Language detection failed, defaulting to 'en'"
            )
            return "en"

    def speak(self, text: str) -> bool:
        """Convert text to speech and play immediately"""
        try:
            self.stop()

            # Clean text
            cleaned_text = self._clean_text(text)
            if not cleaned_text.strip():
                return False

            # Detect language
            language = self._detect_language(cleaned_text)

            # Generate audio file
            temp_wav = os.path.join(
                self.temp_dir, f"speech_{abs(hash(cleaned_text))}.wav"
            )

            self.tts.tts_to_file(
                text=cleaned_text,
                speaker_wav=self.speaker_wav,
                language=language,
                file_path=temp_wav,
            )

            return self.play_audio(temp_wav)

        except Exception as e:
            self.logger.error(f"Error in Coqui speak: {e}")
            return False

    def generate_audio(self, text: str) -> Tuple[str, float]:
        """Generate audio file and return path + duration"""
        try:
            cleaned_text = self._clean_text(text)
            language = self._detect_language(cleaned_text)

            temp_wav = os.path.join(self.temp_dir, f"{hash(text)}.wav")

            self.tts.tts_to_file(
                text=cleaned_text,
                speaker_wav=self.speaker_wav,
                language=language,
                file_path=temp_wav,
            )

            # Get duration
            with sf.SoundFile(temp_wav) as f:
                duration = len(f) / f.samplerate

            return temp_wav, duration

        except Exception as e:
            self.logger.error(f"Error generating audio: {e}")
            raise

    def play_audio(self, audio_file: str) -> bool:
        """Play audio file using pygame"""
        try:
            mixer.music.load(audio_file)
            mixer.music.set_endevent(USEREVENT + 1)
            mixer.music.play()

            while not mixer.music.get_busy():
                time.sleep(0.001)

            # Wait for playback to finish (blocking behavior for speak())
            # Note: If async is needed, remove this loop
            while mixer.music.get_busy():
                time.sleep(0.1)

            return True
        except Exception as e:
            self.logger.error(f"Error playing audio: {e}")
            return False

    def stop(self) -> bool:
        """Stop playback"""
        try:
            mixer.stop()
            mixer.music.stop()
            return True
        except Exception as e:
            self.logger.error(f"Error stopping playback: {e}")
            return False

    def __del__(self):
        """Cleanup"""
        try:
            shutil.rmtree(self.temp_dir)
        except Exception:
            pass
