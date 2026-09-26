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
import tempfile
import time
from typing import Tuple

import requests
import soundfile as sf
from pygame import USEREVENT, mixer

from ..config import config
from .base import TTSBackend


class RemoteTTS(TTSBackend):
    """
    TTS Backend for OpenAI-compatible APIs.
    Works with:
    - OpenAI API
    - LocalAI
    - Any local server exposing /v1/audio/speech
    """

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)

        # Initialize mixer
        mixer.init()
        self.temp_dir = tempfile.mkdtemp(prefix="remote_tts_")

        # Config
        self.base_url = config.get(
            "tts.modules.remote.base_url", "http://localhost:8080/v1"
        )
        self.api_key = config.get(
            "tts.modules.remote.api_key", "sk-no-key-required"
        )
        self.model = config.get("tts.modules.remote.model", "tts-1")
        self.voice = config.get("tts.modules.remote.voice", "alloy")

        # Ensure base_url doesn't end with slash
        if self.base_url.endswith("/"):
            self.base_url = self.base_url[:-1]

    def speak(self, text: str) -> bool:
        try:
            self.stop()
            cleaned_text = self._clean_text(text)
            if not cleaned_text.strip():
                return False

            audio_path, _ = self.generate_audio(cleaned_text)
            return self.play_audio(audio_path)

        except Exception as e:
            self.logger.error(f"Error in RemoteTTS speak: {e}")
            return False

    def generate_audio(self, text: str) -> Tuple[str, float]:
        """Generate audio via API and return path + duration"""
        url = f"{self.base_url}/audio/speech"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {"model": self.model, "input": text, "voice": self.voice}

        try:
            response = requests.post(
                url, json=payload, headers=headers, stream=True
            )
            response.raise_for_status()

            # Save to temp file
            temp_wav = os.path.join(self.temp_dir, f"{abs(hash(text))}.mp3")

            with open(temp_wav, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            # Calculate duration (requires reading the file back)
            # Note: OpenAI usually returns MP3. Soundfile supports MP3 if
            # libsndfile is installed,
            # otherwise we might need pydub or just rely on mixer.
            try:
                with sf.SoundFile(temp_wav) as f:
                    duration = len(f) / f.samplerate
            except Exception:
                # Fallback if soundfile can't read mp3 directly without libs
                duration = 0.0

            return temp_wav, duration

        except Exception as e:
            self.logger.error(f"Remote TTS generation failed: {e}")
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
