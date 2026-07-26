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

# <https://www.gnu.org/licenses/>.

import argparse
import atexit
import json
import logging
import os
import shutil
import signal
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests
from flask import Flask, Response, jsonify, request, send_file, send_from_directory
from flask_cors import CORS
from flask_sock import Sock

from ainara import __version__
from ainara.framework.auth import AuthManager
from ainara.framework.backup import BackupManager
from ainara.framework.chat_manager import ChatManager
from ainara.framework.chat_memory import ChatMemory
from ainara.framework.config import config
from ainara.framework.dependency_checker import DependencyChecker
from ainara.framework.green_memories import GREENMemories
from ainara.framework.health_monitor import HealthMonitor
from ainara.framework.llm import create_llm_backend
from ainara.framework.llm.litellm import LiteLLM
from ainara.framework.logging_setup import logging_manager
from ainara.framework.notifications import NotificationManager
from ainara.framework.stt.faster_whisper import FasterWhisperSTT
from ainara.framework.stt.whisper import WhisperSTT
from ainara.framework.tts import create_tts_backend
from ainara.framework.utils import check_embedding_model, setup_embedding_model
from ainara.framework.wakeword import create_wakeword_backend

config.load_config()


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


def shutdown_server():
    """Gracefully shut down the server."""
    logger.info("Shutdown signal received. Shutting down server.")
    # Use os.kill to send SIGINT to the current process
    # This is more reliable for stopping Flask's development server
    os.kill(os.getpid(), signal.SIGINT)


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
sock = Sock(app)


# Add at module level
startup_time = datetime.now(timezone.utc)


def parse_args():
    parser = argparse.ArgumentParser(description="PyBridge Server")
    parser.add_argument(
        "--port",
        type=int,
        default=8101,
        help="Port to run the server on (default: 8101)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: INFO)",
    )
    parser.add_argument(
        "--profile",
        action="store_true",
        help="Enable profiling for the server",
    )
    return parser.parse_args()


# def setup_app()


def _validate_skill_key(service: str, keys: dict):
    """Performs a simple API call to validate credentials for a given service."""
    logger.info(f"Validating API key for service: {service}")
    headers = {}
    params = {}

    try:
        if service == "tavily":
            api_key = keys.get("api_key")
            if not api_key:
                return False, "API key is missing"
            response = requests.post(
                "https://api.tavily.com/search",
                json={"api_key": api_key, "query": "test", "max_results": 1},
                timeout=10,
            )
            response.raise_for_status()
            return True, "Key is valid."

        elif service == "google":
            api_key = keys.get("api_key")
            cse_id = keys.get("cx")
            if not api_key or not cse_id:
                return False, "API Key and Search Engine ID are required"
            params = {"key": api_key, "cx": cse_id, "q": "test"}
            response = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params=params,
                timeout=10,
            )
            response.raise_for_status()
            return True, "Key and CSE ID are valid."

        elif service == "coinmarketcap":
            api_key = keys.get("api_key")
            if not api_key:
                return False, "API key is missing"
            headers = {"X-CMC_PRO_API_KEY": api_key}
            response = requests.get(
                "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest",
                headers=headers,
                params={"limit": 1},
                timeout=10,
            )
            response.raise_for_status()
            return True, "Key is valid."

        elif service == "newsapi":
            api_key = keys.get("api_key")  # Note: key is apiKey
            if not api_key:
                return False, "API key is missing"
            params = {"q": "test", "apiKey": api_key}
            response = requests.get(
                "https://newsapi.org/v2/everything", params=params, timeout=10
            )
            response.raise_for_status()
            return True, "Key is valid."

        elif service == "perplexity":
            api_key = keys.get("api_key")
            if not api_key:
                return False, "API key is missing"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            data = {
                "model": "sonar",
                "messages": [{"role": "user", "content": "test"}],
            }
            response = requests.post(
                "https://api.perplexity.ai/chat/completions",
                headers=headers,
                json=data,
                timeout=10,
            )
            response.raise_for_status()
            return True, "Key is valid."

        elif service == "metaphor":
            api_key = keys.get("api_key")
            if not api_key:
                return False, "API key is missing"
            headers = {
                "x-api-key": api_key,
                "Content-Type": "application/json",
            }
            data = {"query": "test", "numResults": 1}
            response = requests.post(
                "https://api.metaphor.systems/search",
                headers=headers,
                json=data,
                timeout=10,
            )
            response.raise_for_status()
            return True, "Key is valid."

        elif service == "finance":
            api_key = keys.get("alphavantage_api_key")
            if not api_key:
                return False, "API key is missing"
            params = {
                "function": "SYMBOL_SEARCH",
                "keywords": "BA",
                "apikey": api_key,
            }
            response = requests.get(
                "https://www.alphavantage.co/query",
                params=params,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            if "Error Message" in data or "Information" in data:
                return False, data.get("Error Message") or data.get(
                    "Information"
                )
            return True, "Key is valid."

        elif service == "weather":
            api_key = keys.get("openweathermap_api_key")
            if not api_key:
                return False, "API key is missing"
            params = {"q": "London", "appid": api_key}
            response = requests.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params=params,
                timeout=10,
            )
            response.raise_for_status()
            return True, "Key is valid."

        elif service == "helius":
            api_key = keys.get("api_key")
            if not api_key:
                return False, "API key is missing"
            data = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAsset",
                "params": ["So11111111111111111111111111111111111111112"]
            }
            response = requests.post(
                f"https://mainnet.helius-rpc.com/?api-key={api_key}",
                json=data,
                timeout=10,
            )
            response.raise_for_status()
            return True, "Key is valid."

        else:
            return (
                False,
                f"Validation for service '{service}' is not implemented.",
            )

    except requests.HTTPError as e:
        # Attempt to get a more specific error from the response body
        error_message = str(e)
        try:
            error_details = e.response.json()
            if "error" in error_details:
                if isinstance(error_details["error"], dict):
                    error_message = error_details["error"].get(
                        "message", str(error_details)
                    )
                else:
                    error_message = error_details["error"]
            elif "message" in error_details:
                error_message = error_details["message"]
        except json.JSONDecodeError:
            pass  # Stick with the original HTTPError message
        return False, error_message
    except requests.RequestException as e:
        return False, str(e)


