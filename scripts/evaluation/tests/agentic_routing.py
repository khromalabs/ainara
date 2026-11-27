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

"""
Adversarial routing pairs for the system-skills tier
(docs/architecture/orakle-routing.md).

Verifies the capability-first, agent-last rule: a skill whose card
declares compound scope absorbs a compound request directly (one
execution, one unified result), while requests spanning multiple
capabilities — or compound requests to skills WITHOUT compound scope —
delegate to the agentic process. The retired-behavior fix (multiple
independent interpretations per turn) must not regress.

Candidate blocks are rendered through format_skill_block from the real
capability payload wherever possible, so the eval can never drift from
what the production selection prompt shows.
"""

from ainara.framework.orakle_middleware import format_skill_block
from ainara.orakle.skills.memory.deep_recall import MemoryDeepRecall

from .base import TestCase, TestSuite

# The real Deep Recall core skill, payload built through the same
# mechanical channel the Orakle capabilities endpoint uses.
from ainara.framework.capabilities.skills import introspect_run

DEEP_RECALL_BLOCK = format_skill_block({
    "name": "memory_deep_recall",
    "description": MemoryDeepRecall.__doc__,
    "full_description": MemoryDeepRecall.__doc__,
    "matcher_info": MemoryDeepRecall.matcher_info,
    "run_info": introspect_run(MemoryDeepRecall, "memory_deep_recall"),
    "compound_scope": True,
})

# Faithful stand-in payload rendered through the same mechanical
# channel as the real cards (the Orakle-registered skills are not
# reachable in-process from the evaluation harness).
SEARCH_WEB_BLOCK = format_skill_block({
    "name": "search_web",
    "description": "Web search",
    "full_description": (
        "Search the internet for information about any topic, product,"
        " news, current events, or factual questions using multiple"
        " search providers."
    ),
    "matcher_info": (
        "The user asks for web/world information: news, products, facts,"
        " current events, anything answered from the internet. NOT for"
        " the user's own past conversations or memories."
    ),
    "run_info": {
        "parameters": {
            "query": {
                "type": "string",
                "required": True,
                "description": "The search query",
            },
        },
    },
})

MESSAGING_BLOCK = format_skill_block({
    "name": "messaging.inbox",
    "description": "Messaging",
    "full_description": (
        "Unified messaging management for reading and sending messages"
        " across platforms (Email, Discord, Telegram, etc.)."
    ),
    "matcher_info": (
        "Use this skill to manage communications: check for new messages"
        " across connected platforms and send messages to recipients."
    ),
    "run_info": {
        "parameters": {
            "action": {
                "type": "string",
                "required": True,
                "description": (
                    "The action to perform: 'check' to read messages,"
                    " 'send' to send a message"
                ),
            },
            "target": {
                "type": "string",
                "required": False,
                "description": "Recipient identifier (required for 'send')",
            },
        },
    },
})

WEATHER_BLOCK = format_skill_block({
    "name": "time.weather",
    "description": "Weather",
    "full_description": "Get weather information for a location.",
    "matcher_info": (
        "The user asks about current or forecast weather conditions for"
        " a place."
    ),
    "run_info": {
        "parameters": {
            "location": {
                "type": "string",
                "required": True,
                "description": "The location to get weather for",
            },
        },
    },
})

DEEP_RECALL_DIGEST_MOCK = {
    "success": True,
    "digest": (
        "Recorded history:\n- msg_001: We agreed the Vega project ships"
        " in November.\n- msg_002: The March trip is booked for the 14th."
        "\n\nKnown gaps: none"
    ),
    "turns": 3,
}

DEEP_RECALL_MATCHER_SKILL = {
    "name": "memory_deep_recall",
    "description": MemoryDeepRecall.__doc__ or "Deliberate recall of the user's own past.",
    "parameters": [
        {
            "name": "timeframe",
            "type": "array",
            "required": False,
            "description": (
                "Approximate period(s) the recalled events happened, as"
                " the user stated them"
            ),
        },
    ],
}

SEARCH_WEB_MATCHER_SKILL = {
    "name": "search_web",
    "description": (
        "Search the internet for information about any topic, product,"
        " news, current events, or factual questions using multiple"
        " search providers."
    ),
    "parameters": [
        {
            "name": "query",
            "type": "string",
            "required": True,
            "description": "The search query",
        },
    ],
}

WEATHER_MATCHER_SKILL = {
    "name": "time.weather",
    "description": "Get weather information for a location.",
    "parameters": [
        {
            "name": "location",
            "type": "string",
            "required": True,
            "description": "The location to get weather for",
        },
    ],
}


