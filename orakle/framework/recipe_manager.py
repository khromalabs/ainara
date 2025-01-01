import importlib
import inspect
import pprint
import re
from pathlib import Path

import yaml
from flask import jsonify, request


class RecipeManager:
    def __init__(self, flask_app):
        self.app = flask_app
        self.skills = {}
        self.recipes = {}
        self.load_recipes()

    def preview_dict(self, input_params, step_name=""):
        print(f"\n=== Parameter Preview for step: {step_name} ===")
        print("Input parameters:")
        for key, value in input_params.items():
            print(f"Key: {key}")
            print(f"Value type: {type(value)}")
            print(f"Value: {value}")
            print("-" * 50)

    def camel_to_snake(self, name):
        name = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub("([a-z0-9])([A-Z])", r"\1_\2", name).lower()

    def load_recipes(self):
        recipe_dir = Path(__file__).parent.parent / "recipes"
        print(recipe_dir)
        for recipe_file in recipe_dir.glob("*.yaml"):
            with open(recipe_file) as f:
                recipe = yaml.safe_load(f)
                self.recipes[recipe["endpoint"]] = recipe

            # Load required skills
            for skill_name in recipe["required_skills"]:
                if skill_name not in self.skills:
                    module = importlib.import_module(
                        f".skills.{self.camel_to_snake(skill_name)}", "orakle"
                    )
                    skill_class = getattr(module, skill_name)
                    self.skills[skill_name] = skill_class()

            # Register route for this recipe
            self.register_route(recipe)

    def register_route(self, recipe):
        endpoint = recipe["endpoint"]
        methods = [recipe.get("method", "POST")]

        async def route_handler():
            result = await self.execute_recipe(endpoint, request.json)
            return jsonify(result)

        self.app.add_url_rule(
            endpoint, endpoint.lstrip("/"), route_handler, methods=methods
        )

    async def execute_recipe(self, recipe_name, params):
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
            # Determine the action to be performed
            # based on the step's input type
            # Get the action name from the step, defaulting to "run"
            action_name = step.get("action", "run")
            action = getattr(skill, action_name)

            print(pprint.pformat(action))

            # Prepare the input parameters for the skill action
            if isinstance(step["input"], dict):
                # If the input is a dictionary, process each value
                input_params = {}
                for k, v in step["input"].items():
                    if isinstance(v, str):
                        # Handle variable substitution in strings
                        if v.startswith("$"):
                            # Direct variable reference
                            input_params[k] = context[v.strip("$")]
                        else:
                            # Replace {$var} patterns in strings
                            def replace_var(match):
                                var_path = match.group(1).strip("$")
                                value = context
                                print(f"\nDebug - Variable path: {var_path}")
                                print(f"Debug - Context: {context}")
                                for key in var_path.split('.'):
                                    print(f"Debug - Accessing key: {key}")
                                    value = value[key]
                                    print(f"Debug - Current value: {value}")
                                return str(value)

                            input_params[k] = re.sub(
                                r"{(\$[^}]+)}", replace_var, v
                            )
                    else:
                        input_params[k] = v
                print(f"\nProcessing step: {step['skill']}")
                self.preview_dict(input_params, step['skill'])

            else:
                # If the input is not a dictionary,
                # use the value directly from the context
                # Convert single parameter to a dictionary
                param_name = next(iter(inspect.signature(action).parameters))
                input_params = {param_name: context[step["input"]]}

            # Execute the skill action
            print(f"\nExecuting {step['skill']} with action: {action.__name__}")
            if action.__name__.startswith("async"):
                # If the action is asynchronous,
                # use await to wait for its completion
                result = await action(**input_params)
            else:
                # If the action is not asynchronous, execute it directly
                result = action(**input_params)

            # If the result is a coroutine, await it
            if inspect.iscoroutine(result):
                result = await result

            # Store the result of the action in the context
            context[step["output"]] = result

        # Return the final output from the context,
        # which corresponds to the output of the last step in the flow
        return context[recipe["flow"][-1]["output"]]