def _send_progress(status: str, progress: int, message: str):
    """Sends a progress update to stdout for the parent process."""
    update = {"status": status, "progress": progress, "message": message}
    # Prefix to make it easy to parse from Node.js
    print(f"PYBRIDGE_PROGRESS:{json.dumps(update)}")
    sys.stdout.flush()


def check_resources():
    """Check if required resources are available"""
    try:
        results = {"status": "success", "initialized": False, "details": {}}

        # Check Whisper models
        whisper_status = {"initialized": False}
        stt_selected_module = config.get(
            "stt.selected_module", "faster_whisper"
        )
        if stt_selected_module == "faster_whisper":
            try:
                # FasterWhisperSTT reads config to determine model size
                stt_checker = FasterWhisperSTT()
                whisper_status = stt_checker.check_model()
            except Exception as e:
                logger.error(f"Error checking whisper model: {e}")
                whisper_status["initialized"] = False
                whisper_status["message"] = f"Error checking model: {e}"
        else:  # whisper http
            whisper_status["initialized"] = True
        results["details"]["whisper"] = whisper_status

        # Check embedding model
        embedding_status = check_embedding_model()
        results["details"]["embedding"] = embedding_status

        # Review the overall status
        if whisper_status["initialized"] and embedding_status["initialized"]:
            results["initialized"] = True

        return results
    except Exception as e:
        logger.error(f"Error checking resources: {e}")
        import traceback

        logger.error(traceback.format_exc())
        return {
            "status": "error",
            "message": str(e),
            "initialized": False,
        }


def initialize_resources(status: dict):
    """
    Initialize required resources and stream progress to stdout.
    """
    # Temporarily disable offline mode to allow downloads
    original_hf_offline = os.environ.get("HF_HUB_OFFLINE")
    if "HF_HUB_OFFLINE" in os.environ:
        del os.environ["HF_HUB_OFFLINE"]
    try:
        _send_progress("running", 0, "Starting initialization...")

        resources_to_init = []
        if not status.get("details", {}).get("whisper", {}).get("initialized"):
            resources_to_init.append("whisper")
        if (
            not status.get("details", {})
            .get("embedding", {})
            .get("initialized")
        ):
            resources_to_init.append("embedding")

        # Check if embedding model needs initialization
        embedding_check = check_embedding_model()
        if not embedding_check.get("initialized"):
            resources_to_init.append("embedding")
        if not resources_to_init:
            _send_progress(
                "complete", 100, "All resources already initialized"
            )
            logger.info("Initialization: Resources already present.")
            return True

        completed_resources = 0
        total_resources = len(resources_to_init)
        progress_per_resource = (
            80 / total_resources if total_resources > 0 else 80
        )

        # --- Initialize Whisper models if needed ---
        if "whisper" in resources_to_init:
            current_progress = int(completed_resources * progress_per_resource)
            _send_progress(
                "running", current_progress, "Setting up Whisper models..."
            )
            logger.info("Initialization: Setting up Whisper models...")
            # Instantiating the class will trigger the download
            stt = FasterWhisperSTT()
            whisper_result = stt.setup_model()
            if not whisper_result["success"]:
                message = f"Whisper setup failed: {whisper_result['message']}"
                _send_progress("error", current_progress, message)
                logger.error(message)
                return False
            stt.load_model()
            completed_resources += 1
            _send_progress(
                "running",
                int(completed_resources * progress_per_resource),
                "Whisper setup complete.",
            )

        # --- Initialize Embedding model if needed ---
        if "embedding" in resources_to_init:
            current_progress = int(completed_resources * progress_per_resource)
            _send_progress(
                "running",
                current_progress,
                "Setting up embedding model...",
            )
            logger.info("Initialization: Setting up embedding model...")
            embedding_result = setup_embedding_model()  # Blocking call
            if not embedding_result["success"]:
                message = (
                    "Embedding model setup failed:"
                    f" {embedding_result['message']}"
                )
                _send_progress("error", current_progress, message)
                logger.error(message)
                return False
            completed_resources += 1
            _send_progress(
                "running",
                int(completed_resources * progress_per_resource),
                "Embedding model setup complete.",
            )

        # --- Final success message ---
        _send_progress("complete", 80, "Initialization completed successfully")
        logger.info("Initialization: Completed successfully.")
        return True

    except Exception as e:
        logger.error(f"Error during initialization: {e}")
        import traceback

        logger.error(traceback.format_exc())
        _send_progress("error", 0, f"Initialization error: {str(e)}")
        return False

    finally:
        # Restore the original offline mode setting
        if original_hf_offline is not None:
            os.environ["HF_HUB_OFFLINE"] = original_hf_offline
        else:
            os.environ.pop("HF_HUB_OFFLINE", None)


