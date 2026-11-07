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


def _llm_config(provider: str | None = None) -> dict:
    import os
    from ainara.framework.config import config
    llm_config = config.get("llm", {})
    if provider:
        providers = llm_config.setdefault("providers", [])
        if not any(p.get("model") == provider for p in providers):
            # Synthesize the provider entry from the environment, mirroring
            # what the macmini config carries explicitly.
            env_keys = {
                "zai": "ZAI_API_KEY",
                "groq": "GROQ_API_KEY",
                "cerebras": "CEREBRAS_API_KEY",
                "deepseek": "DEEPSEEK_API_KEY",
                "xiaomi_mimo": "XIAOMI_MIMO_API_KEY",
                "gemini": "GEMINI_API_KEY",
            }
            prefix = provider.split("/")[0]
            api_key = os.environ.get(env_keys.get(prefix, ""), "")
            if not api_key:
                raise RuntimeError(
                    f"No api_key for '{provider}' (set "
                    f"{env_keys.get(prefix, '?')} in the environment or "
                    "add it to ainara.yaml)"
                )
            providers.append({"model": provider, "api_key": api_key})
    return llm_config


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


ENTRY_ALLOWED_SAFE = [
    "khromalabs_ataria_crypto_tradingaccount",
    "khromalabs_ataria_crypto_tradingworkbook",
    "khromalabs_ataria_crypto_analysis",
    "khromalabs_ataria_charts_candles",
    "html_webpage",
    "tools_calculator",
]

ENTRY_BLUEPRINT = {
    "name": "Sentinel Entry Analyst",
    "allowed_skills": ENTRY_ALLOWED_SAFE,
    "system_message": (
        "You are the Sentinel Entry Analyst. Follow the trading workflow "
        "protocol: read market psychology, evaluate ONLY the actionable "
        "setup provided in the goal, apply the catalyst gate and geometry "
        "checks, decide, and validate any real state via ORAKLE skills "
        "(workbook, account exposure). Report reality, never intentions: "
        "a trade that no skill result confirmed in this conversation did "
        "NOT happen. IMPORTANT SESSION CONSTRAINT: the tradingorders "
        "skill is NOT available in this session — never attempt to place, "
        "edit or close orders. If a trade would be warranted, output the "
        "intended order ticket explicitly marked 'NOT EXECUTED (orders "
        "disabled in this session)'."
    ),
}

ENTRY_GOAL = (
    "Find and execute new good and outstanding conviction trading setups "
    "(4h timeframe). === MARKET & PORTFOLIO DATA === USDC Balance: 100.44. "
    "Active Exposure: no active positions or open orders. === "
    "Actionable Setup === HBAR/USDC - $0.0678 (-7.3% 24h) - MCap: $3.0B. "
    "Setup Direction: SHORT. RSI(14): 43.73 (neutral) | MACD: neutral on "
    "4h | Last Closed Vol: 3.7x avg. 4H Market Bias: BEARISH (68% conf) | "
    "Last BOS: bearish_bos @ $0.0675 (Age: 0), EMA bearish cross. Entry "
    "Level (awaiting retest): $0.0675 | SL: $0.0708 (1.76 ATR). Regime: "
    "TRENDING (ADX 29.1, ATR 74th pct, fresh BOS). Stop Hostility: "
    "Efficiency Ratio 0.23 | Est. Adverse Excursion (AEx): 1.93 ATR "
    "(~5.4%). === ASSET-SPECIFIC CATALYSTS === catalyst_strength: high; "
    "catalyst_direction: bullish; catalyst_durability: sustained; "
    "timeline: 2026-11-04 enterprise partnership, 2026-11-03 stablecoin "
    "mainnet launch, 2026-11-02 $50M government grant. === WORKBOOK === "
    "7 WATCH entries at capacity; one entry (hbar) was added this "
    "session with a placeholder invalidation. Evaluate the setup and "
    "act according to protocol (workbook hygiene and exposure "
    "verification as usual; orders are disabled in this session)."
)


def _run_blueprint_suite(
    blueprint: dict,
    goal: str,
    max_turns: int,
    provider_filter: list[str] | None,
    label: str,
) -> None:
    from ainara.bureau.server import run_agent_in_process

    proc = _ensure_orakle()
    try:
        caps = _fetch_capabilities()
        blueprint = dict(blueprint)
        if provider_filter:
            blueprint["llm_providers"] = provider_filter
        q = Queue()
        logger.info("Running %s blueprint with providers: %s",
                    label, blueprint.get("llm_providers", "(default)"))
        run_agent_in_process(
            llm_config=_llm_config(
                (blueprint.get("llm_providers") or [None])[0]
            ),
            orakle_servers=[ORAKLE_URL],
            blueprint=blueprint,
            user_context={"language": "en"},
            goal=goal,
            max_turns=max_turns,
            result_queue=q,
            global_capabilities=caps,
        )
        result = q.get(timeout=10)
        print("\n" + "=" * 70)
        print(f"LIVE {label.upper()} REPRO (read-only skills)")
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
            print("\n  >> Agent DID use skills this time.")
    finally:
        if proc:
            proc.terminate()


def suite_news(provider_filter: list[str] | None) -> None:
    _run_blueprint_suite(
        NEWS_BLUEPRINT, NEWS_GOAL, 10, provider_filter, "news-step")


def suite_entry(provider_filter: list[str] | None) -> None:
    _run_blueprint_suite(
        ENTRY_BLUEPRINT, ENTRY_GOAL, 12, provider_filter, "entry-step")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("suite", choices=["menu", "fabrication", "news", "entry", "all"])
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
    if args.suite in ("entry", "all"):
        suite_entry(args.provider)


if __name__ == "__main__":
    main()
