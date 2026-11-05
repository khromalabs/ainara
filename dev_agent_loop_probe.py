#!/usr/bin/env python
"""Local probe for the Bureau agent-loop / skill-execution regression.

Dev tooling — NOT for commit. Run with the ainara venv:

    venv/bin/python dev_agent_loop_probe.py menu
    venv/bin/python dev_agent_loop_probe.py fabrication
    venv/bin/python dev_agent_loop_probe.py news [--provider groq/openai/gpt-oss-120b]

Suites (all read-only; no tradingorders is ever in an allowed_skills list):

  menu         Deterministic. Starts/uses a local Orakle, fetches
               capabilities, renders the agent system-prompt capability
               menus (news + entry blueprints) exactly as
               run_agent_in_process does, and reports block sizes.
               Tests: is search_web present/complete in the agent menu?
               Did 6194e6fd (full capability menu) bloat the prompt?

  fabrication  Deterministic, no LLM, no Orakle. Feeds the Agent loop a
               scripted response that EMULATES a tool result ("Orakle
               query ... result: {...}") without emitting any <orakle>
               intent — the macmini turn-4 failure signature. Asserts
               what the loop does with it.

  news         Live LLM repro of the Sentinel news_researcher step
               (deployed blueprint, allowed_skills=["search_web","html_website"]).
               Reports turns used, skills actually executed and serving
               provider. Reproduces "1 turn, 0 skills, fabricated data"
               if the regression is in the framework path.
"""

import argparse
import json
import logging
import subprocess
import sys
import time
import urllib.request
from multiprocessing import Queue

REPO = "/home/ruben/lab/src/ainara"
ORAKLE_URL = "http://127.0.0.1:8100"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("probe")


# ─────────────────────────── shared helpers ───────────────────────────


def _ensure_orakle(spawn: bool = True) -> subprocess.Popen | None:
    """Return a running Orakle server process (spawned if needed)."""
    try:
        urllib.request.urlopen(f"{ORAKLE_URL}/health", timeout=2)
        logger.info("Orakle already running on %s", ORAKLE_URL)
        return None
    except Exception:
        pass
    if not spawn:
        raise RuntimeError("Orakle not running and spawn disabled")
    logger.info("Spawning local Orakle server (this loads the matcher "
                "model + ataria skills, may take ~1 min)...")
    proc = subprocess.Popen(
        [f"{REPO}/venv/bin/python", "-m", "ainara.orakle.server",
         "--port", "8100"],
        cwd=REPO,
        stdout=open("/tmp/probe_orakle.log", "w"),
        stderr=subprocess.STDOUT,
    )
    for _ in range(120):
        try:
            urllib.request.urlopen(f"{ORAKLE_URL}/health", timeout=2)
            logger.info("Orakle is up (pid %s, log: /tmp/probe_orakle.log)",
                        proc.pid)
            return proc
        except Exception:
            time.sleep(1)
    proc.kill()
    raise RuntimeError("Orakle failed to become healthy; see "
                       "/tmp/probe_orakle.log")


def _fetch_capabilities() -> list:
    from ainara.framework.orakle_middleware import OrakleCapabilityFetcher
    caps = OrakleCapabilityFetcher([ORAKLE_URL]).fetch_capabilities()
    logger.info("Fetched %d capabilities from Orakle", len(caps))
    return caps


def _llm_config() -> dict:
    from ainara.framework.config import config
    return config.get("llm", {})


# Deployed sentinel_trading.yaml blueprints (macmini, verbatim system
# message trimmed to the first paragraph for the probe; goal verbatim).
NEWS_BLUEPRINT = {
    "name": "Crypto News Researcher",
    "llm_providers": [
        "groq/openai/gpt-oss-120b",
        "cerebras/gpt-oss-120b",
        "gemini/gemini-3.8-flash",
    ],
    "allowed_skills": ["search_web", "html_website"],
    "system_message": (
        "You are a quantitative crypto macro-analyst. Your job is to "
        "identify market-moving events by crossing news recent narratives "
        "(up to 3 days) with hard market data. CRITICAL RULES: 1. Capital "
        "Flow != Optimism. 2. The Apathy/Fear Reality: If the market is "
        "flatlining or reputable sources cite 'Fear', the true sentiment "
        "is fear or cautious at most. Access websites directly if you "
        "need to expand information."
    ),
}
NEWS_GOAL = (
    "Analyze crypto macro factors in the past days (up to 3 days) AND "
    "explicitly cross-reference them with current global market data "
    "(Market Cap % change, 24h Volume), prioritizing the most recent "
    "events. Rate possible findings as high/medium/low impact.\n"
    "**You MUST close your response with this exact report block (fill "
    "in the values):**\n"
    "=== MARKET SENTIMENT CALIBRATION ===\n"
    "market_psychology: [fearful / cautious / neutral / optimistic / greedy]\n"
    "market_mechanics: [distributing / flatlining / accumulating / surging]\n"
    "sentiment_rationale: [one sentence]\n"
    "key_macro_factors: [comma-separated list of top 2-3 macro drivers]"
)

