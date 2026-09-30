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

"""Shared logic for scaffolding new user skills and their SKILL.md docs.

Generated skills are written to the configured ``user_skills.directory``, never
into the core ``ainara/orakle/skills`` tree: in a packaged build that tree is
inside the read-only install, and code generated on a user's request belongs
with the user's own skills. Everything here mirrors how UserSkillsProvider
discovers a skill, so a generated file is found under the name reported for it:

    <user_skills.directory>/<namespace>/<name>.py
    class      Namespace + PascalName      (namespace.capitalize() + PascalName)
    capability user_<namespace>_<name>
"""

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_DEFAULT_PARAM = {
    "name": "query",
    "type": "str",
    "description": "The input or request for this skill",
    "required": True,
    "default": None,
}


def _pascal(s: str) -> str:
    """snake_case -> PascalCase, the same way skill discovery builds class names."""
    return "".join(w.capitalize() for w in s.split("_") if w)


def _camel_to_snake(name: str) -> str:
    """The same conversion skill discovery uses for capability ids."""
    name = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    name = re.sub("([a-z0-9])([A-Z])", r"\1_\2", name)
    return name.lower()


def user_skills_dir() -> Optional[Path]:
    """The configured user skills directory, or None when it is not set."""
    from ainara.framework.config import config

    value = config.get("user_skills.directory")
    return Path(value).expanduser() if value else None


def to_class_name(namespace: str, name: str) -> str:
    """Class name discovery expects: the namespace is capitalize()d whole."""
    return namespace.capitalize() + _pascal(name)


def to_capability_name(class_name: str) -> str:
    """Capability id Orakle serves for a user skill with this class name."""
    return "user_" + _camel_to_snake(class_name)


def namespace_conflict(namespace: str, skills_dir: Path) -> Optional[str]:
    """Why ``namespace`` cannot be used as a user skills directory, or None.

    The user skills directory is put at the front of sys.path and each
    namespace is imported as a top-level package, so a namespace named after a
    standard-library or installed module (``time``, ``json``, ``requests``)
    would shadow that module for the whole process.
    """
    if namespace in sys.stdlib_module_names:
        return f"'{namespace}' is a Python standard-library module"
    try:
        spec = importlib.util.find_spec(namespace)
    except (ImportError, ValueError):
        spec = None
    if spec is None:
        return None
    own = Path(skills_dir).resolve() / namespace
    locations = [Path(p).resolve() for p in (spec.submodule_search_locations or [])]
    if spec.origin:
        locations.append(Path(spec.origin).resolve().parent)
    if own in locations:
        return None
    return f"'{namespace}' is an installed Python module"


def safe_namespace(namespace: str, skills_dir: Path) -> str:
    """``namespace``, or ``my<namespace>`` when the plain name would shadow a module."""
    if namespace_conflict(namespace, skills_dir) is None:
        return namespace
    return "my" + namespace


def list_existing_categories(skills_dir: Optional[Path]) -> List[str]:
    """Namespaces already present in the user skills directory."""
    if not skills_dir or not Path(skills_dir).is_dir():
        return []
    return sorted(
        p.name
        for p in Path(skills_dir).iterdir()
        if p.is_dir() and not p.name.startswith(("_", "."))
    )


# ---------------------------------------------------------------------------
# Content generators
# ---------------------------------------------------------------------------

def _build_param_annotation(p: Dict[str, Any]) -> str:
    """Return the Annotated[...] snippet for one parameter."""
    type_str = p.get("type", "str")
    desc = p.get("description", f"The {p['name'].replace('_', ' ')}")
    required = p.get("required", True)
    default = p.get("default", None)

    if not required:
        if type_str.startswith("Optional["):
            wrapped = type_str
        else:
            wrapped = f"Optional[{type_str}]"
        annotated = f'        {p["name"]}: Annotated[{wrapped}, {desc!r}]'
        if default is None:
            annotated += " = None,"
        elif isinstance(default, str):
            annotated += f" = {default!r},"
        else:
            annotated += f" = {default},"
    else:
        annotated = f'        {p["name"]}: Annotated[{type_str}, {desc!r}],'
    return annotated


