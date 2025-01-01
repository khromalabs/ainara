import os
import yaml
import importlib
from pathlib import Path
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

class RecipeManager:
    def __init__(self):
        self.skills = {}
        self.recipes = {}
        self.load_recipes()
        
    def load_recipes(self):
        recipe_dir = Path(__file__).parent / "recipes"
        for recipe_file in recipe_dir.glob("*.yaml"):
            with open(recipe_file) as f:
                recipe = yaml.safe_load(f)
                self.recipes[recipe["endpoint"]] = recipe
                
            # Load required skills
            for skill_name in recipe["required_skills"]:
                if skill_name not in self.skills:
                    module = importlib.import_module(f"orakle.skills.{skill_name.lower()}")
                    skill_class = getattr(module, skill_name)
                    self.skills[skill_name] = skill_class()
                    
    async def execute_recipe(self, recipe_name, params):
        recipe = self.recipes[recipe_name]
        context = params.copy()
        
        for step in recipe["flow"]:
            skill = self.skills[step["skill"]]
            action = getattr(skill, step["action"])
            
            # Prepare input parameters
            if isinstance(step["input"], dict):
                input_params = {
                    k: context[v.strip("$")] if isinstance(v, str) and v.startswith("$") else v 
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

recipe_manager = RecipeManager()

@app.route("/interpret_url", methods=["POST"])
async def interpret_url():
    result = await recipe_manager.execute_recipe("/interpret_url", request.json)
    return jsonify(result)

if __name__ == "__main__":
    app.run(port=5000)
