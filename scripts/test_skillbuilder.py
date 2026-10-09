#!/usr/bin/env python3
"""Offline gate for tools_skillbuilder: enable gate, preview, create.

The three LLM calls are stubbed, and every path (user skills directory, data
directory) points into a temporary directory, so this never touches the real
config, the core skills tree or a model. It checks:

1. disabled by default: run() refuses, and the skill is hidden at discovery
2. enabled with no user_skills.directory: refuses, writes nothing
3. dry_run returns the code; nothing lands in the skills directory
4. a description writes the skill, and the real UserSkillProvider loads it
   under the reported capability name
5. a repeat request is reported as already existing
6. a namespace that shadows a module ('time') becomes 'mytime'
7. generated code that does not compile is refused before anything is written
"""

import asyncio
import json
import os
import pathlib
import shutil
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# config.set() saves, so point the whole run at a throwaway config file
# before anything reads the real one.
TMP = pathlib.Path(tempfile.mkdtemp(prefix="skillbuilder_gate_"))
(TMP / "ainara.yaml").write_text("{}\n", encoding="utf-8")
os.environ["AINARA_CONFIG"] = str(TMP / "ainara.yaml")

from ainara.framework.config import config  # noqa: E402
from ainara.orakle.skills.tools import skillbuilder  # noqa: E402

FAILURES = []


def check(label, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {label}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILURES.append(label)


class StubLLM:
    """Answers the parse, stack and implementation prompts in turn."""

    def __init__(self, category, name, body):
        self.replies = [
            json.dumps({
                "category": category,
                "name": name,
                "description": "Reverse the given text",
                "matcher_info": "Use this to reverse text. Keywords: reverse",
                "params": [{
                    "name": "text", "type": "str",
                    "description": "Text to reverse", "required": True,
                    "default": None,
                }],
            }),
            json.dumps({
                "stack": [{"purpose": "reverse", "option": "slicing",
                           "type": "stdlib", "requires_key": False,
                           "package": "", "notes": ""}],
                "implementation_notes": "Use slicing.",
            }),
            "NONE\n\n" + body,
        ]

    async def achat(self, chat_history):
        return self.replies.pop(0)


def use_llm(category="text", name="reverser",
            body='return {"success": True, "result": text[::-1]}'):
    stub = StubLLM(category, name, body)
    skillbuilder.create_llm_backend = lambda _cfg: stub


def run(**kwargs):
    return asyncio.run(skillbuilder.ToolsSkillbuilder().run(**kwargs))


def files_under(path):
    return sorted(p.relative_to(path).as_posix() for p in path.rglob("*") if p.is_file())


def main():
    user_dir = TMP / "user_skills"
    data_dir = TMP / "data"
    core_before = files_under(skillbuilder.CORE_SKILLS_DIR)
    try:
        config.set("data.directory", str(data_dir))
        config.set("user_skills.directory", str(user_dir))

        # 1. Off by default
        config.set("skills.builder.enabled", None)
        r = run(description="a skill that reverses text")
        check("disabled: refuses", r.get("refused") == "skill_builder_not_enabled", r)
        check("disabled: hidden at discovery",
              skillbuilder.ToolsSkillbuilder().hiddenCapability is True)
        config.set("skills.builder.enabled", "true")
        check("only a real true enables it",
              run(description="x").get("refused") == "skill_builder_not_enabled")
        config.set("skills.builder.enabled", True)
        check("enabled: visible at discovery",
              skillbuilder.ToolsSkillbuilder().hiddenCapability is False)

        # 2. No user skills directory
        config.set("user_skills.directory", None)
        r = run(description="a skill that reverses text")
        check("no user dir: refuses", not r["success"] and "user_skills.directory" in r["error"], r)
        config.set("user_skills.directory", str(user_dir))

        # 3. dry_run previews, writes nothing
        use_llm()
        r = run(description="a skill that flips strings around", dry_run=True)
        check("dry_run returns the code", r.get("success") and r.get("installed") is False, r)
        check("dry_run writes nothing", not user_dir.exists() or not files_under(user_dir))
        check("dry_run carries the generated body", "text[::-1]" in r["skill_content"])

        # 4. Create writes the skill, and it loads
        use_llm()
        r = run(description="a skill that flips strings around")
        check("create succeeds", r.get("success") and r.get("installed"), r)
        written = (user_dir / "text" / "reverser.py").read_text(encoding="utf-8")
        check("written code is the returned code", written == r["skill_content"])
        check("SKILL.md written", (user_dir / "text" / "reverser.SKILL.md").is_file())

        from ainara.framework.capabilities.skills import UserSkillProvider
        caps = UserSkillProvider(config, None).discover()
        check("UserSkillProvider loads it under the reported name",
              r.get("capability_name") in caps, f"{r.get('capability_name')} not in {list(caps)}")

        # 5. Repeat request
        r = run(description="a skill that is a text reverser")
        check("repeat reported as existing", r.get("already_exists") is True, r)

        # 6. Shadowing namespace
        use_llm(category="time", name="stamp", body='return {"success": True, "result": text}')
        r = run(description="a skill that stamps things with a time")
        check("'time' namespace becomes 'mytime'",
              r.get("capability_name") == "user_mytime_stamp" and r.get("notes"), r)

        # 7. Broken generated code
        use_llm(category="text", name="broken", body="return {")
        r = run(description="a skill that is broken on purpose")
        check("uncompilable code refused", not r["success"] and "does not compile" in r["error"], r)

        check("core skills tree untouched",
              files_under(skillbuilder.CORE_SKILLS_DIR) == core_before)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)

    print()
    print("ALL PASS" if not FAILURES else f"{len(FAILURES)} FAILED: {FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
