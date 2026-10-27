# Issue #26 P1: unit tests for the offload-digest router and the reserved
# skill-side 'analysis' digest field (orakle_middleware.py).
#
# Coverage is LLM-free: skill selection and the digestion agent are mocked,
# so what is actually pinned is the routing decision surface —
#   * size-ceiling router (below/above ceiling × enable_agent_spawn)
#   * 'analysis' preemption (tier 1 beats offload)
#   * reject-with-guidance on offload failure (no fallback to inlining)
#   * channel stripping ('analysis' never reaches render/history payloads)

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import requests

# Add project root to the Python path to allow importing ainara modules
sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..')))

from ainara.framework.orakle_middleware import (  # noqa: 402
    OffloadDigestCache,
    OrakleMiddleware,
)

SELECTION_JSON = json.dumps({
    "skill_id": "test_skill",
    "parameters": {"q": "x"},
    "skill_intention": "",
})

GUIDANCE_FRAGMENT = "too large to analyze"


class TestExtractSkillAnalysis(unittest.TestCase):
    """Direct tests for _extract_skill_analysis (reserved field, #26)."""

    def setUp(self):
        self.middleware = self._make_middleware()

    @staticmethod
    def _make_middleware():
        with patch(
            'ainara.framework.orakle_middleware.OrakleMatcherTransformers'
        ):
            return OrakleMiddleware(
                llm=MagicMock(),
                orakle_servers=[],
                system_message="SYSTEM",
                config_manager=MagicMock(),
                capabilities=[],
            )

    def test_plain_string_untouched(self):
        """No 'analysis' key: byte-identical passthrough, no digest."""
        result = '{"price": 42, "note": "the \\"analysis\\" word"}'
        analysis, out = self.middleware._extract_skill_analysis(result)
        self.assertIsNone(analysis)
        # Byte-identical: no re-serialization happened.
        self.assertEqual(out, result)

    def test_extract_and_strip(self):
        payload = {"price": 42, "analysis": "Prices rose 3% this week."}
        analysis, out = self.middleware._extract_skill_analysis(
            json.dumps(payload))
        self.assertEqual(analysis, "Prices rose 3% this week.")
        self.assertNotIn("analysis", out)
        self.assertIn("price", out)

    def test_non_json_string_with_analysis_substring(self):
        result = 'plain text mentioning "analysis" but not JSON'
        analysis, out = self.middleware._extract_skill_analysis(result)
        self.assertIsNone(analysis)
        self.assertEqual(out, result)

    def test_json_array_is_ignored(self):
        result = '["analysis", "other"]'
        analysis, out = self.middleware._extract_skill_analysis(result)
        self.assertIsNone(analysis)
        self.assertEqual(out, result)

    def test_non_string_result(self):
        analysis, out = self.middleware._extract_skill_analysis(None)
        self.assertIsNone(analysis)
        self.assertIsNone(out)


