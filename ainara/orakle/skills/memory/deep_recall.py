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
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.

"""Deep Recall: deliberative recall over the user's own past.

A thin Orakle core skill over the PyBridge REST endpoint that owns the
DeepRecallEngine and both corpora (GREEN memories + chat logs). The
skill carries no recall logic: it forwards the query and returns the
engine's cited digest as the reserved ``analysis`` field, which the
conversational delivery persists as a mechanical trail record and the
interpretation pass words into speech (recall-specific contract:
``framework.deep_recall.interpretation``). Capability id:
``memory_deep_recall`` (namespace-path derivation:
``memory/deep_recall.py`` → class ``MemoryDeepRecall``).
"""

import asyncio
import logging
import os
from typing import Annotated, Any, Dict, List, Optional, Union

import requests

from ainara.framework.skill import Skill

logger = logging.getLogger(__name__)

# PyBridge is a fixed-local-port service (scripts/services.py parity).
# No config key by design: infrastructure endpoints are framework
# facts, not user or model choices. The env override exists for
# non-default deployments; if ports ever become dynamic, the spawner
# (the component that knows the port) exports it.
PYBRIDGE_URL = os.environ.get(
    "AINARA_PYBRIDGE_URL", "http://127.0.0.1:8101"
)
# An investigation is a bounded multi-turn LLM loop
# (deep_recall.max_turns, default 8) over local corpora: generous but
# finite, so a hung PyBridge never wedges the turn forever.
REQUEST_TIMEOUT = 600


class MemoryDeepRecall(Skill):
    """Deliberate recall of the user's own past: their memories and
    conversation records. DECISION RULE — judge by SOURCE, not by
    TOPIC: when a request is phrased as recall of what the user said,
    decided, planned or experienced before ('recall everything about
    X', 'remember when', 'do you recall'), select this capability
    regardless of subject matter. Topics that sound
    like web material (crypto tokens, migrations, prices, news) are
    still recall requests when the requested source is the user's own
    recorded history; answering them with a web search is wrong. Use
    also to check the recorded history before stating anything about
    past events. NOT for general knowledge, encyclopedic or world
    facts, or current/real-time information.
    """

    # Tier contract (see docs/architecture/orakle-routing.md): the
    # investigation internally decomposes multi-part requests — several
    # topics, people or periods at once ("what did we say about X last
    # week and Y in March") — and returns ONE cited digest covering all
    # parts; interpretation happens once, whole, never per-part.
    compound_scope = True

    # Conversational delivery contract: the digest must be worded
    # under recall-specific rules (never invent past events, gaps stay
    # gaps, citations never spoken) — not the generic interpretation.
    interpretation_template = "framework.deep_recall.interpretation"

    matcher_info = (
        "The user asks to recall, remember, revisit or reconstruct"
        " something from their OWN past: what they said or decided"
        " before, previous conversations, shared history, personal"
        " events, plans made earlier, 'what did we say/talk about',"
        " 'remember when', 'do you recall'. Recall requests may"
        " concern any topic, even web-flavored ones (tokens, migrations, prices, news):"
        " the deciding signal is the SOURCE — the user's own recorded"
        " past — not the subject matter. Also for compound recall"
        " requests bundling several past topics or periods at once"
        " ('what did we say about X last week and Y in March'): one"
        " investigation covers all parts. Also for checking the"
        " recorded history before stating anything about past"
        " events. NOT for general knowledge, encyclopedic or"
        " historical facts about the world, web search, or"
        " current/real-time information."
    )

    async def run(
        self,
        query: Annotated[
            str,
            "The recall topic: the events, people or period to"
            " reconstruct from the recorded history. For compound"
            " requests pass every part in the same query — one"
            " investigation covers all of them.",
        ],
        timeframe: Annotated[
            Optional[Union[str, List[str]]],
            "Approximate period(s) the recalled events happened, as"
            " the user stated them (e.g. 'a few days ago', or a list"
            " like ['last week', 'in March']). One entry per stated"
            " period. Optional; scopes the history search and cuts"
            " investigation time.",
        ] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"query": query}
        if timeframe:
            payload["timeframe"] = timeframe
        try:
            response = await asyncio.to_thread(
                requests.post,
                f"{PYBRIDGE_URL}/framework/deep_recall",
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as e:
            logger.error(f"DEEP_RECALL skill: PyBridge unreachable: {e}")
            return {
                "success": False,
                "result": (
                    "Deep Recall is unreachable right now (the memory"
                    " service did not answer)."
                ),
            }
        if response.status_code == 400:
            detail = response.json().get("result", "invalid request")
            return {"success": False, "result": detail}
        if response.status_code != 200:
            logger.error(
                "DEEP_RECALL skill: PyBridge returned %s: %s",
                response.status_code,
                response.text[:300],
            )
            return {
                "success": False,
                "result": (
                    "The recall investigation could not be completed."
                ),
            }
        data = response.json()
        if not data.get("success"):
            # Fail to silence: the interpretation contract's no-digest
            # branch carries the honest failure; the mechanical string
            # here is only the model-channel error fact.
            return {
                "success": False,
                "result": data.get("result", "investigation failed"),
            }
        # The digest rides the reserved model-channel field: it never
        # reaches render/history as raw payload; conversational
        # delivery persists it as a mechanical trail record and words
        # it into speech via the declared interpretation contract.
        result: Dict[str, Any] = {
            "success": True,
            "analysis": data.get("digest", ""),
        }
        if data.get("turns") is not None:
            result["turns"] = data["turns"]
        return result
