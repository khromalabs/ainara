#!/usr/bin/env python3
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

logging.basicConfig()
logging.getLogger("faster_whisper").setLevel(logging.DEBUG)


def main():
    # Path to the audio file
    if len(sys.argv) < 2:
        print("Usage: python test_faster_whisper.py path/to/audio.wav")
        return

    audio_file = sys.argv[1]
    if not os.path.exists(audio_file):
        print(f"Error: File {audio_file} does not exist")
        return

    print(f"Testing faster-whisper with audio file: {audio_file}")

    try:
        # Import faster-whisper
        print("Importing faster-whisper...")
        from faster_whisper import WhisperModel

        # Load model
        print("Loading model (this may take a moment)...")
        start_time = time.time()
        model = WhisperModel(
            "small",
            device="cuda",
            compute_type="int8_float32",
            download_root=os.path.expanduser("~/.cache/whisper"),
        )
        load_time = time.time() - start_time
        print(f"Model loaded in {load_time:.2f} seconds")

        # Transcribe
        print("Transcribing audio...")
        start_time = time.time()

        # # First try with VAD
        # print("\nWith VAD:")
        # segments, info = model.transcribe(
        #     audio_file,
        #     beam_size=5,
        #     language="en",
        #     vad_filter=True,
        #     vad_parameters=dict(min_silence_duration_ms=500),
        # )
        # transcript_vad = " ".join(segment.text for segment in segments)
        # vad_time = time.time() - start_time

        # Then try without VAD
        # print("\nWithout VAD:")
        print("\nWith VAD:")
        start_time = time.time()
        segments, info = model.transcribe(
            audio_file, beam_size=3, language="en", vad_filter=True,
            # no_speech_threshold=0.8,  # Increase from default 0.6 to be less aggressive
            # log_prob_threshold=-2.0,  # Relax log probability threshold
        )
        transcript_no_vad = " ".join(segment.text for segment in segments)
        no_vad_time = time.time() - start_time

        # Print results
        print("\n--- Results ---")
        print(
            f"Language: {info.language} (probability:"
            f" {info.language_probability:.2f})"
        )
        # print(f"\nWith VAD ({vad_time:.2f}s):")
        # print(f"Transcript: {transcript_vad}")

        print(f"\nWithout VAD ({no_vad_time:.2f}s):")
        print(f"Transcript: {transcript_no_vad}")

    except Exception as e:
        import traceback

        print(f"Error: {e}")
        print(traceback.format_exc())


if __name__ == "__main__":
    main()