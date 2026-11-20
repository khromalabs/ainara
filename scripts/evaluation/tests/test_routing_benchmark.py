# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
#
# This file is dual-licensed under:
# 1. GNU Lesser General Public License v3.0 (LGPL-3.0)
#    (See the included LICENSE_LGPL3.txt file or look into
#    <https://www.gnu.org/licenses/lgpl-3.0.html for details)
# 2. Commercial license
#    (Contact: rgomez@khromalabs.org for licensing options)
#
# You may use, distribute and modify this code under the terms of either license.
# This notice must be preserved in all copies or substantial portions of the code.

"""Offline tests for the routing benchmark harness.

No LLM, no network, no model download: payload extraction, dataset
validation, enumeration rendering, warming verification, trigger
parsing, mock execution, classification and a full end-to-end dry run
with stubs.
"""

import json
import os
import sys

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
))

from scripts.evaluation.routing_benchmark import dataset as ds  # noqa: E402
from scripts.evaluation.routing_benchmark import (  # noqa: E402
    enumerations as en,
)
from scripts.evaluation.routing_benchmark.arms import (  # noqa: E402
    FlatArm,
    OrakleArm,
    build_orakle_system_prompt,
    parse_orakle_tags,
    render_flat_schemas,
)
from scripts.evaluation.routing_benchmark.dataset import (  # noqa: E402
    QueryCase,
    synthesize_distractors,
)
from scripts.evaluation.routing_benchmark.metrics import (  # noqa: E402
    aggregate,
    classify,
    parameter_score,
)
from scripts.evaluation.routing_benchmark.mock_executor import (  # noqa: E402
    execute_stub,
    validate_selection,
)
from scripts.evaluation.routing_benchmark.payload import (  # noqa: E402
    fingerprint,
    lean_from_llm_payload,
)
from scripts.evaluation.routing_benchmark.stubs import (  # noqa: E402
    StubLLM,
    StubMatcher,
)

FIXTURE_RAW = {
    "tools_calculator": {
        "description": "Evaluation of mathematical expressions",
        "matcher_info": "DO NOT use for anything else. Keywords: math.",
        "run_info": {
            "parameters": {
                "expression": {
                    "type": "string",
                    "description": "The expression",
                    "required": True,
                }
            }
        },
    },
    "system_clipboard": {
        "description": "Read and write the system clipboard",
        "matcher_info": "Keywords: clipboard.",
        "run_info": {
            "parameters": {
                "action": {
                    "type": "one of: 'read', 'write', 'clear'",
                    "description": "Operation",
                    "required": True,
                },
                "text": {
                    "type": "string",
                    "description": "Text to write",
                    "required": False,
                },
            }
        },
    },
}


def _registry():
    return lean_from_llm_payload(FIXTURE_RAW)


# --- payload -----------------------------------------------------------

def test_lean_extraction_drops_matcher_info():
    reg = _registry()
    assert set(reg.keys()) == {"tools_calculator", "system_clipboard"}
    assert reg["tools_calculator"].description.startswith("Evaluation")
    # matcher_info never survives into the lean view
    assert all("DO NOT" not in c.description for c in reg.values())


def test_fingerprint_is_content_stable():
    reg = _registry()
    fp1 = fingerprint(reg)
    fp2 = fingerprint({k: reg[k] for k in reversed(list(reg.keys()))})
    assert fp1 == fp2
    reg2 = lean_from_llm_payload(FIXTURE_RAW)
    reg2["tools_calculator"].description = "changed"
    assert fingerprint(reg) != fingerprint(reg2)


def test_parameter_contract_extraction():
    cap = _registry()["system_clipboard"]
    names = {p.name for p in cap.parameters}
    assert names == {"action", "text"}
    action = next(p for p in cap.parameters if p.name == "action")
    assert action.required and "one of" in action.type


# --- dataset -----------------------------------------------------------

