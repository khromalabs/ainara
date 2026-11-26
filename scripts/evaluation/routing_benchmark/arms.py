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

"""Evaluation arms: how a query travels from user to capability.

FlatArm   - the common approach: FULL capability schemas in the context
            window every turn; the model selects natively (JSON out).
OrakleArm - two-stage: the assistant emits an <orakle> intent tag
            (trigger), an embedding matcher narrows the registry
            (retrieval), and a selector model fills skill + parameters
            from a constrained candidate prompt. Assistant and selector
            may be DIFFERENT models (split-brain) and the selector is a
            stateless specialist: its prompt is mechanical per query,
            so provider failover is invisible to the warming cache.

LLM backends are duck-typed (ainara.framework.llm.LLMBackend or any
object exposing prepare_chat/chat, or a plain callable); they are always
injected, which keeps the harness importable offline with stubs.
"""

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from .enumerations import EnumBlock
from .metrics import RunRecord, expected_rank, now, parameter_score
from .mock_executor import execute_stub
from .payload import Capability

logger = logging.getLogger(__name__)


# --- LLM plumbing -----------------------------------------------------

def complete(llm: Any, system: str, user: str) -> Tuple[str, float]:
    """One completion through a duck-typed backend. Returns (text, secs).

    Supports LLMBackend-style objects (prepare_chat + chat) and plain
    callables (system, user) -> str, e.g. stubs.
    """
    start = now()
    if hasattr(llm, "prepare_chat") and hasattr(llm, "chat"):
        chat_history = llm.prepare_chat(
            system_message=system, new_message=user
        )
        result = llm.chat(chat_history=chat_history, stream=False)
        text = result[0] if isinstance(result, tuple) else result
    elif callable(llm):
        text = llm(system, user)
    else:
        raise TypeError(f"unsupported LLM backend type: {type(llm)!r}")
    return str(text), now() - start


def parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Extract the first JSON object from a response (tolerant)."""
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def parse_orakle_tags(text: str) -> List[str]:
    """Extract intent queries from <orakle> tags in a streamed reply.

    Handles the simple form (<orakle>intent</orakle>) and the data form
    (<orakle query="intent">payload</orakle>), case-insensitive. The
    data attribute carries the action intent; the tag content is the
    data acted upon and is NOT part of the matching intent.
    """
    pattern = re.compile(
        r"<orakle(?:\s+query=\"([^\"]*)\")?\s*>(.*?)</orakle>",
        re.IGNORECASE | re.DOTALL,
    )
    intents = []
    for attr_intent, content in pattern.findall(text):
        intent = attr_intent.strip() or content.strip()
        if intent:
            intents.append(intent)
    return intents


# --- Prompt builders ---------------------------------------------------

ORAKLE_POLICY = """You combine built-in knowledge with real-world
interaction capabilities through the ORAKLE system: state your intent
in plain English inside ORAKLE tags and the underlying system handles
all function-calling mechanics, parameter mapping and execution.

The query must be in English.

## ORAKLE SYNTAX
Simple form: <orakle>full query in natural language</orakle>
Data form (large payload to act upon):
<orakle query="action intent in natural language">data payload</orakle>

# NOTE: deliberately condensed benchmark stand-in, NOT the production
# prompt. The canonical contract lives in
# ainara/templates/framework.orakle.syntax.mu (shared partial included
# by the chat_manager and agent system prompts); keep this block in
# sync with it when the contract changes.

## POLICY
1. ALWAYS use ORAKLE for real-time data, real-world actions, or when
   in doubt about data freshness. Never answer such requests from
   memory.
2. Do not mention tools, APIs or skills; do not comment on execution.
3. Use built-in knowledge only for general knowledge that cannot be
   stale.
4. Split complex multi-step requests into separate ORAKLE commands.

