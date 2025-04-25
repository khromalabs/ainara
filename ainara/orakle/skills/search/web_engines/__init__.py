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


import importlib
import inspect
import logging
import os
import pkgutil
from typing import Dict, Type

from .base import SearchEngineBase

logger = logging.getLogger(__name__)


def discover_engines() -> Dict[str, Type[SearchEngineBase]]:
    """
    Dynamically discover all search engine implementations in the web_engines directory
    """
    engines = {}
    # Get the directory of the current package
    package_dir = os.path.dirname(__file__)

    for _, module_name, is_pkg in pkgutil.iter_modules([package_dir]):
        # Skip base module and any module starting with underscore
        if module_name == "base" or module_name.startswith("_"):
            continue

        try:
            # Import the module
            module = importlib.import_module(f".{module_name}", __package__)

            # Find all classes in the module that inherit from SearchEngineBase
            for name, obj in inspect.getmembers(module):
                if (inspect.isclass(obj) and
                        issubclass(obj, SearchEngineBase) and
                        obj != SearchEngineBase):
                    # Use the module name as the engine key
                    engines[module_name] = obj
                    logger.info(f"Discovered search engine: {module_name} -> {name}")
        except Exception as e:
            logger.error(f"Error loading search engine module {module_name}: {str(e)}")

    return engines