def test_seed_dataset_loads_and_validates():
    path = _seed_path()
    cases = ds.load_dataset(path)
    categories = {c.category for c in cases}
    assert {"route", "abstain", "trap"} <= categories
    assert any(c.delicacy == "delicate" for c in cases)
    reg = _registry()
    # seed references real skills beyond the tiny fixture: expect
    # warnings, not crashes
    warnings = ds.validate_against_registry(cases, reg)
    assert warnings


def test_dataset_validation_rejects_bad_cases():
    try:
        ds._validate_case(
            QueryCase(id="x", category="route", query="q"), "t", 1
        )
        assert False, "route without expected_skill_id must fail"
    except ValueError:
        pass
    try:
        ds._validate_case(
            QueryCase(id="x", category="abstain", query="q",
                      expected_skill_id="a"), "t", 1
        )
        assert False, "abstain with expected_skill_id must fail"
    except ValueError:
        pass


def test_distractors_are_confusable_and_unique():
    d = synthesize_distractors(40, seed=1)
    assert len(d) == 40
    assert all(cid.startswith("distractor_") for cid in d)


# --- enumerations ------------------------------------------------------

def test_render_ids_and_domains_and_none():
    reg = _registry()
    ids = en.render_ids(reg)
    assert "tools_calculator" in ids.text
    dom = en.render_domains(reg)
    assert "tools_calculator" not in dom.text  # no ids revealed
    assert "clipboard" in dom.text  # verb phrase carries permission
    assert len(dom.text) < len(render_flat_schemas(reg))
    none_block = en.render_none()
    assert "clip" not in none_block.text.lower()


def test_domain_of_conventions():
    assert en.domain_of("system_clipboard") == "system"
    assert en.domain_of("user_crypto_eventscanner") == "crypto"
    assert en.domain_of(
        "khromalabs_ataria_crypto_analysis"
    ) == "crypto"


def test_warm_renderer_happy_path(tmp_path=None):
    reg = _registry()
    renderer = en.WarmedRenderer(reg, cache_dir=None)

    def good_summarize(warming_input):
        assert "tools_calculator" in warming_input
        assert "DO NOT" not in warming_input  # matcher_info excluded
        return {"domains": [
            {"name": "tools", "actions": "evaluate expressions",
             "capability_ids": ["tools_calculator"]},
            {"name": "system", "actions": "clipboard control",
             "capability_ids": ["system_clipboard"]},
        ]}

    block = renderer.render("stub-model", good_summarize)
    assert block.level == "warmed"
    assert "clipboard control" in block.text


def test_warm_renderer_rejects_hallucination():
    reg = _registry()
    renderer = en.WarmedRenderer(reg, cache_dir=None)

    def hallucinating_summarize(warming_input):
        return {"domains": [
            {"name": "fake", "actions": "invented capability",
             "capability_ids": ["fake_skill_xyz"]},
            {"name": "partial", "actions": "partial coverage",
             "capability_ids": ["tools_calculator"]},
        ]}

    block = renderer.render("stub-model", hallucinating_summarize)
    # graceful fallback to ids with the problems recorded
    assert block.level == "ids"
    assert block.metadata.get("warmed_fallback")


def test_warm_cache_roundtrip():
    reg = _registry()
    import tempfile

    cache_dir = tempfile.mkdtemp(prefix="warm_cache_test_")
    renderer = en.WarmedRenderer(reg, cache_dir=cache_dir)
    calls = {"n": 0}

    def summarize(warming_input):
        calls["n"] += 1
        return {"domains": [
            {"name": "all", "actions": "everything",
             "capability_ids": sorted(reg.keys())},
        ]}

    renderer.render("m", summarize)
    renderer.render("m", summarize)
    assert calls["n"] == 1, "second render must be served from cache"


# --- trigger parsing -----------------------------------------------------

def test_parse_orakle_tags():
    text = "Sure.\n<orakle>get weather in Paris</orakle>\nDone."
    assert parse_orakle_tags(text) == ["get weather in Paris"]
    text = '<orakle query="save this">large payload</orakle>'
    assert parse_orakle_tags(text) == ["save this"]
    assert parse_orakle_tags("<ORAKLE>UPPER</ORAKLE>") == ["UPPER"]
    assert parse_orakle_tags("<orakle></orakle>") == []
    assert parse_orakle_tags("no tags here") == []
    assert parse_orakle_tags("<orakle>unclosed") == []


