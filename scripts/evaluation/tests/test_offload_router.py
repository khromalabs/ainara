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

# Add project root to the Python path to allow importing ainara modules
sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..')))

from ainara.framework.orakle_middleware import OrakleMiddleware  # noqa: 402

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
        self.middleware.matcher.match.return_value = [
            {"skill_id": "test_skill", "score": 0.9},
        ]

        # Router knobs (the config keys these mirror are schema-declared).
        self.middleware.enable_agent_spawn = False
        self.middleware.offload_raw_max_bytes = self.CEILING

        # Recording fakes for the two downstream paths.
        self.interpretation_calls = []
        self.offload_calls = []
        self.offload_digest = "DIGESTED FINDINGS"
        self.skill_info = None

        def fake_interpretation(results, query, **kwargs):
            self.interpretation_calls.append(results)
            yield "INTERPRETED"

        def fake_offload(**kwargs):
            self.offload_calls.append(kwargs.get("raw_result"))
            yield "_orakle_loading_signal_|spawn_agent\n"
            if self.offload_digest is not None:
                yield self.offload_digest

        self.middleware.stream_command_interpretation = fake_interpretation
        self.middleware._spawn_offload_digest = fake_offload
        self.middleware._get_chat_context = MagicMock(return_value=[])
        self.middleware.execute_orakle_command = MagicMock(
            side_effect=lambda skill_id, params, history: self.skill_result)
        self.middleware._get_skill_info = MagicMock(
            side_effect=lambda skill_id: self.skill_info)

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
        """Defaults preserve the pre-#26 behavior byte-identically."""
        big = "x" * (self.CEILING + 1)
        self._run(big)
        self.assertEqual(self.offload_calls, [])
        self.assertEqual(self.interpretation_calls, [[big]])

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


if __name__ == "__main__":
    unittest.main()