ENTRY_ALLOWED = [
    "khromalabs_ataria_crypto_tradingaccount",
    "khromalabs_ataria_crypto_tradingorders",
    "khromalabs_ataria_crypto_tradingworkbook",
    "khromalabs_ataria_crypto_analysis",
    "khromalabs_ataria_charts_candles",
    "html_webpage",
    "tools_calculator",
]


# ─────────────────────────── suite: menu ──────────────────────────────


def suite_menu() -> None:
    from ainara.framework.orakle_middleware import format_capabilities_menu

    proc = _ensure_orakle()
    try:
        caps = _fetch_capabilities()
        by_name = {c["name"]: c for c in caps}
        print("\n" + "=" * 70)
        print("CAPABILITY MENU FORENSICS (exactly what agent prompts embed)")
        print("=" * 70)

        for label, allowed in (
            ("news_researcher", NEWS_BLUEPRINT["allowed_skills"]),
            ("entry_analyst", ENTRY_ALLOWED),
        ):
            print(f"\n--- blueprint: {label} ---")
            resolved, missing = [], []
            for s in allowed:
                (resolved if s in by_name else missing).append(s)
            print(f"  resolved: {resolved}")
            if missing:
                print(f"  !! MISSING from Orakle capability payload: {missing}")
            menu = format_capabilities_menu(
                [by_name[s] for s in resolved if s in by_name]
            )
            print(f"  menu chars: {len(menu)}  (~{len(menu)//4} tokens)")
            for s in resolved:
                block = format_capabilities_menu([by_name[s]])
                has_params = "Parameters:" in block
                n_params = block.count("\n- ")
                print(
                    f"  - {s}: block={len(block)} chars, "
                    f"params_declared={n_params if has_params else 0}"
                )
            if label == "news_researcher" and "search_web" in by_name:
                print("\n--- search_web block as the agent sees it ---")
                print(format_capabilities_menu([by_name["search_web"]]))
    finally:
        if proc:
            proc.terminate()


# ─────────────────────── suite: fabrication ───────────────────────────


class _FakeLLM:
    """Scripted LLM: yields canned chunk lists, one per chat() call."""

    def __init__(self, scripts):
        self._scripts = scripts
        self.calls = 0

    def add_msg(self, msg, context, role):
        context.append({"role": role, "content": msg})

    def chat(self, chat_history=None, stream=True, **kw):
        script = self._scripts[min(self.calls, len(self._scripts) - 1)]
        self.calls += 1
        yield from script


class _StubMiddleware:
    """Passthrough middleware: capabilities empty, no execution path."""

    capabilities = []

    def process_stream(self, llm_stream, context, **kw):
        yield from llm_stream


FABRICATED_TURN = (
    "Two remaining items: (1) the workbook entry needs its invalidation "
    "corrected; (2) final exposure verification. Updating the entry with "
    "proper invalidation prices:\n\n"
    "Orakle query 'trading workbook action update coin test: replace "
    "invalidation with exact screener levels' result: "
    "{'result': {'requested_action': 'update', 'results': "
    "[{'coin_id': 'test', 'result': {'success': True, 'message': "
    "'Updated test/usdc workbook entry.'}}], 'success': True}}\n\n"
    "Exposure re-verified: everything matches. All done.\n\n"
    "<goal_complete>true</goal_complete>\n<final_answer>Workbook updated "
    "and verified. All done.</final_answer>"
)
CLEAN_COMPLETION_TURN = (
    "<goal_complete>true</goal_complete>\n<final_answer>No actions were "
    "taken. Honest report: nothing was executed.</final_answer>"
)


