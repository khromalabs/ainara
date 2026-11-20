# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
#
# This file is dual-licensed under:
# 1. GNU Lesser General Public License v3.0 (LGPL-3.0)
#    (See the included LICENSE_LGPL3.txt file or look into
#    <https://www.gnu.org/licenses/lgpl-3.0.html for details)
# 2. Commercial license
#    (Contact: rgomez@khromalabs.org for licensing options)
#
# You may use, distribute and modify this code under the terms of either license.
# This notice must be preserved in all copies or substantial portions of the code.

"""Mock execution: contract validation, never real execution.

The benchmark must NEVER fire real skills (clipboard writes, trading
orders, file mutations). Selections are validated against the
capability's declared parameter contract and answered with a structured
stub result. Side effects live only in the assertion, not on disk.
"""

import logging
import re
from typing import Any, Dict, List, Tuple

from .payload import Capability

logger = logging.getLogger(__name__)


def validate_selection(
    capability: Capability, params: Dict[str, Any]
) -> Tuple[bool, List[str]]:
    """Validate a selection's parameters against the capability contract.

    Returns (ok, problems). Problems are human-readable strings for the
    run record; they feed the param_partial / param_miss classification.
    """
    problems: List[str] = []
    known = {p.name for p in capability.parameters}

    for name in params:
        if name not in known:
            problems.append(f"unknown parameter: {name}")

    for p in capability.parameters:
        if p.required and (
            p.name not in params
            or params.get(p.name) in (None, "")
        ):
            problems.append(f"missing required parameter: {p.name}")

    # Literal-plausibility: declared types like "one of: 'a', 'b', 'c'"
    for p in capability.parameters:
        value = params.get(p.name)
        if value is None:
            continue
        match = re.search(r"one of:\s*(.+)", p.type, re.IGNORECASE)
        if match:
            options = re.findall(r"'([^']+)'", match.group(1))
            if options and str(value) not in options:
                problems.append(
                    f"parameter {p.name}: {value!r} not in allowed "
                    f"values {options}"
                )

    return (not problems, problems)


def execute_stub(
    capability: Capability, params: Dict[str, Any]
) -> Dict[str, Any]:
    """Structured stub result for a validated selection.

    Mirrors the skill structured-return contract so downstream
    interpretation stages can be evaluated later without any real
    execution happening.
    """
    ok, problems = validate_selection(capability, params)
    return {
        "success": ok,
        "capability": capability.id,
        "params": params,
        "problems": problems,
        "result": {"mock": True} if ok else None,
        "error": None if ok else "contract validation failed",
    }
