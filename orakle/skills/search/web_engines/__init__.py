# Ainara - Open Source AI Assistant Framework
# Copyright (C) 2025 Rubén Gómez http://www.khromalabs.org

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
