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
import re
import shutil
import subprocess
import sys
import tempfile
import time  # @TODO: For future CLI playback
from typing import Generator, Optional, Tuple

import soundfile as sf

# from ..config import config  # For future voice selection from config
from .base import TTSBackend

# from pygame import mixer, USEREVENT # @TODO: For future CLI playback


logger = logging.getLogger(__name__)


class MacOSTTS(TTSBackend):
    """
    Text-to-Speech backend using macOS's native 'say' command.
    Generates WAV audio files suitable for frontend consumption.
    Uses 'afconvert' (macOS built-in) for AIFF to WAV conversion.
    """

    def __init__(self):
        super().__init__()  # Initializes self.logger
        self.temp_dir = tempfile.mkdtemp(prefix="macos_tts_")
        self.afconvert_path = None  # Will be set in setup
        self._is_setup = False
        # @TODO: For future CLI playback, initialize pygame mixer here
        # For example:
        # try:
        #     mixer.init(frequency=22050) # Match PiperTTS for consistency
        # except Exception as e:
        #     logger.error(f"Pygame mixer initialization failed: {e}")
        #     # Decide if this is critical for MacOSTTS if CLI is ever enabled
        #     # For now, it's not critical as we focus on generate_audio
        logger.debug(f"MacOSTTS initialized. Temp dir: {self.temp_dir}")

    def setup(self) -> bool:
        """
        Validate and set up MacOSTTS requirements.
        Checks for macOS, 'say' command, and 'afconvert'.
        """
        logger.info("Setting up MacOSTTS...")
        if sys.platform != "darwin":
            logger.error("MacOSTTS can only be used on macOS.")
            self._is_setup = False
            return False

        if not shutil.which("say"):
            logger.error("'say' command not found. MacOSTTS cannot function.")
            self._is_setup = False
            return False
        logger.debug("'say' command found.")

        self.afconvert_path = shutil.which("afconvert")
        if not self.afconvert_path:
            logger.error(
                "'afconvert' command not found. MacOSTTS cannot perform WAV"
                " conversion. Please ensure Core Audio Utilities are installed"
                " (usually part of Xcode Command Line Tools)."
            )
            self._is_setup = False
            return False
        logger.debug(f"'afconvert' command found at: {self.afconvert_path}")

        logger.info("MacOSTTS setup successful.")
        self._is_setup = True
        return True

    def speak(self, text: str) -> bool:
        """
        Convert text to speech and play it.
        @TODO: Not fully implemented for CLI playback.
               This is a conceptual placeholder.
        """
        self.logger.info(
            "MacOSTTS.speak() called. @TODO: Implement for future CLI"
            " playback."
        )
        if not self._is_setup:
            logger.error("MacOSTTS not set up. Cannot speak.")
            return False

        # Conceptual implementation for future CLI playback:
        # self.stop() # Stop any current playback
        # audio_file, _ = self.generate_audio(text)
        # if audio_file:
        #     try:
        #         result = self.play_audio(audio_file)
        #         if result:
        #             # Wait for playback to complete if it's synchronous
        #             while mixer.music.get_busy(): # Requires pygame.mixer
        #                 time.sleep(0.1)
        #         return result
        #     finally:
        #         # Clean up the generated file if it was only for direct speech
        #         if os.path.exists(audio_file):
        #             try:
        #                 os.remove(audio_file)
        #             except Exception as e_clean:
        #                 logger.warning(f"Could not remove temp audio file {audio_file}: {e_clean}")
        return False

    def stop(self) -> bool:
        """
        Stop current speech.
        @TODO: Not fully implemented for CLI playback.
               This is a conceptual placeholder.
        """
        self.logger.info(
            "MacOSTTS.stop() called. @TODO: Implement for future CLI playback."
        )
        # Conceptual implementation for future CLI playback:
        # if self._is_setup:
        #     try:
        #         if mixer.get_init(): # Requires pygame.mixer
        #             mixer.music.stop()
        #             # mixer.stop() # May not be needed if only music is used
        #         return True
        #     except Exception as e:
        #         self.logger.error(f"Error stopping pygame mixer: {e}")
        #         return False
        return True  # Return True by default as there's no persistent process to stop for generate_audio

    def generate_audio(self, text: str) -> Tuple[Optional[str], float]:
        """
        Generate audio file for text and return its path and duration.
        Outputs a WAV file (22050 Hz, mono, 16-bit PCM Little Endian).
        """
        if not self._is_setup:
            logger.error("MacOSTTS not set up. Cannot generate audio.")
            return None, 0.0

        cleaned_text = self._clean_text(text)
        if not cleaned_text.strip():
            logger.warning("No text to synthesize after cleaning.")
            return None, 0.0

        temp_aiff_filepath = None
        target_wav_filepath = None

        try:
            # 1. Generate AIFF using 'say'
            unique_name = (
                f"macos_tts_{abs(hash(cleaned_text))}_{int(time.time() * 1000)}"
            )
            temp_aiff_filename = f"{unique_name}.aiff"
            temp_aiff_filepath = os.path.join(
                self.temp_dir, temp_aiff_filename
            )

            # Voice selection (optional, can be configured)
            voice_to_use = config.get("tts.modules.macos.voice", "Samantha")
            say_cmd = ["say", "-o", temp_aiff_filepath]
            say_cmd.extend(["-v", voice])
            say_cmd.append(cleaned_text)

            logger.debug(f"Running 'say' command: {' '.join(say_cmd)}")
            process_say = subprocess.Popen(
                say_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            _, stderr_say_bytes = process_say.communicate()
            stderr_say = stderr_say_bytes.decode(
                sys.getdefaultencoding(), errors="replace"
            )

            if process_say.returncode != 0:
                logger.error(
                    "macOS 'say' command failed (code"
                    f" {process_say.returncode}): {stderr_say}"
                )
                return None, 0.0

            if (
                not os.path.exists(temp_aiff_filepath)
                or os.path.getsize(temp_aiff_filepath) == 0
            ):
                logger.error(
                    "'say' command completed but AIFF file not found or is"
                    f" empty: {temp_aiff_filepath}. Stderr: {stderr_say}"
                )
                return None, 0.0
            logger.debug(f"Generated AIFF file: {temp_aiff_filepath}")

            # 2. Convert AIFF to WAV using afconvert
            target_wav_filename = f"{unique_name}.wav"
            target_wav_filepath = os.path.join(
                self.temp_dir, target_wav_filename
            )

            # WAV format: 22050 Hz, 1 channel (mono), signed 16-bit PCM Little Endian
            afconvert_cmd = [
                self.afconvert_path,
                temp_aiff_filepath,
                target_wav_filepath,
                "-f",
                "WAVE",  # Output format WAVE
                "-d",
                "LEI16@22050",  # Data format: Linear PCM, Little Endian, Integer 16-bit, @ 22050Hz
                "-c",
                "1",  # Channels: 1 (mono)
            ]
            logger.debug(
                f"Running afconvert command: {' '.join(afconvert_cmd)}"
            )
            process_afconvert = subprocess.Popen(
                afconvert_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            _, stderr_afconvert_bytes = process_afconvert.communicate()
            stderr_afconvert = stderr_afconvert_bytes.decode(
                sys.getdefaultencoding(), errors="replace"
            )

            if process_afconvert.returncode != 0:
                logger.error(
                    "afconvert AIFF to WAV conversion failed (code"
                    f" {process_afconvert.returncode}): {stderr_afconvert}"
                )
                return None, 0.0

            if (
                not os.path.exists(target_wav_filepath)
                or os.path.getsize(target_wav_filepath) == 0
            ):
                logger.error(
                    "afconvert command completed but WAV file not found or is"
                    f" empty: {target_wav_filepath}. Stderr:"
                    f" {stderr_afconvert}"
                )
                return None, 0.0
            logger.debug(f"Converted to WAV file: {target_wav_filepath}")

            # 3. Get duration of the final WAV file
            try:
                with sf.SoundFile(target_wav_filepath) as f_wav:
                    duration = len(f_wav) / f_wav.samplerate
            except Exception as e_dur:
                logger.error(
                    "Could not get duration of WAV file"
                    f" {target_wav_filepath} using soundfile: {e_dur}"
                )
                # As a last resort, try to parse afinfo if soundfile fails with the WAV
                try:
                    afinfo_cmd = ["afinfo", "-b", target_wav_filepath]
                    process_afinfo = subprocess.run(
                        afinfo_cmd,
                        capture_output=True,
                        text=True,
                        check=True,
                        encoding=sys.getdefaultencoding(),
                        errors="replace",
                    )
                    match = re.search(
                        r"duration:\s*([\d.]+)\s*sec", process_afinfo.stdout
                    )
                    if match:
                        duration = float(match.group(1))
                    else:
                        logger.error(
                            "Could not parse duration from afinfo output for"
                            f" {target_wav_filepath}"
                        )
                        return None, 0.0
                except Exception as e_afinfo_wav:
                    logger.error(
                        f"afinfo command failed for WAV {target_wav_filepath}:"
                        f" {e_afinfo_wav}"
                    )
                    return None, 0.0

            logger.debug(f"WAV file duration: {duration:.3f}s")

            return target_wav_filepath, duration

        except Exception as e:
            logger.error(
                f"Error in MacOSTTS.generate_audio: {e}", exc_info=True
            )
            return None, 0.0
        finally:
            # 4. Clean up the intermediate AIFF file
            if temp_aiff_filepath and os.path.exists(temp_aiff_filepath):
                try:
                    os.remove(temp_aiff_filepath)
                    logger.debug(
                        f"Cleaned up temporary AIFF file: {temp_aiff_filepath}"
                    )
                except Exception as e_clean:
                    logger.warning(
                        "Could not remove temporary AIFF file"
                        f" {temp_aiff_filepath}: {e_clean}"
                    )
            # Note: The generated WAV file (target_wav_filepath) is NOT cleaned up here.
            # It's expected to be used by ChatManager and cleaned up later by ChatManager._cleanup_audio_file

    def play_audio(self, audio_file: str) -> bool:
        """
        Play audio file asynchronously.
        @TODO: Not fully implemented for CLI playback.
               This is a conceptual placeholder.
        """
        self.logger.info(
            "MacOSTTS.play_audio() called. @TODO: Implement for future CLI"
            " playback."
        )
        # Conceptual implementation for future CLI playback:
        # if not self._is_setup:
        #     logger.error("MacOSTTS not set up. Cannot play audio.")
        #     return False
        # try:
        #     if mixer.get_init(): # Requires pygame.mixer
        #         mixer.music.load(audio_file)
        #         # mixer.music.set_endevent(USEREVENT + 1) # Optional: for event handling
        #         mixer.music.play()
        #         # Wait for playback to actually start for synchronization
        #         # This loop is crucial for accurate timing if used.
        #         while not mixer.music.get_busy() and mixer.music.get_pos() == -1: # Check get_pos for actual start
        #             time.sleep(0.001) # Sleep briefly
        #         return True
        #     else:
        #         logger.warning("Pygame mixer not initialized, cannot play audio for CLI.")
        #         return False
        # except Exception as e:
        #     self.logger.error(f"Error playing audio with pygame mixer: {e}")
        #     return False
        return False  # Default for non-CLI focus

    def speak_sync(
        self, text: str
    ) -> Generator[Tuple[str, float], None, None]:
        """
        Stream text to speech with precise timing.
        @TODO: Not implemented. This is a placeholder.
        """
        self.logger.info(
            "MacOSTTS.speak_sync() called. @TODO: Not implemented."
        )
        # This is a generator, so it must yield if it's to be called.
        # To make it a valid (but non-functional) generator:
        if False:
            yield "", 0.0
        return  # Or: raise NotImplementedError("speak_sync is not implemented for MacOSTTS")

    def __del__(self):
        """Cleanup temp files on deletion."""
        try:
            if hasattr(self, "temp_dir") and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                logger.debug(
                    f"Cleaned up MacOSTTS temp directory: {self.temp_dir}"
                )
        except Exception as e:
            logger.error(f"Error cleaning up MacOSTTS temp directory: {e}")
