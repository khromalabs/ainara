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
import platform
from pathlib import Path

logger = logging.getLogger(__name__)


def find_nexus_manifest(start_path: str, max_levels: int = 5) -> dict:
    """
    Finds and parses the nexus.json manifest file by traversing up the directory tree.

    Args:
        start_path: The starting file path to begin the search from.
        max_levels: The maximum number of parent directories to check.

    Returns:
        A dictionary containing the parsed manifest data.

    Raises:
        FileNotFoundError: If nexus.json is not found within the traversal limit.
    """
    current_path = Path(start_path).resolve().parent
    for _ in range(max_levels):
        manifest_path = current_path / "nexus.json"
        if manifest_path.is_file():
            with open(manifest_path, "r") as f:
                return json.load(f)

        if current_path == current_path.parent:  # Reached root
            break
        current_path = current_path.parent

    raise FileNotFoundError(
        f"Could not find nexus.json within {max_levels} levels "
        f"up from {start_path}"
    )
