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


import logging
import re
from typing import Annotated, Any, Dict, Optional

import sympy
from sympy.parsing.sympy_parser import (implicit_multiplication_application,
                                        parse_expr, standard_transformations)

from ainara.framework.skill import Skill


class ToolsCalculator(Skill):
    """Evaluation of non-trivial mathematical expressions"""

    matcher_info = (
        "Use this skill ONLY when the user provides a complex mathematical"
        " expression or equation to be solved. This skill can handle"
        " arithmetic operations, trigonometric functions, logarithms,"
        " equations, and more. Examples include: 'calculate 2 + 2', 'solve x^2"
        " - 4 = 0', 'what is sin(pi/2)', 'evaluate 5 factorial'.\n\nKeywords:"
        " calculate, solve, evaluate, math, mathematics, equation, expression,"
        " addition, subtraction, multiplication, division, exponent, square"
        " root, cube root, logarithm, sine, cosine, tangent, inverse,"
        " hyperbolic, factorial, permutation, combination, pi, euler,"
        " scientific notation, fraction, complex number, mean, median,"
        " standard deviation, base conversion, random number."
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

    async def solve_equation(
        self,
        equation: Annotated[
            str, "String containing the equation (must contain '=')"
        ],
    ) -> Dict[str, Any]:
        """Solves a mathematical equation"""
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
                rf"\b{alias}\s*\(",
                f"{func_name}(",
                result,
                flags=re.IGNORECASE,
            )
        return result

    async def run(
        self,
        expression: Annotated[
            str, "A string containing the mathematical expression or equation"
        ],
        precision: Annotated[
            Optional[int], "Number of decimal places for the result"
        ] = None,
        evaluate: Annotated[
            Optional[bool], "Whether to evaluate the expression numerically"
        ] = None,
        variables: Annotated[
            Optional[Dict[str, Any]],
            "Dictionary of variables and their values",
        ] = None,
    ) -> Dict[str, Any]:
        """Evaluates a mathematical expression or solves an equation

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

            # Get optional parameters with defaults
            precision_val = 10 if precision is None else precision
            evaluate_val = True if evaluate is None else evaluate
            variables_val = {} if variables is None else variables

            # Apply function name aliases
            expression = self._apply_function_aliases(expression)

            # Parse the expression as a regular calculation
            expr = parse_expr(
                expression,
                transformations=self.transformations,
                local_dict={**self.constants, **variables_val},
            )

            # Evaluate the expression
            if evaluate_val:
                result = float(expr.evalf(precision_val))
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

    async def get_supported_functions(self) -> Dict[str, Any]:
        """Returns a dictionary of supported mathematical functions and their descriptions"""
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
