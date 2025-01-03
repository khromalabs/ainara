import importlib
import inspect
import logging
import pprint
import re
from pathlib import Path
from typing import get_type_hints

import yaml
# import chardet
from flask import jsonify, request


class RecipeManager:
    def __init__(self, flask_app):
        self.app = flask_app
        self.skills = {}
        self.recipes = {}
        self.load_recipes()
        self.register_capabilities_endpoint()

    def get_capabilities(self):
        """Get information about all available skills and recipes"""
        capabilities = {"skills": {}, "recipes": {}}

        # Get skills information
        for skill_name, skill_instance in self.skills.items():
            skill_info = {
                "description": skill_instance.__class__.__doc__ or "",
                "methods": {},
            }

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
            if 'return' in type_hints:
                method_info["return_type"] = str(type_hints['return'])

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

            capabilities["skills"][skill_name] = skill_info

        # Get recipes information
        for endpoint, recipe in self.recipes.items():
            recipe_info = {
                "endpoint": endpoint,
                "method": recipe.get("method", "POST"),
                "required_skills": recipe.get("required_skills", []),
                "parameters": recipe.get("parameters", []),
                "flow": recipe.get("flow", []),
            }
            capabilities["recipes"][endpoint] = recipe_info

        return capabilities

    def register_capabilities_endpoint(self):
        """Register the /capabilities endpoint"""

        @self.app.route("/capabilities", methods=["GET"])
        def get_capabilities():
            return jsonify(self.get_capabilities())

    def preview_dict(self, input_params, step_name=""):
        logger = logging.getLogger(__name__)
        logger.debug(f"=== Parameter Preview for step: {step_name} ===")
        logger.debug("Input parameters:")
        for key, value in input_params.items():
            logger.debug(f"Key: {key}")
            logger.debug(f"Value type: {type(value)}")
            logger.debug(f"Value: {value}")
            logger.debug("-" * 50)

    def camel_to_snake(self, name):
        name = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub("([a-z0-9])([A-Z])", r"\1_\2", name).lower()

    def load_recipes(self):
        recipe_dir = Path(__file__).parent.parent / "orakle" / "recipes"
        logger = logging.getLogger(__name__)
        logger.debug(f"Loading recipes from: {recipe_dir}")
        for recipe_file in recipe_dir.glob("*.yaml"):
            with open(recipe_file) as f:
                recipe = yaml.safe_load(f)
                self.recipes[recipe["endpoint"]] = recipe

            # Load required skills
            for skill_name in recipe["required_skills"]:
                if skill_name not in self.skills:
                    module = importlib.import_module(
                        f".skills.{self.camel_to_snake(skill_name)}",
                        "ainara.orakle",
                    )
                    skill_class = getattr(module, skill_name)
                    self.skills[skill_name] = skill_class()

            # Register route for this recipe
            self.register_route(recipe)

    # def enforce_utf8_encoding(self, text):
    #     # detected = chardet.detect(text.encode())
    #     # original_encoding = detected['encoding']
    #     # print("\n=== Detected encoding ===")
    #     # print(f"Content: {original_encoding}")
    #     # print("========================================\n")
    #     # return text.encode(original_encoding).decode('utf-8')
    #     common_encodings = [
    #         'latin-1',
    #         'utf-8',
    #         'iso-8859-1',
    #         'cp1252'
    #     ]
    #     # detected = chardet.detect(text.encode())
    #     # print("\n=== Detected encoding ===")
    #     # print(f"Detected: {detected}")
    #     # print(f"Confidence: {detected['confidence']}")
    #     # print(f"Text: {text}")
    #     # print("========================================\n")
    #     # if detected['confidence'] > 0.8: # trust high confidence detections
    #     #     try:
    #     #         return text.encode(detected['encoding']).decode('utf-8')
    #     #     except (UnicodeEncodeError, UnicodeDecodeError) as e:
    #     #         print(f"Encoding error: {e}")
    #     #         return None
    #     for source_enc in common_encodings:
    #         try:
    #             fixed = text.encode(source_enc).decode('utf-8')
    #             # Basic validation: check if contains expected characters
    #             if 'Ã' not in fixed and 'Â' not in fixed:  # Common mojibake
    #                 return fixed
    #         except (UnicodeEncodeError, UnicodeDecodeError) as e:
    #             logger = logging.getLogger(__name__)
    #             logger.warning(f"Encoding error: {e}")
    #             continue
    #     return text

    def register_route(self, recipe):
        endpoint = recipe["endpoint"]
        methods = [recipe.get("method", "POST")]

        async def route_handler():
            result = await self.execute_recipe(endpoint, request.json)
            # if isinstance(result, str):
            #     result = self.enforce_utf8_encoding(result)
            # elif isinstance(result, dict):
            #     for key, value in result.items():
            #         if isinstance(value, str):
            #             result[key] = self.enforce_utf8_encoding(value)
            # # print("\n=== Final Result Before JSON Conversion ===")
            # # print(f"Type: {type(result)}")
            # # print(f"Content: {result}")
            # # print("========================================\n")
            # # return jsonify(result)
            if isinstance(result, str):
                return result
            elif isinstance(result, dict):
                return jsonify(result)

        self.app.add_url_rule(
            f"/recipes/{endpoint.lstrip('/')}", endpoint.lstrip("/"), route_handler, methods=methods
        )

    async def execute_recipe(self, recipe_name, params):
        logger = logging.getLogger(__name__)
        # Retrieve the recipe from the recipes dictionary using the provided
        # recipe_name
        recipe = self.recipes[recipe_name]

        # Create a mapping from parameter names to input values
        context = {}
        if "parameters" in recipe:
            for param in recipe["parameters"]:
                param_name = param["name"]
                if param_name in params:
                    context[param_name] = params[param_name]
                # Also store under any alternative names provided
                if "aliases" in param:
                    for alias in param["aliases"]:
                        if alias in params:
                            context[param_name] = params[alias]
        else:
            context = params.copy()

        # Iterate over each step in the recipe's flow
        for step in recipe["flow"]:
            # Retrieve the skill from the skills dictionary
            # using the step's skill name
            skill = self.skills[step["skill"]]
            # Always use the run method
            logger.info(pprint.pformat(skill.run))

            # Prepare the input parameters for the skill action
            if isinstance(step["input"], dict):
                # If the input is a dictionary, process each value
                input_params = {}
                for k, v in step["input"].items():
                    if isinstance(v, str):
                        # Handle variable substitution in strings
                        if v.startswith("$"):
                            # Direct variable reference
                            var_name = v.strip("$")
                            # Check if this parameter is optional
                            # in the recipe definition
                            param_is_optional = False
                            if "parameters" in recipe:
                                for param in recipe["parameters"]:
                                    if param["name"] == var_name and param.get(
                                        "optional", False
                                    ):
                                        param_is_optional = True
                                        break

                            if var_name not in context:
                                if param_is_optional:
                                    # Skip this parameter if it's optional
                                    continue
                                else:
                                    logger.error(
                                        f"Variable '{var_name}' not found in"
                                        " context"
                                    )
                                    logger.debug(
                                        "Available context variables:"
                                        f" {list(context.keys())}"
                                    )
                                    raise KeyError(
                                        f"Required variable '{var_name}' not"
                                        " found in recipe context"
                                    )
                            input_params[k] = context[var_name]
                        else:
                            # Replace {$var} patterns in strings
                            def replace_var(match):
                                var_path = match.group(1).strip("$")
                                value = context
                                logger.debug(f"Variable path: {var_path}")
                                logger.debug(f"Context: {context}")
                                for key in var_path.split("."):
                                    logger.debug(f"Accessing key: {key}")
                                    value = value[key]
                                    logger.debug(f"Current value: {value}")
                                return str(value)

                            input_params[k] = re.sub(
                                r"{(\$[^}]+)}", replace_var, v
                            )
                    else:
                        input_params[k] = v
                logger = logging.getLogger(__name__)
                logger.debug(f"Processing step: {step['skill']}")
                self.preview_dict(input_params, step["skill"])

            else:
                # If the input is not a dictionary,
                # use the value directly from the context
                # Convert single parameter to a dictionary
                param_name = next(iter(inspect.signature(skill.run).parameters))
                if param_name == 'self':  # Skip self parameter
                    param_name = next(iter(inspect.signature(skill.run).parameters.items()))[0]
                input_params = {param_name: context[step["input"]]}

            # Execute the skill's run method
            logger = logging.getLogger(__name__)
            logger.debug(f"Executing {step['skill']}.run()")

            # Add output type information to the step
            return_hint = get_type_hints(skill.run).get('return')
            if return_hint:
                step['output_type'] = str(return_hint)

            if inspect.iscoroutinefunction(skill.run):
                # If run is async, await it
                result = await skill.run(**input_params)
            else:
                # If run is not async, execute directly
                result = skill.run(**input_params)

            # If the result is a coroutine, await it
            if inspect.iscoroutine(result):
                result = await result

            # Store the result of the action in the context
            context[step["output"]] = result

        # Return the final output from the context,
        # which corresponds to the output of the last step in the flow
        return context[recipe["flow"][-1]["output"]]
