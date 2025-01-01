from flask import Flask
from flask_cors import CORS

from .recipe_manager import RecipeManager

app = Flask(__name__)
CORS(app)


recipe_manager = RecipeManager(app)

if __name__ == "__main__":
    app.run(port=5000)
