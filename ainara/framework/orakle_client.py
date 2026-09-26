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
from typing import List

import requests

logger = logging.getLogger(__name__)

"""
Execute an Orakle skill by calling the server's /run endpoint directly.

This is the shared, low-level execution function used by both
OrakleMiddleware and the Conductor's skill steps.

Args:
    orakle_servers: List of Orakle server base URLs.
    skill_id: The ID of the skill to execute.
    params: Dictionary of parameters for the skill.
    timeout: HTTP request timeout in seconds.

Returns:
    The skill result as a string.
"""


def call_skill(
    orakle_servers: List[str],
    skill_id: str,
    params: dict,
    timeout: int = 300,
    max_retries: int = 3,
) -> str:
    import time

    for server in orakle_servers:
        endpoint = f"{server.rstrip('/')}/run/{skill_id}"

        for attempt in range(max_retries):
            try:
                logger.info(
                    f"Calling skill '{skill_id}' on {endpoint} with params:"
                    f" {params} (Attempt {attempt + 1}/{max_retries})"
                )
                response = requests.post(
                    endpoint, json=params, timeout=timeout
                )
                if response.status_code == 200:
                    try:
                        json_response = response.json()
                        if not json_response:
                            return "Empty response received"
                        if isinstance(json_response, str):
                            return json_response
                        return json.dumps(json_response, indent=2)
                    except json.JSONDecodeError:
                        text_response = response.text
                        return (
                            text_response
                            if text_response
                            else "Empty response"
                        )
                else:
                    error_msg = (
                        f"Error: Server returned {response.status_code}"
                    )
                    try:
                        error_details = response.json()
                        error_msg += (
                            f"\nDetails: {json.dumps(error_details, indent=2)}"
                        )
                    except (ValueError, json.JSONDecodeError):
                        if response.text:
                            error_msg += f"\nDetails: {response.text}"
                    return error_msg
            except requests.RequestException as e:
                logger.warning(
                    f"Network error calling {endpoint} (Attempt"
                    f" {attempt + 1}): {str(e)}"
                )
                if attempt < max_retries - 1:
                    time.sleep(
                        1
                    )  # Breve pausa para dejar respirar al servidor
                continue
    return "Error: No Orakle servers available"