def generate_skill_content(
    category: str,
    name: str,
    description: str,
    params: Optional[List[Dict[str, Any]]] = None,
    matcher_info: Optional[str] = None,
    extra_imports: Optional[List[str]] = None,
    implementation_body: Optional[str] = None,
) -> str:
    """Generate the full Python source for a new skill file.

    Args:
        extra_imports: Additional import lines to append after standard imports
            (e.g. ["import pytz", "from datetime import datetime"]).
        implementation_body: Code to place inside the try: block instead of the
            default TODO stub. Should be indented with 12 spaces (3 levels).
    """
    class_name = to_class_name(category, name)
    capability_name = to_capability_name(class_name)
    readable_name = name.replace("_", " ")
    keywords = name.replace("_", ", ")

    effective_params = params if params else [_DEFAULT_PARAM]

    # Determine if we need Optional in imports
    needs_optional = any(not p.get("required", True) for p in effective_params)
    typing_imports = ["Annotated", "Any", "Dict"]
    if needs_optional:
        typing_imports.append("Optional")

    safe_description = description.replace('"""', "'''")
    c = f'"""User skill: {safe_description}"""\n\n'
    c += "import logging\n"
    c += f"from typing import {', '.join(typing_imports)}\n"
    if extra_imports:
        c += "\n".join(extra_imports) + "\n"
    c += "\n"
    c += "from ainara.framework.skill import Skill\n\n\n"
    c += f"class {class_name}(Skill):\n"
    c += f'    """{safe_description}"""\n\n'
    c += "    matcher_info = (\n"
    if matcher_info:
        c += f"        {matcher_info!r}\n"
    else:
        c += f"        {f'Use this skill when the user wants to {description.lower()}. '!r}\n"
        c += f"        {f'Keywords: {keywords}'!r}\n"
    c += "    )\n\n"
    c += "    def __init__(self):\n"
    c += "        super().__init__()\n"
    c += "        self.logger = logging.getLogger(__name__)\n"
    c += "\n"
    c += "    async def run(\n"
    c += "        self,\n"
    for p in effective_params:
        c += _build_param_annotation(p) + "\n"
    c += "    ) -> Dict[str, Any]:\n"
    c += f'        """Executes the {readable_name} skill\n\n'
    c += "        Args:\n"
    for p in effective_params:
        c += f"            {p['name']}: {p.get('description', '')}\n"
    c += "\n"
    c += "        Returns:\n"
    c += "            Dict with success (bool) and result or error keys\n"
    c += '        """\n'
    c += "        try:\n"
    if implementation_body:
        # Ensure body is indented to 12 spaces (inside try:)
        lines = implementation_body.splitlines()
        for line in lines:
            c += f"            {line}\n" if line.strip() else "\n"
    else:
        c += "            # TODO: Implement skill logic here\n"
        first_param = effective_params[0]["name"]
        c += f'            result = f"{{{first_param}}} processed by {capability_name}"\n'
        c += '            return {"success": True, "result": result}\n'
    c += "        except Exception as e:\n"
    c += f'            self.logger.error(f"{{self.name}} failed: {{e}}")\n'
    c += '            return {"success": False, "error": str(e)}\n'
    return c