class AgenticRoutingTestSuite(TestSuite):
    """
    System-skills tier routing: compound-scope absorption vs agentic
    delegation, and matcher top_k survival for compound recall.
    """

    def __init__(self):
        name = "agentic_routing"
        description = (
            "Capability-first, agent-last routing: skills with declared"
            " compound scope take compound requests directly; everything"
            " else spanning capabilities delegates to the agent"
        )

        test_cases = [
            # 1. Recall-only compound request -> the compound-scope skill
            # takes it directly. The template's compound rule must beat
            # the old "compound ALWAYS -> agent" reflex.
            TestCase(
                test_id="compound_recall_direct",
                description=(
                    "Recall-only compound request absorbed by deep_recall"
                    " in a single execution"
                ),
                input_query=(
                    "remember what we said about the Vega project last"
                    " week and also about the trip in March"
                ),
                expected_skill_id="memory_deep_recall",
                expected_parameters={
                    "timeframe": ["last week", "in March"],
                },
                expected_requires_agent=False,
                mock_skill_execution_result=DEEP_RECALL_DIGEST_MOCK,
                expected_interpretation_keywords=[
                    "Vega",
                    "March",
                    "trip",
                ],
                candidate_skills_info=(
                    DEEP_RECALL_BLOCK + "---\n\n" + SEARCH_WEB_BLOCK
                ),
                metadata={"tier": "encapsulated_compound"},
            ),
            # 2. Recall + action -> spans capabilities -> agent. The
            # compound-scope card is present and must NOT absorb it:
            # email delivery is outside its contract.
            TestCase(
                test_id="recall_then_action_delegates",
                description=(
                    "Recall plus an external action spans capabilities:"
                    " delegate to the agent"
                ),
                input_query=(
                    "check what we agreed with Pablo about the budget,"
                    " then email it to him"
                ),
                expected_skill_id="",
                expected_parameters={},
                expected_requires_agent=True,
                mock_skill_execution_result="",
                expected_interpretation_keywords=[],
                candidate_skills_info=(
                    DEEP_RECALL_BLOCK + "---\n\n" + MESSAGING_BLOCK
                ),
                metadata={"tier": "agent_delegation"},
            ),
            # 3. Two web questions in one turn -> agent. search_web has
            # no compound scope; absorbing would resurrect the split
            # interpretation the agentic loop fixed (retired behavior).
            TestCase(
                test_id="two_web_questions_delegates",
                description=(
                    "Two independent web questions in one turn: agent"
                    " (search_web has no compound scope)"
                ),
                input_query=(
                    "search for reviews of the Pixel 10, and also look up"
                    " when the Nintendo Switch 2 launches"
                ),
                expected_skill_id="",
                expected_parameters={},
                expected_requires_agent=True,
                mock_skill_execution_result="",
                expected_interpretation_keywords=[],
                candidate_skills_info=(
                    SEARCH_WEB_BLOCK + "---\n\n" + DEEP_RECALL_BLOCK
                ),
                metadata={"tier": "agent_delegation"},
            ),
            # 4. Single recall -> direct skill, still the plain path.
            TestCase(
                test_id="single_recall_direct",
                description="Single-topic recall goes straight to deep_recall",
                input_query=(
                    "what did we decide about the trip last week?"
                ),
                expected_skill_id="memory_deep_recall",
                expected_parameters={"timeframe": ["last week"]},
                expected_requires_agent=False,
                mock_skill_execution_result=DEEP_RECALL_DIGEST_MOCK,
                expected_interpretation_keywords=[
                    "trip",
                    "decided",
                ],
                candidate_skills_info=(
                    DEEP_RECALL_BLOCK + "---\n\n" + SEARCH_WEB_BLOCK
                ),
                metadata={"tier": "encapsulated_single"},
            ),
            # 5. Matcher top_k survival: a compound recall phrasing must
            # still rank deep_recall into the candidate set ahead of
            # web search (recall vs web is the dangerous confusion).
            TestCase(
                test_id="compound_recall_matcher_survival",
                description=(
                    "Matcher ranks deep_recall into top_k for a compound"
                    " recall phrasing despite web-search distractors"
                ),
                input_query=(
                    "remember what we said about the Vega project last"
                    " month and the trip in March"
                ),
                expected_skill_id="memory_deep_recall",
                expected_parameters={},
                mock_skill_execution_result=DEEP_RECALL_DIGEST_MOCK,
                expected_interpretation_keywords=[
                    "Vega",
                    "March",
                ],
                run_matcher=True,
                available_skills=[
                    DEEP_RECALL_MATCHER_SKILL,
                    SEARCH_WEB_MATCHER_SKILL,
                    WEATHER_MATCHER_SKILL,
                ],
                metadata={"tier": "matcher_survival"},
            ),
            # 6. Multi-facet research question (the 2026-11-26 session
            # failure shape): several distinct sub-questions bundled
            # into one web-search phrasing. search_web has no compound
            # scope and returns per-query raw results — the findings
            # need gathering and combining -> agent, even though the
            # query names a single mechanism.
            TestCase(
                test_id="multifacet_research_delegates",
                description=(
                    "Multi-facet research request phrased as one search:"
                    " delegate to the agent"
                ),
                input_query=(
                    "search the web for statistics and studies on"
                    " co-parenting conflict in Spain, including shared"
                    " custody rates, and specifically how children with"
                    " autism affect post-separation conflict"
                ),
                expected_skill_id="",
                expected_parameters={},
                expected_requires_agent=True,
                mock_skill_execution_result="",
                expected_interpretation_keywords=[],
                candidate_skills_info=SEARCH_WEB_BLOCK,
                metadata={"tier": "agent_delegation"},
            ),
        ]

        super().__init__(name, description, test_cases)
