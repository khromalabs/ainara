import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Generator, Optional, Tuple

import soundfile as sf
from pygame import USEREVENT, mixer

from ..config import ConfigManager
from .base import TTSBackend


class PiperTTS(TTSBackend):
    """Piper implementation of TTS backend"""

    def __init__(self):
        """Initialize piper backend"""
        self._current_process: Optional[subprocess.Popen] = None
        self.config = ConfigManager()

        # Initialize pygame mixer for audio playback
        mixer.init(frequency=22050)

        # Create temp directory for audio files
        self.temp_dir = tempfile.mkdtemp(prefix="piper_tts_")

        # Initialize logging
        self.logger = logging.getLogger(__name__)

        self.logger.debug("PiperTTS initialization started")

        # Get piper config
        self.binary = self.config.get(
            "tts.modules.piper.binary", "/usr/bin/piper-tts"
        )
        self.model = self.config.get("tts.modules.piper.model")
        # Expand ~ in model path
        if self.model and "~" in self.model:
            self.model = os.path.expanduser(self.model)
        self.options = self.config.get("tts.modules.piper.options", "").split()

        self.logger.debug("Initialized PiperTTS with:")
        self.logger.debug(f"Binary: {self.binary}")
        self.logger.debug(f"Model: {self.model}")
        self.logger.debug(f"Options: {self.options}")

        # Check if model exists
        if not os.path.exists(self.model):
            self.logger.error(f"Model file not found: {self.model}")
            raise RuntimeError(f"Model file not found: {self.model}")

        # Check if model's json file exists
        # json_file = self.model.replace(".onnx", ".json")
        # json_file2 = self.model + ".json"
        # if not os.path.exists(json_file) or os.path.exists(json_file2):
        #     self.logger.error(f"Model config file not found: {json_file}")
        #     raise RuntimeError(f"Model config file not found: {json_file}")

        # Check if required commands are available
        try:
            self.logger.debug(f"Checking piper binary: {self.binary}")
            self.logger.debug(f"Using model: {self.model}")
            self.logger.debug(f"Using options: {self.options}")

            subprocess.run(
                [self.binary, "--help"], capture_output=True, check=True
            )
            # Check aplay installation
            if not shutil.which("aplay"):
                self.logger.error("aplay command not found")
                raise RuntimeError(
                    "aplay not found. Please install alsa-utils package"
                )

            subprocess.run(
                ["aplay", "--version"], capture_output=True, check=True
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            self.logger.error(f"Command check failed: {str(e)}")
            raise RuntimeError(
                "Required commands not found. Please install piper and sox"
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
                # Generate speech and pipe directly to aplay
                piper_cmd = (
                    [self.binary, "--model", self.model]
                    + self.options
                    + ["--output_raw"]
                )
                aplay_cmd = [
                    "aplay",
                    "-r",
                    "22050",
                    "-f",
                    "S16_LE",
                    "-t",
                    "raw",
                ]

                self.logger.debug(
                    f"Running piper command: {' '.join(piper_cmd)}"
                )
                self.logger.debug(
                    f"Running aplay command: {' '.join(aplay_cmd)}"
                )

                # Start piper process
                piper_process = subprocess.popen(
                    piper_cmd,
                    stdin=subprocess.pipe,
                    stdout=subprocess.pipe,
                    stderr=subprocess.pipe,
                    text=False,
                )

                # Start aplay process
                # self._current_process = subprocess.Popen(
                #     aplay_cmd,
                #     stdin=piper_process.stdout,
                #     stdout=subprocess.PIPE,
                #     stderr=subprocess.PIPE,
                # )

                # Clean and write the text to piper
                cleaned_phrase = self._clean_text(phrase)
                stdout, stderr = piper_process.communicate(
                    input=cleaned_phrase
                )
                if piper_process.returncode != 0:
                    self.logger.error(
                        "Piper failed with return code"
                        f" {piper_process.returncode}"
                    )
                    self.logger.error(f"Piper stderr: {stderr}")
                    raise RuntimeError(f"Piper failed: {stderr}")

                # Wait for audio playback to complete and track the actual
                # duration
                start_time = time.time()
                self._current_process.wait()
                actual_duration = time.time() - start_time

                # Print the phrase synchronized with audio
                # self._print_synchronized(phrase, actual_duration)

                # Yield for any external processing
                yield phrase, actual_duration

                # Small pause between phrases
                time.sleep(0.2)

            except Exception as e:
                print(f"Speech error: {e}")
                continue

    def speak(self, text: str) -> bool:
        self.logger.debug(f"speak() called with text: {text[:50]}...")
        """Convert text to speech using spd-say (non-streaming version)

        Args:
            text: The text to convert to speech

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Stop any current speech
            self.stop()

            # Generate speech and pipe directly to aplay
            piper_cmd = (
                [self.binary, "--model", self.model]
                + self.options
                + ["--output_raw"]
            )
            aplay_cmd = ["aplay", "-r", "22050", "-f", "S16_LE", "-t", "raw"]

            # Start piper process
            piper_process = subprocess.Popen(
                piper_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
            )

            # Start aplay process
            self._current_process = subprocess.Popen(
                aplay_cmd,
                stdin=piper_process.stdout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )

            # Close piper's stdout in the parent process
            piper_process.stdout.close()

            # Write the text to piper and get stderr
            self.logger.debug("Sending text to piper process")
            cleaned_text = self._clean_text(text)
            _, stderr = piper_process.communicate(
                input=cleaned_text.encode("utf-8")
            )
            stderr_text = stderr.decode("utf-8") if stderr else ""

            if piper_process.returncode != 0:
                self.logger.error(
                    f"Piper failed with return code {piper_process.returncode}"
                )
                self.logger.error(f"Piper stderr: {stderr_text}")
                return False

            # Wait for audio playback to complete
            self.logger.debug("Waiting for audio playback to complete")
            self._current_process.wait()
            self.logger.debug("Audio playback completed")
            return True
        except Exception:
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

    def _clean_text(self, text: str) -> str:
        """Remove symbols that shouldn't be read by TTS

        Args:
            text: Text to clean

        Returns:
            str: Cleaned text with removed symbols
        """
        return re.sub("[*#]", "", text)

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
            return True
        except Exception:
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
                text=True,
            )

            cleaned_text = self._clean_text(text)
            stdout, stderr = process.communicate(input=cleaned_text)

            if process.returncode != 0:
                self.logger.error(f"Piper failed: {stderr}")
                raise RuntimeError(f"Piper failed: {stderr}")

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