def test_orakle_system_prompt_includes_enumeration():
    reg = _registry()
    prompt = build_orakle_system_prompt(en.render_ids(reg))
    assert "tools_calculator" in prompt
    assert "<orakle>" in prompt
    prompt = build_orakle_system_prompt(en.render_none())
    assert "tools_calculator" not in prompt


# --- mock executor -------------------------------------------------------

def test_validate_selection():
    cap = _registry()["system_clipboard"]
    # missing required parameter
    ok, problems = validate_selection(cap, {"text": "hello"})
    assert not ok and any("action" in p for p in problems)
    ok, problems = validate_selection(
        cap, {"action": "write", "text": "hello"}
    )
    assert ok and not problems
    ok, problems = validate_selection(
        cap, {"action": "destroy", "text": "x"}
    )
    assert not ok and any("allowed values" in p for p in problems)
    ok, problems = validate_selection(cap, {"bogus": 1})
    assert not ok and any("bogus" in p for p in problems)


def test_execute_stub_never_executes():
    cap = _registry()["system_clipboard"]
    result = execute_stub(cap, {"action": "write", "text": "hi"})
    assert result["success"] and result["result"] == {"mock": True}
    # no side effects anywhere: the stub result IS the record


# --- metrics / classification ---------------------------------------------

def test_parameter_score():
    assert parameter_score({}, {}) == 1.0
    assert parameter_score({"a": "x"}, {"a": "X"}) == 1.0
    assert parameter_score({"a": "xx y"}, {"a": "y"}) == 0.5
    assert parameter_score({"b": "x"}, {"a": "x"}) == 0.0
    assert parameter_score({}, {"a": "x"}) == 0.0


def test_classification_matrix():
    base = {
        "expected_skill_id": "s1",
        "emitted": True,
        "candidates": [{"skill_id": "s1"}, {"skill_id": "s2"}],
        "selected_skill_id": "s1",
        "parameter_score": 1.0,
    }
    assert classify("route", dict(base)) == "correct"
    trap = dict(base, emitted=False, selected_skill_id=None)
    assert classify("trap", trap) == "silent_memory_answer"
    retr = dict(
        base, candidates=[{"skill_id": "s2"}], selected_skill_id="s2"
    )
    assert classify("route", retr) == "retrieval_miss"
    sel = dict(base, selected_skill_id="s2")
    assert classify("route", sel) == "selection_miss"
    params = dict(base, parameter_score=0.5)
    assert classify("route", params) == "param_partial"
    assert classify("abstain", dict(base)) == "abstain_false_positive"
    assert classify(
        "abstain",
        {"emitted": False, "selected_skill_id": None},
    ) == "abstain_correct"


# --- end-to-end dry run ------------------------------------------------------

def _seed_path():
    return os.path.join(
        os.path.dirname(__file__), "..", "routing_benchmark",
        "datasets", "seed.jsonl",
    )


def _seed_cases():
    return ds.load_dataset(_seed_path())


def _small_registry():
    reg = _registry()
    reg.update(synthesize_distractors(8, seed=3))
    return reg


def test_flat_arm_end_to_end():
    cases = _seed_cases()
    registry = _small_registry()
    llm = StubLLM(
        responses=[(
            r"\{",
            json.dumps({
                "skill_id": "tools_calculator",
                "parameters": {"expression": "25 * 13 + 7"},
            }),
        )],
        default=json.dumps({"skill_id": None}),
        model_tag="stub",
    )
    arm = FlatArm(assistant_llm=llm, registry=registry)
    records = [arm.run(c) for c in cases]
    assert len(records) == len(cases)
    assert all(r.context_chars > 0 for r in records)
    assert any(
        r.classification == "correct"
        for r in records
        if r.case_id == "calc_simple"
    )
    summary = aggregate(records)
    assert summary["overall"]["n"] == len(cases)


