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
import json
import logging
import os
import re
import subprocess
import sys
import venv
from pathlib import Path
from typing import (Annotated, Any, Dict, Optional, Union, get_args,
                    get_origin, get_type_hints, is_typeddict)
from flask import send_from_directory

# from ainara.framework.connectors.manager import ConnectorManager
from ainara.framework.connectors.router import ConnectorRouter
from ainara.framework.mcp.client_manager import MCPClientManager

from .base import CapabilityProvider

logger = logging.getLogger(__name__)


class BasePythonSkillProvider(CapabilityProvider):
    """Abstract base provider for discovering Python-based skills from the filesystem."""

    def __init__(
        self,
        config,
        mcp_client_manager: Optional[MCPClientManager],
        # connector_manager: Optional[ConnectorManager] = None,
        connector_router: Optional[ConnectorRouter] = None,
        startup_time: Optional[float] = None,
    ):
        self.config = config
        self.mcp_client_manager = mcp_client_manager
        # self.connector_manager = connector_manager
        self.connector_router = connector_router
        self.startup_time = startup_time
        self.capabilities: Dict[str, Dict[str, Any]] = {}
        self.load_errors: list = []

    def execute(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Execute a skill."""

        # logger.info(f"PRESENT CAPABILITIES:\n{self.capabilities}")

        capability_data = self.capabilities.get(name)
        if not capability_data:
            raise ValueError(f"Skill '{name}' not found by provider.")

        # Mid-session modification guard
        file_path = capability_data.get("file_path")
        logger.info(f"file_path: {file_path}")
        if file_path and self.startup_time:
            logger.info(f"self.startup_time: {self.startup_time}")
            try:
                file_mtime = os.path.getmtime(file_path)
                logger.info(f"file_mtime: {file_mtime}")
                if file_mtime > self.startup_time:
                    raise RuntimeError(
                        f"Skill '{name}' was modified after server startup. "
                        "Please restart the application to use it."
                    )
            except OSError:
                pass  # File might not exist anymore, let normal execution fail

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
                        logger.info(
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
                # Skip parameters marked as hidden (e.g. for UI/Scheduler only)
                if p_info.get("hidden", False):
                    continue

                desc += f"- {p_name} (type: {p_info['type']})"
                if p_info["required"]:
                    desc += " (required)"
                desc += f": {p_info['description']}\n"
        return desc + "---\n"

    def _generate_json_schema(self, type_hint: Any) -> Dict[str, Any]:
        """Generate a JSON Schema from a Python type hint."""
        origin = get_origin(type_hint)
        args = get_args(type_hint)

        # Handle TypedDict
        if is_typeddict(type_hint):
            properties = {}
            required_keys = getattr(
                type_hint, "__required_keys__", frozenset()
            )

            # If __required_keys__ is empty but total=True (default), all keys are required
            if not required_keys and getattr(type_hint, "__total__", True):
                required_keys = type_hint.__annotations__.keys()

            for name, t_val in type_hint.__annotations__.items():
                properties[name] = self._generate_json_schema(t_val)

            return {
                "type": "object",
                "properties": properties,
                "required": list(required_keys),
                "title": type_hint.__name__,
            }

        # Handle List
        if (
            origin is list or origin is list
        ):  # Handle both typing.List and built-in list
            return {
                "type": "array",
                "items": self._generate_json_schema(args[0]) if args else {},
            }

        # Handle Dict
        if origin is dict or origin is dict:
            # Dict[Key, Value] -> JSON object with additionalProperties
            return {
                "type": "object",
                "additionalProperties": (
                    self._generate_json_schema(args[1])
                    if len(args) > 1
                    else {}
                ),
            }

        # Handle Optional / Union
        if origin is Union:
            # Filter out NoneType to find the actual type
            non_none_types = [t for t in args if t is not type(None)]
            if len(non_none_types) == 1:
                return self._generate_json_schema(non_none_types[0])
            # Complex unions could be handled with "anyOf", but keeping it simple for now
            return {}

        # Handle Primitives
        if type_hint is int:
            return {"type": "integer"}
        if type_hint is float:
            return {"type": "number"}
        if type_hint is bool:
            return {"type": "boolean"}
        if type_hint is str:
            return {"type": "string"}

        return {}

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
                is_hidden = False

                if origin is Annotated and len(args) >= 2:
                    actual_type = args[0]
                    if isinstance(args[1], str):
                        param_desc = args[1]
                    else:
                        logger.warning(
                            f"Annotated metadata for '{param_name}' in"
                            f" capability '{capability_name}' is not a string."
                        )

                    # Check for "hidden" flag in Annotated args
                    if "hidden" in args[1:]:
                        is_hidden = True

                # Generate JSON Schema for the type
                json_schema = self._generate_json_schema(actual_type)

                details["parameters"][param_name] = {
                    "type": str(actual_type),
                    "default": (
                        "None"
                        if param.default is param.empty
                        else repr(param.default)
                    ),
                    "required": param.default is param.empty,
                    "description": param_desc,
                    "hidden": is_hidden,
                    "schema": json_schema,
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

    def _load_metadata_registry(self, skills_dir: Path) -> Dict[str, Any]:
        """Load pre-computed skill metadata from JSON if it exists."""
        metadata_file = skills_dir / "skills_metadata.json"
        if metadata_file.exists():
            try:
                with open(metadata_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(
                    "Failed to load skills_metadata.json from"
                    f" {metadata_file}: {e}"
                )
        return {}

    def get_extra_config_properties(self) -> Dict[str, Dict[str, Any]]:
        """Return config properties that are not tied to a single capability."""
        return {}

    def discover(
        self,
        skills_dir: Path,
        prefix_module: str,
        class_name_prefix: str = "",
        capability_type: str = "skill",
        flat: bool = False,
    ) -> Dict[str, Dict[str, Any]]:
        """Load native skills and add them to the capabilities dictionary."""
        import importlib

        self.capabilities = {}
        metadata = self._load_metadata_registry(skills_dir)
        is_frozen = getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")

        # In flat mode (user skills) scan top-level *.py; otherwise use subdirectories
        if flat:
            glob_patterns = ["*.pyc", "*.py"] if is_frozen else ["*.py"]
        else:
            glob_patterns = ["*/*.pyc", "*/*.py"] if is_frozen else ["*/*.py"]

        skill_files = set()
        for pattern in glob_patterns:
            skill_files.update(skills_dir.glob(pattern))

        logger.info(
            f"Scanning for skills in: {skills_dir} (pattern: {glob_patterns})"
        )

        for skill_file in skill_files:
            if skill_file.stem.startswith("__") or skill_file.stem == "base":
                continue

            try:
                rel_path = skill_file.relative_to(skills_dir)
                module_path = ".".join(rel_path.with_suffix("").parts)
                parts = rel_path.with_suffix("").parts

                if flat:
                    # Flat structure: e.g., "hello.py" → parts = ("hello",)
                    if len(parts) == 1:
                        file_name = parts[0]
                        class_name = class_name_prefix + file_name.capitalize()
                    else:
                        logger.warning(
                            f"Skipping nested file in flat mode: {skill_file}"
                        )
                        continue
                else:
                    # Subdirectory structure: e.g., "dir/sub.py" → parts = ("dir", "sub")
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
                logger.info(f"Importing module: {full_module_path}")

                # In frozen mode, load from file path directly
                if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
                    # Try .pyc first, then .py
                    pyc_path = skill_file.with_suffix(".pyc")
                    load_path = pyc_path if pyc_path.exists() else skill_file

                    spec = importlib.util.spec_from_file_location(
                        full_module_path, load_path
                    )
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        sys.modules[full_module_path] = module
                        spec.loader.exec_module(module)
                    else:
                        raise ImportError(
                            f"Could not load spec for {load_path}"
                        )
                else:
                    # Development mode - use standard import
                    module = importlib.import_module(full_module_path)
                if hasattr(module, class_name):
                    skill_class = getattr(module, class_name)

                    if inspect.isclass(skill_class):
                        try:
                            instance = skill_class()

                            # # Added: Inject ConnectorManager if available
                            # if self.connector_manager:
                            #     instance.connector_manager = self.connector_manager

                            if self.connector_router:
                                instance.router = self.connector_router

                            snake_name = self.camel_to_snake(class_name)
                            embeddings_boost_factor = 1.0
                            if hasattr(instance, "embeddings_boost_factor"):
                                embeddings_boost_factor = float(
                                    getattr(
                                        instance, "embeddings_boost_factor"
                                    )
                                )

                            # Use pre-computed metadata if available, otherwise fallback to runtime inspection
                            meta = metadata.get(snake_name, {})
                            capability_info = {
                                "instance": instance,
                                "type": capability_type,
                                "origin": "local",
                                "file_path": str(skill_file),
                                "description": meta.get(
                                    "description",
                                    getattr(instance.__class__, "__doc__", "")
                                    or "",
                                ),
                                "matcher_info": meta.get(
                                    "matcher_info",
                                    getattr(instance, "matcher_info", ""),
                                ),
                                "hidden": meta.get(
                                    "hidden",
                                    getattr(
                                        instance, "hiddenCapability", False
                                    ),
                                ),
                                "embeddings_boost_factor": (
                                    embeddings_boost_factor
                                ),
                                "run_info": meta.get(
                                    "run_info",
                                    self._get_method_details(
                                        instance, "run", snake_name
                                    ),
                                ),
                            }
                            if capability_type == "nexus":
                                config_params = []
                                try:
                                    config_params = instance.get_config_properties()
                                except Exception as prop_e:
                                    self.load_errors.append(
                                        {
                                            "skill_id": snake_name,
                                            "error": (
                                                "config property resolution failed: "
                                                f"{prop_e}"
                                            ),
                                        }
                                    )
                                if config_params:
                                    for p in config_params:
                                        p.setdefault("scope", "skill")
                                        p.setdefault("skill", snake_name)
                                    capability_info["config_params"] = config_params

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
                snake_name = self.camel_to_snake(class_name) if 'class_name' in locals() else skill_file.stem
                self.load_errors.append({
                    "skill_id": snake_name,
                    "error": f"{type(e).__name__}: {str(e)}"
                })
            except Exception as e:
                logger.error(
                    f"Unexpected error loading skill from {skill_file}:"
                    f" {str(e)}",
                    exc_info=True,
                )
                snake_name = self.camel_to_snake(class_name) if 'class_name' in locals() else skill_file.stem
                self.load_errors.append({
                    "skill_id": snake_name,
                    "error": f"{type(e).__name__}: {str(e)}"
                })
        return self.capabilities


class NativeSkillProvider(BasePythonSkillProvider):
    """Provider for discovering and executing native Python skills."""

    def discover(self) -> Dict[str, Dict[str, Any]]:
        skills_dir = Path(__file__).parent.parent.parent / "orakle" / "skills"
        prefix_module = "ainara.orakle.skills"
        capabilities = super().discover(skills_dir, prefix_module)
        logger.info(f"Loaded {len(capabilities)} native skills.")
        return capabilities


class UserSkillProvider(BasePythonSkillProvider):
    """Provider for discovering and executing user-defined Python skills."""

    def __init__(self, config, mcp_client_manager, connector_router=None, startup_time=None):
        super().__init__(config, mcp_client_manager, connector_router, startup_time)

        dir_path = config.get("user_skills.directory")
        if dir_path:
            self.user_skills_dir = Path(dir_path).expanduser()
            self.user_venv_dir = self.user_skills_dir / ".venv"
            self._setup_user_venv()
        else:
            self.user_skills_dir = None
            self.user_venv_dir = None
            logger.warning(
                "User skills are enabled, but no 'directory' is configured. "
                "Skipping user skill venv setup."
            )

    def _setup_user_venv(self):
        """Set up the user virtual environment and prepend to sys.path."""
        req_file = self.user_skills_dir / "requirements.txt"
        if not req_file.exists():
            return

        if not self.user_venv_dir.exists():
            logger.info(f"Creating user venv at {self.user_venv_dir}")
            venv.create(self.user_venv_dir, with_pip=True)

        # Install/update dependencies
        pip_executable = str(self.user_venv_dir / ("Scripts" if os.name == "nt" else "bin") / "pip")
        logger.info(f"Installing user skill dependencies from {req_file}")
        try:
            subprocess.run(
                [pip_executable, "install", "-r", str(req_file)],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            logger.error(f"Venv setup timed out after 120 seconds for {req_file}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to install user skill dependencies: {e.stderr}")

        # Prepend venv site-packages to sys.path
        if os.name == "nt":
            site_packages = self.user_venv_dir / "Lib" / "site-packages"
        else:
            py_version = f"python{sys.version_info.major}.{sys.version_info.minor}"
            site_packages = self.user_venv_dir / "lib" / py_version / "site-packages"

        if site_packages.exists():
            sys.path.insert(0, str(site_packages))

    def discover(self) -> Dict[str, Dict[str, Any]]:
        """Discover user skills, prefixing with 'user_' and scanning for UI components."""
        self.capabilities = {}
        discovered = {}

        if not self.user_skills_dir:
            logger.warning(
                "User skills are enabled, but no 'directory' is configured. "
                "Skipping user skill discovery."
            )
            return {}

        if not self.user_skills_dir.is_dir():
            logger.info(f"User skills directory not found: {self.user_skills_dir}")
            return {}

        # Add user skills dir to sys.path so importlib can find namespaces
        sys.path.insert(0, str(self.user_skills_dir))

        for namespace_dir in self.user_skills_dir.iterdir():
            if not namespace_dir.is_dir() or namespace_dir.name.startswith(("_", ".")):
                continue

            # prefix_module is just the namespace directory name
            caps = super().discover(
                namespace_dir,
                namespace_dir.name,
                flat=True,
                class_name_prefix=namespace_dir.name.capitalize(),
                capability_type="user_skill",
            )

            for cap_id, cap_data in list(caps.items()):
                new_cap_id = f"user_{cap_id}"
                cap_data["origin"] = "user"

                # Check for UI components in the top-level _components directory
                ui_components_path = self.user_skills_dir / "_components"
                if ui_components_path.is_dir():
                    component_name = "".join(w.capitalize() for w in cap_id.split("_"))
                    component_dir = (ui_components_path / component_name).resolve()

                    if component_dir.is_dir():
                        cap_data["ui"] = {"component": component_name}
                        cap_data["ui_path"] = str(ui_components_path)
                        logger.info(f"Associated user skill '{new_cap_id}' with component '{component_name}'")

                discovered[new_cap_id] = cap_data

        self.capabilities = discovered

        logger.info(f"Loaded {len(discovered)} user skills.")
        return self.capabilities

    def serve_component(self, component_path: str) -> Any:
        """Serve a UI component file from the top-level user skills _components directory."""
        path_parts = Path(component_path).parts
        if len(path_parts) < 2:
            raise FileNotFoundError("Invalid component path format.")

        component_name, *rest = path_parts

        ui_dir = (self.user_skills_dir / "_components" / component_name).resolve()
        if not ui_dir.is_dir():
            raise FileNotFoundError(f"No UI components found for component '{component_name}'.")

        file_path = Path(*rest).as_posix()
        full_path = (ui_dir / file_path).resolve()

        if not str(full_path).startswith(str(ui_dir)):
            raise PermissionError("Access denied: path traversal attempt.")

        logger.info(f"Serving user component: {file_path} from {ui_dir}")
        return send_from_directory(ui_dir, file_path)