def check_download_capability():
    """Check if Hugging Face Hub is reachable for resource downloads."""
    try:
        # Use a lightweight HEAD request to check connectivity without downloading content
        response = requests.head("https://huggingface.co", timeout=10)
        response.raise_for_status()  # Raises HTTPError for 4xx/5xx status
        logger.info("Hugging Face Hub is reachable.")
        return {
            "can_download": True,
            "message": "Hugging Face Hub is reachable.",
        }
    except requests.RequestException as e:
        logger.warning(f"Could not reach Hugging Face Hub: {e}")
        return {
            "can_download": False,
            "message": f"Could not reach Hugging Face Hub: {str(e)}",
        }


def create_app():
    llm = create_llm_backend(config.get("llm", {}))
    app.llm = llm

    # Initialize background event queue
    app.background_queue = []

    # # --- DEBUG: ChromaDB Dependency Check ---
    # import sys
    # import traceback
    # logger.info("Starting ChromaDB dependency debug check...")
    # logger.info(f"Platform: {sys.platform}, Frozen: {getattr(sys, 'frozen', False)}")
    # if getattr(sys, 'frozen', False):
    #     logger.info(f"MEIPASS path: {sys._MEIPASS}")
    #
    # chroma_deps = [
    #     ('chromadb', 'import chromadb'),
    #     ('chromadb-hnswlib', 'import hnswlib'),
    #     ('onnxruntime', 'import onnxruntime'),
    #     ('onnxruntime.capi', 'from onnxruntime import capi as onnx_capi'),  # Check binary extension
    # ]
    #
    # for dep, import_stmt in chroma_deps:
    #     try:
    #         exec(import_stmt)
    #         logger.info(f"SUCCESS: Imported {dep}")
    #         # Check for a key file in MEIPASS (e.g., hnswlib binary)
    #         if dep == 'hnswlib' and getattr(sys, 'frozen', False):
    #             hnswlib_path = os.path.join(sys._MEIPASS, 'hnswlib', 'hnswlib.pyd')  # Adjust for Windows .pyd
    #             if os.path.exists(hnswlib_path):
    #                 logger.info(f"SUCCESS: Found hnswlib binary at {hnswlib_path}")
    #             else:
    #                 logger.info(f"WARNING: hnswlib binary not found at {hnswlib_path}")
    #     except Exception as e:
    #         logger.info(f"FAILURE: {dep} - {str(e)}\n{traceback.format_exc()}")
    # logger.info("ChromaDB dependency debug check complete.")
    # # --- END DEBUG ---

    # Get audio buffer size from config
    AUDIO_BUFFER_SIZE_MB = config.get("audio.buffer_size_mb", 10)

    # Check STT dependencies
    try:
        DependencyChecker.print_stt_dependency_report()

        # Log more detailed information about hardware acceleration
        cuda_available, cuda_version, missing_libs, cuda_details = (
            DependencyChecker.check_cuda_availability()
        )
        if cuda_available:
            logger.info(
                f"CUDA {cuda_version} is available for hardware acceleration"
            )
            if cuda_details.get("device_name"):
                logger.info(f"Using GPU: {cuda_details['device_name']}")
        elif cuda_details["has_nvidia_hardware"]:
            logger.warning("NVIDIA GPU detected but CUDA is not available")
            logger.warning("Speech recognition will use CPU mode (slower)")
            if sys.platform == "win32":
                logger.warning(
                    "On Windows, you may need to install NVIDIA CUDA drivers"
                    " manually"
                )
                logger.warning(
                    "Visit https://www.nvidia.com/Download/index.aspx to"
                    " download drivers"
                )
    except ImportError:
        logger.info(
            "Dependency checker not available, skipping dependency check"
        )

    # Choose STT backend based on configuration. This is safe now because
    # the main script block ensures models are downloaded before this runs.
    # TODO Remove the STT configuration and setup from the server code
    stt_selected_module = config.get("stt.selected_module", "faster_whisper")
    if stt_selected_module == "faster_whisper":
        stt = FasterWhisperSTT()
        logger.info("Using FasterWhisper STT backend")
    else:
        stt = WhisperSTT()
        logger.info("Using HTTP Whisper STT backend")

    # Initialize TTS with auto-setup
    try:
        logger.info("Initializing TTS system...")
        tts_config = config.get("tts", {})
        tts = create_tts_backend(tts_config)
        logger.info(
            "TTS system initialized successfully using"
            f" {tts.__class__.__name__}"
        )
    except Exception as e:
        logger.error(f"Failed to initialize TTS system: {e}")
        import traceback

        logger.error(traceback.format_exc())
        raise

    # --- Initialize Wake Word Backend ---
    try:
        logger.info("Initializing Wake Word backend...")
        app.wakeword = create_wakeword_backend(config.config)
        app.wakeword.load_model()
        logger.info(f"Wake Word backend initialized. Models: {app.wakeword.get_loaded_models()}")
    except Exception as e:
        logger.error(f"Failed to initialize Wake Word backend: {e}")
        app.wakeword = None

    # Use the appropriate user data directory
    user_data_dir = config.get("data.directory")
    static_dir = os.path.join(user_data_dir, "pybridge", "static")
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

    # --- Initialize Core Managers ---

    # 1. Initialize System Storage (Required for Auth and Memory)
    from ainara.framework.storage import create_system_storage

    try:
        system_storage = create_system_storage()
        app.storage = system_storage
        logger.info(
            f"System storage initialized: {system_storage.__class__.__name__}"
        )
    except Exception as e:
        logger.critical(f"Failed to initialize system storage: {e}")
        # We cannot proceed without storage for Auth
        sys.exit(1)

    # 2. Initialize ChatMemory if enabled (Injecting system storage)
    chat_memory = None
    if config.get("memory.enabled", True):
        chat_memory = ChatMemory(storage_backend=system_storage)
        logger.info("Chat memory initialized")
    else:
        logger.info("Chat memory disabled by configuration")

    # 3. Initialize Auth Manager (Injecting system storage)
    # Now AuthManager always has access to storage, even if memory is disabled
    auth_manager = AuthManager(system_storage)

    # Initialize GREENMemories
    green_memories = None
    user_profile_summary = None
    if chat_memory:
        # GREENMemories are completely dependant of ChatMemory so is ok to enable
        # them only if chat_memory is present, with a direct reference
        green_memories = GREENMemories(
            llm=app.llm,
            chat_memory=chat_memory,
        )
        logger.info("User Memories Manager initialized")
        # Perform initial consolidation at startup
        logger.info("Processing new messages for user profile...")

        def memory_progress_callback(progress, current, total):
            # Scale progress from 0-100 to 70-90
            scaled_progress = 70 + int(progress * 0.20)
            _send_progress(
                "running",
                scaled_progress,
                f"Learning from last chat... ({current}/{total})",
            )

        green_memories.process_new_messages_for_update(
            progress_callback=memory_progress_callback, max_progress=90
        )
        logger.info("Message processing complete.")

        # Generate the narrative user profile summary
        user_profile_summary = green_memories.generate_user_profile_summary()
        if user_profile_summary:
            logger.info("User profile summary generated successfully.")

    # Create chat_manager as app attribute so it's accessible to all routes
    app.chat_manager = ChatManager(
        llm=app.llm,
        tts=tts,
        flask_app=app,
        orakle_servers=config.get("orakle.servers", ["http://127.0.0.1:8100"]),
        chat_memory=chat_memory,
        green_memories=green_memories,
        user_profile_summary=user_profile_summary,
        storage_backend=system_storage
    )

    # Initialize Notification Manager
    # It uses the system storage for persistence
    # Don't activate notifications without memory, anyway
    if chat_memory and hasattr(chat_memory, "storage"):
        app.notification_manager = NotificationManager(app.llm, system_storage)
    else:
        logger.info("Notifications disabled (Chat Memory not available)")

    # Initialize and start the backup manager
    app.backup_manager = BackupManager(config)
    app.backup_manager.start()
    # Ensure the backup thread is stopped cleanly on exit
    atexit.register(app.backup_manager.stop)

    # --- Health Monitor ---
    app.health_monitor = HealthMonitor(shutdown_callback=shutdown_server)
    atexit.register(app.health_monitor.stop)

    @sock.route('/wakeword')
    def wakeword_socket(ws):
        """WebSocket endpoint for streaming audio for wake word detection"""
        logger.info("Wake word socket connected")
        cooldown_until = 0

        try:
            while True:
                data = ws.receive()
                if not data:
                    logger.debug("Wake word socket received empty data or closed")
                    break

                if hasattr(app, 'wakeword') and app.wakeword:
                    # Process audio chunk to keep model state updated (flush buffers)
                    scores = app.wakeword.process_chunk(data)

                    # Cooldown check: ignore results if in cooldown
                    if time.time() < cooldown_until:
                        logger.debug(f"Cooldown active ({cooldown_until - time.time():.2f}s). Ignoring scores: {scores}")
                        continue

                    # Check threshold
                    threshold = config.get("wakeword.threshold", 0.5)

                    # Log significant scores to trace detection progression
                    max_score = max(scores.values()) if scores else 0
                    if max_score > 0.1:
                        logger.debug(f"Processing scores: {scores}")

                    for model_name, score in scores.items():
                        if score > threshold:
                            logger.info(f"Wake word detected: {model_name} (score: {score:.4f})")

                            # Set cooldown (2 seconds) to ignore subsequent buffered chunks
                            cooldown_until = time.time() + 4.0

                            ws.send(json.dumps({
                                "detected": True,
                                "model": model_name,
                                "score": float(score)
                            }))
                            # Break inner loop to avoid sending multiple detections for the same frame
                            break
        except Exception as e:
            logger.warning(f"Wake word socket Exception: {e}")
        finally:
            logger.debug("Wake word socket disconnected")

    @app.route("/auth/portal", methods=["GET"])
    def auth_portal():
        """Serves the local HTML page for wallet connection."""
        if not auth_manager:
            return "Auth system unavailable (Storage missing)", 503
        return auth_manager.get_portal_html()

    @app.route("/auth/verify", methods=["POST"])
    def auth_verify():
        """Verifies wallet signature and balance."""
        if not auth_manager:
            return (
                jsonify(
                    {"success": False, "message": "Auth system unavailable"}
                ),
                503,
            )

        data = request.get_json()
        wallet = data.get("wallet")
        signature = data.get("signature")
        message = data.get("message")

        if not wallet or not signature or not message:
            return (
                jsonify({"success": False, "message": "Missing parameters"}),
                400,
            )

        success, msg = auth_manager.verify_and_login(
            wallet, signature, message
        )
        return jsonify({"success": success, "message": msg})

    @app.route("/auth/status", methods=["GET"])
    def auth_status():
        """Checks current authentication status."""
        if not auth_manager:
            return jsonify(
                {"authorized": False, "reason": "system_unavailable"}
            )

        return jsonify(auth_manager.is_authorized())

    @app.route("/config/status", methods=["GET"])
    def get_config_status():
        """Return the validation status of the initial user configuration."""
        return jsonify(
            {
                "initial_config_valid": config.initial_config_valid,
                "errors": config.validation_errors,
            }
        )

    @app.route("/health", methods=["GET"])
    def health_check():
        """Comprehensive health check endpoint"""
        start_time = time.time()

        # Get memory configuration
        backup_enabled = config.get("backup.enabled", False)

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
                "backup_manager": app.backup_manager is not None,
            },
            "dependencies": {
                "llm_available": app.llm is not None,
                "storage_available": hasattr(app, "storage"),
            },
        }

        # Add backup status details
        if backup_enabled and hasattr(app, "backup_manager"):
            bm = app.backup_manager
            status["backup"] = {
                "enabled": True,
                "status": bm.last_backup_status,
                "last_run": bm.last_backup_timestamp,
                "error": bm.last_backup_error,
            }
        else:
            status["backup"] = {"enabled": False, "status": "disabled"}

        # Check if all essential services are available
        all_services_ok = all(status["services"].values())
        all_dependencies_ok = all(status["dependencies"].values())

        if not all_services_ok or not all_dependencies_ok:
            status["status"] = "degraded"
            status["message"] = "Some services or dependencies are unavailable"
        # Also mark as degraded if the last backup failed
        elif (
            status["backup"]["enabled"]
            and status["backup"]["status"] != "success"
        ):
            status["status"] = "degraded"
            if status["backup"]["status"] == "failure":
                status["message"] = (
                    "The last backup attempt failed. Please check the logs."
                )
            else:
                status["message"] = (
                    "A backup has not been successfully completed yet."
                )

        # Add response time measurement
        status["response_time_ms"] = (time.time() - start_time) * 1000

        # Record health check status to conditionally start the monitor
        app.health_monitor.record_health_check(status=status["status"])

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
            # # logger.info(f"new configuration: {pprint.pformat(data)}")

            new_llm = create_llm_backend(config.get("llm", {}))
            app.llm = new_llm
            app.chat_manager.update_llm(new_llm)

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

        # Check buffer size and" cleanup if needed
        cleanup_audio_buffer(audio_dir, AUDIO_BUFFER_SIZE_MB)

        return send_file(
            os.path.join(audio_dir, filename), mimetype="audio/wav"
        )

    @app.route("/docs/list", methods=["GET"])
    def docs_list():
        """Return list of available documentation sites."""
        base = config.get_nexus_base_path()
        sites = []
        if base.is_dir():
            for vendor_dir in base.iterdir():
                if not vendor_dir.is_dir() or vendor_dir.name.startswith(("_", ".")):
                    continue
                for app_dir in vendor_dir.iterdir():
                    if not app_dir.is_dir() or app_dir.name.startswith(("_", ".")):
                        continue
                    if (app_dir / "site" / "index.html").is_file():
                        sites.append({
                            "publisher": vendor_dir.name,
                            "application": app_dir.name,
                        })
        return jsonify(sites)

    @app.route("/docs/<publisher>/<application>/", defaults={"filename": "index.html"})
    @app.route("/docs/<publisher>/<application>/<path:filename>")
    def serve_docs(publisher, application, filename):
        """Serve static documentation files for a given publisher/application."""
        if ".." in publisher or ".." in application or ".." in filename:
            return jsonify({"error": "Invalid path"}), 400
        base = config.get_nexus_base_path()
        site_dir = base / publisher / application / "site"
        if not site_dir.is_dir():
            return jsonify({"error": "Documentation site not found"}), 404
        return send_from_directory(str(site_dir), filename)

    @app.route("/framework/chat", methods=["POST"])
    def framework_chat():
        data = request.get_json()

        def generate():
            for event in app.chat_manager.chat_completion(
                data["message"], stream="json"
            ):
                yield event

        return Response(generate(), mimetype="text/event-stream")

    @app.route("/framework/chat/search", methods=["GET"])
    def search_chat_history():
        """
        Search chat history with syntax support.
        Query params:
            q: Search query (supports "phrase", -exclude, ~semantic)
            limit: Max results (default 10)
            offset: Pagination offset (default 0)
        """
        query = request.args.get("q", "")
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))

        if not query:
            return jsonify({"results": []})

        try:
            results = app.chat_manager.chat_memory.search_entries(
                query, limit=limit, offset=offset
            )
            return jsonify({"results": results})
        except Exception as e:
            logger.error(f"Error searching chat history: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/framework/chat/history", methods=["GET"])
    def get_chat_history():
        """
        Retrieve and format chat history for a specific day.
        Accepts a 'date' query parameter in YYYY-MM-DD format.
        Defaults to the most recent day with history if no date is provided.
        """
        if (
            not hasattr(app, "chat_manager")
            or not app.chat_manager.chat_memory
        ):
            return (
                jsonify(
                    {"error": "Chat memory is not available or disabled."}
                ),
                503,
            )

        try:
            memory = app.chat_manager.chat_memory
            since_timestamp = request.args.get("since")

            if since_timestamp:
                # Fetch messages since the provided timestamp
                new_messages = memory.get_chat_history(
                    start_date=since_timestamp, limit=100
                )

                # Exclude the message with the exact start timestamp to avoid duplication
                filtered_messages = [
                    m
                    for m in new_messages
                    if m.get("timestamp") != since_timestamp
                ]

                if not filtered_messages:
                    # Return empty history and no new timestamp if nothing new
                    return jsonify({"history": "", "last_timestamp": None})

                # Format into a concise Markdown string
                history_md = memory.format_messages_to_markdown(
                    filtered_messages
                )
                # Get the timestamp of the very last message to send back to the client
                last_timestamp = filtered_messages[-1].get("timestamp")

                return jsonify(
                    {"history": history_md, "last_timestamp": last_timestamp}
                )

            date_str = request.args.get("date")
            if date_str:
                try:
                    target_date = date.fromisoformat(date_str)
                except ValueError:
                    return (
                        jsonify(
                            {"error": "Invalid date format. Use YYYY-MM-DD."}
                        ),
                        400,
                    )
            else:
                # Default to the date of the most recent message (UTC)
                last_message = memory.get_recent_entries(limit=1)
                if not last_message:
                    return jsonify(
                        {
                            "history": "# Chat History\n\nNo history found.",
                            "date": (
                                datetime.now(timezone.utc).strftime("%Y-%m-%d")
                            ),
                            "has_previous": False,
                            "has_next": False,
                        }
                    )
                # Timestamps are ISO strings in UTC
                target_date = datetime.fromisoformat(
                    last_message[0]["timestamp"]
                ).date()

            # Define the UTC day boundaries
            start_of_day = datetime.combine(
                target_date, datetime.min.time(), tzinfo=timezone.utc
            )
            end_of_day = datetime.combine(
                target_date, datetime.max.time(), tzinfo=timezone.utc
            )

            # Fetch messages for the target day
            messages_for_day = memory.get_chat_history(
                start_date=start_of_day.isoformat(),
                end_date=end_of_day.isoformat(),
                limit=5000,  # A generous limit for a single day
                sort="DESC",
            )
            # The backend returns newest first, so we reverse for chronological order
            messages_for_day.reverse()

            # Format into a concise Markdown string
            markdown_lines = [
                f"<h3>History for {target_date.strftime('%A, %B %d, %Y')}</h3>"
            ]
            if not messages_for_day:
                markdown_lines.append("\n_No messages for this day._")
            else:
                formatted_messages = memory.format_messages_to_markdown(
                    messages_for_day
                )
                markdown_lines.append(formatted_messages)
            history_md = "\n".join(markdown_lines)

            # Efficiently check for previous/next days with history
            # Check for any message before the start of the target day
            prev_day_check_end = start_of_day - timedelta(microseconds=1)
            has_previous = bool(
                memory.get_chat_history(
                    end_date=prev_day_check_end.isoformat(), limit=1
                )
            )

            # Check for any message after the end of the target day
            next_day_check_start = end_of_day + timedelta(microseconds=1)
            has_next = bool(
                memory.get_chat_history(
                    start_date=next_day_check_start.isoformat(), limit=1
                )
            )

            output = {
                "history": history_md,
                "date": target_date.strftime("%Y-%m-%d"),
                "has_previous": has_previous,
                "has_next": has_next,
            }
            if messages_for_day:
                output["last_timestamp"] = (
                    messages_for_day[-1].get("timestamp"),
                )
            return jsonify(output)
        except Exception as e:
            logger.error(f"Error fetching chat history: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return jsonify({"error": "Failed to retrieve chat history."}), 500

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
            result = stt.transcribe_file(temp_path)

            # [MODIFIED] Handle both dictionary (FasterWhisper) and string (Legacy/HTTP) returns
            text = ""
            confidence = 0.0
            detected_language = language

            if isinstance(result, dict):
                text = result.get("text", "")
                confidence = result.get("confidence", 0.0)
                # Use detected language if available and not manually set
                if language == "auto" and "language" in result:
                    detected_language = result["language"]
            else:
                text = str(result)
                confidence = 1.0 if text else 0.0

            # Format response to match what OpenAI Whisper API returns
            response = {
                "text": text,
                "confidence": confidence,  # [NEW] Add confidence score
                "task": task,
                "language": detected_language,
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

            litellm_provider = LiteLLM()
            providers = litellm_provider.get_available_providers()
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
                        "placeholder": "http://127.0.0.1:8000/v1",
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

    @app.route("/test-skill-key", methods=["POST"])
    def test_skill_key():
        """Test API key for a given skill/service."""
        try:
            data = request.get_json()
            logger.info(f"data: {data}")
            service = data.get("service")
            keys = data.get("keys")

            if not service or not keys:
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": "Service and keys are required.",
                        }
                    ),
                    400,
                )

            is_valid, message = _validate_skill_key(service, keys)

            if is_valid:
                return jsonify({"success": True, "message": message})
            else:
                # Return 200 OK on validation failure so frontend can parse it
                return jsonify({"success": False, "message": message})

        except Exception as e:
            logger.error(f"Error in /test-skill-key: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return jsonify({"success": False, "message": str(e)}), 500

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
            normalized_model = app.llm.normalize_model_name(model, provider)

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
                response = app.llm.chat(
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

    @app.route("/hardware/acceleration", methods=["GET"])
    def check_hardware_acceleration():
        """Check if hardware acceleration is available"""
        try:
            # Get detailed acceleration information and recommendations
            cuda_available, cuda_version, missing_libs, details = (
                DependencyChecker.check_cuda_availability()
            )
            recommendations = (
                DependencyChecker.get_acceleration_recommendation()
            )

            return jsonify(
                {
                    "cuda_available": cuda_available,
                    "cuda_version": cuda_version,
                    "has_nvidia_hardware": details["has_nvidia_hardware"],
                    "platform": sys.platform,
                    "gpu_list": details["gpu_list"],
                    "missing_libs": missing_libs,
                    "details": details,
                    "recommendations": recommendations,
                }
            )
        except Exception as e:
            logger.error(f"Error checking hardware acceleration: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500

    @app.route("/config/defaults", methods=["GET"])
    def get_default_config():
        """Return the default configuration"""
        try:
            import os
            import sys

            import yaml

            # Check if we're running in a PyInstaller bundle
            if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
                # Running in PyInstaller bundle
                # Use the bundled resource path
                default_config_path = os.path.join(
                    sys._MEIPASS, "resources", "ainara.yaml.defaults"
                )
                logger.info(
                    "Running from PyInstaller bundle, looking for config at:"
                    f" {default_config_path}"
                )
            else:
                # Running from source - use the original approach
                default_config_path = os.path.join(
                    os.path.dirname(
                        os.path.dirname(os.path.abspath(__file__))
                    ),
                    "..",
                    "resources",
                    "ainara.yaml.defaults",
                )
                logger.info(
                    "Running from source, looking for config at:"
                    f" {default_config_path}"
                )

            # Check if the file exists
            if not os.path.exists(default_config_path):
                logger.error(
                    f"Default config file not found at: {default_config_path}"
                )
                return (
                    jsonify({"error": "Default configuration file not found"}),
                    404,
                )

            # Load the default config
            with open(default_config_path, "r") as f:
                default_config = yaml.safe_load(f)

            return jsonify(default_config)
        except Exception as e:
            logger.error(f"Error loading default configuration: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return jsonify({"error": str(e)}), 500

    @app.route("/framework/queue/push", methods=["POST"])
    def push_to_queue():
        """Endpoint for Orakle to push background skill results"""
        try:
            data = request.get_json()
            if not data:
                return jsonify({"error": "No data provided"}), 400

            # Basic validation (Orakle sends 'result', not 'content')
            if "source" not in data or "result" not in data:
                return jsonify({"error": "Missing source or result"}), 400

            # Pass to Notification Manager if available
            if hasattr(app, "notification_manager"):
                app.notification_manager.process_payload(data)
                logger.info(
                    f"Processing background event from {data.get('source')}"
                )
                return jsonify({"status": "processing"})
            else:
                return jsonify(
                    {"status": "ignored", "reason": "notifications_disabled"}
                )

        except Exception as e:
            logger.error(f"Error pushing to queue: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/framework/notifications/status", methods=["GET"])
    def get_notification_status():
        """Check if there are pending notifications for the tray icon"""
        pending_count = 0
        if hasattr(app, "notification_manager"):
            pending_count = app.notification_manager.pending_notifications()
            show_report = request.args.get("report", False)
            if show_report:
                pending_items = (
                    app.notification_manager.get_and_clear_notifications(
                        do_clear=False
                    )
                )
                for item in pending_items:
                    logger.info(f" [{item['source']}]: {item['summary']}\n")
        return jsonify({"pending": pending_count})

    return app


if __name__ == "__main__":
    args = parse_args()
    # Set up logging first, before any logger calls
    logging_manager.setup(log_level=args.log_level, log_name="pybridge.log")
    # logging_manager.addFilter(["pybridge", "chat_completion"])

    # Set up profiling if enabled
    if args.profile:
        import cProfile
        import pstats

        # import os
        # Use the log directory from logging_manager
        log_dir = logging_manager._log_directory
        profile_output = os.path.join(log_dir, "pybridge_profile.prof")
        logger.info(
            f"Profiling enabled. Output will be saved to {profile_output}"
        )
        profiler = cProfile.Profile()
        profiler.enable()

    # --- Startup Resource Initialization ---
    logger.info("--- Starting PyBridge Service ---")
    logger.info("Step 1: Checking if local resources are initialized...")
    resources_status = check_resources()
    logger.info(json.dumps(resources_status))

    if not resources_status.get("initialized"):
        logger.info("Resources not initialized. Proceeding with setup.")
        logger.info(
            "Step 2: Checking download capability from Hugging Face Hub..."
        )
        download_check = check_download_capability()

        if not download_check.get("can_download"):
            error_msg = (
                "Cannot download required models. No internet connection or"
                " Hugging Face Hub is unreachable."
            )
            logger.critical(error_msg)
            # Send one final progress update for the UI before exiting
            _send_progress("error", 100, error_msg)
            sys.exit(1)  # Exit with error code

        logger.info(
            "Download is possible. Starting resource initialization..."
        )
        logger.info(
            "Step 3: Initializing resources (this may take a while)..."
        )
        success = initialize_resources(resources_status)
        if not success:
            error_msg = (
                "Failed to initialize required resources. The service cannot"
                " start."
            )
            logger.critical(error_msg)
            # initialize_resources already sends a final progress update on error
            sys.exit(1)  # Exit with error code
        logger.info("Resource initialization complete.")
    else:
        logger.info("All resources are already initialized.")

    # Prevent dynamic downloads from HuggingFace Hub
    os.environ["HF_HUB_OFFLINE"] = "1"

    app = create_app()

    # Run the app with or without profiling
    try:
        app.run(port=args.port)
    finally:
        # If profiling is enabled, save the profile data
        if args.profile:
            profiler.disable()
            logger.info(f"Saving profiling data to {profile_output}")
            profiler.dump_stats(profile_output)
            # Print some basic stats to the log
            stats = pstats.Stats(profile_output)
            logger.info("Top 10 functions by cumulative time:")
            stats.sort_stats("cumulative").print_stats(10)