def suite_fabrication() -> None:
    from ainara.framework.agent.core import Agent

    llm = _FakeLLM([FABRICATED_TURN, CLEAN_COMPLETION_TURN])
    blueprint = {
        "name": "Probe Agent",
        "allowed_skills": ["some_skill_a", "some_skill_b"],
        "system_message": "",
    }
    agent = Agent(
        llm=llm,
        orakle_middleware=_StubMiddleware(),
        blueprint=blueprint,
        system_message="You are a test agent.",
        user_context={"language": "en"},
    )
    result = agent.run("Update the workbook entry for TEST.", max_turns=5)

    # Forensics: what actually persisted in the conversation context?
    context_dump = "\n".join(
        m.get("content", "") for m in agent.context
    )
    forged_persisted = "Updated test/usdc workbook entry" in context_dump
    corrective_issued = any(
        m.get("role") == "user" and "fabricated block" in m.get("content", "")
        for m in agent.context
    )
    forged_in_answer = "Updated test/usdc workbook entry" in result.get(
        "response", ""
    )

    print("\n" + "=" * 70)
    print("FABRICATION GUARD TEST (forge + declare completion, same turn)")
    print("=" * 70)
    print(f"  turns_used             : {result.get('turns_used')}")
    print(f"  skills_executed        : {result.get('skills_executed')}")
    print(f"  failure_reason         : {result.get('failure_reason')}")
    print(f"  forged text in context : {forged_persisted}")
    print(f"  forged text in answer  : {forged_in_answer}")
    print(f"  corrective msg issued  : {corrective_issued}")
    print(f"  response head          : {result.get('response', '')[:100]!r}")

    guard_ok = (
        not forged_persisted
        and not forged_in_answer
        and corrective_issued
        and result.get("turns_used", 0) >= 2
        and not result.get("skills_executed")
    )
    print("\n  >> Model forged a full tool result AND declared goal "
          "completion in one turn.")
    print("  >> Guard verdict: "
          + ("FORGERY PURGED, completion withheld, corrective turn "
             "forced (guard WORKING)" if guard_ok else
             "forgery ACCEPTED into context (blind spot — guard missing "
             "or ineffective)"))


# ─────────────────────────── suite: news ──────────────────────────────


def suite_news(provider_filter: list[str] | None) -> None:
    from ainara.bureau.server import run_agent_in_process

    proc = _ensure_orakle()
    try:
        caps = _fetch_capabilities()
        blueprint = dict(NEWS_BLUEPRINT)
        if provider_filter:
            blueprint["llm_providers"] = provider_filter
        q = Queue()
        logger.info("Running news blueprint with providers: %s",
                    blueprint["llm_providers"])
        run_agent_in_process(
            llm_config=_llm_config(),
            orakle_servers=[ORAKLE_URL],
            blueprint=blueprint,
            user_context={"language": "en"},
            goal=NEWS_GOAL,
            max_turns=10,
            result_queue=q,
            global_capabilities=caps,
        )
        result = q.get(timeout=10)
        print("\n" + "=" * 70)
        print("LIVE NEWS-STEP REPRO (deployed blueprint, read-only skills)")
        print("=" * 70)
        print(f"  serving provider : {result.get('llm_provider')}")
        print(f"  provider attempts: {result.get('llm_provider_attempts')}")
        print(f"  turns_used       : {result.get('turns_used')}")
        print(f"  skills_executed  : {result.get('skills_executed')}")
        print(f"  failure_reason   : {result.get('failure_reason')}")
        resp = result.get("response", "")
        print(f"  response ({len(resp)} chars), first 600:\n{resp[:600]}")
        if not result.get("skills_executed"):
            print("\n  >> REPRODUCED: agent completed with ZERO skill "
                  "executions. Everything in the answer is parametric "
                  "memory — check whether the response contains "
                  "invented figures.")
        else:
            print("\n  >> Agent DID use skills this time — regression "
                  "not reproduced with this provider/model.")
    finally:
        if proc:
            proc.terminate()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("suite", choices=["menu", "fabrication", "news", "all"])
    ap.add_argument("--provider", action="append",
                    help="Override llm_providers for the news suite "
                         "(repeatable)")
    args = ap.parse_args()

    if args.suite in ("fabrication", "all"):
        suite_fabrication()
    if args.suite in ("menu", "all"):
        suite_menu()
    if args.suite in ("news", "all"):
        suite_news(args.provider)


if __name__ == "__main__":
    main()