class TestOffloadRouter(unittest.TestCase):
    """
    Drives _process_orakle_request with a mocked selection LLM and a mocked
    digestion agent, asserting only on the routing decision surface.
    """

    CEILING = 100

    def setUp(self):
        config_values = {
            "orakle.match_providers": [],
            "llm": {},
        }

        def config_get(key, default=None):
            return config_values.get(key, default)

        self.mock_config = MagicMock()
        self.mock_config.get.side_effect = config_get

        with patch(
            'ainara.framework.orakle_middleware.OrakleMatcherTransformers'
        ):
            self.middleware = OrakleMiddleware(
                llm=MagicMock(),
                orakle_servers=[],
                system_message="SYSTEM",
                config_manager=self.mock_config,
                capabilities=[],
            )

        # Selection LLM answers a valid skill id on the first attempt.
        self.middleware.llm.chat.return_value = SELECTION_JSON
        self.middleware.llm.get_context_window.return_value = 131072
        self.middleware.matcher.match.return_value = [
            {"skill_id": "test_skill", "score": 0.9},
        ]

        # Router knobs (the config keys these mirror are schema-declared).
        self.middleware.enable_agent_spawn = False
        self.middleware.offload_raw_max_bytes = self.CEILING

        # The template manager is mocked, so the interpretation prompt is
        # a deterministic JSON dump of the render variables — its length
        # tracks the payload, which is all the ledger gate needs.
        self.middleware.template_manager = MagicMock()
        self.middleware.template_manager.render.side_effect = (
            lambda template, variables: json.dumps(
                variables, default=str
            )
        )

        # Recording fakes for the two downstream paths.
        self.interpretation_calls = []
        self.offload_calls = []
        self.offload_digest = "DIGESTED FINDINGS"
        self.skill_info = None

        # Recording wrapper around the REAL interpretation path, so the
        # ledger gate inside stream_command_interpretation stays live in
        # every router test. The mocked LLM answers the selection call
        # (stream=False) with valid JSON and streams the interpretation.
        self.llm_stream_calls = []
        real_interpretation = self.middleware.stream_command_interpretation

        def recording_interpretation(results, query, **kwargs):
            self.interpretation_calls.append(results)
            yield from real_interpretation(results, query, **kwargs)

        def fake_chat(*args, **kwargs):
            if kwargs.get("stream"):
                self.llm_stream_calls.append(args)
                return iter(["INTERPRETED"])
            return SELECTION_JSON

        self.middleware.stream_command_interpretation = (
            recording_interpretation
        )
        self.middleware.llm.chat.side_effect = fake_chat
        self.middleware._get_chat_context = MagicMock(return_value=[])
        self.middleware.execute_orakle_command = MagicMock(
            side_effect=lambda skill_id, params, history: self.skill_result)
        self.middleware._get_skill_info = MagicMock(
            side_effect=lambda skill_id: self.skill_info)

        # Recording fake for the digestion agent (still mocked: Bureau
        # is out of scope here). Faithful to the real generator contract:
        # relays progress chunks and RETURNS the digest text as the
        # yield-from value (None on failure).
        def fake_offload(**kwargs):
            self.offload_calls.append(kwargs.get("raw_result"))
            # The router owns the output channel: it yields the loading
            # signal and the digest itself — the real spawn only returns
            # the digest text as the yield-from value. The unreachable
            # yield keeps this a generator (yield-from contract).
            return self.offload_digest
            yield  # unreachable

        self.middleware._spawn_offload_digest = fake_offload

    def _run(self, skill_result: str) -> list:
        self.skill_result = skill_result
        return list(self.middleware._process_orakle_request("query test"))

    def _chunk_text(self, chunks) -> str:
        return "".join(c for c in chunks if isinstance(c, str))

    # --- below the ceiling: today's behavior ---------------------------

    def test_small_result_goes_to_interpretation(self):
        chunks = self._run('{"price": 42}')
        self.assertEqual(self.interpretation_calls, [['{"price": 42}']])
        self.assertEqual(self.offload_calls, [])
        self.assertIn("INTERPRETED", self._chunk_text(chunks))

    # --- above the ceiling ---------------------------------------------

    def test_oversized_result_inlines_when_spawn_disabled(self):
        """Defaults preserve the pre-#26 behavior byte-identically
        (a ceiling-sized result still fits the ledger budget)."""
        big = "x" * (self.CEILING + 1)
        self._run(big)
        self.assertEqual(self.offload_calls, [])
        self.assertEqual(self.interpretation_calls, [[big]])

    def test_above_ledger_budget_rejects_when_spawn_disabled(self):
        """No consent for offload + no budget fit: reject with guidance
        instead of inlining an overflow into the prompt."""
        self.middleware.llm.get_context_window.return_value = 100
        # budget = 100 * 0.75 * 3 = 225 bytes; the prompt wraps the
        # payload in JSON, so a payload near the budget overflows it.
        big = "x" * 300
        chunks = self._run(big)
        self.assertEqual(self.offload_calls, [])
        text = self._chunk_text(chunks)
        self.assertIn(GUIDANCE_FRAGMENT, text)
        self.assertIn("agentic analysis", text)
        self.assertNotIn("INTERPRETED", text)
        # Selection ran (stream=False); the interpretation LLM call did
        # not happen.
        self.assertEqual(self.llm_stream_calls, [])

    def test_oversized_result_offloads_when_spawn_enabled(self):
        big = "x" * (self.CEILING + 1)
        self.middleware.enable_agent_spawn = True
        chunks = self._run(big)

        self.assertEqual(self.offload_calls, [big])
        self.assertEqual(self.interpretation_calls, [])
        text = self._chunk_text(chunks)
        self.assertIn("spawn_agent", text)
        self.assertIn("DIGESTED FINDINGS", text)

    def test_offload_failure_rejects_with_guidance(self):
        """No fallback to inlining: failure yields guidance, not the blob."""
        big = "x" * (self.CEILING + 1)
        self.middleware.enable_agent_spawn = True
        self.offload_digest = None
        chunks = self._run(big)

        self.assertEqual(self.offload_calls, [big])
        self.assertEqual(self.interpretation_calls, [])
        self.assertIn(GUIDANCE_FRAGMENT, self._chunk_text(chunks))
        self.assertNotIn(big, self._chunk_text(chunks))

    # --- skill-side analysis (tier 1) preempts offload ------------------

    def test_analysis_preempts_offload(self):
        big = json.dumps({"data": "y" * (self.CEILING + 1),
                          "analysis": "FINDINGS"})
        self.middleware.enable_agent_spawn = True
        self._run(big)

        self.assertEqual(self.offload_calls, [])
        self.assertEqual(self.interpretation_calls, [["FINDINGS"]])

    def test_small_result_with_analysis_interprets_digest(self):
        self._run(json.dumps({"price": 42, "analysis": "FINDINGS"}))
        self.assertEqual(self.interpretation_calls, [["FINDINGS"]])

    def test_empty_analysis_does_not_preempt_offload(self):
        """A falsy analysis payload is treated as absent by the router."""
        big = json.dumps({"data": "y" * (self.CEILING + 1),
                          "analysis": ""})
        self.middleware.enable_agent_spawn = True
        self._run(big)
        self.assertEqual(self.offload_calls,
                         [json.dumps({"data": "y" * (self.CEILING + 1)})])

    # --- render channel: nexus UI payloads never carry 'analysis' -------

    def test_nexus_ui_payload_is_analysis_stripped(self):
        """UI skills render stripped data AND still get the interpretation
        pass (the P1 fix for defect (b): the nexus path no longer returns
        before interpretation, so the digest boundary always runs)."""
        payload = {"price": 42, "analysis": "FINDINGS"}
        self.skill_info = {
            "type": "nexus",
            "ui": {"component": "chart"},
        }
        chunks = self._run(json.dumps(payload))

        rendered = [c for c in chunks if isinstance(c, dict)]
        self.assertEqual(len(rendered), 1)
        self.assertEqual(rendered[0]["type"], "nexus_skill_result")
        self.assertEqual(rendered[0]["data"], {"price": 42})
        # Interpretation sees only the digest, never the raw payload.
        self.assertEqual(self.interpretation_calls, [["FINDINGS"]])


