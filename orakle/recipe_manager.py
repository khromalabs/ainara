import importlib
import re
from pathlib import Path
import pprint

import yaml
from flask import jsonify, request


class RecipeManager:
    def __init__(self, flask_app):
        self.app = flask_app
        self.skills = {}
        self.recipes = {}
        self.load_recipes()

    def camel_to_snake(self, name):
        name = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub("([a-z0-9])([A-Z])", r"\1_\2", name).lower()

    def load_recipes(self):
        recipe_dir = Path(__file__).parent / "recipes"
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
        # Retrieve the recipe from the recipes dictionary using the provided recipe_name
        recipe = self.recipes[recipe_name]
        # Create a copy of the input parameters to use as the context
        context = params.copy()

        # Iterate over each step in the recipe's flow
        for step in recipe["flow"]:
            # Retrieve the skill from the skills dictionary using the step's skill name
            skill = self.skills[step["skill"]]
            # Determine the action to be performed based on the step's input type
            if isinstance(step["input"], dict):
                action = getattr(skill, step["action"])
            else:
                action = "run"

            print(pprint.pformat(action))

            # Prepare the input parameters for the skill action
            if isinstance(step["input"], dict):
                # If the input is a dictionary, map each key to the corresponding value in the context
                input_params = {
                    k: (
                        context[
                            v.strip("$")
                        ]  # If the value starts with "$", use it as a context key
                        if isinstance(v, str) and v.startswith("$")
                        else v  # Otherwise, use the value directly
                    )
                    for k, v in step["input"].items()
                }
            else:
                # If the input is not a dictionary, use the value directly from the context
                input_params = context[step["input"]]

            # Execute the skill action
            if action.__name__.startswith("async"):
                # If the action is asynchronous, use await to wait for its completion
                result = await action(**input_params)
            else:
                # If the action is not asynchronous, execute it directly
                result = action(**input_params)

            # Store the result of the action in the context
            context[step["output"]] = result

        # Return the final output from the context, which corresponds to the output of the last step in the flow
        return context[recipe["flow"][-1]["output"]]
