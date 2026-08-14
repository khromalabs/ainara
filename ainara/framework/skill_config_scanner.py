"""Scan Python skill source for exposed configuration parameters.

Only ``.get(...)`` calls that include an explicit, non-empty ``description=``
keyword argument are considered.  This keeps the contract simple: a
configuration parameter is only surfaced to the Wizard when the skill author
declares its purpose at the call site.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

config_manager_class = "ConfigManager"


def _normalise_value(value: Any) -> Any:
    """Convert tuple/unsupported values to JSON-friendly structures."""
    if isinstance(value, tuple):
        return [_normalise_value(item) for item in value]
    if isinstance(value, list):
        return [_normalise_value(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _normalise_value(v) for k, v in value.items()}
    return value


def _dotted_name(node: ast.AST) -> Optional[str]:
    """Return a dotted string for a Name/Attribute expression."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        if base is None:
            return None
        return f"{base}.{node.attr}"
    return None


def _annotation_refers_to_config_manager(annotation: ast.AST) -> bool:
    """Return True if the annotation mentions ConfigManager by name."""
    for child in ast.walk(annotation):
        if isinstance(child, ast.Name) and child.id == config_manager_class:
            return True
        if isinstance(child, ast.Attribute) and child.attr == config_manager_class:
            return True
    return False


def _collect_known_config_managers(tree: ast.AST) -> set:
    """Collect dotted names that are known to be config_manager_class instances."""
    known = set()

    # from ainara.framework.config import config  (or ... as cfg)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "ainara.framework.config":
                for alias in node.names:
                    if alias.name == "config":
                        known.add(alias.asname or alias.name)

    # x = ConfigManager(...)  /  self.x = ConfigManager(...)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if (
                isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == config_manager_class
            ):
                for target in node.targets:
                    name = _dotted_name(target)
                    if name:
                        known.add(name)
        elif isinstance(node, ast.AnnAssign):
            if _annotation_refers_to_config_manager(node.annotation):
                name = _dotted_name(node.target)
                if name:
                    known.add(name)

    # def f(..., config_manager: ConfigManager, ...)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = []
            for group in (
                node.args.posonlyargs,
                node.args.args,
                node.args.kwonlyargs,
            ):
                args.extend(group)
            if node.args.vararg:
                args.append(node.args.vararg)
            if node.args.kwarg:
                args.append(node.args.kwarg)
            for arg in args:
                if arg.annotation and _annotation_refers_to_config_manager(arg.annotation):
                    known.add(arg.arg)

    # Propagate through simple assignments: a = b, self.a = b
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                rhs_name = _dotted_name(node.value)
                if rhs_name in known:
                    for target in node.targets:
                        target_name = _dotted_name(target)
                        if target_name and target_name not in known:
                            known.add(target_name)
                            changed = True
            elif isinstance(node, ast.AnnAssign):
                if node.value is not None:
                    rhs_name = _dotted_name(node.value)
                    if rhs_name in known:
                        target_name = _dotted_name(node.target)
                        if target_name and target_name not in known:
                            known.add(target_name)
                            changed = True

    return known


def _is_known_config_get(node: ast.Call, known_configs: set) -> bool:
    target = _dotted_name(node.func.value)
    if not target:
        return False
    if target in known_configs:
        return True
    # A known config manager may be an ancestor of the target (e.g., self.cfg)
    return any(
        target.startswith(known + ".") or known.startswith(target + ".")
        for known in known_configs
    )


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


def _infer_value_type_from_schema(schema: Any) -> Optional[str]:
    """Infer a wizard value_type from a JSON Schema declaration."""
    if not isinstance(schema, dict):
        return None
    schema_type = schema.get("type")
    if schema_type == "integer":
        return "number"
    if schema_type in (
        "string",
        "number",
        "boolean",
        "array",
        "object",
        "null",
    ):
        return schema_type
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return _infer_value_type(enum[0])
    return None


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

    known_config_managers = _collect_known_config_managers(tree)

    params: List[Dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "get"):
            continue

        # Extract the leaf key early so we can log which property is skipped
        param = None
        if node.args:
            first_arg = node.args[0]
            if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                param = first_arg.value

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
            if param is not None and _is_known_config_get(node, known_config_managers):
                logger.warning(
                    "Ignoring config property '%s' in %s:%d: missing "
                    "non-empty 'description=' keyword, so it will not be "
                    "exposed through the wizard.",
                    param,
                    source_path,
                    node.lineno,
                )
            continue

        if param is None:
            continue

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

        # Parse optional schema= keyword
        schema = None
        for kw in node.keywords:
            if kw.arg == "schema":
                schema_value, schema_success = _parse_literal(kw.value)
                if schema_success:
                    schema = _normalise_value(schema_value)
                break
        if not isinstance(schema, dict):
            schema = None

        norm_default = _normalise_value(default_value)
        value_type = _infer_value_type_from_schema(schema) if schema is not None else None
        if value_type is None:
            value_type = _infer_value_type(norm_default)

        param_info = {
            "param": param,
            "description": description,
            "default": norm_default,
            "value_type": value_type,
        }
        if schema is not None:
            param_info["schema"] = schema

        if full_key_prefix:
            if param.startswith("apis."):
                param_info["full_key"] = param
            else:
                param_info["full_key"] = f"{full_key_prefix}.{param}"
        else:
            param_info["full_key"] = param

        params.append(param_info)

    return params