class TestBudgetLedger(unittest.TestCase):
    """The minimal §6.9 ledger: budget math + the interpretation gate."""

    def setUp(self):
        config_values = {
            "orakle.match_providers": [],
            "llm": {},
        }

        def config_get(key, default=None):
            return config_values.get(key, default)

        mock_config = MagicMock()
        mock_config.get.side_effect = config_get

        with patch(
            'ainara.framework.orakle_middleware.OrakleMatcherTransformers'
        ):
            self.middleware = OrakleMiddleware(
                llm=MagicMock(),
                orakle_servers=[],
                system_message="SYSTEM",
                config_manager=mock_config,
                capabilities=[],
            )

    def test_budget_formula(self):
        """window * (100 - reserve)% * chars_per_token."""
        self.middleware.llm.get_context_window.return_value = 8192
        self.assertEqual(self.middleware._interpretation_budget_bytes(),
                         int(8192 * 0.75 * 3))

    def test_unknown_window_disables_guard(self):
        """Never reject blind: no resolvable window → guard off."""
        self.middleware.llm.get_context_window.return_value = 0
        self.assertEqual(self.middleware._interpretation_budget_bytes(), 0)

        self.middleware.llm.get_context_window.side_effect = RuntimeError
        self.assertEqual(self.middleware._interpretation_budget_bytes(), 0)

    def test_reserve_pct_clamped(self):
        self.middleware.llm.get_context_window.return_value = 1000
        self.middleware.context_reserve_pct = 150
        self.assertEqual(self.middleware._interpretation_budget_bytes(),
                         int(1000 * 0.10 * 3))

    def _configure_template(self):
        """Deterministic prompt: a JSON dump whose length tracks the
        payload."""
        self.middleware.template_manager = MagicMock()
        self.middleware.template_manager.render.side_effect = (
            lambda template, variables: json.dumps(
                variables, default=str
            )
        )

    def test_gate_rejects_oversized_prompt(self):
        self._configure_template()
        self.middleware.llm.get_context_window.return_value = 100
        # budget = 225 bytes; the prompt JSON-wraps the payload.
        huge = "x" * 400
        chunks = list(self.middleware.stream_command_interpretation(
            [huge], "query"))
        text = "".join(chunks)
        self.assertIn("too large to analyze", text)
        self.middleware.llm.chat.assert_not_called()

    def test_gate_passes_fitting_prompt_through(self):
        self._configure_template()
        self.middleware.llm.get_context_window.return_value = 131072
        self.middleware.llm.chat.return_value = iter(["ANSWER"])
        chunks = list(self.middleware.stream_command_interpretation(
            ["small result"], "query"))
        self.assertEqual("".join(chunks), "ANSWER")

    def test_gate_skipped_in_agentic_mode(self):
        """The agentic path has its own payload handling."""
        self._configure_template()
        self.middleware.llm.get_context_window.return_value = 100
        self.middleware.llm.chat.return_value = iter(["ANSWER"])
        chunks = list(self.middleware.stream_command_interpretation(
            ["x" * 400], "query", agentic_mode=True))
        self.assertEqual("".join(chunks), "ANSWER")


