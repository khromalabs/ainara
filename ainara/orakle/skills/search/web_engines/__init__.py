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
import importlib.util
import inspect
import logging
import os
import pkgutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Type, Union

from .base import SearchEngineBase

logger = logging.getLogger(__name__)


def _collect_engine_classes(
    module, module_name: str, engines: Dict[str, Type[SearchEngineBase]]
) -> None:
    """Register the first SearchEngineBase subclass found in module.

    The engine key is the module name (consistent with core engines).
    Name collisions are refused with a warning: first source wins (core
    engines are discovered before user-contributed ones).
    """
    for name, obj in inspect.getmembers(module):
        if (
            inspect.isclass(obj)
            and issubclass(obj, SearchEngineBase)
            and obj != SearchEngineBase
        ):
            if module_name in engines:
                logger.warning(
                    f"Search engine '{module_name}' already registered;"
                    f" ignoring duplicate from {module.__name__}"
                )
                return
            engines[module_name] = obj
            logger.info(f"Discovered search engine: {module_name} -> {name}")
            return


def _discover_engines_in_directory(
    directory: Path, engines: Dict[str, Type[SearchEngineBase]]
) -> None:
    """Discover user-contributed engines in a filesystem directory.

    Each ``*.py`` file is imported as a top-level module after prepending
    the directory to sys.path. Modules whose name would shadow an existing
    module (stdlib, installed package or another engine) are refused with
    a clear error instead of being imported — the same shadowing hazard
    flagged for user skills in #17's open questions.
    """
    if not directory.is_dir():
        logger.warning(f"Search engines directory not found: {directory}")
        return

    for file_path in sorted(directory.glob("*.py")):
        module_name = file_path.stem
        if module_name.startswith(("_", ".")):
            continue

        existing_spec = importlib.util.find_spec(module_name)
        if existing_spec is not None:
            existing_origin = os.path.normpath(
                os.path.abspath(existing_spec.origin or "")
            )
            if existing_origin != os.path.normpath(os.path.abspath(file_path)):
                logger.error(
                    f"Refusing to load search engine '{file_path}': module"
                    f" name '{module_name}' would shadow an existing module"
                    f" ({existing_origin or 'namespace package'}). Rename"
                    " the file."
                )
                continue

        if module_name in engines:
            logger.warning(
                f"User search engine '{module_name}' collides with an"
                " already-registered engine; skipping"
            )
            continue

        if str(directory) not in sys.path:
            sys.path.insert(0, str(directory))
        try:
            module = importlib.import_module(module_name)
            _collect_engine_classes(module, module_name, engines)
        except Exception as e:
            logger.error(
                f"Error loading user search engine module {module_name}:"
                f" {str(e)}"
            )


def discover_engines(
    extra_dirs: Optional[List[Union[str, Path]]] = None,
) -> Dict[str, Type[SearchEngineBase]]:
    """Dynamically discover all search engine implementations.

    Two sources, in priority order:

    - the built-in ``web_engines`` package (core engines)
    - each directory in ``extra_dirs`` (user-contributed engines, e.g.
      ``search.web.user_engines_directory``), imported as top-level
      modules with the same contract as core engines (subclass
      SearchEngineBase, config section ``apis.search.<module name>``)
    """
    engines: Dict[str, Type[SearchEngineBase]] = {}
    # Get the directory of the current package
    package_dir = os.path.dirname(__file__)

    for _, module_name, is_pkg in pkgutil.iter_modules([package_dir]):
        # Skip base module and any module starting with underscore
        if module_name == "base" or module_name.startswith("_"):
            continue

        try:
            # Import the module
            module = importlib.import_module(f".{module_name}", __package__)
            _collect_engine_classes(module, module_name, engines)
        except Exception as e:
            logger.error(
                f"Error loading search engine module {module_name}:"
                f" {str(e)}"
            )

    for extra_dir in extra_dirs or []:
        _discover_engines_in_directory(Path(extra_dir).expanduser(), engines)

    return engines
