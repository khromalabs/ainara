#!/usr/bin/env python3
import argparse
import sys
import os
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Test Kokoro TTS voices")
    parser.add_argument("-v", "--voice", help="Voice ID (e.g., ef_dora, em_santa, af_sarah)", default=None)
    parser.add_argument("-l", "--lang", help="Language code (es, en-us)", default=None)
    parser.add_argument("text", nargs="?", help="Text to speak")

    args = parser.parse_args()

    # Set environment variables before importing KokoroTTS
    if args.lang:
        os.environ["AINARA_KOKORO_LANG"] = args.lang
    if args.voice:
        os.environ["AINARA_KOKORO_VOICE"] = args.voice

    # Now import framework (after env vars are set)
    current_dir = Path(__file__).resolve().parent
    root_dir = current_dir.parent
    sys.path.append(str(root_dir))

    from ainara.framework.config import config
    from ainara.framework.tts.kokoro import KokoroTTS

    # Load text from argument or stdin
    text = args.text
    if not text:
        if not sys.stdin.isatty():
            text = sys.stdin.read().strip()
        else:
            print("Usage: python scripts/test_tts.py 'Text to speak'")
            print("   OR: echo 'Text to speak' | python scripts/test_tts.py")
            return

    print(f"Initializing TTS... (Voice: {args.voice or 'default'}, Lang: {args.lang or 'default'})")

    # Load config to ensure defaults are present
    config.load_config()

    try:
        tts = KokoroTTS()
        print(f"Speaking: '{text}'")
        success = tts.speak(text, voice=args.voice, lang=args.lang)

        if success:
            print("Done.")
        else:
            print("Failed to speak.")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
