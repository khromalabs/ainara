# Ainara - Open Source AI Assistant Framework
# Copyright (C) 2025 Rubén Gómez http://www.khromalabs.org

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, see
# <https://www.gnu.org/licenses/>.

from typing import Any, Dict

import re
import sympy
import logging
from sympy.parsing.sympy_parser import (implicit_multiplication_application,
                                        parse_expr, standard_transformations)

from ainara.framework.skill import Skill


class ToolsCalculator(Skill):
    """Evaluation of non-trivial mathematical expressions"""

    matcher_info = (
        "ONLY use this skill when the user provided a complex mathematical"
        " expression to be solved."
    )

    def __init__(self):
        super().__init__()
        # Setup parsing transformations for more natural math syntax
        self.transformations = standard_transformations + (
            implicit_multiplication_application,
        )
        # Define available constants
        self.constants = {
            "pi": sympy.pi,
            "e": sympy.E,
            "inf": sympy.oo,
            "infinity": sympy.oo,
        }
        # Define function aliases for more intuitive usage
        self.function_aliases = {
            "cosine": "cos",
            "sine": "sin",
            "tangent": "tan",
            "squareroot": "sqrt",
            "square_root": "sqrt",
            "arcsin": "asin",
            "arccos": "acos",
            "arctan": "atan",
            "ln": "log",
        }
        self.logger = logging.getLogger(__name__)

    async def solve_equation(self, equation: str) -> Dict[str, Any]:
        """
        Calculus, calculations, solve a mathematical equation, sums,
        substrations, multiplications, divisions, square roots, cosine,
        sine. Just provide the result of the calculation don't give any
        further comments about it.

        Args:
            equation: String containing the equation (must contain '=')

        Returns:
            Dict containing the solution results
        """
        try:
            # Split equation into left and right sides
            if "=" not in equation:
                raise ValueError("Equation must contain '='")

            left, right = equation.split("=")

            # Apply function name aliases
            left = self._apply_function_aliases(left)
            right = self._apply_function_aliases(right)

            # Parse both sides and move everything to left side
            left_expr = parse_expr(
                left.strip(), transformations=self.transformations
            )
            right_expr = parse_expr(
                right.strip(), transformations=self.transformations
            )
            equation_expr = left_expr - right_expr

            # Find all variables in the equation
            variables = list(equation_expr.free_symbols)

            if not variables:
                raise ValueError("No variables found in equation")

            # Solve the equation
            solutions = sympy.solve(equation_expr, variables[0])

            return {
                "success": True,
                "solutions": [str(sol) for sol in solutions],
                "equation": str(equation_expr) + " = 0",
            }

        except Exception as e:
            return {
                "success": False,
                "error": "Error solving equation",
                "details": str(e),
            }

    def _apply_function_aliases(self, expression: str) -> str:
        """Replace function name aliases with their SymPy equivalents"""
        result = expression
        for alias, func_name in self.function_aliases.items():
            # Use regex to replace only function names, not variables
            result = re.sub(
                rf'\b{alias}\s*\(',
                f'{func_name}(',
                result,
                flags=re.IGNORECASE
            )
        return result

    async def run(self, expression: str, **kwargs) -> Dict[str, Any]:
        """
        Evaluates a mathematical expression or solves an equation.

        Args:
            expression: A string containing the mathematical expression or equation.
            **kwargs:
                - precision: An optional integer specifying the number of decimal places for the result.
                - evaluate: An optional boolean indicating whether to evaluate the expression numerically.
                - variables: An optional dictionary of variables and their values.

        Returns:
            A dictionary containing the evaluation results.

        Raises:
            sympy.SympifyError: If the expression is invalid.
            Exception: If there is a calculation error.

        Examples:
            "2 + 2" → {"success": True, "result": 4, "expression": "2 + 2"}
            "sin(pi/2)" → {"success": True, "result": 1, "expression": "sin(pi/2)"}
            "cosine(pi)" → {"success": True, "result": -1, "expression": "cos(pi)"}
            "sqrt(16)" → {"success": True, "result": 4, "expression": "sqrt(16)"}
            "2*x + 1" (x=3) → {"success": True, "result": 7, "expression": "2*x + 1"}
            "log(e)" → {"success": True, "result": 1, "expression": "log(e)"}
            "x^2 - 4 = 0" → {"success": True, "solutions": ["-2", "2"], "equation": "x^2 - 4 = 0"}
            "2*x + 1 = 5" → {"success": True, "solutions": ["2"], "equation": "2*x + 1 = 5"}
        """
        self.logger.info("CALCULATOR: " + expression)
        try:
            # Check if this is an equation
            if "=" in expression:
                return await self.solve_equation(expression)

            # Get optional parameters
            precision = kwargs.get("precision", 10)
            evaluate = kwargs.get("evaluate", True)
            variables = kwargs.get("variables", {})

            # Apply function name aliases
            expression = self._apply_function_aliases(expression)

            # Parse the expression as a regular calculation
            expr = parse_expr(
                expression,
                transformations=self.transformations,
                local_dict={**self.constants, **variables},
            )

            # Evaluate the expression
            if evaluate:
                result = float(expr.evalf(precision))
                # Handle special cases
                if result == float("inf"):
                    result = "infinity"
                elif result == float("-inf"):
                    result = "-infinity"
                elif abs(result) < 1e-10:  # Handle very small numbers
                    result = 0
            else:
                # Return symbolic result as string
                result = str(expr)

            self.logger.info("CALCULATOR RESULT: " + expression)

            return {"success": True, "result": result, "expression": str(expr)}

        except sympy.SympifyError as e:
            return {
                "success": False,
                "error": "Invalid mathematical expression",
                "details": str(e),
            }
        except Exception as e:
            return {
                "success": False,
                "error": "Calculation error",
                "details": str(e),
            }

    async def get_supported_functions(self) -> Dict[str, str]:
        """Return a dictionary of supported mathematical functions and their descriptions"""
        return {
            "Basic Arithmetic": "+ - * / ^ () =",
            "Functions": {
                "sqrt(x)": "Square root",
                "abs(x)": "Absolute value",
                "exp(x)": "Exponential",
                "log(x)": "Natural logarithm",
                "log(x, b)": "Logarithm with base b",
                "sin(x)": "Sine",
                "cos(x)": "Cosine",
                "tan(x)": "Tangent",
                "asin(x)": "Inverse sine",
                "acos(x)": "Inverse cosine",
                "atan(x)": "Inverse tangent",
                # Add aliases to documentation
                "cosine(x)": "Alias for cos(x)",
                "sine(x)": "Alias for sin(x)",
                "tangent(x)": "Alias for tan(x)",
                "squareroot(x)": "Alias for sqrt(x)",
            },
            "Constants": {
                "pi": "π (3.14159...)",
                "e": "Euler's number (2.71828...)",
            },
            "Equation Solving": {
                "x + 1 = 2": "Linear equations",
                "x^2 = 4": "Quadratic equations",
                "sin(x) = 0": "Trigonometric equations",
            },
        }
