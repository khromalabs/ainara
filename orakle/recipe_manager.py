import re
import importlib
from pathlib import Path

import yaml
from flask import jsonify, request


class RecipeManager:
    def __init__(self, flask_app):
        self.app = flask_app
        self.skills = {}
        self.recipes = {}
        self.load_recipes()

    def camel_to_snake(self, name):
        name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        return re.sub('([a-z0-9])([A-Z])', r'\1_\2', name).lower()

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
                        f".skills.{self.camel_to_snake(skill_name)}",
                        "orakle"
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
        recipe = self.recipes[recipe_name]
        context = params.copy()

        for step in recipe["flow"]:
            skill = self.skills[step["skill"]]
            action = getattr(skill, step["action"])

            # Prepare input parameters
            if isinstance(step["input"], dict):
                input_params = {
                    k: (
                        context[v.strip("$")]
                        if isinstance(v, str) and v.startswith("$")
                        else v
                    )
                    for k, v in step["input"].items()
                }
            else:
                input_params = context[step["input"]]

            # Execute skill action
            if action.__name__.startswith("async"):
                result = await action(**input_params)
            else:
                result = action(**input_params)

            # Store result in context
            context[step["output"]] = result

        return context[recipe["flow"][-1]["output"]]