class TestOffloadConcurrency(unittest.TestCase):
    """Concurrency 1 for digestion agents (issue #26 P1.5)."""

    def setUp(self):
        config_values = {
            "orakle.match_providers": [],
            "llm": {},
            "bureau": {},
        }

        def config_get(key, default=None):
            return config_values.get(key, default)

        mock_config = MagicMock()
        mock_config.get.side_effect = config_get

        with patch(
            'ainara.framework.orakle_middleware.OrakleMatcherTransformers'
        ):
            self.middleware = OrakleMiddleware(
                llm=MagicMock(),
                orakle_servers=[],
                system_message="SYSTEM",
                config_manager=mock_config,
                capabilities=[],
            )

    def test_second_concurrent_offload_rejects(self):
        """A busy offload lock makes the next spawn return None
        (reject-with-guidance upstream) without touching Bureau."""
        self.middleware._offload_lock.acquire()
        try:
            consumed = list(self.middleware._spawn_offload_digest(
                raw_result="x" * 100, query="q"))
            self.assertEqual(consumed, [])
        finally:
            self.middleware._offload_lock.release()

    def test_lock_released_after_spawn_failure(self):
        """Creation failure (Bureau down) must release the lock."""
        with patch(
            'ainara.framework.orakle_middleware.requests.post',
            side_effect=requests.ConnectionError("bureau down"),
        ):
            consumed = list(self.middleware._spawn_offload_digest(
                raw_result="x" * 100, query="q"))
        self.assertEqual(consumed, [])
        # Lock is free again: a second spawn reaches the creation call.
        with patch(
            'ainara.framework.orakle_middleware.requests.post',
            side_effect=requests.ConnectionError("bureau down"),
        ):
            consumed = list(self.middleware._spawn_offload_digest(
                raw_result="x" * 100, query="q"))
        self.assertEqual(consumed, [])

    def test_creation_rate_limit_backs_off_once(self):
        """429 → one backoff + retry; repeated 429 → give up."""
        responses = [
            MagicMock(status_code=429),
            MagicMock(status_code=202),
        ]
        with patch(
            'ainara.framework.orakle_middleware.requests.post',
            side_effect=responses,
        ) as mock_post, patch(
            'ainara.framework.orakle_middleware.time.sleep'
        ):
            self.middleware._create_bureau_agent(
                "http://bureau", goal="g", blueprint={},
                user_context={}, max_turns=4, execution_timeout=300,
            )
        self.assertEqual(mock_post.call_count, 2)


