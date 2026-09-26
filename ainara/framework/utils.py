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

import json
import logging
import os
import sys

from datetime import datetime, timezone
from typing import Optional
from ainara.framework.config import config

try:
    from fastembed import TextEmbedding

    FASTEMBED_AVAILABLE = True
except ImportError:
    FASTEMBED_AVAILABLE = False


from colorama import Fore, Style

logger = logging.getLogger(__name__)


def load_spacy_model(model_name="en_core_web_sm"):
    """
    Load a spaCy model, handling bundled models in frozen environments.

    Args:
        model_name: Name of the spaCy model to load

    Returns:
        Loaded spaCy model or None if loading fails
    """
    import spacy

    try:
        model_version = "<not in bundle>"
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            spacy_path = os.path.join(sys._MEIPASS, model_name)
            meta_file = os.path.join(spacy_path, "meta.json")
            if os.path.exists(meta_file):
                try:
                    with open(meta_file, "r") as f:
                        meta_data = json.load(f)
                        model_version = meta_data.get("version")
                        model_name = os.path.join(
                            spacy_path, f"{model_name}-{model_version}"
                        )
                except Exception as e:
                    logger.error(f"Could not read version from meta.json: {e}")
                    raise
            else:
                logger.error("Could not read meta.json file")
                raise
        logger.info(f"Loading spaCy model '{model_name}'")
        nlp = spacy.load(model_name)
        logger.info("Initialized spaCy")
        return nlp
    except Exception as e:
        logger.warning(f"Failed to load spaCy model '{model_name}': '{e}'")
        if 'spacy_path' in locals():
            logger.warning(f"spacy_path: '{spacy_path}'")
        return None


def format_orakle_command(command: str) -> str:
    """Format Orakle command with colors and layout"""
    import re

    # Extract command parts
    match = re.match(
        r'(SKILL|RECIPE)\("([^"]+)",\s*({[^}]+})', command.strip()
    )
    if not match:
        return command

    cmd_type, name, params = match.groups()

    # Parse and format parameters
    try:
        params_dict = json.loads(params)
        formatted_params = "\n".join(
            f"  {Fore.GREEN}{k}{Style.RESET_ALL}:"
            f" {Fore.YELLOW}{repr(v)}{Style.RESET_ALL}"
            for k, v in params_dict.items()
        )
    except json.JSONDecodeError:
        formatted_params = params

    # Build formatted command
    return (
        f"{Fore.CYAN}╭─ {cmd_type}{Style.RESET_ALL} "
        f"{Fore.LIGHTBLUE_EX}{name}{Style.RESET_ALL}\n"
        f"{Fore.CYAN}╰─ Parameters:{Style.RESET_ALL}\n"
        f"{formatted_params}"
    )


def get_embedding_model_name():
    """Gets the embedding model name from the configuration."""
    return config.get(
        "user_profile.vector_storage.embedding_model",
        config.get(
            "memory.vector_storage.embedding_model",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        ),
    )


def check_embedding_model():
    """
    Checks if the fastembed embedding model is downloaded.

    Returns:
        dict: A dictionary with status and model information.
    """
    if not FASTEMBED_AVAILABLE:
        return {
            "initialized": False,
            "message": "fastembed library not found.",
            "model_name": get_embedding_model_name(),
        }

    model_name = get_embedding_model_name()
    cache_dir = config.get("cache.directory")

    # FastEmbed stores models with a specific naming convention in the cache_dir.
    # Example: models--qdrant--paraphrase-multilingual-MiniLM-L12-v2-onnx-Q
    # We search for a directory that contains the model name (without organization).
    model_simple_name = model_name.split("/")[-1]
    found_path = None

    try:
        if os.path.exists(cache_dir):
            logger.info(f"Checking cache directory: {cache_dir}")
            for name in os.listdir(cache_dir):
                # Look for fastembed style directory names
                if name.startswith("models--") and model_simple_name in name:
                    full_path = os.path.join(cache_dir, name)
                    if os.path.isdir(full_path) and os.listdir(full_path):
                        found_path = full_path
                        break

        if found_path:
            logger.info(f"Embedding model '{model_name}' found in cache at {found_path}.")
            return {
                "initialized": True,
                "message": "Model is cached.",
                "model_name": model_name,
            }

        logger.info(f"Embedding model '{model_name}' not found in cache.")
        return {
            "initialized": False,
            "message": "Model not found in local cache.",
            "model_name": model_name,
        }
    except Exception as e:
        logger.error(
            "An unexpected error occurred while checking for embedding model"
            f" '{model_name}': {e}"
        )
        return {
            "initialized": False,
            "message": f"An error occurred: {e}",
            "model_name": model_name,
        }


