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

from typing import Dict, Any, Union
import sympy
from sympy.parsing.sympy_parser import parse_expr, standard_transformations, implicit_multiplication_application

from ainara.framework.skill import Skill


class ToolsCalculator(Skill):
    """Skill for evaluating mathematical expressions"""

    def __init__(self):
        super().__init__()
        # Setup parsing transformations for more natural math syntax
        self.transformations = (
            standard_transformations +
            (implicit_multiplication_application,)
        )
        # Define available constants
        self.constants = {
            'pi': sympy.pi,
            'e': sympy.E,
            'inf': sympy.oo,
            'infinity': sympy.oo
        }

    async def solve_equation(self, equation: str) -> Dict[str, Any]:
        """
        Calculus, calculations, solve a mathematical equation, sums,
        substrations, multiplications, divisions, square roots, cosine,
        sine

        Args:
            equation: String containing the equation (must contain '=')

        Returns:
            Dict containing the solution results
        """
        try:
            # Split equation into left and right sides
            if '=' not in equation:
                raise ValueError("Equation must contain '='")

            left, right = equation.split('=')

            # Parse both sides and move everything to left side
            left_expr = parse_expr(left.strip(), transformations=self.transformations)
            right_expr = parse_expr(right.strip(), transformations=self.transformations)
            equation_expr = left_expr - right_expr

            # Find all variables in the equation
            variables = list(equation_expr.free_symbols)

            if not variables:
                raise ValueError("No variables found in equation")

            # Solve the equation
            solutions = sympy.solve(equation_expr, variables[0])

            return {
                'success': True,
                'solutions': [str(sol) for sol in solutions],
                'equation': str(equation_expr) + " = 0"
            }

        except Exception as e:
            return {
                'success': False,
                'error': 'Error solving equation',
                'details': str(e)
            }

    async def run(
        self,
        expression: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Evaluate a mathematical expression or solve an equation
        Calculus, calculations, solve a mathematical equation, sums,
        substrations, multiplications, divisions, square roots, cosine,
        sine

        Args:
            expression: String containing the mathematical expression or equation
            **kwargs:
                - precision: int (number of decimal places for result)
                - evaluate: bool (whether to evaluate the expression numerically)

        Returns:
            Dict containing the evaluation results

        Examples:
            "2 + 2"              → 4
            "sin(pi/2)"          → 1
            "sqrt(16)"           → 4
            "2*x + 1" (x=3)     → 7
            "log(e)"             → 1
            "x^2 - 4 = 0"       → [-2, 2]
            "2*x + 1 = 5"       → [2]
        """
        try:
            # Check if this is an equation
            if '=' in expression:
                return await self.solve_equation(expression)

            # Get optional parameters
            precision = kwargs.get('precision', 10)
            evaluate = kwargs.get('evaluate', True)
            variables = kwargs.get('variables', {})

            # Parse the expression as a regular calculation
            expr = parse_expr(
                expression,
                transformations=self.transformations,
                local_dict={**self.constants, **variables}
            )

            # Evaluate the expression
            if evaluate:
                result = float(expr.evalf(precision))
                # Handle special cases
                if result == float('inf'):
                    result = 'infinity'
                elif result == float('-inf'):
                    result = '-infinity'
                elif abs(result) < 1e-10:  # Handle very small numbers
                    result = 0
            else:
                # Return symbolic result as string
                result = str(expr)

            return {
                'success': True,
                'result': result,
                'expression': str(expr)
            }

        except sympy.SympifyError as e:
            return {
                'success': False,
                'error': 'Invalid mathematical expression',
                'details': str(e)
            }
        except Exception as e:
            return {
                'success': False,
                'error': 'Calculation error',
                'details': str(e)
            }

    async def get_supported_functions(self) -> Dict[str, str]:
        """Return a dictionary of supported mathematical functions and their descriptions"""
        return {
            'Basic Arithmetic': '+ - * / ^ () =',
            'Functions': {
                'sqrt(x)': 'Square root',
                'abs(x)': 'Absolute value',
                'exp(x)': 'Exponential',
                'log(x)': 'Natural logarithm',
                'log(x, b)': 'Logarithm with base b',
                'sin(x)': 'Sine',
                'cos(x)': 'Cosine',
                'tan(x)': 'Tangent',
                'asin(x)': 'Inverse sine',
                'acos(x)': 'Inverse cosine',
                'atan(x)': 'Inverse tangent',
            },
            'Constants': {
                'pi': 'π (3.14159...)',
                'e': 'Euler\'s number (2.71828...)',
            },
            'Equation Solving': {
                'x + 1 = 2': 'Linear equations',
                'x^2 = 4': 'Quadratic equations',
                'sin(x) = 0': 'Trigonometric equations'
            }
        }
