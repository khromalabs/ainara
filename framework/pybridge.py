#!/usr/bin/env python3

# Ainara - Open Source AI Assistant Framework
# Copyright (C) 2025 Rubén Gómez https://www.khromalabs.org

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, see
# <https://www.gnu.org/licenses/>.

import argparse
import atexit
import logging
import os
import shutil

from flask import Flask, Response, jsonify, request, send_file
from flask_cors import CORS


def cleanup_audio_directory(static_folder: str) -> None:
    """Clean up all audio files from the static directory on server start"""
    audio_dir = os.path.join(static_folder, "audio")
    try:
        if os.path.exists(audio_dir):
            shutil.rmtree(audio_dir)
        os.makedirs(audio_dir)
        logger.info("Audio directory cleaned on server start")
    except Exception as e:
        logger.error(f"Error cleaning audio directory on startup: {e}")


logger = logging.getLogger(__name__)


def get_directory_size(directory):
    """Calculate total size of files in directory in bytes"""
    total_size = 0
    for dirpath, _, filenames in os.walk(directory):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            total_size += os.path.getsize(fp)
    return total_size


def cleanup_audio_buffer(directory, max_size_mb):
    """Clean up oldest files until directory is under max size"""
    max_size_bytes = max_size_mb * 1024 * 1024  # Convert MB to bytes

    # Get list of files with their creation times
    files = []
    for filename in os.listdir(directory):
        filepath = os.path.join(directory, filename)
        if os.path.isfile(filepath):
            files.append((filepath, os.path.getctime(filepath)))

    # Sort by creation time (oldest first)
    files.sort(key=lambda x: x[1])

    # Remove oldest files until we're under the limit
    current_size = get_directory_size(directory)
    for filepath, _ in files:
        if current_size <= max_size_bytes:
            break
        try:
            file_size = os.path.getsize(filepath)
            os.remove(filepath)
            current_size -= file_size
            logger.debug(f"Cleaned up old audio file: {filepath}")
        except Exception as e:
            logger.error(f"Error cleaning up old audio file: {e}")


from ainara.framework.chat_manager import ChatManager
from ainara.framework.config import ConfigManager
from ainara.framework.llm import create_llm_backend
from ainara.framework.logging_setup import logging_manager
from ainara.framework.stt.whisper import WhisperSTT
from ainara.framework.tts.piper import PiperTTS

app = Flask(__name__)
CORS(app)

# Set up logging first, before any logger calls
logging_manager.setup(log_dir="/tmp", log_level="INFO")
logging_manager.addFilter(["pybridge", "chat_completion"])


def parse_args():
    parser = argparse.ArgumentParser(description="PyBridge Server")
    parser.add_argument(
        "--port",
        type=int,
        default=5001,
        help="Port to run the server on (default: 5001)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: INFO)",
    )
    return parser.parse_args()


def create_app():
    config = ConfigManager()
    config.load_config()

    # Get audio buffer size from config
    AUDIO_BUFFER_SIZE_MB = config.get("audio.buffer_size_mb", 10)

    llm_config = config.get("llm", {})
    llm = create_llm_backend(llm_config)

    tts = PiperTTS()
    stt = WhisperSTT()

    # Add static directory for audio files and clean any previous files
    app.static_folder = "static"
    cleanup_audio_directory(app.static_folder)

    # Register cleanup function to run on server shutdown
    def cleanup_on_shutdown():
        try:
            audio_dir = os.path.join(app.static_folder, "audio")
            shutil.rmtree(audio_dir)
            os.makedirs(audio_dir)
            logger.info("Audio buffer cleaned up on shutdown")
        except Exception as e:
            logger.error(f"Error cleaning audio buffer on shutdown: {e}")

    atexit.register(cleanup_on_shutdown)

    # Create chat_manager as app attribute so it's accessible to all routes
    app.chat_manager = ChatManager(
        llm=llm,
        tts=tts,
        flask_app=app,
        orakle_servers=config.get("orakle.servers", ["http://127.0.0.1:5000"]),
    )

    @app.route("/static/audio/<filename>")
    def serve_audio(filename):
        """Serve audio files and maintain buffer size"""
        audio_dir = os.path.join(app.static_folder, "audio")

        # Check buffer size and cleanup if needed
        cleanup_audio_buffer(audio_dir, AUDIO_BUFFER_SIZE_MB)

        return send_file(
            os.path.join(audio_dir, filename), mimetype="audio/wav"
        )

    @app.route("/framework/chat", methods=["POST"])
    def framework_chat():
        data = request.get_json()

        def generate():
            for event in app.chat_manager.chat_completion(
                data["message"], stream="json"
            ):
                yield event

        return Response(generate(), mimetype="text/event-stream")

    @app.route("/framework/tts", methods=["POST"])
    def framework_tts():
        data = request.get_json()
        success = tts.speak(data["text"])
        return jsonify({"success": success})

    @app.route("/framework/stt", methods=["POST"])
    def framework_stt():
        if "audio" not in request.files:
            return jsonify({"error": "No audio file provided"}), 400
        audio_file = request.files["audio"]
        text = stt.transcribe_file(audio_file)
        return jsonify({"text": text})

    return app


if __name__ == "__main__":
    args = parse_args()
    app = create_app()
    app.run(port=args.port)
