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
import pprint
import sys
# import pprint
import re
from pathlib import Path
from typing import Annotated, get_args, get_origin, get_type_hints

from flask import jsonify, request


class CapabilitiesManager:
    def __init__(self, flask_app):
        self.logger = logging.getLogger(__name__)
        self.app = flask_app
        self.skills = {}
        self.load_skills()
        self.register_skills_endpoints()
        self.register_capabilities_endpoint()

    def reload_skills(self):
        """Reload skills without registering new endpoints"""
        self.logger.info("Reloading skills after configuration update")
        # Clear existing skills
        self.skills = {}
        # Reload skills
        self.load_skills()
        for skill in self.skills:
            self.skills[skill].reload()
        # Don't call register_skills_endpoints() here again
        self.logger.info(f"Reloaded {len(self.skills)} skills")

    def get_capabilities(self):
        logger = logging.getLogger(__name__)  # Or use self.logger if appropriate
        logger.critical(f"CRITICAL: Running CapabilitiesManager with Python version: {sys.version}")
        logger.critical(f"CRITICAL: Python executable: {sys.executable}")

        """Get information about all available skills and recipes"""
        capabilities = {"skills": {}, "recipes": {}}

        # Get skills information (excluding hidden ones)
        # Modify the skill info collection part:
        for skill_name, skill_instance in self.skills.items():
            # Debug logging
            logging.info(f"Processing skill: {skill_name}")
            # logging.info(f"Class docstring: {skill_instance.__class__.__doc__}")
            # Skip hidden skills
            if getattr(skill_instance, "hiddenCapability", False):
                logging.info(
                    f"Skipping hidden skill in capabilities: {skill_name}"
                )
                continue
            skill_info = {
                "description": skill_instance.__class__.__doc__ or "",
                "matcher_info": (
                    skill_instance.matcher_info
                    if hasattr(skill_instance, "matcher_info")
                    else ""
                ),
            }
            # # Debug logging
            # logging.info(f"Skill description: {skill_info['description']}\nMatcher info: {skill_info['matcher_info']}")
            if not skill_info["description"]:
                logging.error(
                    "No valid description found in skill "
                    + skill_name
                    + ". Skipping skill."
                )
                continue

            # Get information about run method
            run_method = skill_instance.run
            method_info = {
                "description": run_method.__doc__ or "",
                "parameters": {},
            }

            # Get parameter and return type information
            sig = inspect.signature(run_method)
            try:
                # --- DEBUG LINE ADDED ---
                self.logger.info("get_capabilities 1")

                logger = logging.getLogger(__name__)
                logger.critical(f"CRITICAL: sys.path = {sys.path}")
                try:
                    logger.critical(f"CRITICAL: Loaded inspect module from: {inspect.__file__}")
                except Exception as e:
                    logger.critical(f"CRITICAL: Could not get inspect.__file__: {e}")

                def has_future_annotations(module_name):
                    try:
                        module = sys.modules.get(module_name)
                        return hasattr(module, '__future__') and 'annotations' in module.__dict__.get('__future__', {})
                    except Exception:
                        return False

                # from inspect import CO_FUTURE_ANNOTATIONS
                self.logger.info("get_capabilities 2")
                # future_annotations_enabled = bool(run_method.__code__.co_flags & CO_FUTURE_ANNOTATIONS)
                module_name = run_method.__module__
                future_annotations_enabled = has_future_annotations(module_name)
                self.logger.info("get_capabilities 3")
                self.logger.info(
                    f"Skill '{skill_name}': Checking 'run' method defined in module '{run_method.__module__}'. "
                    f"'from __future__ import annotations' enabled: {future_annotations_enabled}"
                )
                self.logger.info("get_capabilities 4")
                # --- END DEBUG LINE ---

                type_hints = get_type_hints(run_method, include_extras=True)

                # Add return type if available
                if "return" in type_hints:
                    method_info["return_type"] = str(type_hints["return"])

                for param_name, param in sig.parameters.items():
                    if param_name != "self":
                        param_type = type_hints.get(param_name, "any")

                        # Add debug logging
                        self.logger.info(
                            f"Processing parameter '{param_name}' in skill"
                            f" '{skill_name}'"
                        )
                        self.logger.info(f"Parameter type: {param_type}")
                        self.logger.info(
                            f"Type origin: {get_origin(param_type)}"
                        )

                        # Raise an exception if parameter lacks Annotated type hint
                        if get_origin(param_type) is not Annotated:
                            raise ValueError(
                                f"Parameter '{param_name}' in skill"
                                f" '{skill_name}' must use Annotated type hint"
                                " for documentation"
                            )

                        # Extract the description from Annotated metadata
                        args = get_args(param_type)
                        if len(args) < 2 or not isinstance(args[1], str):
                            raise ValueError(
                                f"Parameter '{param_name}' in skill"
                                f" '{skill_name}' must have a string"
                                " description in Annotated type hint"
                            )

                        param_info = {
                            "type": str(
                                args[0]
                            ),  # Use the actual type from Annotated
                            "default": (
                                "None"
                                if param.default == param.empty
                                else str(param.default)
                            ),
                            "required": param.default == param.empty,
                            "description": args[1],
                        }

                        method_info["parameters"][param_name] = param_info
            except ValueError as e:
                # Log the error and re-raise to prevent loading skills with missing annotations
                self.logger.error(
                    f"Error processing skill '{skill_name}': {str(e)}"
                )
                raise

            skill_info["run"] = method_info

            capabilities["skills"][
                self.camel_to_snake(skill_name)
            ] = skill_info

        # # Get recipes information
        # for endpoint, recipe in self.recipes.items():
        #     recipe_info = {
        #         "endpoint": endpoint,
        #         "description": recipe.get("description", ""),
        #         "method": recipe.get("method", "POST"),
        #         "required_skills": recipe.get("required_skills", []),
        #         "parameters": recipe.get("parameters", []),
        #         "flow": recipe.get("flow", []),
        #     }
        #     capabilities["recipes"][endpoint] = recipe_info

        return capabilities

    def register_capabilities_endpoint(self):
        """Register the /capabilities endpoint"""

        @self.app.route("/capabilities", methods=["GET"])
        def get_capabilities():
            return jsonify(self.get_capabilities())

    def register_skills_endpoints(self):
        """Register direct endpoints for each skill"""
        for skill_name, skill_instance in self.skills.items():

            route_path = f"/skills/{self.camel_to_snake(skill_name)}"

            def create_skill_handler(skill_name, skill):
                def handler():
                    if not request.is_json and not request.data:
                        return jsonify({"error": "Request must be JSON"}), 400

                    try:
                        from asgiref.sync import async_to_sync

                        # Parse the request data
                        data = request.get_json(force=True)
                        # If data is a string starting with SKILL, parse it
                        if isinstance(data, str) and data.startswith("SKILL("):
                            import re

                            match = re.match(
                                r'SKILL\("([^"]+)",\s*({[^}]+})\)', data
                            )
                            if match:
                                data = eval(
                                    match.group(2)
                                )  # Safely evaluate the JSON part

                        self.logger.info("ORAKLE data:" + pprint.pformat(data))

                        if inspect.iscoroutinefunction(skill.run):
                            result = async_to_sync(skill.run)(**data)
                        else:
                            result = skill.run(**request.get_json())

                        self.logger.info(
                            "ORAKLE raw result:" + pprint.pformat(result)
                        )

                        if isinstance(result, dict):
                            return jsonify(result)
                        else:
                            return result, 200, {"Content-Type": "text/plain"}
                    except Exception as e:
                        return jsonify({"error": str(e)}), 500

                # Set a unique name for the handler function
                handler.__name__ = f"handle_{skill_name}"
                return handler

            endpoint_name = f"skill_{skill_name}"
            self.app.route(
                route_path, methods=["POST"], endpoint=endpoint_name
            )(create_skill_handler(skill_name, skill_instance))
            self.logger.info(f"Registered skill endpoint: {route_path}")

    def preview_dict(self, input_params, step_name=""):
        self.logger.debug(f"=== Parameter Preview for step: {step_name} ===")
        self.logger.debug("Input parameters:")
        for key, value in input_params.items():
            self.logger.debug(f"Key: {key}")
            self.logger.debug(f"Value type: {type(value)}")
            self.logger.debug(f"Value: {value}")
            self.logger.debug("-" * 50)

    def camel_to_snake(self, name):
        name = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub("([a-z0-9])([A-Z])", r"\1_\2", name).lower()

    def load_skills(self):
        """Load all available skills from the skills directory"""
        skills_dir = Path(__file__).parent.parent / "orakle" / "skills"
        self.logger.debug(f"Loading skills from: {skills_dir}")

        # Get all Python files in the skills directory and subdirectories
        for skill_file in skills_dir.rglob("*.py"):

            # Skip files in nested directories
            if skill_file.parent.parent != skills_dir:
                continue
            # Skip __init__ files and base files
            if skill_file.stem.startswith("__") or skill_file.stem == "base":
                continue

            try:
                # Get relative path from skills directory
                rel_path = skill_file.relative_to(skills_dir)
                # Convert path to module path
                # (e.g., html/url_downloader -> html.url_downloader)
                module_path = ".".join(rel_path.with_suffix("").parts)

                # Get the parent directory name and file name
                dir_name = skill_file.parent.name
                file_name = skill_file.stem

                # Convert directory and file names to proper case
                # (e.g., html/distill -> HtmlDistill)
                class_name = dir_name.title() + file_name.title()

                # Import the module and get the skill class
                module = importlib.import_module(
                    f".skills.{module_path}", "ainara.orakle"
                )
                skill_class = getattr(module, class_name)

                # Instantiate the skill and add it to the skills dictionary
                self.skills[class_name] = skill_class()
                self.logger.info(f"Loaded skill: {class_name}")

            except (ImportError, AttributeError) as e:
                self.logger.error(
                    f"Failed to load skill from {skill_file}: {str(e)}"
                )

    # # DEPRECATED FUNCTIONALITY recipes are being substituted by
    # # parametrized skills which may act as a simple skill, as a recipe or
    # # as an agent
    # def register_recipes_endpoints(self):
