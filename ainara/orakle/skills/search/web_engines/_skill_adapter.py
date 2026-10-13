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

"""Adapter exposing descriptor-carrying skills as search engines.

This is the integration surface of the engine-provider seam (#22): a
skill — core, user or curated optional — declares a
``search_engine_descriptor`` class attribute and SearchWeb wraps its
``run()`` with :class:`SkillEngineAdapter` so it joins the meta-search
pool like any built-in engine. No framework-internal imports are needed
by contributed skills.

The module name is prefixed with an underscore on purpose:
``discover_engines()`` skips it — adapters are built on demand by
SearchWeb, never discovered from the filesystem.
"""

import asyncio
import inspect
import logging
from typing import Any, Dict, List

from .base import SearchEngineBase, SearchResult

logger = logging.getLogger(__name__)


class SkillEngineAdapter(SearchEngineBase):
    """Wrap a skill declaring ``search_engine_descriptor`` as an engine.

    Contract for the wrapped skill (standard structured-return
    conventions):

    - ``run()`` must accept ``query`` and ``num_results`` keyword
      arguments (unknown extra kwargs should be tolerated via
      ``**kwargs``); it may be async or sync.
    - It returns ``{"success": bool, "results": [...]}`` where each
      result is a dict with ``title`` (required), ``url`` or ``link``
      (required), ``snippet``, and optionally ``published_date``,
      ``relevance_score`` and ``metadata`` (engine-defined structured
      fields, kept opaque by consumers).
    - The descriptor drives pool behavior:

          {
              "specialties": ["jobs"],       # required, non-empty
              "participation": "specialty",  # "specialty" (default) | "weighted"
              "weight": {"jobs": 1.0},       # optional, per search type
          }

    Failures degrade silently (logged, empty result list), matching how
    built-in engines behave inside the meta-search.
    """

    def __init__(
        self,
        skill: Any,
        descriptor: Dict[str, Any],
        engine_name: str,
        timeout: float = 15.0,
    ):
        specialties = descriptor.get("specialties") or []
        if not specialties:
            raise ValueError(
                f"search_engine_descriptor of '{engine_name}' must declare a"
                " non-empty 'specialties' list"
            )
        self.skill = skill
        self.descriptor = descriptor
        self.engine_name = engine_name
        self.timeout = timeout
        self._specialties = list(specialties)
        participation = descriptor.get("participation", "specialty")
        if participation not in ("specialty", "weighted"):
            logger.warning(
                f"Contributed engine '{engine_name}' declares unknown"
                f" participation '{participation}'; using 'specialty'"
            )
            participation = "specialty"
        self.PARTICIPATION = participation
        self._weights = dict(descriptor.get("weight", {}))

    @property
    def is_available(self) -> bool:
        # Discovery already gated the skill's instantiation; whether the
        # contributed engine joins the pool is an opt-in decision taken by
        # SearchWeb.register_engine_providers()
        return True

    def get_search_type_specialties(self) -> List[str]:
        return list(self._specialties)

    def get_default_weight(self, search_type: str = "comprehensive") -> float:
        return self._weights.get(search_type, 0.25)

    async def search(
        self, query: str, num_results: int = 5, **kwargs
    ) -> List[SearchResult]:
        try:
            if inspect.iscoroutinefunction(self.skill.run):
                payload = await asyncio.wait_for(
                    self.skill.run(
                        query=query, num_results=num_results, **kwargs
                    ),
                    timeout=self.timeout,
                )
            else:
                # Sync skills run in a thread so the event loop is not
                # blocked; wait_for still bounds total latency (the worker
                # thread itself may linger, which is logged on timeout)
                loop = asyncio.get_running_loop()
                payload = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: self.skill.run(
                            query=query, num_results=num_results, **kwargs
                        ),
                    ),
                    timeout=self.timeout,
                )
        except asyncio.TimeoutError:
            logger.error(
                f"Contributed engine '{self.engine_name}' timed out after"
                f" {self.timeout}s; degrading silently"
            )
            return []
        except Exception as e:
            logger.error(
                f"Contributed engine '{self.engine_name}' failed: {e}"
            )
            return []

        return self._parse_results(payload)

    def _parse_results(self, payload: Any) -> List[SearchResult]:
        if not isinstance(payload, dict):
            logger.error(
                f"Contributed engine '{self.engine_name}' returned a"
                f" non-dict payload ({type(payload).__name__})"
            )
            return []

        if payload.get("success") is False:
            logger.error(
                f"Contributed engine '{self.engine_name}' reported failure:"
                f" {payload.get('error') or payload.get('message')}"
            )
            return []

        raw_results = payload.get("results") or []
        results: List[SearchResult] = []
        for i, item in enumerate(raw_results):
            if not isinstance(item, dict):
                logger.debug(
                    f"Contributed engine '{self.engine_name}': skipping"
                    f" non-dict result #{i}"
                )
                continue
            title = item.get("title")
            link = item.get("url") or item.get("link")
            if not title or not link:
                logger.debug(
                    f"Contributed engine '{self.engine_name}': result #{i}"
                    " missing 'title' or 'url'/'link', skipping"
                )
                continue

            result = SearchResult(
                title=title,
                link=link,
                snippet=item.get("snippet", ""),
                provider=self.engine_name,
            )
            result.source_engine = self.engine_name
            result.published_date = item.get("published_date")
            score = item.get("relevance_score")
            if score is not None:
                try:
                    result.relevance_score = float(score)
                except (TypeError, ValueError):
                    pass
            metadata = item.get("metadata")
            if isinstance(metadata, dict):
                result.metadata = dict(metadata)
            results.append(result)

        return results
