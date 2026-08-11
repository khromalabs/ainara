"""Scan Python skill source for exposed configuration parameters.

Only ``.get(...)`` calls that include an explicit, non-empty ``description=``
keyword argument are considered.  This keeps the contract simple: a
configuration parameter is only surfaced to the Wizard when the skill author
declares its purpose at the call site.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, List, Optional


def _normalise_value(value: Any) -> Any:
    """Convert tuple/unsupported values to JSON-friendly structures."""
    if isinstance(value, tuple):
        return [_normalise_value(item) for item in value]
    if isinstance(value, list):
        return [_normalise_value(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _normalise_value(v) for k, v in value.items()}
    return value


def _infer_value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _parse_literal(node: ast.AST):
    """Return (value, success) for a literal AST node."""
    try:
        return ast.literal_eval(node), True
    except (ValueError, TypeError, SyntaxError, MemoryError):
        return None, False


def scan_skill_config_params(
    source_path: Path,
    full_key_prefix: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Scan a single Python skill file for exposed config parameters.

    Args:
        source_path: Path to a readable Python source file.
        full_key_prefix: Optional dotted prefix for ``full_key``.  If omitted,
            ``full_key`` is just the leaf parameter name.

    Returns:
        A list of dicts with keys: ``param``, ``full_key``, ``description``,
        ``default``, ``value_type``.
    """
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    params: List[Dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "get"):
            continue

        # Must have description= with non-empty string literal
        description = None
        for kw in node.keywords:
            if kw.arg == "description":
                if (
                    isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str)
                    and kw.value.value.strip()
                ):
                    description = kw.value.value.strip()
                break

        if description is None:
            continue

        # First positional argument must be a string literal (the leaf key)
        if not node.args:
            continue
        first_arg = node.args[0]
        if not (
            isinstance(first_arg, ast.Constant)
            and isinstance(first_arg.value, str)
        ):
            continue

        param = first_arg.value

        # Determine default from second positional or default= keyword
        default_value = None
        default_success = False
        if len(node.args) >= 2:
            default_value, default_success = _parse_literal(node.args[1])
        else:
            for kw in node.keywords:
                if kw.arg == "default":
                    default_value, default_success = _parse_literal(kw.value)
                    break

        if not default_success:
            default_value = None

        norm_default = _normalise_value(default_value)
        value_type = _infer_value_type(norm_default)

        param_info = {
            "param": param,
            "description": description,
            "default": norm_default,
            "value_type": value_type,
        }

        if full_key_prefix:
            param_info["full_key"] = f"{full_key_prefix}.{param}"
        else:
            param_info["full_key"] = param

        params.append(param_info)

    return params
