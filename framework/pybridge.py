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
import pprint
import shutil
import signal
import sys
import time
from datetime import datetime, timezone

from flask import Flask, Response, jsonify, request, send_file
from flask_cors import CORS

from ainara import __version__
from ainara.framework.chat_manager import ChatManager
from ainara.framework.config import ConfigManager
from ainara.framework.llm import create_llm_backend
from ainara.framework.logging_setup import logging_manager
from ainara.framework.stt.faster_whisper import FasterWhisperSTT
from ainara.framework.stt.whisper import WhisperSTT
from ainara.framework.tts.piper import PiperTTS
from ainara.framework.utils.dependency_checker import DependencyChecker
from ainara.framework.utils.paths import get_user_data_dir

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
        DependencyChecker.print_stt_dependency_report()
    except ImportError:
        logger.info(
            "Dependency checker not available, skipping dependency check"
        )

    tts = PiperTTS()

    # Choose STT backend based on configuration
    stt_selected_module = config.get("stt.selected_module", "faster_whisper")
    if stt_selected_module == "faster_whisper":
        # Pre-download the model if using faster-whisper
        model_size = config.get(
            "stt.modules.faster_whisper.model_size", "small"
        )
        try:
            logger.info(
                f"Pre-downloading Faster-Whisper {model_size} model..."
            )
            from huggingface_hub import hf_hub_download
            cache_dir = config.get_subdir("cache.directory", "whisper")
            model_path = hf_hub_download(
                repo_id=f"guillaumekln/faster-whisper-{model_size}",
                filename="model.bin",
                cache_dir=cache_dir,
            )
            logger.info(
                f"Faster-Whisper {model_size} model cached/downloaded to"
                f" {model_path}"
            )
        except Exception as e:
            logger.warning(f"Failed to pre-download model: {e}")
            logger.warning("Model will be downloaded when first used")

        stt = FasterWhisperSTT()
        logger.info("Using FasterWhisper STT backend")
    else:
        stt = WhisperSTT()
        logger.info("Using HTTP Whisper STT backend")

    # Initialize TTS with auto-setup
    try:
        logger.info("Initializing TTS system...")
        tts = PiperTTS()
        logger.info("TTS system initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize TTS system: {e}")
        import traceback

        logger.error(traceback.format_exc())
        raise

    # Use the appropriate user data directory
    user_data_dir = get_user_data_dir()
    static_dir = os.path.join(user_data_dir, 'static', 'pybridge')
    os.makedirs(static_dir, exist_ok=True)
    app.static_folder = static_dir
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
        memory_config = config.get("memory", {})
        memory_enabled = memory_config.get("enabled", False)

        status = {
            "status": "ok",
            "version": __version__,
            "uptime_seconds": (
                (datetime.now(timezone.utc) - startup_time).total_seconds()
            ),
            "services": {
                "chat_manager": app.chat_manager is not None,
                "config_manager": config is not None,
                "logging": logging_manager is not None,
            },
            "dependencies": {"llm_available": llm is not None},
        }

        # Only include storage check if memory is enabled
        if memory_enabled:
            status["dependencies"][
                "storage_available"
            ] = False  # Should implement actual storage check

        # Check if all essential services are available
        all_services_ok = all(status["services"].values())
        all_dependencies_ok = all(status["dependencies"].values())

        if not all_services_ok or not all_dependencies_ok:
            status["status"] = "degraded"
            status["message"] = "Some services or dependencies are unavailable"

        # Add response time measurement
        status["response_time_ms"] = (time.time() - start_time) * 1000

        return status

    @app.route("/config", methods=["GET"])
    def get_config():
        """Return the current configuration with sensitive information masked"""
        # Check if the request includes a parameter to show unmasked values
        show_sensitive = (
            request.args.get("show_sensitive", "false").lower() == "true"
        )

        if show_sensitive:
            # Return the full config without masking
            return jsonify(config.config)
        else:
            # Return the masked config for normal use
            safe_config = config.get_safe_config()
            return jsonify(safe_config)

    @app.route("/config", methods=["PUT"])
    def update_config():
        """Update the configuration"""
        try:
            data = request.get_json()
            if not data:
                return (
                    jsonify({"success": False, "error": "No data provided"}),
                    400,
                )

            # Validate the configuration
            validation_result = config.validate_config(data)
            if not validation_result["valid"]:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Invalid configuration",
                            "errors": validation_result["errors"],
                        }
                    ),
                    400,
                )

            # Update the configuration
            config.update_config(data)
            logger.info(f"new configuration: {pprint.pformat(data)}")
            # llm.initialize_provider(config)
            new_llm = create_llm_backend(config.get("llm", {}))
            app.chat_manager.llm = new_llm

            return jsonify({"success": True})
        except Exception as e:
            logger.error(f"Error updating configuration: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return jsonify({"success": False, "error": str(e)}), 500

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
        return jsonify(
            {
                "status": "available",
                "service": "PyBridge STT",
                "models": ["whisper-1"],
            }
        )

    @app.route("/framework/stt", methods=["POST"])
    def framework_stt():
        logger.info(
            f"Received STT request with files: {list(request.files.keys())}"
        )
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

        logger.info(
            f"STT request: model={model}, format={response_format},"
            f" language={language}, task={task}"
        )

        # Always save the uploaded file to a temporary location for consistent handling
        import os
        import tempfile

        # Create a temporary file
        fd, temp_path = tempfile.mkstemp(suffix=".wav")
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
                "model": model,
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

    @app.route("/providers", methods=["GET"])
    def get_providers():
        """Return a list of available LLM providers from LiteLLM with optional filtering"""
        try:
            # Get filter parameter (comma-separated list of model name fragments)
            filter_models = request.args.get("filter", "").lower().split(",")
            filter_models = [
                f.strip() for f in filter_models if f.strip()
            ]  # Clean up filters

            logger.info(
                "Model filter requested:"
                f" {filter_models if filter_models else 'None'}"
            )

            providers = llm.get_available_providers()
            # logger.info(f"PROVIDERS1:\n{pprint.pformat(providers)}")

            # Format the response
            formatted_providers = {}
            for provider_name, provider_data in providers.items():
                models = provider_data["models"]

                # Format models for the UI
                formatted_models = []
                for model in models:
                    # Only include chat models
                    if model.get("mode") in [
                        "chat",
                        "completion",
                        None,
                        "unknown",
                    ]:
                        # Apply filter if specified
                        model_name_lower = model["name"].lower()

                        if filter_models:
                            # Split into positive and negative filters
                            positive_filters = [
                                f
                                for f in filter_models
                                if not f.startswith("-")
                            ]
                            negative_filters = [
                                f[1:]
                                for f in filter_models
                                if f.startswith("-")
                            ]

                            # Check if model matches any positive filter (if there are any)
                            if positive_filters and not any(
                                f in model_name_lower for f in positive_filters
                            ):
                                continue

                            # Check if model matches any negative filter (exclude if it does)
                            if any(
                                f in model_name_lower for f in negative_filters
                            ):
                                continue

                        formatted_models.append(
                            {
                                "id": model["full_name"],
                                "name": model["name"],
                                # "default": (
                                #     False
                                # ),  # First one will be set to default below
                                "context_window": model.get("context_window"),
                            }
                        )

                # Skip providers with no usable models
                if not formatted_models:
                    continue

                # # Set first model as default if available
                # if formatted_models:
                #     formatted_models[0]["default"] = True

                formatted_providers[provider_name.lower()] = {
                    "name": provider_name,
                    "models": formatted_models,
                    "fields": [
                        {
                            "id": "api_key",
                            "name": "API Key",
                            "type": "password",
                            "required": True,
                        }
                    ],
                }

                # Add api_base field for providers that might need it
                if provider_name.lower() not in [
                    "openai",
                    "anthropic",
                    "google",
                ]:
                    formatted_providers[provider_name.lower()][
                        "fields"
                    ].append(
                        {
                            "id": "api_base",
                            "name": "API Base URL",
                            "type": "text",
                            "required": False,
                        }
                    )

            # Add a custom provider option
            formatted_providers["custom"] = {
                "name": "Custom API",
                "fields": [
                    {
                        "id": "api_base",
                        "name": "API Base URL",
                        "type": "text",
                        "placeholder": "http://localhost:8000/v1",
                        "required": True,
                    },
                    {
                        "id": "api_key",
                        "name": "API Key (if required)",
                        "type": "password",
                        "required": False,
                    },
                    {
                        "id": "model",
                        "name": "Model Name",
                        "type": "text",
                        "required": True,
                    },
                ],
            }

            # Add filter information to response
            response_data = {
                "providers": formatted_providers,
                "meta": {
                    "filtered": bool(filter_models),
                    "filters": filter_models if filter_models else [],
                },
            }

            logger.info(
                f"Returning {len(formatted_providers)} providers with filter:"
                f" {filter_models}"
            )
            return jsonify(response_data)
        except Exception as e:
            logger.error(f"Error getting providers: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return jsonify({"error": str(e), "providers": {}}), 500

    @app.route("/test-llm", methods=["POST"])
    def test_llm_connection():
        """Test LLM connection with provided parameters"""
        try:
            data = request.get_json()
            if "model" not in data:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": (
                                "Missing required parameters: model is"
                                " required"
                            ),
                        }
                    ),
                    400,
                )

            # Extract parameters
            model = data.get("model")
            provider = data.get("provider")
            api_key = data.get("api_key", None)  # Optional
            api_base = data.get("api_base", None)  # Optional

            # Create a temporary provider config for the LLM backend
            normalized_model = llm.normalize_model_name(model, provider)

            logger.info(
                f"Testing LLM connection for model: provider: {provider} "
                f" model (normalized): {normalized_model}"
            )

            temp_provider = {"model": normalized_model}

            # Add optional parameters if provided
            if api_key:
                temp_provider["api_key"] = api_key
            if api_base:
                temp_provider["api_base"] = api_base

            # Test with a simple conversation
            test_message = (
                "Hello, this is a test message. Please respond with a short"
                " greeting."
            )
            try:
                response = llm.chat(
                    chat_history=[
                        {
                            "role": "system",
                            "content": (
                                "You are a helpful assistant. Keep responses"
                                " very brief for this test."
                            ),
                        },
                        {"role": "user", "content": test_message},
                    ],
                    stream=False,
                    provider=temp_provider,
                )

                return jsonify(
                    {
                        "success": bool(response),
                        "message": (
                            "LLM connection test successful"
                            if response
                            else "LLM connection test failed"
                        ),
                        "test_prompt": test_message,
                        "response": response,
                    }
                )
            except Exception as e:
                logger.error(f"Error during LLM test chat: {e}")
                import traceback

                logger.error(traceback.format_exc())
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": (
                                f"Error during test conversation: {str(e)}"
                            ),
                        }
                    ),
                    500,
                )

        except Exception as e:
            logger.error(f"Error in test-llm endpoint: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/config/models_contexts", methods=["GET"])
    def get_llm_models():
        """Return available LLM models and their context sizes"""

        configured_providers = config.get("llm.providers", {})

        try:
            providers = llm.get_available_providers()
            result_models = []

            for configured_model in configured_providers:
                configured_model_get = configured_model.get("model")
                # First look in manually configured models contexts
                manual_model_contexts = config.get("llm.model_contexts")
                if configured_model_get in manual_model_contexts:
                    result_models.append({
                        "model": configured_model_get,
                        "context_window": manual_model_contexts.get(configured_model_get)
                    })
                    continue

                # Then look in the complete providers list
                configured_model_provider, configured_model_name = (
                    configured_model_get.split("/", 1)
                )
                if configured_model_provider in providers:
                    provider = providers[configured_model_provider]
                    for model in provider["models"]:
                        model_name = model.get("name")
                        if model_name == configured_model_name or model_name == configured_model_get:
                            result_models.append({
                                "model": configured_model.get("model"),
                                "context_window": model.get("context_window")
                            })
                            break

            return jsonify({"models": result_models})

        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/config/defaults", methods=["GET"])
    def get_default_config():
        """Return the default configuration"""
        try:
            import yaml
            import os
            import sys

            # Check if we're running in a PyInstaller bundle
            if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
                # Running in PyInstaller bundle
                # Use the bundled resource path
                default_config_path = os.path.join(sys._MEIPASS, "ainara", "resources", "ainara.yaml.defaults")
                logger.info(f"Running from PyInstaller bundle, looking for config at: {default_config_path}")
            else:
                # Running from source - use the original approach
                default_config_path = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "resources",
                    "ainara.yaml.defaults"
                )
                logger.info(f"Running from source, looking for config at: {default_config_path}")

            # Check if the file exists
            if not os.path.exists(default_config_path):
                logger.error(f"Default config file not found at: {default_config_path}")
                return jsonify({"error": "Default configuration file not found"}), 404

            # Load the default config
            with open(default_config_path, "r") as f:
                default_config = yaml.safe_load(f)

            return jsonify(default_config)
        except Exception as e:
            logger.error(f"Error loading default configuration: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500

    return app


if __name__ == "__main__":
    args = parse_args()
    # Set up logging first, before any logger calls
    logging_manager.setup(log_level=args.log_level, log_name="pybridge.log")
    logging_manager.addFilter(["pybridge", "chat_completion"])
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
