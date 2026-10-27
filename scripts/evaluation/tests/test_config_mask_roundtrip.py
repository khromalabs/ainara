# Issue #34: PUT /config round-trip overwrites masked API keys with the
# mask. Pins the fix: ConfigManager.restore_masked_values substitutes an
# incoming value that is EXACTLY the mask of the stored secret with the
# secret itself, so a read-modify-PUT client can never store a mask
# string over a real secret. LLM-free, offline.

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..')))

from ainara.framework.config import ConfigManager  # noqa: 402

SECRET = "REDACTED-REVOKED-TEST-KEY-0123456789abcdef"
MASKED = SECRET[:2] + "*" * (len(SECRET) - 4) + SECRET[-2:]
SHORT_SECRET = "abc"          # len <= 4 -> mask is a bare '****'
SHORT_MASK = "****"


def make_manager(stored):
    """A ConfigManager over an in-memory config (no file I/O)."""
    mgr = ConfigManager.__new__(ConfigManager)
    mgr.config = copy.deepcopy(stored)
    return mgr


class TestMaskValue(unittest.TestCase):
    def test_long_value(self):
        self.assertEqual(
            ConfigManager._mask_value(SECRET), MASKED)
        self.assertIn("**", MASKED)
        self.assertEqual(MASKED[:2], SECRET[:2])
        self.assertEqual(MASKED[-2:], SECRET[-2:])

    def test_short_value_bare_stars(self):
        self.assertEqual(ConfigManager._mask_value(SHORT_SECRET), SHORT_MASK)

    def test_non_string(self):
        self.assertEqual(ConfigManager._mask_value(12345), SHORT_MASK)


class TestRestoreMaskedValues(unittest.TestCase):
    """The reported repro: read masked GET /config -> flip an unrelated
    field -> PUT. The masked secret must come back as the secret."""

    def setUp(self):
        self.stored = {
            "orakle": {"enable_agent_spawn": False},
            "llm": {
                "selected_provider": "gemini/gemini-3.8-flash",
                "providers": [
                    {
                        "api_key": SECRET,
                        "model": "gemini/gemini-3.8-flash",
                        "context_window": 130072,
                    }
                ],
                "memories_processors": ["gemini/gemini-3.8-flash"],
            },
        }
        self.mgr = make_manager(self.stored)

    def _roundtrip_payload(self):
        """What a naive client PUTs after a masked GET + one flip —
        masked from the LIVE stored config (mgr.config)."""
        from ainara.framework.config import SENSITIVE_KEY_HINTS

        payload = copy.deepcopy(self.mgr.config)

        def mask(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(v, (dict, list)):
                        mask(v)
                    elif any(h in k.lower() for h in SENSITIVE_KEY_HINTS) and v:
                        obj[k] = self.mgr._mask_value(v)
            elif isinstance(obj, list):
                for item in obj:
                    if isinstance(item, (dict, list)):
                        mask(item)

        mask(payload)
        payload["orakle"]["enable_agent_spawn"] = True  # the only change
        return payload

    def test_mask_roundtrip_preserves_secret(self):
        payload = self._roundtrip_payload()
        self.assertEqual(payload["llm"]["providers"][0]["api_key"], MASKED)

        restored = self.mgr.restore_masked_values(payload)
        self.assertEqual(
            restored["llm"]["providers"][0]["api_key"], SECRET)
        # The unrelated flip survives untouched.
        self.assertTrue(restored["orakle"]["enable_agent_spawn"])

    def test_real_new_secret_passes_through(self):
        """A genuinely new key must not be treated as a mask."""
        new_key = "sk-real-new-key"
        payload = self._roundtrip_payload()
        payload["llm"]["providers"][0]["api_key"] = new_key
        restored = self.mgr.restore_masked_values(payload)
        self.assertEqual(restored["llm"]["providers"][0]["api_key"], new_key)

    def test_short_secret_bare_stars_restored(self):
        self.mgr.config["llm"]["providers"][0]["api_key"] = SHORT_SECRET
        payload = self._roundtrip_payload()
        self.assertEqual(payload["llm"]["providers"][0]["api_key"], SHORT_MASK)
        restored = self.mgr.restore_masked_values(payload)
        self.assertEqual(
            restored["llm"]["providers"][0]["api_key"], SHORT_SECRET)

    def test_mask_of_mask_is_not_mistaken_for_secret(self):
        """A value that merely looks masked but doesn't match the stored
        mask exactly passes through untouched."""
        payload = self._roundtrip_payload()
        payload["llm"]["providers"][0]["api_key"] = "XY" + "*" * 40 + "ZZ"
        restored = self.mgr.restore_masked_values(payload)
        self.assertEqual(
            restored["llm"]["providers"][0]["api_key"],
            "XY" + "*" * 40 + "ZZ")

    def test_new_sensitive_key_without_stored_counterpart(self):
        """Mask-shaped value on a key with nothing stored: cannot be
        'unchanged' — passes through as a (weird) literal new key."""
        payload = self._roundtrip_payload()
        payload["llm"]["vault_token"] = "****"
        restored = self.mgr.restore_masked_values(payload)
        self.assertEqual(restored["llm"]["vault_token"], "****")

    def test_appended_provider_still_restored(self):
        """Append case: existing index alignment holds for the old entry;
        the new entry has no stored counterpart and passes through."""
        payload = self._roundtrip_payload()
        payload["llm"]["providers"].append(
            {"api_key": "sk-brand-new", "model": "gpt/x"})
        restored = self.mgr.restore_masked_values(payload)
        self.assertEqual(
            restored["llm"]["providers"][0]["api_key"], SECRET)
        self.assertEqual(
            restored["llm"]["providers"][1]["api_key"], "sk-brand-new")

    def test_original_stored_config_not_mutated(self):
        payload = self._roundtrip_payload()
        self.mgr.restore_masked_values(payload)
        self.assertEqual(self.mgr.config["llm"]["providers"][0]["api_key"],
                         SECRET)

    def test_non_dict_payload_shapes(self):
        """Lists at the top of a section, and type mismatches against the
        stored config, must not raise."""
        payload = {"llm": {"providers": [
            {"api_key": MASKED, "model": "x"}]}}
        restored = self.mgr.restore_masked_values(payload)
        self.assertEqual(restored["llm"]["providers"][0]["api_key"], SECRET)

        weird = {"orakle": {"enable_agent_spawn": ["not-a-dict"]}}
        restored = self.mgr.restore_masked_values(weird)
        self.assertEqual(restored["orakle"]["enable_agent_spawn"],
                         ["not-a-dict"])

    def test_stored_mask_from_legacy_clobber_is_held_stable(self):
        """A config already clobbered by the old bug stores a literal
        mask string. Masking is idempotent for long values, so the
        round-trip treats the stored mask as 'unchanged' and holds it
        stable — no further corruption; the user must re-enter the key
        to recover, but nothing degrades in the meantime."""
        self.mgr.config["llm"]["providers"][0]["api_key"] = MASKED
        # Idempotence is what makes this stable.
        self.assertEqual(self.mgr._mask_value(MASKED), MASKED)
        payload = self._roundtrip_payload()
        self.assertEqual(payload["llm"]["providers"][0]["api_key"], MASKED)
        restored = self.mgr.restore_masked_values(payload)
        self.assertEqual(restored["llm"]["providers"][0]["api_key"], MASKED)


if __name__ == "__main__":
    unittest.main()
