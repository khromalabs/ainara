"""Meta-skill that scaffolds new user skills from natural language descriptions.

Generated skills are written to the configured user_skills.directory and load as
user_<namespace>_<name> capabilities. They are never written into the core
skills tree, which is read-only inside a packaged build.
"""

import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

from ainara.framework.config import config
from ainara.framework.llm import create_llm_backend
from ainara.framework.skill import Skill
from ainara.framework.skill_scaffolder import (
    create_skill,
    list_existing_categories,
    safe_namespace,
    to_capability_name,
    to_class_name,
    user_skills_dir,
)

logger = logging.getLogger(__name__)

# Core skills root: tools/skillbuilder.py -> tools/ -> skills/. Read only, to
# avoid generating a user skill that duplicates a core one.
CORE_SKILLS_DIR = Path(__file__).parent.parent

_PARSE_PROMPT = """\
You are an AI assistant that extracts structured metadata from a natural-language
description of a software skill/tool.

Given the user's description, return ONLY a JSON object with these fields:

{{
  "category": "<one lowercase word, one of the suggested ones or a new one>",
  "name": "<lowercase snake_case skill name, 1-3 words>",
  "description": "<concise one-sentence description, no trailing period>",
  "matcher_info": "<sentence(s) describing when to use this skill, including keywords>",
  "params": [
    {{
      "name": "<snake_case>",
      "type": "<Python type: str | int | float | bool | Optional[str] | Literal['a','b']>",
      "description": "<what this parameter does>",
      "required": true or false,
      "default": null or a literal value
    }}
  ]
}}

Rules:
- category must be a single lowercase word: letters and digits only, no underscores
- name must be lowercase alphanumeric with underscores only, not the same as category
- description should start with a capital letter
- params must cover the inputs needed to execute the skill
- If you are unsure about a type, use "str"
- Return ONLY the JSON, no markdown fences, no extra text

Suggested categories: {categories}
"""

_STACK_RESEARCH_PROMPT = """\
You are an expert at finding the best free, no-signup APIs and Python libraries for a given task.

Goal: {description}
Parameters the skill will receive: {param_names}

Installed Python packages (prefer these — no installation needed):
{installed_packages}

Return ONLY a JSON object with this structure:
{{
  "stack": [
    {{
      "purpose": "what this component does in the skill",
      "option": "library or API name",
      "type": "stdlib" | "library" | "free_api",
      "requires_key": false,
      "package": "importable package name (e.g. requests, pytz)",
      "notes": "brief usage notes or endpoint if free_api"
    }}
  ],
  "implementation_notes": "1-3 sentences on how to combine these components"
}}

Rules:
- Prefer stdlib > installed library > free API (no key) > free API (key)
- Never suggest an API that requires authentication or signup
- Only suggest packages that are in the installed list above, or stdlib
- If nothing suitable is installed, suggest the simplest stdlib approach even if imperfect
- Do NOT suggest scheduling/background-job libraries (apscheduler, schedule,
  threading, sched). Recurring execution is handled by the Ainara framework, not
  the skill — the skill body only performs ONE execution.
- Do NOT suggest libraries for desktop notifications (plyer, win10toast) or for
  sending email (smtplib as a "notifier"). Delivery to the user is handled by the
  framework; the skill should return its result as data.
- Return ONLY the JSON, no markdown fences
"""

