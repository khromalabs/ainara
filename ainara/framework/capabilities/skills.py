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

import asyncio
import inspect
import logging
import re
# import os
from abc import ABC
from pathlib import Path
from typing import (Annotated, Any, Dict, Optional, get_args, get_origin,
                    get_type_hints)

from ainara.framework.mcp.client_manager import MCPClientManager

from .base import CapabilityProvider

logger = logging.getLogger(__name__)


class BasePythonSkillProvider(CapabilityProvider, ABC):
    """Abstract base provider for discovering Python-based skills from the filesystem."""

    def __init__(self, config, mcp_client_manager: Optional[MCPClientManager]):
        self.config = config
        self.mcp_client_manager = mcp_client_manager
        self.capabilities: Dict[str, Dict[str, Any]] = {}

    def execute(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Execute a skill."""
        capability_data = self.capabilities.get(name)
        if not capability_data:
            raise ValueError(f"Skill '{name}' not found by provider.")

        instance = capability_data["instance"]
        run_method = getattr(instance, "run", None)
        if not (run_method and callable(run_method)):
            raise TypeError(f"Skill '{name}' has no callable 'run' method.")

        logger.info(f"Executing skill: {name} with args: {arguments}")
        try:
            if inspect.iscoroutinefunction(run_method):
                loop = None
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:  # No running loop
                    pass

                if loop and loop.is_running():
                    if (
                        self.mcp_client_manager
                        and self.mcp_client_manager._loop
                    ):
                        logger.debug(
                            f"Executing async skill '{name}' using MCP event"
                            " loop."
                        )
                        future = asyncio.run_coroutine_threadsafe(
                            run_method(**arguments),
                            self.mcp_client_manager._loop,
                        )
                        return future.result(
                            timeout=self.config.get(
                                "framework.async_skill_timeout", 120
                            )
                        )
                    else:
                        logger.warning(
                            f"Executing async skill '{name}' in a temporary"
                            " event loop."
                        )
                        return asyncio.run(run_method(**arguments))
                else:
                    logger.warning(
                        f"Executing async skill '{name}' in a new event loop."
                    )
                    return asyncio.run(run_method(**arguments))
            else:
                return run_method(**arguments)
        except Exception as e:
            logger.error(f"Error executing skill '{name}': {e}", exc_info=True)
            raise RuntimeError(f"Failed to execute skill '{name}': {e}") from e

    def format_for_llm(self, capability_data: Dict[str, Any]) -> str:
        """Format a skill's description for an LLM prompt."""
        name = next(
            (k for k, v in self.capabilities.items() if v == capability_data),
            None,
        )
        if not name:
            return ""

        run_info = capability_data.get("run_info", {})
        params = run_info.get("parameters", {})
        desc = f"Skill: {name}\n"
        desc += f"Description: {capability_data['description']}\n"
        if params:
            desc += "Arguments:\n"
            for p_name, p_info in params.items():
                desc += f"- {p_name} (type: {p_info['type']})"
                if p_info["required"]:
                    desc += " (required)"
                desc += f": {p_info['description']}\n"
        return desc + "---\n"

    def _get_method_details(
        self, instance: Any, method_name: str, capability_name: str
    ) -> Dict[str, Any]:
        """Inspect a method (like 'run') and return its details."""
        method = getattr(instance, method_name, None)
        details = {
            "description": f"Executes the '{capability_name}' capability.",
            "parameters": {},
            "return_type": "unknown",
            "error": None,
        }

        if not (method and callable(method)):
            details["error"] = f"No callable '{method_name}' method found."
            return details

        details["description"] = method.__doc__ or details["description"]

        try:
            sig = inspect.signature(method)
            type_hints = get_type_hints(method, include_extras=True)

            if "return" in type_hints:
                details["return_type"] = str(type_hints["return"])

            for param_name, param in sig.parameters.items():
                if param_name == "self":
                    continue

                param_type_hint = type_hints.get(param_name, Any)
                param_desc = f"Parameter '{param_name}'"
                origin = get_origin(param_type_hint)
                args = get_args(param_type_hint)
                actual_type = param_type_hint

                if origin is Annotated and len(args) >= 2:
                    actual_type = args[0]
                    if isinstance(args[1], str):
                        param_desc = args[1]
                    else:
                        logger.warning(
                            f"Annotated metadata for '{param_name}' in"
                            f" capability '{capability_name}' is not a string."
                        )

                details["parameters"][param_name] = {
                    "type": str(actual_type),
                    "default": (
                        "None"
                        if param.default is param.empty
                        else repr(param.default)
                    ),
                    "required": param.default is param.empty,
                    "description": param_desc,
                }
        except Exception as e:
            logger.error(
                f"Error inspecting '{method_name}' method for capability"
                f" '{capability_name}': {e}",
                exc_info=True,
            )
            details["error"] = f"Failed to inspect method: {e}"

        return details

    def camel_to_snake(self, name):
        # Improved camel_to_snake to handle sequences of capitals (like LLM)
        name = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        name = re.sub("([a-z0-9])([A-Z])", r"\1_\2", name)
        return name.lower()

    def discover(
        self, skills_dir: Path, prefix_module: str, class_name_prefix: str = "", capability_type: str = "skill"
    ) -> Dict[str, Dict[str, Any]]:
        """Load native skills and add them to the capabilities dictionary."""
        import importlib

        self.capabilities = {}
        logger.info(f"Scanning for skills in: {skills_dir}")
        # logger.info(f"2 Current path: {os.getcwd()}")

        for skill_file in skills_dir.glob("*/*.py"):
            if skill_file.stem.startswith("__") or skill_file.stem == "base":
                continue

            try:
                rel_path = skill_file.relative_to(skills_dir)
                module_path = ".".join(rel_path.with_suffix("").parts)
                parts = rel_path.with_suffix("").parts
                if len(parts) == 2:
                    dir_name, file_name = parts
                    class_name = (
                        class_name_prefix
                        + dir_name.capitalize()
                        + file_name.capitalize()
                    )
                else:
                    logger.warning(
                        "Skipping skill file with unexpected path structure:"
                        f" {skill_file}"
                    )
                    continue

                full_module_path = f"{prefix_module}.{module_path}"
                logger.debug(f"Importing module: {full_module_path}")
                module = importlib.import_module(full_module_path)
                if hasattr(module, class_name):
                    skill_class = getattr(module, class_name)

                    if inspect.isclass(skill_class):
                        try:
                            instance = skill_class()
                            snake_name = self.camel_to_snake(class_name)
                            embeddings_boost_factor = 1.0
                            if hasattr(instance, "embeddings_boost_factor"):
                                embeddings_boost_factor = float(
                                    getattr(
                                        instance, "embeddings_boost_factor"
                                    )
                                )

                            capability_info = {
                                "instance": instance,
                                "type": capability_type,
                                "origin": "local",
                                "description": (
                                    getattr(instance.__class__, "__doc__", "")
                                    or ""
                                ),
                                "matcher_info": getattr(
                                    instance, "matcher_info", ""
                                ),
                                "hidden": getattr(
                                    instance, "hiddenCapability", False
                                ),
                                "embeddings_boost_factor": (
                                    embeddings_boost_factor
                                ),
                                "run_info": self._get_method_details(
                                    instance, "run", snake_name
                                ),
                            }
                            self.capabilities[snake_name] = capability_info
                            logger.info(
                                f"Loaded skill: {class_name} as"
                                f" {snake_name} with embeddings_boost_factor:"
                                f" {embeddings_boost_factor}"
                            )
                        except Exception as inst_e:
                            logger.error(
                                "Failed to instantiate skill"
                                f" {class_name} from {skill_file}: {inst_e}",
                                exc_info=True,
                            )
                    else:
                        logger.warning(
                            f"Found {class_name} in {full_module_path}, but"
                            " it's not a class."
                        )
                else:
                    logger.warning(
                        f"Class {class_name} not found in module"
                        f" {full_module_path}"
                    )

            except (ImportError, AttributeError, TypeError) as e:
                logger.error(
                    f"Failed to load skill from {skill_file}: {str(e)}",
                    exc_info=True,
                )
            except Exception as e:
                logger.error(
                    f"Unexpected error loading skill from {skill_file}:"
                    f" {str(e)}",
                    exc_info=True,
                )
        return self.capabilities


class NativeSkillProvider(BasePythonSkillProvider):
    """Provider for discovering and executing native Python skills."""

    def discover(self) -> Dict[str, Dict[str, Any]]:
        skills_dir = Path(__file__).parent.parent.parent / "orakle" / "skills"
        prefix_module = "ainara.orakle.skills"
        capabilities = super().discover(skills_dir, prefix_module)
        logger.info(f"Loaded {len(capabilities)} native skills.")
        return capabilities
