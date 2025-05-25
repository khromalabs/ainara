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