_IMPLEMENTATION_PROMPT = """\
You are writing a Python skill for an AI assistant framework.

Skill goal: {description}

Stack to use (do NOT use any other packages):
{stack_spec}

Implementation notes from the researcher:
{implementation_notes}

The method signature is already written. Parameters available as local variables:
{param_list}

Framework rules (IMPORTANT — the skill runs inside the Ainara framework):
  - The body performs the work for ONE execution only. Do NOT implement any
    scheduling, recurring timers, or background jobs: no apscheduler,
    BackgroundScheduler, threading, sched, time.sleep loops, or while-True. The
    framework calls run() each time the user asks; you only write what happens
    for a single run.
  - Do NOT send the result to the user yourself (no smtplib email, no desktop-toast
    / PowerShell / notify-send / osascript). Just return the result as data; the
    framework delivers it.
  - Never hardcode secrets, SMTP servers, or credentials. Read configuration with:
        from ainara.framework.config import config
        value = config.get("some.config.path")
  - For persistent skill data files, use the configured data directory:
        from ainara.framework.config import get_data_dir
        data_dir = get_data_dir()
  - Do NOT create or block on an event loop (no asyncio.run); the body may use
    already-awaited results but the run() method is already async.

Output format — write exactly two sections separated by a blank line:

SECTION 1: import lines only (one per line, e.g. "import requests")
  - Include every package the implementation body uses
  - Omit logging, typing, and ainara.framework.skill (already imported)
  - If no imports are needed, write the single word: NONE

SECTION 2: the code that goes INSIDE the try: block (no try/except wrapper, no def line)
  - End with: return {{"success": True, "result": <human-readable result string>}}
  - The "result" value should directly answer the user's query as a readable string
  - Handle sub-failures with specific error messages before the final return
  - Indent with 0 spaces (the caller adds indentation automatically)

No markdown fences, no explanation — just the two sections.
"""


