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

"""Stubs for offline dry runs and harness validation.

StubLLM replays canned responses keyed by a substring of the user
message; StubMatcher does naive keyword matching over registered
descriptions. Neither touches a model download, the network, or the
ainara package -- they exist so the entire harness pipeline can be
validated end-to-end without any backend, and so the benchmark's own
plumbing has an executable specification.
"""

import re
from typing import Any, Dict, List, Optional


class StubLLM:
    """Duck-typed LLM: replays canned responses.

    ``responses`` maps a regex matched against the (system+user) text
    to a response string; first match wins, checked in insertion order.
    Falls back to ``default``.
    """

    def __init__(self, responses: Optional[List[Dict[str, str]]] = None,
                 default: str = "{}", model_tag: str = "stub",
                 match_user_only: bool = False):
        self.rules = [
            (re.compile(pattern, re.IGNORECASE | re.DOTALL), response)
            for pattern, response in (responses or [])
        ]
        self.default = default
        self.model_tag = model_tag
        self.match_user_only = match_user_only

    def prepare_chat(self, system_message: str, new_message: str) -> Dict:
        return {"system": system_message, "user": new_message}

    def chat(self, chat_history: Dict, stream: bool = False) -> str:
        if self.match_user_only:
            blob = chat_history["user"]
        else:
            blob = chat_history["system"] + "\n" + chat_history["user"]
        for pattern, response in self.rules:
            if pattern.search(blob):
                return response
        return self.default


class StubMatcher:
    """Naive keyword-overlap matcher (OrakleMatcherBase-compatible).

    Scores = fraction of query keywords found in the skill description;
    deterministic and offline.
    """

    def __init__(self):
        self.skills_registry: Dict[str, Dict[str, Any]] = {}

    def register_skill(self, skill_id, description, metadata=None):
        self.skills_registry[skill_id] = {
            "description": description,
            "metadata": metadata or {},
        }

    def match(self, query, threshold=0.05, top_k=6) -> List[Dict]:
        query_words = set(re.findall(r"\w+", query.lower()))
        scored = []
        for skill_id, info in self.skills_registry.items():
            words = set(re.findall(r"\w+", info["description"].lower()))
            if not words:
                continue
            overlap = len(query_words & words) / len(query_words)
            if overlap >= threshold:
                scored.append({"skill_id": skill_id, "score": overlap})
        scored.sort(key=lambda m: -m["score"])
        return scored[:top_k]
