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
import sys
import signal
import time

from flask import Flask, Response, jsonify, request, send_file
from datetime import datetime, timezone
from flask_cors import CORS

from ainara.framework.chat_manager import ChatManager
from ainara.framework.config import ConfigManager
from ainara.framework.llm import create_llm_backend
from ainara.framework.logging_setup import logging_manager
from ainara.framework.stt.whisper import WhisperSTT
from ainara.framework.stt.faster_whisper import FasterWhisperSTT
from ainara.framework.tts.piper import PiperTTS

from ainara import __version__

config = ConfigManager()
config.load_config()
llm = create_llm_backend(config.get("llm", {}))


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


app = Flask(__name__)
CORS(app)

# Set up logging first, before any logger calls
logging_manager.setup(log_dir="/tmp", log_level="INFO")
logging_manager.addFilter(["pybridge", "chat_completion"])


# Add at module level
startup_time = datetime.now(timezone.utc)


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

    # Get audio buffer size from config
    AUDIO_BUFFER_SIZE_MB = config.get("audio.buffer_size_mb", 10)

    # Check STT dependencies
    try:
        from ainara.framework.utils.dependency_checker import DependencyChecker
        # stt_deps = DependencyChecker.print_stt_dependency_report()
        DependencyChecker.print_stt_dependency_report()
    except ImportError:
        logger.info("Dependency checker not available, skipping dependency check")

    tts = PiperTTS()

    # Choose STT backend based on configuration
    stt_backend = config.get("stt.backend", "http_whisper")
    if stt_backend == "faster_whisper":
        # Pre-download the model if using faster-whisper
        model_size = config.get("stt.modules.faster_whisper.model_size", "small")
        try:
            logger.info(f"Pre-downloading Faster-Whisper {model_size} model...")
            from huggingface_hub import hf_hub_download

            cache_dir = os.path.expanduser("~/.cache/whisper")
            model_path = hf_hub_download(
                repo_id=f"guillaumekln/faster-whisper-{model_size}",
                filename="model.bin",
                cache_dir=cache_dir
            )
            logger.info(f"Faster-Whisper {model_size} model downloaded to {model_path}")
        except Exception as e:
            logger.warning(f"Failed to pre-download model: {e}")
            logger.warning("Model will be downloaded when first used")

        stt = FasterWhisperSTT()
        logger.info("Using FasterWhisper STT backend")
    else:
        stt = WhisperSTT()
        logger.info("Using HTTP Whisper STT backend")

    # Add static directory for audio files and clean any previous files
    app.static_folder = "../static/pybridge"
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

    @app.route("/health", methods=["GET"])
    def health_check():
        """Comprehensive health check endpoint"""
        start_time = time.time()

        # Get memory configuration
        memory_config = config.get('memory', {})
        memory_enabled = memory_config.get('enabled', False)

        status = {
            "status": "ok",
            "version": __version__,
            "uptime_seconds": (datetime.now(timezone.utc) - startup_time).total_seconds(),
            "services": {
                "capabilities_manager": app.capabilities_manager is not None,
                "config_manager": config is not None,
                "logging": logging_manager is not None
            },
            "dependencies": {
                "llm_available": llm and llm.is_available(),
            }
        }

        # Only include storage check if memory is enabled
        if memory_enabled:
            status["dependencies"]["storage_available"] = False  # Should implement actual storage check

        # Check if all essential services are available
        all_services_ok = all(status["services"].values())
        all_dependencies_ok = all(status["dependencies"].values())

        if not all_services_ok or not all_dependencies_ok:
            status["status"] = "degraded"
            status["message"] = "Some services or dependencies are unavailable"

        # Add response time measurement
        status["response_time_ms"] = (time.time() - start_time) * 1000

        return status

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

    # Add a new route for GET requests to the same endpoint
    @app.route("/framework/stt", methods=["GET"])
    def framework_stt_status():
        """Simple endpoint to check if the STT service is available"""
        return jsonify({
            "status": "available",
            "service": "PyBridge STT",
            "models": ["whisper-1"]
        })

    @app.route("/framework/stt", methods=["POST"])
    def framework_stt():
        logger.info(f"Received STT request with files: {list(request.files.keys())}")
        logger.info(f"Form data: {dict(request.form)}")

        if "file" not in request.files:
            # Try the 'audio' key as fallback for backward compatibility
            if "audio" not in request.files:
                return jsonify({"error": "No audio file provided"}), 400
            audio_file = request.files["audio"]
        else:
            audio_file = request.files["file"]

        # Extract other parameters that might be sent by Polaris
        model = request.form.get("model", "whisper-1")
        response_format = request.form.get("response_format", "json")
        language = request.form.get("language", "auto")
        task = request.form.get("task", "transcribe")

        logger.info(f"STT request: model={model}, format={response_format}, language={language}, task={task}")

        # Always save the uploaded file to a temporary location for consistent handling
        import tempfile
        import os

        # Create a temporary file
        fd, temp_path = tempfile.mkstemp(suffix='.wav')
        os.close(fd)

        try:
            # Save the uploaded file
            audio_file.save(temp_path)
            # Transcribe using the saved file path
            text = stt.transcribe_file(temp_path)

            # Format response to match what OpenAI Whisper API returns
            response = {
                "text": text,
                "task": task,
                "language": language,
                "duration": 0,  # We don't have actual duration info
                "model": model
            }
            return jsonify(response)
        except Exception as e:
            logger.error(f"Error transcribing audio: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return jsonify({"error": str(e), "text": ""}), 500
        finally:
            # Clean up
            if os.path.exists(temp_path):
                os.remove(temp_path)

    return app


if __name__ == "__main__":
    args = parse_args()
    app = create_app()

    # Add signal handler for graceful shutdown
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        # Run cleanup functions
        atexit._run_exitfuncs()
        sys.exit(0)

    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    app.run(port=args.port)