def setup_embedding_model():
    """
    Downloads and caches the fastembed embedding model.

    Returns:
        dict: A dictionary with success status and a message.
    """
    # logger.info("0")
    if not FASTEMBED_AVAILABLE:
        # logger.info("FASTEMBED_AVAILABLE NOT")
        # logger.info("1")
        return {
            "success": False,
            "message": "fastembed library not found.",
        }

    model_name = get_embedding_model_name()
    cache_dir = config.get("cache.directory")
    # logger.info("2")
    try:
        logger.info(f"Downloading and caching embedding model: {model_name}...")
        # Instantiating the model triggers the download and caching process.
        # logger.info("3")
        TextEmbedding(
            model_name=model_name,
            cache_dir=cache_dir,
        )
        logger.info(f"Successfully downloaded and cached model: {model_name}")
        # logger.info("5")
        return {"success": True, "message": "Model downloaded successfully."}
    except Exception as e:
        # logger.info("6")
        logger.error(f"Failed to download embedding model '{model_name}': {e}")
        return {"success": False, "message": str(e)}


def format_relative_time_terse(timestamp_str: Optional[str]) -> Optional[str]:
    """Convert an ISO timestamp into a terse relative time marker for LLM-native notation.

    Produces compact markers like "2h", "3d", "1w", "yesterday_eve" designed
    for token-efficient LLM consumption rather than human readability.

    Returns None if the timestamp is missing or unparseable.
    """
    if not timestamp_str:
        return None
    try:
        last_dt = datetime.fromisoformat(timestamp_str)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        delta = now - last_dt
        total_seconds = delta.total_seconds()

        if total_seconds < 3600:
            minutes = max(1, int(total_seconds / 60))
            return f"{minutes}min"
        elif total_seconds < 86400:
            hours = int(total_seconds / 3600)
            return f"{hours}h"
        elif total_seconds < 172800:
            local_dt = last_dt.astimezone()
            hour = local_dt.hour
            if hour < 12:
                return "yesterday_morn"
            elif hour < 17:
                return "yesterday_aft"
            elif hour < 21:
                return "yesterday_eve"
            else:
                return "yesterday_night"
        elif total_seconds < 604800:
            days = int(total_seconds / 86400)
            return f"{days}d"
        elif total_seconds < 2592000:
            weeks = int(total_seconds / 604800)
            return f"{weeks}w"
        else:
            months = int(total_seconds / 2592000)
            return f"{months}mo"
    except Exception as e:
        logger.warning(
            f"Could not format terse relative time from '{timestamp_str}': {e}"
        )
        return None


def format_relative_time(timestamp_str: Optional[str]) -> Optional[str]:
    """Convert an ISO timestamp into a human-readable relative time string.

    Produces natural-language descriptions like "22 minutes ago",
    "earlier today", "yesterday evening", or "3 days ago" so the LLM
    can acknowledge the time gap between sessions naturally rather than
    receiving a raw ISO timestamp it has to interpret.

    Returns None if the timestamp is missing or unparseable.
    """
    if not timestamp_str:
        return None
    try:
        last_dt = datetime.fromisoformat(timestamp_str)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        delta = now - last_dt
        total_seconds = delta.total_seconds()

        if total_seconds < 60:
            return "moments ago"
        elif total_seconds < 3600:
            minutes = int(total_seconds / 60)
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        elif total_seconds < 7200:
            return "about an hour ago"
        elif total_seconds < 86400:
            hours = int(total_seconds / 3600)
            return f"about {hours} hours ago"
        elif total_seconds < 172800:
            local_dt = last_dt.astimezone()
            hour = local_dt.hour
            if hour < 12:
                time_of_day = "morning"
            elif hour < 17:
                time_of_day = "afternoon"
            elif hour < 21:
                time_of_day = "evening"
            else:
                time_of_day = "night"
            return f"yesterday {time_of_day}"
        elif total_seconds < 604800:
            days = int(total_seconds / 86400)
            return f"{days} days ago"
        elif total_seconds < 1209600:
            return "about a week ago"
        elif total_seconds < 2592000:
            weeks = int(total_seconds / 604800)
            return f"about {weeks} weeks ago"
        else:
            months = int(total_seconds / 2592000)
            return f"about {months} month{'s' if months != 1 else ''} ago"
    except Exception as e:
        logger.warning(
            f"Could not format relative time from '{timestamp_str}': {e}"
        )
        return None
