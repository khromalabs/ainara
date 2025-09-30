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

import os
import shutil
import tempfile
import uuid
from typing import Tuple

from elevenlabs.client import ElevenLabs
from pydub import AudioSegment
from simpleaudio import WaveObject

from ainara.framework.config import ConfigManager
from ainara.framework.tts.base import TTSBackend


class ElevenLabsTTS(TTSBackend):
    """TTS backend using Eleven Labs API"""

    def __init__(self):
        super().__init__()
        self.config = ConfigManager()
        api_key = self.config.get("tts.modules.elevenlabs.api_key")
        if not api_key:
            self.logger.error("Eleven Labs API key not found in configuration")
            raise ValueError("Eleven Labs API key is required")

        self.client = ElevenLabs(api_key=api_key)
        self.voice = self.config.get("tts.modules.elevenlabs.voice", "uYXf8XasLslADfZ2MB4u")
        self.model = self.config.get("tts.modules.elevenlabs.model", "eleven_multilingual_v2")
        self.temp_dir = tempfile.mkdtemp(prefix="elevenlabs_tts_")
        self.playback_object = None
        self.logger.info(f"Initialized ElevenLabsTTS with voice: {self.voice}")

    def __del__(self):
        """Clean up temporary files"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def generate_audio(self, text: str) -> Tuple[str, float]:
        """Generate audio file for text and return its path and duration"""
        cleaned_text = self._clean_text(text)
        if not cleaned_text.strip():
            self.logger.warning("Skipping TTS for empty or cleaned text.")
            return "", 0.0

        try:
            audio_content = self.client.text_to_speech.convert(
                text=cleaned_text, voice_id=self.voice, model_id=self.model
            )
            output_filename = f"{uuid.uuid4()}.mp3"
            output_path = os.path.join(self.temp_dir, output_filename)
            with open(output_path, "wb") as f:
                for chunk in audio_content:
                    f.write(chunk)

            # Convert to WAV for simpleaudio and get duration
            audio = AudioSegment.from_mp3(output_path)
            wav_filename = f"{uuid.uuid4()}.wav"
            wav_path = os.path.join(self.temp_dir, wav_filename)
            audio.export(wav_path, format="wav")

            duration = len(audio) / 1000.0  # pydub duration is in milliseconds
            self.logger.debug(
                f"Generated audio file: {wav_path}, duration: {duration:.2f}s"
            )
            return wav_path, duration
        except Exception as e:
            self.logger.error(f"Error generating audio from Eleven Labs: {e}")
            return "", 0.0

    def play_audio(self, audio_file: str) -> bool:
        """Play audio file asynchronously"""
        if not os.path.exists(audio_file):
            self.logger.error(f"Audio file not found: {audio_file}")
            return False

        self.stop()  # Stop any currently playing audio

        try:
            wave_obj = WaveObject.from_wave_file(audio_file)
            self.playback_object = wave_obj.play()
            self.logger.info(f"Started playback of {audio_file}")
            return True
        except Exception as e:
            self.logger.error(f"Error playing audio file {audio_file}: {e}")
            return False

    def speak(self, text: str) -> bool:
        """Convert text to speech"""
        audio_file, _ = self.generate_audio(text)
        if audio_file:
            return self.play_audio(audio_file)
        return False

    def stop(self) -> bool:
        """Stop current speech"""
        if self.playback_object and self.playback_object.is_playing():
            self.playback_object.stop()
            self.playback_object = None
            self.logger.info("Stopped audio playback.")
            return True
        return False