class ToolsSkillbuilder(Skill):
    """Scaffold a new Ainara skill from a natural language description"""

    # Always included in matcher candidates so skill-creation queries are never
    # lost to higher-scoring domain-specific skills (e.g. search/web skills
    # when the query mentions "SEO skill" or similar).
    embeddings_boost_factor = 3

    matcher_info = (
        "Use this skill when the user explicitly asks to CREATE, BUILD, ADD, or MAKE a new skill, "
        "tool, or capability for Ainara — regardless of what the skill is about. "
        "The topic of the requested skill (time, weather, finance, etc.) is irrelevant; "
        "what matters is that the user is requesting a NEW skill be created. "
        "Trigger phrases: 'create a skill', 'build a skill', 'add a skill', 'make a skill', "
        "'new skill', 'scaffold a skill', 'I want a skill that', 'add a capability', "
        "'please create a skill', 'can you build a skill'. "
        "Do NOT use this for requests to USE an existing skill — only for creating new ones."
    )

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)

    def _find_existing_skill(
        self, description: str, user_dir: Optional[Path]
    ) -> Optional[tuple]:
        """Scan core and user skills for one whose name words all appear in the description.

        Returns (capability_name, skill_file) if a match is found, else None.
        This check runs before the LLM call to short-circuit duplicate creation.
        Two strategies are used:
        - Token match: all underscore-split words of the filename appear in the
          space-split words of the description (e.g. "lookup" in "lookup timezone")
        - Merged match: the filename stem with underscores stripped appears
          anywhere in the description stripped of spaces/underscores
          (e.g. "timezonelookup" found in "time zone lookup" → "timezonelookup")
        """
        stop_words = {
            "a", "an", "the", "for", "of", "to", "in", "that", "and", "or",
            "by", "with", "is", "it", "skill", "build", "create", "make",
            "add", "new", "me", "i", "want", "need", "please", "can",
            "could", "would", "should", "based", "on", "using", "accept",
            "input", "output", "return", "get", "set", "my",
        }
        desc_lower = description.lower()
        desc_words = {
            w
            for w in re.split(r"[\s_\-,./]+", desc_lower)
            if len(w) > 2 and w not in stop_words
        }
        # Merged form: description with all non-alpha stripped, for compound matching
        desc_merged = re.sub(r"[^a-z0-9]", "", desc_lower)

        roots = [(CORE_SKILLS_DIR, False)]
        if user_dir:
            roots.append((user_dir, True))
        for root, is_user in roots:
            match = self._scan_for_match(root, is_user, stop_words,
                                         desc_words, desc_merged)
            if match:
                return match
        return None

    @staticmethod
    def _scan_for_match(root, is_user, stop_words, desc_words, desc_merged):
        if not root.is_dir():
            return None
        for category_dir in sorted(root.iterdir()):
            if not category_dir.is_dir() or category_dir.name.startswith(("_", ".")):
                continue
            for skill_file in sorted(category_dir.glob("*.py")):
                if skill_file.name.startswith("_"):
                    continue
                if is_user:
                    cap = to_capability_name(
                        to_class_name(category_dir.name, skill_file.stem))
                else:
                    cap = f"{category_dir.name}_{skill_file.stem}"
                stem = skill_file.stem.lower()
                skill_words = {
                    w
                    for w in re.split(r"[_]+", stem)
                    if len(w) > 2 and w not in stop_words
                }
                # Strategy 1: all token words appear in description tokens
                if skill_words and skill_words.issubset(desc_words):
                    return cap, skill_file
                # Strategy 2: merged stem appears in merged description
                # e.g. "timezone_lookup" → "timezonelookup" found in "timezonelookup"
                stem_merged = re.sub(r"[^a-z0-9]", "", stem)
                if len(stem_merged) > 4 and stem_merged in desc_merged:
                    return cap, skill_file
        return None

    def _get_installed_packages(self) -> List[str]:
        """Return a sorted list of installed package names in the current Python env."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "list", "--format=columns"],
                capture_output=True, text=True, timeout=10,
            )
            lines = result.stdout.splitlines()[2:]  # skip header rows
            return sorted(line.split()[0].lower() for line in lines if line.strip())
        except Exception as e:
            self.logger.warning(f"pip list failed: {e}")
            return []

    async def _research_stack(
        self, description: str, params: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Ask the LLM to pick the best free stack for the given skill goal.

        Returns a dict with keys: stack (list), implementation_notes (str),
        extra_imports (list[str]). Returns empty/fallback values on failure.
        """
        installed = self._get_installed_packages()
        param_names = ", ".join(p["name"] for p in params) if params else "none"
        installed_str = "\n".join(f"  - {p}" for p in installed) if installed else "  (unknown)"

        system_prompt = _STACK_RESEARCH_PROMPT.format(
            description=description,
            param_names=param_names,
            installed_packages=installed_str,
        )
        llm = create_llm_backend(config.get("llm", {}))
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Research the best free stack for: {description}"},
        ]
        try:
            raw = await llm.achat(chat_history=messages)
            raw = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
            data = json.loads(raw)
        except Exception as e:
            self.logger.warning(f"Stack research failed, falling back to stub: {e}")
            return {"stack": [], "implementation_notes": "", "extra_imports": []}

        # Build extra_imports from the stack entries
        extra_imports: List[str] = []
        seen: set = set()
        for item in data.get("stack", []):
            pkg = item.get("package", "").strip()
            if not pkg or pkg in seen:
                continue
            seen.add(pkg)
            # Stdlib modules use plain "import X"; others too — let LLM decide details
            # We just record the top-level package for the implementation prompt
        data["extra_imports"] = extra_imports  # populated by implementation step
        return data

    async def _generate_implementation(
        self,
        description: str,
        params: List[Dict[str, Any]],
        stack_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Generate the actual run() body and required imports using the chosen stack.

        Returns {"extra_imports": [...], "implementation_body": "..."} or empty on failure.
        """
        if not stack_data.get("stack"):
            return {}

        stack_spec = json.dumps(stack_data["stack"], indent=2)
        param_list = "\n".join(
            f"  {p['name']}: {p.get('type', 'str')} — {p.get('description', '')}"
            for p in params
        ) if params else "  (no parameters)"

        system_prompt = _IMPLEMENTATION_PROMPT.format(
            description=description,
            stack_spec=stack_spec,
            implementation_notes=stack_data.get("implementation_notes", ""),
            param_list=param_list,
        )
        llm = create_llm_backend(config.get("llm", {}))
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Write the implementation body now."},
        ]
        try:
            raw = await llm.achat(chat_history=messages)
            raw = re.sub(r"```(?:python)?\s*", "", raw).strip().rstrip("`").strip()
        except Exception as e:
            self.logger.warning(f"Implementation generation failed: {e}")
            return {}

        # Parse the two-section output: imports (section 1) then body (section 2)
        # Sections are separated by the first blank line after the import block.
        import_lines: List[str] = []
        body_lines: List[str] = []
        in_body = False
        for line in raw.splitlines():
            if in_body:
                body_lines.append(line)
            elif not line.strip():
                # First blank line marks the boundary
                in_body = True
            elif line.strip().upper() == "NONE":
                in_body = True  # no imports, next content is body
            elif line.startswith("import ") or line.startswith("from "):
                import_lines.append(line.strip())
            else:
                # Unexpected non-import line before blank separator → treat as body start
                in_body = True
                body_lines.append(line)

        return {
            "extra_imports": import_lines,
            "implementation_body": "\n".join(body_lines).strip(),
        }

    async def _parse_description(
        self, description: str, user_dir: Path
    ) -> Dict[str, Any]:
        """Ask the LLM to extract structured skill metadata from free text."""
        categories = ", ".join(list_existing_categories(user_dir)) or "tools"
        system_prompt = _PARSE_PROMPT.format(categories=categories)

        llm = create_llm_backend(config.get("llm", {}))
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": description},
        ]
        raw = await llm.achat(chat_history=messages)

        # Strip markdown fences if the model added them
        raw = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()

        return json.loads(raw)

    def _normalize_parsed(self, parsed: Dict[str, Any]) -> None:
        """Normalize category and name in-place to valid snake_case."""
        category = parsed.get("category", "")
        if isinstance(category, str):
            # One lowercase word: discovery capitalize()s the namespace whole,
            # so "home_automation" would not resolve to its class.
            parsed["category"] = re.sub(r"[^a-z0-9]", "", category.lower())
        for field in ("name",):
            value = parsed.get(field, "")
            if isinstance(value, str):
                # Lowercase, replace hyphens/spaces/dots with underscores, strip extras
                value = value.strip().lower()
                value = re.sub(r"[-\s.]+", "_", value)
                value = re.sub(r"[^a-z0-9_]", "", value)
                value = re.sub(r"_+", "_", value).strip("_")
                parsed[field] = value

    def _validate_parsed(self, parsed: Dict[str, Any]) -> Optional[str]:
        """Return an error string if parsed metadata is invalid, else None."""
        for field in ("category", "name", "description"):
            if not parsed.get(field):
                return f"Missing required field: {field}"
        if not re.match(r"^[a-z][a-z0-9]*$", parsed["category"]):
            return f"Invalid category: {parsed['category']}"
        if not re.match(r"^[a-z][a-z0-9_]*$", parsed["name"]):
            return f"Invalid name: {parsed['name']}"
        return None

    async def run(
        self,
        description: Annotated[
            str,
            "Natural language description of the skill to create, e.g. "
            "'I want a skill that checks my calendar and summarizes today\\'s meetings'",
        ],
        dry_run: Annotated[
            bool,
            "If true, return the generated code without writing files to disk",
            "hidden",
        ] = False,
        category: Annotated[
            Optional[str],
            "Override the category (optional; LLM will suggest one if omitted)",
        ] = None,
        name: Annotated[
            Optional[str],
            "Override the skill name in snake_case (optional; LLM will suggest one if omitted)",
        ] = None,
    ) -> Dict[str, Any]:
        """Scaffold a new user skill from a plain-English description.

        The skill uses an LLM to extract the category, name, description,
        parameters and matcher_info from the user's free-text input, then
        generates a fully wired Python skill file (and SKILL.md) in the
        configured user skills directory.

        Returns:
            Dict containing success (bool), skill_file path, capability_name,
            class_name, and the generated skill_content for review.
        """
        user_dir = user_skills_dir()
        if not user_dir:
            return {
                "success": False,
                "error": (
                    "No user skills directory is configured, so there is nowhere"
                    " to write a new skill. Set user_skills.directory in"
                    " ainara.yaml and ask again."
                ),
            }

        # Pre-LLM check: bail early if a skill with matching name already exists
        existing = self._find_existing_skill(description, user_dir)
        if existing:
            cap, skill_file = existing
            return {
                "success": True,
                "already_exists": True,
                "capability_name": cap,
                "skill_file": str(skill_file),
                "message": (
                    f"Skill '{cap}' already exists at {skill_file} - "
                    "nothing was changed. To rebuild it from scratch, "
                    "delete the file and ask again."
                ),
            }

        try:
            parsed = await self._parse_description(description, user_dir)
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "error": f"LLM returned non-JSON response: {e}",
            }
        except Exception as e:
            self.logger.error(f"LLM parse failed: {e}")
            return {"success": False, "error": f"Failed to parse description: {e}"}

        # Allow caller overrides
        if category:
            parsed["category"] = category.lower()
        if name:
            parsed["name"] = name.lower()

        # Normalize category and name to valid snake_case before validating
        self._normalize_parsed(parsed)

        error = self._validate_parsed(parsed)
        if error:
            return {"success": False, "error": error, "parsed": parsed}

        # A namespace named after a Python module would shadow it for the whole
        # process once the user skills directory is on sys.path.
        requested_category = parsed["category"]
        parsed["category"] = safe_namespace(requested_category, user_dir)

        params: List[Dict[str, Any]] = parsed.get("params", [])

        # --- Stack research + implementation generation ---
        stack_data: Dict[str, Any] = {}
        extra_imports: List[str] = []
        implementation_body: Optional[str] = None
        try:
            stack_data = await self._research_stack(parsed["description"], params)
            if stack_data.get("stack"):
                impl = await self._generate_implementation(
                    parsed["description"], params, stack_data
                )
                extra_imports = impl.get("extra_imports", [])
                implementation_body = impl.get("implementation_body") or None
        except Exception as e:
            self.logger.warning(f"Stack research/impl generation skipped: {e}")

        result = create_skill(
            category=parsed["category"],
            name=parsed["name"],
            description=parsed["description"],
            skills_dir=user_dir,
            params=params or None,
            matcher_info=parsed.get("matcher_info"),
            extra_imports=extra_imports or None,
            implementation_body=implementation_body,
            with_skill_md=True,
            dry_run=dry_run,
            force=False,
        )

        if result["errors"]:
            err = result["errors"][0]
            # "already exists" is not a failure — return success so the agent
            # doesn't treat it as an error and retry in a loop.
            if "already exists" in err:
                cap = result["capability_name"]
                return {
                    "success": True,
                    "already_exists": True,
                    "capability_name": cap,
                    "skill_file": str(result["skill_file"]),
                    "message": (
                        f"Skill '{cap}' already exists at "
                        f"{result['skill_file']} - nothing was changed. "
                        "To rebuild it from scratch, delete the file and ask again."
                    ),
                }
            return {
                "success": False,
                "error": err,
                "parsed": parsed,
            }

        files_written = [str(f) for f in result["files_written"]]
        response = {
            "success": True,
            "class_name": result["class_name"],
            "capability_name": result["capability_name"],
            "skill_file": str(result["skill_file"]),
            "parsed": parsed,
            "stack_used": stack_data.get("stack", []),
            "implementation_generated": implementation_body is not None,
        }

        if dry_run:
            response["skill_content"] = result["skill_content"]
            response["md_content"] = result["md_content"]
            response["message"] = (
                f"Dry run: would create {result['class_name']} "
                f"as capability '{result['capability_name']}'. "
                "No files written."
            )
        else:
            response["files_written"] = files_written
            response["message"] = (
                f"Created user skill '{result['capability_name']}' "
                f"({result['class_name']}) at {result['skill_file']}. "
                "Review its run() method, then restart Orakle to load it."
            )

        notes = []
        if parsed["category"] != requested_category:
            notes.append(
                f"Namespace '{requested_category}' would shadow a Python module,"
                f" so the skill is in '{parsed['category']}'."
            )
        if parsed.get("schedule"):
            notes.append(
                "Orakle does not run user skills on a schedule, so no schedule"
                " was added; trigger it from a conversation or an external"
                " scheduler instead."
            )
        if notes:
            response["notes"] = notes

        return response