def generate_skill_md(
    category: str,
    name: str,
    description: str,
    params: Optional[List[Dict[str, Any]]] = None,
    matcher_info: Optional[str] = None,
) -> str:
    """Generate a SKILL.md file following the agentskills.io open standard."""
    class_name = to_class_name(category, name)
    capability_name = to_capability_name(class_name)
    display_name = " ".join(
        w.title()
        for w in re.split(r"[_\s-]+", f"{category} {name}")
        if w
    )
    effective_params = params if params else [_DEFAULT_PARAM]
    trigger = matcher_info or f"Use this skill when the user wants to {description.lower()}."

    c = "---\n"
    c += f'name: "{capability_name}"\n'
    c += 'version: "1.0"\n'
    c += f"description: {json.dumps(description)}\n"
    c += f'category: "{category}"\n'
    c += "---\n\n"
    c += f"# {display_name}\n\n"
    c += f"## Description\n\n{description}\n\n"
    c += f"## Trigger Conditions\n\n{trigger}\n\n"
    c += "## Parameters\n\n"
    c += "| Name | Type | Required | Default | Description |\n"
    c += "|------|------|----------|---------|-------------|\n"
    for p in effective_params:
        req = "yes" if p.get("required", True) else "no"
        default = "" if p.get("required", True) else str(p.get("default", ""))
        c += f"| {p['name']} | {p.get('type', 'string')} | {req} | {default} | {p.get('description', '')} |\n"
    c += "\n"
    c += "## Returns\n\n"
    c += "| Field | Type | Description |\n"
    c += "|-------|------|-------------|\n"
    c += "| success | boolean | Whether the operation succeeded |\n"
    c += "| result | any | The skill output (present on success) |\n"
    c += "| error | string | Error message (present on failure) |\n\n"
    c += "## Examples\n\n"
    c += "```\n"
    first_param = effective_params[0]
    c += f'# Input: User asks to {description.lower()}\n'
    c += f'# {first_param["name"]}: "example request"\n'
    c += f'# Output: {{"success": true, "result": "example request processed by {capability_name}"}}\n'
    c += "```\n"
    return c


# ---------------------------------------------------------------------------
# File creation
# ---------------------------------------------------------------------------

def create_skill(
    category: str,
    name: str,
    description: str,
    skills_dir: Path,
    params: Optional[List[Dict[str, Any]]] = None,
    with_skill_md: bool = True,
    matcher_info: Optional[str] = None,
    extra_imports: Optional[List[str]] = None,
    implementation_body: Optional[str] = None,
    dry_run: bool = False,
    force: bool = False,
) -> Dict[str, Any]:
    """Create a user skill file (and optionally SKILL.md) under ``skills_dir``.

    ``category`` is the namespace directory and must be one lowercase word,
    because discovery capitalize()s it whole to build the class name.

    Returns a dict with keys: class_name, capability_name, skill_file,
    files_written (list of Path), errors (list of str).
    """
    skills_dir = Path(skills_dir)
    class_name = to_class_name(category, name)
    capability_name = to_capability_name(class_name)
    category_dir = skills_dir / category
    skill_file = category_dir / f"{name}.py"
    md_file = category_dir / f"{name}.SKILL.md"

    result: Dict[str, Any] = {
        "class_name": class_name,
        "capability_name": capability_name,
        "skill_file": skill_file,
        "files_written": [],
        "errors": [],
        "skill_content": generate_skill_content(
            category, name, description, params, matcher_info,
            extra_imports=extra_imports, implementation_body=implementation_body,
        ),
        "md_content": generate_skill_md(category, name, description, params, matcher_info)
        if with_skill_md
        else None,
    }

    if not re.fullmatch(r"[a-z][a-z0-9]*", category):
        result["errors"].append(
            f"Invalid namespace '{category}': use one lowercase word, letters and digits only."
        )
        return result
    conflict = namespace_conflict(category, skills_dir)
    if conflict:
        result["errors"].append(f"Namespace '{category}' would shadow a module: {conflict}.")
        return result

    if dry_run:
        return result

    if skill_file.exists() and not force:
        result["errors"].append(
            f"{skill_file} already exists. Pass force=True to overwrite."
        )
        return result

    category_dir.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(result["skill_content"], encoding="utf-8")
    result["files_written"].append(skill_file)

    if with_skill_md:
        md_file.write_text(result["md_content"], encoding="utf-8")
        result["files_written"].append(md_file)

    return result
