#!/usr/bin/env python
"""Reconstruct the September (dev011 era) vs current agent system prompts.

Dev tooling — NOT for commit. Shows exactly what changed in what the
agent LLM sees, per blueprint, including sizes.

    venv/bin/python dev_prompt_compare.py
"""

import re
import subprocess
import sys

ATARIA_SEP = "d67d80c"      # macmini ataria checkout on Sep 29 (pulled 09-26)
ATARIA_DIR = "/home/ruben/macmini/lab/src/ataria"
AINARA_DIR = "/home/ruben/lab/src/ainara"
OLD_TEMPLATE_REF = "6194e6fd^"  # dev011-era agent template (pre full-menu)

ENTRY_SKILLS = [
    # (skill_id, repo, ref, relpath)
    ("tradingaccount", "ataria", ATARIA_SEP, "crypto/tradingaccount.py"),
    ("tradingorders", "ataria", ATARIA_SEP, "crypto/tradingorders.py"),
    ("tradingworkbook", "ataria", ATARIA_SEP, "crypto/tradingworkbook.py"),
    ("crypto_analysis", "ataria", ATARIA_SEP, "crypto/analysis.py"),
    ("charts_candles", "ataria", ATARIA_SEP, "charts/candles.py"),
    ("html_webpage", "ainara", "6194e6fd^", "ainara/orakle/skills/html/webpage.py"),
    ("tools_calculator", "ainara", "6194e6fd^", "ainara/orakle/skills/tools/calculator.py"),
]

SEARCH_WEB_SEP = ("ainara", "6194e6fd^", "ainara/orakle/skills/search/web.py")


def git_show(repo_dir: str, ref: str, path: str) -> str:
    out = subprocess.run(
        ["git", "-c", "safe.directory=*", "show", f"{ref}:{path}"],
        cwd=repo_dir, capture_output=True, text=True, check=True,
    )
    return out.stdout


def class_docstring(src: str) -> str:
    """First triple-quoted string right after the first class statement."""
    m = re.search(r"class\s+\w+[^:]*:\s*(?:\"\"\"|''')(.*?)(?:\"\"\"|''')",
                  src, re.DOTALL)
    return m.group(1).strip() if m else ""


def tokens(s: str) -> int:
    return len(s) // 4


def main() -> None:
    # ── September era ──
    old_template = git_show(AINARA_DIR, OLD_TEMPLATE_REF,
                            "ainara/templates/framework.agent.system_prompt.mu")
    sep_descriptions = []
    for sid, repo, ref, path in ENTRY_SKILLS:
        src = git_show(ATARIA_DIR if repo == "ataria" else AINARA_DIR, ref, path)
        sep_descriptions.append(class_docstring(src))
    sep_hint = ", ".join(sep_descriptions)
    sep_prompt = old_template.replace("{{skills_hint_text}}", sep_hint)
    # rudimentary mustache handling for the conditional block
    sep_prompt = re.sub(r"\{\{#nexus_available\}\}.*?\{\{/nexus_available\}\}",
                        "", sep_prompt, flags=re.DOTALL)
    sep_prompt = (sep_prompt
                  .replace("{{current_date}}", "Thursday 2026-11-05")
                  .replace("{{current_time}}", "18:01:00"))

    # ── Current era (menu from the live probe measurements) ──
    cur_template = open(f"{AINARA_DIR}/ainara/templates/"
                        "framework.agent.system_prompt.mu").read()
    from ainara.framework.orakle_middleware import format_capabilities_menu
    proc = subprocess.Popen(
        [f"{AINARA_DIR}/venv/bin/python", "-m", "ainara.orakle.server",
         "--port", "8101"],
        cwd=AINARA_DIR, stdout=open("/tmp/pc_orakle.log", "w"),
        stderr=subprocess.STDOUT)
    import time, urllib.request
    caps = None
    for _ in range(120):
        try:
            from ainara.framework.orakle_middleware import OrakleCapabilityFetcher
            caps = OrakleCapabilityFetcher(["http://127.0.0.1:8101"]) \
                .fetch_capabilities()
            break
        except Exception:
            time.sleep(1)
    try:
        by_name = {c["name"]: c for c in caps}
        menu = format_capabilities_menu(
            [by_name[s["name"].split("_")[-1]] if False else by_name[k]
             for k, s in {
                "khromalabs_ataria_crypto_tradingaccount": None,
                "khromalabs_ataria_crypto_tradingorders": None,
                "khromalabs_ataria_crypto_tradingworkbook": None,
                "khromalabs_ataria_crypto_analysis": None,
                "khromalabs_ataria_charts_candles": None,
                "html_webpage": None,
                "tools_calculator": None,
             }.items() if k in by_name]
        )
        cur_prompt = cur_template.replace("{{skills_hint_text}}", menu)
        cur_prompt = re.sub(r"\{\{#nexus_available\}\}.*?\{\{/nexus_available\}\}",
                            "", cur_prompt, flags=re.DOTALL)
        cur_prompt = (cur_prompt
                      .replace("{{current_date}}", "Thursday 2026-11-05")
                      .replace("{{current_time}}", "18:01:00"))

        print("=" * 72)
        print("AGENT SYSTEM PROMPT — September (dev011) vs current (dev012)")
        print("=" * 72)
        print(f"September prompt : {len(sep_prompt):6d} chars "
              f"(~{tokens(sep_prompt)} tokens)")
        print(f"  └ skills_hint  : {len(sep_hint):6d} chars "
              f"(~{tokens(sep_hint)} tokens)")
        print(f"Current prompt   : {len(cur_prompt):6d} chars "
              f"(~{tokens(cur_prompt)} tokens)")
        print(f"  └ skills menu  : {len(menu):6d} chars "
              f"(~{tokens(menu)} tokens)")
        print(f"DELTA            : {len(cur_prompt)-len(sep_prompt):+6d} chars")

        # news step, search_web, old vs new
        sep_sw = class_docstring(git_show(AINARA_DIR, SEARCH_WEB_SEP[1],
                                          SEARCH_WEB_SEP[2]))
        sw_block = format_capabilities_menu([by_name["search_web"]])
        print("\n--- news_researcher skills hint ---")
        print(f"September (search_web docstring): {len(sep_sw)} chars")
        print(f"Current   (search_web menu block): {len(sw_block)} chars")

        # fragments
        print("\n" + "=" * 72)
        print("SAMPLE: tradingorders, as seen by the entry_analyst LLM")
        print("=" * 72)
        print("\n########## SEPTEMBER (comma-joined docstring) ##########\n")
        print(sep_descriptions[1])
        print("\n########## CURRENT (annotation-derived block) ##########\n")
        print(format_capabilities_menu([by_name["khromalabs_ataria_crypto_tradingorders"]]))
    finally:
        proc.terminate()


if __name__ == "__main__":
    sys.path.insert(0, AINARA_DIR)
    main()
