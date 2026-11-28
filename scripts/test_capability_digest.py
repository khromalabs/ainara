"""Component tests for the capability digest (framework/capability_digest.py).

Uses a stub LLM and the live Orakle payload if the server is reachable,
otherwise a synthetic payload; validation-gate tests always run on the
synthetic payload so results are server-independent. Run:

    python scripts/test_capability_digest.py
"""

import json
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ainara.framework.capability_digest import (  # noqa: E402
    build_capability_digest,
    payload_hash,
    _parse_entries,
    _validate_entries,
)

ORAKLE_URL = "http://localhost:8100/capabilities?type=llm"

SYNTHETIC_PAYLOAD = {
    "search_web": {
        "description": "Search the internet for information about any topic,"
        " product, news, current events, or factual questions using multiple"
        " search providers.",
        "run_info": {
            "parameters": {
                "query": {"type": "string", "required": True,
                          "description": "Search web query string"},
                "search_type": {
                    "type": "one of: 'comprehensive', 'academic', 'recent',"
                    " 'exploratory', 'news', 'crypto', 'jobs'",
                    "required": False,
                    "description": "Type of search to perform",
                },
                "recency": {
                    "type": "string or list of strings",
                    "required": False,
                    "description": "Filter results by recency (e.g. '24h',"
                    " '7d', '1w').",
                },
            }
        },
    },
    "memory_deep_recall": {
        "description": "Deliberate recall of the user's own past: their"
        " memories and conversation records.",
        "run_info": {"parameters": {}},
    },
    "tools_calculator": {
        "description": "Evaluation of non-trivial mathematical expressions",
        "run_info": {"parameters": {}},
    },
}


def load_capabilities():
    """Processed capability list from the live server or the synthetic one."""
    try:
        with urllib.request.urlopen(ORAKLE_URL, timeout=5) as resp:
            raw = json.load(resp)
        print("[load] live Orakle payload")
    except Exception as exc:
        print(f"[load] live server unreachable ({exc}); synthetic payload")
        raw = SYNTHETIC_PAYLOAD
    return process_payload(raw)


def process_payload(raw):
    capabilities = []
    for name, info in raw.items():
        params = []
        for pname, pinfo in (
            (info.get("run_info") or {}).get("parameters") or {}
        ).items():
            params.append(
                {
                    "name": pname,
                    "type": pinfo.get("type", ""),
                    "description": pinfo.get("description", ""),
                }
            )
        capabilities.append(
            {"name": name, "description": info.get("description", ""),
             "parameters": params}
        )
    return capabilities


class StubLLM:
    """Minimal LLM stand-in returning canned compiler responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def chat(self, chat_history=None, stream=False):
        self.calls += 1
        return self.responses.pop(0) if self.responses else ""


def json_response(entries):
    return "```json\n" + json.dumps(entries) + "\n```"


def covering_response(capabilities):
    """Valid compiler response covering every capability of the payload.

    Entry text carries the fixed option lists verbatim where present, so
    the closed-list rendering can be asserted on any payload.
    """
    entries = []
    for i, cap in enumerate(capabilities):
        fixed = [
            f"{p['name']}: "
            + "|".join(
                v
                for v in [
                    s.strip("'\" ")
                    for s in str(p.get("type", "")).split("of:")[-1].split(",")
                ]
                if v
            )
            for p in cap["parameters"]
            if "one of:" in str(p.get("type", "")).lower()
        ]
        text = f"perform ability {i} via the matching backend"
        if fixed:
            text += " — fixed options: " + "; ".join(fixed)
        entries.append({"text": text, "covers": [cap["name"]]})
    return entries


def main():
    failures = []
    capabilities = load_capabilities()

    # --- 1. payload hash: stable, and sensitive to wording changes ---
    h1 = payload_hash(capabilities)
    h2 = payload_hash(capabilities)
    if h1 != h2:
        failures.append("payload_hash is not stable")
    tweaked = [dict(c) for c in capabilities]
    tweaked[0] = dict(tweaked[0], description=tweaked[0]["description"] + " x")
    if payload_hash(tweaked) == h1:
        failures.append("payload_hash ignores description changes")
    print(f"[ok] payload hash stable: {h1[:12]}")

    # --- 2. mechanical fallback: closed lists, cached ---
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp) / "capability_digest.json"
        digest = build_capability_digest(capabilities, None, cache_path=cache)
        if "..." in digest or "…" in digest:
            failures.append("mechanical menu contains an ellipsis")
        if not cache.exists():
            failures.append("mechanical menu did not persist cache")
        print(f"[ok] mechanical fallback rendered "
              f"{len(digest.splitlines()) - 1} entries")

    # --- 3. LLM compilation happy path (any payload size) ---
    syn_caps = process_payload(SYNTHETIC_PAYLOAD)
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp) / "capability_digest.json"
        stub = StubLLM([json_response(covering_response(syn_caps))])
        digest = build_capability_digest(
            syn_caps, stub, cache_path=cache
        )
        if any(c["name"] in digest for c in syn_caps):
            failures.append("compiled digest leaks capability ids")
        if ("comprehensive|academic|recent|exploratory|news|crypto|jobs"
                not in digest):
            failures.append("fixed option list not rendered complete")
        if "..." in digest or "…" in digest:
            failures.append("compiled digest contains an ellipsis")
        if stub.calls != 1:
            failures.append(f"expected 1 LLM call, got {stub.calls}")
        # --- 4. cache hit: same payload, no further LLM calls ---
        stub2 = StubLLM([])
        digest2 = build_capability_digest(
            syn_caps, stub2, cache_path=cache
        )
        if digest2 != digest:
            failures.append("cached digest differs from generated one")
        if stub2.calls != 0:
            failures.append("cache hit still invoked the LLM")
        print("[ok] LLM compilation, validation and hash-gated cache")

    # --- 5. validation gates reject breaches (synthetic payload) ---
    all_covered = [
        {"text": f"ability {i}", "covers": [c["name"]]}
        for i, c in enumerate(syn_caps)
    ]
    bad_cases = {
        "ellipsis": [{"text": "search the web (types: news|crypto|...)",
                      "covers": ["search_web"]}],
        "id leak": all_covered[:1] + [
            {"text": "use search_web for internet queries",
             "covers": ["search_web"]}],
        "mechanism talk": all_covered[:1] + [
            {"text": "call the search_web tool",
             "covers": ["search_web"]}],
        "incomplete coverage": [{"text": "search the web",
                                 "covers": ["search_web"]}],
    }
    for label, entries in bad_cases.items():
        if _validate_entries(entries, syn_caps) is not None:
            failures.append(f"validation gate accepted a '{label}' breach")
    if _parse_entries("garbage without json") is not None:
        failures.append("parser accepted non-JSON response")
    print("[ok] validation gates reject ellipsis/id-leak/mechanism/coverage")

    # --- 6. LLM failure twice → mechanical fallback, no crash ---
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp) / "capability_digest.json"
        stub = StubLLM(["not json at all", json_response(
            [{"text": "partial", "covers": ["search_web"]}])])
        digest = build_capability_digest(
            capabilities, stub, cache_path=cache
        )
        if stub.calls != 2:
            failures.append(f"expected 2 LLM attempts, got {stub.calls}")
        if "Through ORAKLE" not in digest:
            failures.append("fallback digest missing header")
        print("[ok] compiler failure falls back to mechanical projection")

    print()
    if failures:
        print("FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