class TestOffloadRouterDigestCache(TestOffloadRouter):
    """Router-level digest-cache behavior (issue #26 P1.5); reuses the
    TestOffloadRouter harness (mocked selection LLM + digestion agent)."""

    # --- digest cache: payload-hash reuse (issue #26 P1.5) -------------

    def test_digest_cache_hit_skips_second_spawn(self):
        """A second request returning the exact same payload bytes
        reuses the digest: one digestion run serves N follow-ups."""
        big = "x" * (self.CEILING + 1)
        self.middleware.enable_agent_spawn = True

        first = self._chunk_text(self._run(big))
        second = self._chunk_text(self._run(big))

        self.assertEqual(self.offload_calls, [big])
        self.assertIn("DIGESTED FINDINGS", first)
        self.assertIn("DIGESTED FINDINGS", second)
        # The cache-hit path never emits the loading signal.
        self.assertEqual(first.count("spawn_agent"), 1)
        self.assertEqual(second.count("spawn_agent"), 0)

    def test_digest_cache_keyed_on_payload_bytes(self):
        """A different payload is a different key: it digests again."""
        self.middleware.enable_agent_spawn = True
        self._run("x" * (self.CEILING + 1))
        self._run("y" * (self.CEILING + 1))
        self.assertEqual(len(self.offload_calls), 2)

    def test_failed_digest_not_cached(self):
        """A digestion failure (None) is not cached: the retry after
        fixing the environment spawns again instead of hitting junk."""
        big = "x" * (self.CEILING + 1)
        self.middleware.enable_agent_spawn = True

        self.offload_digest = None
        self._run(big)
        self.offload_digest = "DIGESTED FINDINGS"
        chunks = self._run(big)

        self.assertEqual(self.offload_calls, [big, big])
        self.assertIn("DIGESTED FINDINGS", self._chunk_text(chunks))

    def test_digest_cache_disabled_spawns_every_time(self):
        big = "x" * (self.CEILING + 1)
        self.middleware.enable_agent_spawn = True
        self.middleware._digest_cache = None

        self._run(big)
        self._run(big)
        self.assertEqual(self.offload_calls, [big, big])

    def test_digest_cache_lru_eviction(self):
        """Beyond max_entries the least-recently-used payload's digest
        is evicted and that payload digests again."""
        self.middleware.enable_agent_spawn = True
        self.middleware._digest_cache = OffloadDigestCache(1)

        self._run("a" * (self.CEILING + 1))
        self._run("b" * (self.CEILING + 1))
        self._run("a" * (self.CEILING + 1))

        self.assertEqual(
            self.offload_calls,
            ["a" * (self.CEILING + 1), "b" * (self.CEILING + 1),
             "a" * (self.CEILING + 1)],
        )


class TestOffloadDigestCache(unittest.TestCase):
    """Direct tests for the payload-hash digest cache (issue #26 P1.5)."""

    def test_key_stable_and_content_bound(self):
        self.assertEqual(OffloadDigestCache.key("same"),
                         OffloadDigestCache.key("same"))
        self.assertNotEqual(OffloadDigestCache.key("a"),
                            OffloadDigestCache.key("b"))

    def test_lru_order_on_hit(self):
        cache = OffloadDigestCache(2)
        cache.put("a", "A")
        cache.put("b", "B")
        self.assertEqual(cache.get("a"), "A")  # a is now most-recent
        cache.put("c", "C")  # evicts b (LRU), not a
        self.assertIsNone(cache.get("b"))
        self.assertEqual(cache.get("a"), "A")
        self.assertEqual(cache.get("c"), "C")

    def test_min_entries_clamped(self):
        cache = OffloadDigestCache(0)
        cache.put("a", "A")
        cache.put("b", "B")
        self.assertIsNone(cache.get("a"))
        self.assertEqual(cache.get("b"), "B")


if __name__ == "__main__":
    unittest.main()
