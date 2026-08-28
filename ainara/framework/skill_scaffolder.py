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

"""Shared logic for scaffolding new Ainara skill files and SKILL.md docs."""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).parent.parent.parent
SKILLS_DIR = ROOT / "ainara" / "orakle" / "skills"

COPYRIGHT_HEADER = """\
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
# Lesser General Public License for more details."""

_DEFAULT_PARAM = {
    "name": "query",
    "type": "str",
    "description": "The input or request for this skill",
    "required": True,
    "default": None,
}


def _camel(s: str) -> str:
    return "".join(w.title() for w in re.split(r"[_\s-]+", s) if w)


def to_class_name(category: str, name: str) -> str:
    """Convert category + name to the CamelCase class name used by auto-discovery."""
    return _camel(category) + _camel(name)


def to_capability_name(class_name: str) -> str:
    """Convert a CamelCase class name to the snake_case capability key."""
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", class_name)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s)
    return s.lower()


def list_existing_categories() -> List[str]:
    """Return the names of existing skill categories."""
    return sorted(
        p.name
        for p in SKILLS_DIR.iterdir()
        if p.is_dir() and not p.name.startswith("_")
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
        annotated = f'        {p["name"]}: Annotated[{wrapped}, "{desc}"]'
        if default is None:
            annotated += " = None,"
        elif isinstance(default, str):
            annotated += f' = "{default}",'
        else:
            annotated += f" = {default},"
    else:
        annotated = f'        {p["name"]}: Annotated[{type_str}, "{desc}"],'
    return annotated


def generate_init_content() -> str:
    return COPYRIGHT_HEADER + "\n"


def _render_default_schedule(schedule: Dict[str, Any]) -> str:
    """Render a default_schedule dict as indented Python for a skill __init__.

    Ensures the framework-required keys are present: the OrakleScheduler pops
    "kwargs" and "default" from the config, so both must always exist.
    """
    cfg = dict(schedule)
    cfg.setdefault("trigger", "cron")
    cfg.setdefault("kwargs", {})
    cfg.setdefault("default", True)
    # Order keys for readability: trigger first, kwargs/default last
    ordered_keys = (
        ["trigger"]
        + [k for k in cfg if k not in ("trigger", "kwargs", "default")]
        + ["kwargs", "default"]
    )
    lines = ["        self.default_schedule = {"]
    for k in ordered_keys:
        lines.append(f"            {k!r}: {cfg[k]!r},")
    lines.append("        }")
    return "\n".join(lines)


def generate_skill_content(
    category: str,
    name: str,
    description: str,
    params: Optional[List[Dict[str, Any]]] = None,
    with_schedule: bool = False,
    matcher_info: Optional[str] = None,
    extra_imports: Optional[List[str]] = None,
    implementation_body: Optional[str] = None,
    default_schedule: Optional[Dict[str, Any]] = None,
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

    c = f'"""Skill for {description.lower()}"""\n\n'
    c += "import logging\n"
    c += f"from typing import {', '.join(typing_imports)}\n"
    if extra_imports:
        c += "\n".join(extra_imports) + "\n"
    c += "\n"
    c += "from ainara.framework.skill import Skill\n\n\n"
    c += f"class {class_name}(Skill):\n"
    c += f'    """{description}"""\n\n'
    c += "    matcher_info = (\n"
    if matcher_info:
        c += f'        "{matcher_info}"\n'
    else:
        c += f'        "Use this skill when the user wants to {description.lower()}. "\n'
        c += f'        "Keywords: {keywords}"\n'
    c += "    )\n\n"
    c += "    def __init__(self):\n"
    c += "        super().__init__()\n"
    c += "        self.logger = logging.getLogger(__name__)\n"
    if default_schedule:
        # Emit a real, framework-registered schedule (persistent, survives restarts).
        c += "        # Recurring execution handled by the framework OrakleScheduler.\n"
        c += _render_default_schedule(default_schedule) + "\n"
    elif with_schedule:
        c += '        # self.default_schedule = {"trigger": "interval", "minutes": 15}\n'
        c += '        # self.default_schedule = {"trigger": "cron", "hour": 8, "minute": 0}\n'
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
    c += f'description: "{description}"\n'
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
    params: Optional[List[Dict[str, Any]]] = None,
    with_schedule: bool = False,
    with_skill_md: bool = True,
    matcher_info: Optional[str] = None,
    extra_imports: Optional[List[str]] = None,
    implementation_body: Optional[str] = None,
    default_schedule: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
    force: bool = False,
) -> Dict[str, Any]:
    """Create a new skill file (and optionally SKILL.md) on disk.

    Returns a dict with keys: class_name, capability_name, skill_file,
    files_written (list of Path), errors (list of str).
    """
    class_name = to_class_name(category, name)
    capability_name = to_capability_name(class_name)
    category_dir = SKILLS_DIR / category
    skill_file = category_dir / f"{name}.py"
    init_file = category_dir / "__init__.py"
    md_file = category_dir / f"{name}.SKILL.md"

    result: Dict[str, Any] = {
        "class_name": class_name,
        "capability_name": capability_name,
        "skill_file": skill_file,
        "files_written": [],
        "errors": [],
        "skill_content": generate_skill_content(
            category, name, description, params, with_schedule, matcher_info,
            extra_imports=extra_imports, implementation_body=implementation_body,
            default_schedule=default_schedule,
        ),
        "md_content": generate_skill_md(category, name, description, params, matcher_info)
        if with_skill_md
        else None,
    }

    if dry_run:
        return result

    if not category_dir.exists():
        category_dir.mkdir(parents=True, exist_ok=True)

    if not init_file.exists():
        init_file.write_text(generate_init_content(), encoding="utf-8")
        result["files_written"].append(init_file)

    if skill_file.exists() and not force:
        result["errors"].append(
            f"{skill_file} already exists. Pass force=True to overwrite."
        )
        return result

    skill_file.write_text(result["skill_content"], encoding="utf-8")
    result["files_written"].append(skill_file)

    if with_skill_md:
        md_file.write_text(result["md_content"], encoding="utf-8")
        result["files_written"].append(md_file)

    return result
