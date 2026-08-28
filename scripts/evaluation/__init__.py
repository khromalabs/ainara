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

"""
Evaluation framework for Ainara's Orakle middleware and LLM performance.

This package provides tools to systematically evaluate how different LLMs 
perform within the Orakle framework across various test scenarios.
"""

__all__ = ["run_evaluation", "OrakleEvaluator", "TestCase", "TestSuite"]

# Resolved on first use rather than at import. These pull in the whole Ainara
# framework (runner -> framework.config -> jsonschema, yaml, ...), and this
# package is also the parent of `scripts.evaluation.tests`, so importing ONE
# unit test module used to require every framework dependency to be present.
#
# That is not a theoretical cost: the executor's venv deliberately does not hold
# the framework's dependencies — it holds the venue signing SDKs, which conflict
# with them — so the executor's own unit tests could not be imported in the only
# environment that can run them, and they failed with `No module named
# 'jsonschema'` before reaching a single assertion.
#
# PEP 562: `from scripts.evaluation import run_evaluation` still works and still
# raises ImportError if the framework really is missing; it just no longer
# happens on the way to somewhere else.
_LAZY = {
    "run_evaluation": (".runner", "run_evaluation"),
    "OrakleEvaluator": (".evaluator", "OrakleEvaluator"),
    "TestCase": (".tests.base", "TestCase"),
    "TestSuite": (".tests.base", "TestSuite"),
}


def __getattr__(name):
    try:
        module, attr = _LAZY[name]
    except KeyError:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}") from None
    from importlib import import_module
    return getattr(import_module(module, __name__), attr)


def __dir__():
    return sorted(set(globals()) | set(_LAZY))