{enumeration_intro}"""


def build_orakle_system_prompt(enum_block: EnumBlock) -> str:
    if enum_block.level == "ids":
        intro = (
            "Your available ORAKLE capabilities are: "
            + enum_block.text
        )
    elif enum_block.level == "none":
        intro = enum_block.text
    else:
        intro = enum_block.text
    return ORAKLE_POLICY.format(enumeration_intro=intro)


def render_flat_schemas(registry: Dict[str, Capability]) -> str:
    """Mechanical full-schema enumeration for the flat arm."""
    blocks = []
    for cap_id in sorted(registry.keys()):
        cap = registry[cap_id]
        lines = [f"## Skill: {cap_id}", f"Description: {cap.description}"]
        if cap.parameters:
            lines.append("Parameters:")
            for p in cap.parameters:
                req = "Required" if p.required else "Optional"
                default = (
                    f", default: {p.default}" if p.default is not None
                    else ""
                )
                lines.append(
                    f"- {p.name} ({p.type}, {req}{default}): "
                    f"{p.description}"
                )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


FLAT_CONTRACT = """You can invoke the skills listed above. Reply with a
single JSON object and nothing else:
{"skill_id": "<skill id>", "parameters": {...}}
Use {"skill_id": null} when no skill applies and the request must be
answered from your own knowledge."""


def build_flat_system_prompt(registry: Dict[str, Capability]) -> str:
    return (
        "You are a helpful AI assistant with access to the following "
        "skills.\n\n" + render_flat_schemas(registry)
        + "\n\n" + FLAT_CONTRACT
    )


# --- Arms ---------------------------------------------------------------

class Arm(ABC):
    """Base class. run() returns a fully attributed RunRecord."""

    def __init__(
        self,
        name: str,
        assistant_llm: Any,
        selector_llm: Any = None,
        registry: Optional[Dict[str, Capability]] = None,
    ):
        self.name = name
        self.assistant_llm = assistant_llm
        # Split-brain default: selector falls back to the assistant
        # model when not explicitly provided.
        self.selector_llm = selector_llm or assistant_llm
        self.registry = registry or {}

    @abstractmethod
    def run(self, case) -> RunRecord:
        ...


class FlatArm(Arm):
    """Flat enumeration: full schemas in context every turn."""

    def __init__(self, **kwargs):
        super().__init__(name="flat", **kwargs)

    def run(self, case) -> RunRecord:
        record = RunRecord(
            case_id=case.id,
            category=case.category,
            delicacy=case.delicacy,
            arm=self.name,
            enumeration="flat_schemas",
            assistant_model=getattr(self.assistant_llm, "model_tag", "?"),
            selector_model=getattr(self.selector_llm, "model_tag", "?"),
            n_registry=len(self.registry),
            query=case.query,
            expected_skill_id=case.expected_skill_id,
            expected_params=case.expected_params,
        )

        system = build_flat_system_prompt(self.registry)
        record.context_chars = len(system)
        response, latency = complete(self.assistant_llm, system, case.query)
        record.latencies["assistant"] = latency
        record.latencies["total"] = latency
        record.trigger = {
            "emitted": False,
            "raw": response[:2000],
        }

        data = parse_json_object(response)
        if not data:
            record.errors.append("unparseable flat-arm response")
            record.classification = _final_classify(case, record)
            return record

        selected = data.get("skill_id")
        record.selection = {
            "selected_skill_id": selected,
            "parameters": data.get("parameters", {}),
            "raw": response[:2000],
        }
        if selected is not None:
            record.trigger["emitted"] = True
        score = None
        if selected == case.expected_skill_id and selected in self.registry:
            score = parameter_score(
                data.get("parameters", {}), case.expected_params
            )
            execute_stub(self.registry[selected], data.get("parameters", {}))
        record.parameter_score = score
        record.classification = _final_classify(case, record)
        return record


class OrakleArm(Arm):
    """Two-stage: trigger -> retrieval -> constrained selection.

    matcher: object exposing match(query, threshold, top_k) -> list of
    {"skill_id", "score"} dicts (OrakleMatcherTransformers-compatible).
    Injected so offline dry runs can use a stub.
    """

    def __init__(self, matcher: Any, top_k: int = 6, **kwargs):
        super().__init__(name="orakle", **kwargs)
        self.matcher = matcher
        self.top_k = top_k
        self.threshold = 0.05

    def run(self, case) -> RunRecord:
        record = RunRecord(
            case_id=case.id,
            category=case.category,
            delicacy=case.delicacy,
            arm=self.name,
            enumeration=self._enumeration_label,
            assistant_model=getattr(self.assistant_llm, "model_tag", "?"),
            selector_model=getattr(self.selector_llm, "model_tag", "?"),
            n_registry=len(self.registry),
            query=case.query,
            expected_skill_id=case.expected_skill_id,
            expected_params=case.expected_params,
        )
        total_start = now()

        # Stage 1: trigger (assistant model).
        system = build_orakle_system_prompt(self.enum_block)
        record.context_chars = len(system)
        response, latency = complete(self.assistant_llm, system, case.query)
        record.latencies["assistant"] = latency
        intents = parse_orakle_tags(response)
        record.trigger = {
            "emitted": bool(intents),
            "intents": intents,
            "raw": response[:2000],
        }
        if not intents:
            # No delegation: the model answered from its own knowledge.
            # For trap cases this is the critical silent failure.
            record.latencies["total"] = now() - total_start
            record.classification = _final_classify(case, record)
            return record

        # Stage 2: retrieval (embedding matcher, over the FIRST intent).
        intent = intents[0]
        matches, latency = self._retrieve(intent)
        record.latencies["retrieval"] = latency
        record.retrieval = {
            "intent": intent,
            "candidates": [
                {"skill_id": m["skill_id"], "score": m.get("score")}
                for m in matches
            ],
            "expected_rank": (
                expected_rank(matches, case.expected_skill_id)
                if case.expected_skill_id
                else None
            ),
        }
        if not matches:
            record.selection = {"selected_skill_id": None}
            record.latencies["total"] = now() - total_start
            record.classification = _final_classify(case, record)
            return record

        # Stage 3: constrained selection (selector model).
        candidates_block = render_candidates(matches, self.registry)
        selection_response, latency = self._select(intent, candidates_block)
        record.latencies["selection"] = latency
        data = parse_json_object(selection_response)
        if not data:
            record.errors.append("unparseable selection response")
            record.selection = {"raw": selection_response[:2000]}
            record.latencies["total"] = now() - total_start
            record.classification = _final_classify(case, record)
            return record

        selected = data.get("skill_id")
        params = data.get("parameters", {}) or {}
        record.selection = {
            "selected_skill_id": selected,
            "parameters": params,
            "raw": selection_response[:2000],
        }
        score = None
        if (
            selected
            and selected == case.expected_skill_id
            and selected in self.registry
        ):
            score = parameter_score(params, case.expected_params)
            execute_stub(self.registry[selected], params)
        record.parameter_score = score
        record.latencies["total"] = now() - total_start
        record.classification = _final_classify(case, record)
        return record

    # -- configuration hooks -------------------------------------------

    def set_enumeration(self, enum_block: EnumBlock) -> None:
        self.enum_block = enum_block
        self._enumeration_label = enum_block.level

    def _retrieve(self, intent: str) -> Tuple[List[Dict], float]:
        start = now()
        matches = self.matcher.match(
            intent, threshold=self.threshold, top_k=self.top_k
        )
        return matches, now() - start

    def _select(self, intent: str, candidates_block: str) -> Tuple[str, float]:
        # This rendering mirrors the real selection contract; the
        # canonical template lives in
        # ainara/templates/framework.chat_manager.orakle_select_and_params.mu
        system = (
            "You are a skill selection engine. Given a natural language "
            "query and candidate skills with their parameter contracts, "
            "select the best skill and fill its parameters. Reply with a "
            "single JSON object: {\"skill_id\": \"...\", "
            "\"parameters\": {...}}. If no candidate fits, reply "
            "{\"skill_id\": null, \"parameters\": {}}."
        )
        user = f"Query: {intent}\n\nCandidate skills:\n{candidates_block}"
        return complete(self.selector_llm, system, user)


def render_candidates(
    matches: List[Dict], registry: Dict[str, Capability]
) -> str:
    """Format the candidate block for the selection prompt."""
    blocks = []
    for i, match in enumerate(matches, 1):
        cap = registry.get(match["skill_id"])
        if cap is None:
            continue
        lines = [f"## Skill {i}: {cap.id}", f"Description: {cap.description}"]
        if cap.parameters:
            lines.append("Parameters:")
            for p in cap.parameters:
                req = "Required" if p.required else "Optional"
                lines.append(
                    f"- {p.name} ({p.type}, {req}): {p.description}"
                )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _final_classify(case, record: RunRecord) -> str:
    from .metrics import classify

    record_dict = {
        "expected_skill_id": record.expected_skill_id,
        "emitted": record.trigger.get("emitted", False),
        "candidates": record.retrieval.get("candidates"),
        "retrieval_ran": bool(record.retrieval),
        "selected_skill_id": record.selection.get("selected_skill_id"),
        "parameter_score": record.parameter_score,
    }
    return classify(case.category, record_dict)
