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
# import pprint
import re
from pathlib import Path
from typing import get_type_hints

# import yaml
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
                logging.info(f"Skipping hidden skill in capabilities: {skill_name}")
                continue
            skill_info = {
                "description": skill_instance.__class__.__doc__ or "",
                "matcher_info": skill_instance.matcher_info if hasattr(skill_instance, 'matcher_info') else "",
            }
            # # Debug logging
            # logging.info(f"Skill description: {skill_info['description']}\nMatcher info: {skill_info['matcher_info']}")
            if not skill_info["description"]:
                logging.error(
                    "No valid description found in skill " +
                    skill_name + ". Skipping skill."
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
            type_hints = get_type_hints(run_method)

            # Add return type if available
            if "return" in type_hints:
                method_info["return_type"] = str(type_hints["return"])

            for param_name, param in sig.parameters.items():
                if param_name != "self":
                    param_info = {
                        "type": str(type_hints.get(param_name, "any")),
                        "default": (
                            None
                            if param.default == param.empty
                            else str(param.default)
                        ),
                        "required": param.default == param.empty,
                    }
                    method_info["parameters"][param_name] = param_info

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

                        self.logger.info("ORAKLE raw result:" + pprint.pformat(result))

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
            self.logger.info(
                f"Registered skill endpoint: {route_path}"
            )

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
    #     """Load all available recipes from the recipes directory"""
    #     recipes_dir = Path(__file__).parent.parent / "orakle" / "recipes"
    #     logger = logging.getLogger(__name__)
    #     logger.debug(f"Loading recipes from: {recipes_dir}")
    #
    #     for recipe_file in recipes_dir.glob("*.yaml"):
    #         try:
    #             with open(recipe_file) as f:
    #                 recipe = yaml.safe_load(f)
    #
    #             # Validate that all required skills are available
    #             missing_skills = [
    #                 skill
    #                 for skill in recipe.get("required_skills", [])
    #                 if skill not in self.skills
    #             ]
    #
    #             if missing_skills:
    #                 logger.error(
    #                     f"Recipe {recipe_file.name} requires unavailable"
    #                     f" skills: {', '.join(missing_skills)}"
    #                 )
    #                 continue
    #
    #             self.recipes[recipe["endpoint"]] = recipe
    #             self.register_route(recipe)
    #             logger.info(f"Loaded recipe: {recipe['endpoint']}")
    #
    #         except Exception as e:
    #             logger.error(
    #                 f"Failed to load recipe from {recipe_file}: {str(e)}"
    #             )

    # def register_route(self, recipe):
    #     endpoint = recipe["endpoint"]
    #     methods = [recipe.get("method", "POST")]
    #
    #     # Create a unique handler function for this recipe
    #     def create_recipe_handler(recipe_endpoint):
    #         def handler():
    #             if not request.is_json:
    #                 return jsonify({"error": "Request must be JSON"}), 400
    #
    #             try:
    #                 from asgiref.sync import async_to_sync
    #
    #                 result = async_to_sync(self.execute_recipe)(
    #                     recipe_endpoint, request.get_json()
    #                 )
    #                 if isinstance(result, dict):
    #                     return jsonify(result)
    #                 else:
    #                     return result, 200, {"Content-Type": "text/plain"}
    #             except Exception as e:
    #                 return jsonify({"error": str(e)}), 500
    #
    #         # Set unique name for the handler
    #         handler.__name__ = f"handle_recipe_{recipe_endpoint}"
    #         return handler
    #
    #     # Register the route handler with unique endpoint name
    #     route_path = f"/recipes{endpoint}"
    #     endpoint_name = f"recipe_{endpoint}"
    #     self.app.route(route_path, methods=methods, endpoint=endpoint_name)(
    #         create_recipe_handler(endpoint)
    #     )
    #     logging.getLogger(__name__).info(
    #         f"Registered recipe endpoint: {route_path}"
    #     )
    #
    # async def execute_recipe(self, recipe_name, params):
    #     logger = logging.getLogger(__name__)
    #     # Retrieve the recipe from the recipes dictionary using the provided
    #     # recipe_name
    #     recipe = self.recipes[recipe_name]
    #
    #     # Create a mapping from parameter names to input values
    #     context = {}
    #     if "parameters" in recipe:
    #         for param in recipe["parameters"]:
    #             param_name = param["name"]
    #             if param_name in params:
    #                 context[param_name] = params[param_name]
    #             # Also store under any alternative names provided
    #             if "aliases" in param:
    #                 for alias in param["aliases"]:
    #                     if alias in params:
    #                         context[param_name] = params[alias]
    #     else:
    #         context = params.copy()
    #
    #     # Iterate over each step in the recipe's flow
    #     for step in recipe["flow"]:
    #         # Retrieve the skill from the skills dictionary
    #         # using the step's skill name
    #         skill = self.skills[step["skill"]]
    #         # Always use the run method
    #         # logger.info(pprint.pformat(skill.run))
    #
    #         # Prepare the input parameters for the skill action
    #         if isinstance(step["input"], dict):
    #             # If the input is a dictionary, process each value
    #             input_params = {}
    #             for k, v in step["input"].items():
    #                 if isinstance(v, str):
    #                     # Handle variable substitution in strings
    #                     if v.startswith("$"):
    #                         # Direct variable reference
    #                         var_name = v.strip("$")
    #                         # Check if this parameter is optional
    #                         # in the recipe definition
    #                         param_is_optional = False
    #                         if "parameters" in recipe:
    #                             for param in recipe["parameters"]:
    #                                 if param["name"] == var_name and param.get(
    #                                     "optional", False
    #                                 ):
    #                                     param_is_optional = True
    #                                     break
    #
    #                         if var_name not in context:
    #                             if param_is_optional:
    #                                 # Skip this parameter if it's optional
    #                                 continue
    #                             else:
    #                                 logger.error(
    #                                     f"Variable '{var_name}' not found in"
    #                                     " context"
    #                                 )
    #                                 logger.debug(
    #                                     "Available context variables:"
    #                                     f" {list(context.keys())}"
    #                                 )
    #                                 raise KeyError(
    #                                     f"Required variable '{var_name}' not"
    #                                     " found in recipe context"
    #                                 )
    #                         input_params[k] = context[var_name]
    #                     else:
    #                         # Replace {$var} patterns in strings
    #                         def replace_var(match):
    #                             var_path = match.group(1).strip("$")
    #                             value = context
    #                             logger.debug(f"Variable path: {var_path}")
    #                             logger.debug(f"Context: {context}")
    #                             for key in var_path.split("."):
    #                                 logger.debug(f"Accessing key: {key}")
    #                                 value = value[key]
    #                                 logger.debug(f"Current value: {value}")
    #                             return str(value)
    #
    #                         input_params[k] = re.sub(
    #                             r"{(\$[^}]+)}", replace_var, v
    #                         )
    #                 else:
    #                     input_params[k] = v
    #             logger = logging.getLogger(__name__)
    #             logger.debug(f"Processing step: {step['skill']}")
    #             self.preview_dict(input_params, step["skill"])
    #
    #         else:
    #             # If the input is not a dictionary,
    #             # use the value directly from the context
    #             # Convert single parameter to a dictionary
    #             param_name = next(
    #                 iter(inspect.signature(skill.run).parameters)
    #             )
    #             if param_name == "self":  # Skip self parameter
    #                 param_name = next(
    #                     iter(inspect.signature(skill.run).parameters.items())
    #                 )[0]
    #             input_params = {param_name: context[step["input"]]}
    #
    #         # Execute the skill's run method
    #         logger = logging.getLogger(__name__)
    #         logger.debug(f"Executing {step['skill']}.run()")
    #
    #         # Add output type information to the step
    #         return_hint = get_type_hints(skill.run).get("return")
    #         if return_hint:
    #             step["output_type"] = str(return_hint)
    #
    #         # Handle both async and sync skills uniformly
    #         if inspect.iscoroutinefunction(skill.run):
    #             result = await skill.run(**input_params)
    #         else:
    #             # Wrap sync functions to be compatible with async flow
    #             result = skill.run(**input_params)
    #
    #         # Store the result of the action in the context
    #         context[step["output"]] = result
    #
    #     # Return the final output from the context,
    #     # which corresponds to the output of the last step in the flow
    #     return context[recipe["flow"][-1]["output"]]