import logging
import os
import queue
import tempfile

import numpy as np
import requests
import sounddevice as sd
import soundfile as sf

from ..config import ConfigManager
from .base import STTBackend


class WhisperSTT(STTBackend):
    """OpenAI Whisper API implementation of STT backend"""

    def __init__(self):
        self.config = ConfigManager()
        self.sample_rate = 16000

        self.service = self.config.get("stt.modules.whisper.service", "openai")
        service_config = self.config.get(
            f"stt.modules.whisper.{self.service}", {}
        )

        if self.service not in ["openai", "custom"]:
            raise ValueError(f"Unknown Whisper service: {self.service}")

        self.api_key = service_config.get("api_key")
        self.api_url = service_config.get("api_url")
        self.model = service_config.get("model", "whisper-1")
        self.headers = service_config.get("headers", {})

        if not self.api_key or not self.api_url:
            raise RuntimeError(
                f"Whisper {self.service} service not properly configured"
            )

    def listen(self) -> str:
        """Record audio from microphone and transcribe"""
        logger = logging.getLogger(__name__)
        logger.info("Listening... Press Enter to stop recording")

        # Setup audio queue and recording flag
        audio_queue = queue.Queue()
        recording = True

        def audio_callback(indata, frames, time, status):
            if status:
                logger.warning(f"Audio status: {status}")
            if recording:
                audio_queue.put(indata.copy())

        # Start recording in a separate thread
        stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            callback=audio_callback,
            blocksize=int(self.sample_rate * 0.5),  # 0.5 second blocks
        )

        chunks = []
        with stream:
            # Wait for Enter key
            input()
            recording = False

            # Get remaining data from queue
            while not audio_queue.empty():
                chunks.append(audio_queue.get())

        logger.info("Processing speech...")

        if not chunks:
            logger.warning("No audio recorded")
            return ""

        # Convert to numpy array
        audio_data = np.concatenate(chunks)

        # Save to temporary file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            sf.write(f.name, audio_data, self.sample_rate)
            return self.transcribe_file(f.name)

    def transcribe_file(self, audio_file: str) -> str:
        """Transcribe an audio file using configured Whisper service"""
        try:
            headers = self.headers.copy()
            if self.service == "openai":
                headers["Authorization"] = f"Bearer {self.api_key}"
            elif self.service == "custom":
                headers["Authorization"] = self.api_key

            with open(audio_file, "rb") as f:
                files = {
                    "file": (os.path.basename(audio_file), f, "audio/wav"),
                    "model": (None, self.model),
                    "response_format": (None, "json"),
                    "language": (None, "auto"),
                    "task": (None, "transcribe"),
                }

                response = requests.post(
                    self.api_url, headers=headers, files=files
                )

                response.raise_for_status()
                result = response.json()

                return result.get("text", "").strip()

        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Transcription failed: {str(e)}")
            raise RuntimeError(
                f"Whisper {self.service} transcription failed: {str(e)}"
            )