def test_orakle_arm_end_to_end_split_brain():
    cases = _seed_cases()
    registry = _small_registry()
    matcher = StubMatcher()
    for cap_id, cap in registry.items():
        matcher.register_skill(cap_id, cap.description)

    assistant = StubLLM(
        responses=[(
            r"weather|news|clipboard|file|browser|launch|portfolio|"
            r"mercadona|calculate|fetch|price|cart|latest|advancements",
            "<orakle>intent for stub</orakle>",
        )],
        default="From my own knowledge: it depends.",
        model_tag="stub-assistant",
        match_user_only=True,
    )
    selector = StubLLM(
        responses=[(
            r"\{",
            json.dumps({
                "skill_id": "tools_calculator",
                "parameters": {"expression": "stub"},
            }),
        )],
        default=json.dumps({"skill_id": None}),
        model_tag="stub-selector",
    )
    arm = OrakleArm(
        matcher=matcher, assistant_llm=assistant,
        selector_llm=selector, registry=registry,
    )
    arm.set_enumeration(en.render_ids(registry))
    records = [arm.run(c) for c in cases]
    assert len(records) == len(cases)
    # split-brain is visible in every record
    assert all(
        r.assistant_model == "stub-assistant"
        and r.selector_model == "stub-selector"
        for r in records
    )
    # stage attribution: triggered records carry candidates + rank
    triggered = [r for r in records if r.trigger["emitted"]]
    assert triggered
    assert all(
        "expected_rank" in r.retrieval for r in triggered
    )
    # silent-memory records: the stub abstains (no regex hit) only on
    # knowledge questions, which are abstain cases -> classified
    # abstain_correct. Silent-memory on route cases is covered by
    # test_orakle_arm_silent_memory_answer below.
    abstain_correct = [
        r for r in records
        if r.classification == "abstain_correct"
        and r.category == "abstain"
    ]
    assert abstain_correct
    summary = aggregate(records)
    assert summary["overall"]["silent_memory_rate"] is not None


def test_orakle_arm_silent_memory_answer():
    """A route case the assistant answers from memory = critical failure."""
    case = QueryCase(
        id="route_no_trigger",
        category="route",
        query="What is the current price of AAPL?",
        expected_skill_id="finance_stocks",
        expected_params={"symbol": "AAPL"},
    )
    registry = _small_registry()
    matcher = StubMatcher()
    for cap_id, cap in registry.items():
        matcher.register_skill(cap_id, cap.description)
    assistant = StubLLM(
        default="AAPL is around 150 dollars, I believe.",
        model_tag="stub-assistant",
    )
    selector = StubLLM(default=json.dumps({"skill_id": None}))
    arm = OrakleArm(
        matcher=matcher, assistant_llm=assistant,
        selector_llm=selector, registry=registry,
    )
    arm.set_enumeration(en.render_ids(registry))
    record = arm.run(case)
    assert record.classification == "silent_memory_answer"
    assert not record.trigger["emitted"]


def test_orakle_arm_retrieval_miss_is_attributed():
    cases = [QueryCase(
        id="route_impossible",
        category="route",
        query="something no stub keyword matches at all qxyzzy",
        expected_skill_id="tools_calculator",
        expected_params={},
    )]
    registry = _small_registry()
    matcher = StubMatcher()
    for cap_id, cap in registry.items():
        matcher.register_skill(cap_id, cap.description)
    assistant = StubLLM(
        responses=[(r"qxyzzy", "<orakle>qxyzzy</orakle>")],
        default="nope",
    )
    selector = StubLLM(default=json.dumps({"skill_id": None}))
    arm = OrakleArm(
        matcher=matcher, assistant_llm=assistant,
        selector_llm=selector, registry=registry,
    )
    arm.set_enumeration(en.render_ids(registry))
    record = arm.run(cases[0])
    # candidates exist but never contain the expected skill: the
    # guaranteed-failure mode flat arms cannot exhibit
    assert record.classification == "retrieval_miss"
    assert record.retrieval["expected_rank"] is None
