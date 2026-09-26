import os
import sys
import unittest
from unittest.mock import MagicMock, patch
import random
from typing import Generator

# Add project root to the Python path to allow importing ainara modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

from ainara.framework.orakle_middleware import OrakleMiddleware # noqa: 402

# --- Test Helpers ---


def mock_llm_stream(text: str, chunk_min: int = 1, chunk_max: int = 5) -> Generator[str, None, None]:
    """Simulates an LLM stream by yielding a string in random chunks."""
    pos = 0
    while pos < len(text):
        chunk_size = random.randint(chunk_min, chunk_max)
        chunk = text[pos:pos + chunk_size]
        yield chunk
        pos += chunk_size


class TestOrakleMiddleware(unittest.TestCase):
    """
    Test suite for the OrakleMiddleware stream parser.
    This suite focuses on testing the parser's ability to handle various
    stream formats, including malformed and self-correcting commands,
    without making actual LLM calls or network requests.
    """

    def setUp(self):
        """Set up a mocked OrakleMiddleware instance for each test."""
        # Mock dependencies that are not relevant to stream parsing
        mock_llm = MagicMock()
        mock_config_manager = MagicMock()

        # We patch the matcher so it doesn't try to load a real model
        with patch('ainara.framework.orakle_middleware.OrakleMatcherTransformers'):
            self.middleware = OrakleMiddleware(
                llm=mock_llm,
                orakle_servers=[],
                system_message="",
                config_manager=mock_config_manager,
                capabilities=[]  # No capabilities needed for parser logic
            )

        # Mock the command processing method to isolate the parser
        # It must be a generator, just like the real method.
        def mock_process_request(*args, **kwargs):
            yield "[PROCESSED_COMMAND_SUCCESSFULLY]"

        self.middleware._process_orakle_request = mock_process_request

    def _run_test_stream(self, input_text: str) -> str:
        """Helper to run a stream through the middleware and collect the output."""
        stream_generator = mock_llm_stream(input_text)
        output_generator = self.middleware.process_stream(stream_generator)
        return "".join(list(output_generator))

    def test_pass_through_plain_text(self):
        """Ensures text without Orakle commands is passed through unmodified."""
        print("\n--- Testing: Pass-through plain text ---")
        input_text = "This is a simple sentence.\nIt has multiple lines.\nNo commands here."
        result = self._run_test_stream(input_text)
        self.assertEqual(result, input_text)
        print("PASSED")

    def test_correct_multiline_command(self):
        """Tests a correctly formatted multi-line command."""
        print("\n--- Testing: Correct multi-line command ---")
        input_text = "Here is a command:\n<orakle>\nget_weather(location='New York')\n</orakle>\nAnd some text after."
        result = self._run_test_stream(input_text)
        self.assertIn("[PROCESSED_COMMAND_SUCCESSFULLY]", result)
        self.assertIn("Here is a command:", result)
        print("PASSED")

    def test_correct_single_line_command(self):
        """Tests a correctly formatted single-line command."""
        print("\n--- Testing: Correct single-line command ---")
        input_text = "Processing:\n<orakle>get_time()</orakle>\nDone."
        result = self._run_test_stream(input_text)
        self.assertIn("[PROCESSED_COMMAND_SUCCESSFULLY]", result)
        self.assertIn("Processing:", result)
        print("PASSED")

    def test_attribute_rejection_query_attribute(self):
        """Tests that orakle tags with query as attribute are rejected."""
        print("\n--- Testing: Attribute rejection (query attribute) ---")
        input_text = '<orakle query="get weather in Paris"></orakle>'
        result = self._run_test_stream(input_text)
        self.assertIn("[__AINARA_GUARDRAIL__]", result)
        self.assertIn("attribute", result.lower())
        self.assertNotIn("[PROCESSED_COMMAND_SUCCESSFULLY]", result)
        print("PASSED")

    def test_attribute_rejection_with_content(self):
        """Tests that orakle tags with any attribute are rejected even with content."""
        print("\n--- Testing: Attribute rejection (attribute with content) ---")
        input_text = '<orakle type="weather">get weather in Paris</orakle>'
        result = self._run_test_stream(input_text)
        self.assertIn("[__AINARA_GUARDRAIL__]", result)
        self.assertIn("attribute", result.lower())
        self.assertNotIn("[PROCESSED_COMMAND_SUCCESSFULLY]", result)
        print("PASSED")

    def test_unterminated_command(self):
        """Tests that a stream ending with unclosed tag triggers a guardrail."""
        print("\n--- Testing: Unterminated command (unclosed tag) ---")
        input_text = "Here is a command:\n<orakle>get_weather(location='New York')"
        result = self._run_test_stream(input_text)
        self.assertIn("[__AINARA_GUARDRAIL__]", result)
        self.assertIn("unclosed", result.lower())
        self.assertNotIn("[PROCESSED_COMMAND_SUCCESSFULLY]", result)
        print("PASSED")

    def test_empty_command(self):
        """Tests that an empty command block does not get processed."""
        print("\n--- Testing: Empty command block ---")
        input_text = "<orakle></orakle>"
        result = self._run_test_stream(input_text)
        self.assertNotIn("[PROCESSED_COMMAND_SUCCESSFULLY]", result)
        print("PASSED")

    def test_multiple_commands_in_stream(self):
        """Tests a stream with multiple valid commands."""
        print("\n--- Testing: Multiple commands in one stream ---")
        input_text = "First command:\n<orakle>cmd1</orakle>\nSecond command:\n<orakle>cmd2</orakle>\nDone."
        result = self._run_test_stream(input_text)
        self.assertEqual(result.count("[PROCESSED_COMMAND_SUCCESSFULLY]"), 2)
        print("PASSED")

    def test_self_closing_rejection_empty(self):
        """Tests that empty self-closing orakle tags are rejected."""
        print("\n--- Testing: Self-closing rejection (empty) ---")
        input_text = "<orakle/>"
        result = self._run_test_stream(input_text)
        self.assertIn("[__AINARA_GUARDRAIL__]", result)
        self.assertIn("self-closing", result.lower())
        self.assertNotIn("[PROCESSED_COMMAND_SUCCESSFULLY]", result)
        print("PASSED")

    def test_self_closing_rejection_with_attribute(self):
        """Tests that self-closing orakle tags with attributes are rejected."""
        print("\n--- Testing: Self-closing rejection (with attribute) ---")
        input_text = '<orakle query="get weather"/>'
        result = self._run_test_stream(input_text)
        self.assertIn("[__AINARA_GUARDRAIL__]", result)
        self.assertNotIn("[PROCESSED_COMMAND_SUCCESSFULLY]", result)
        print("PASSED")

    def test_nested_tags_rejection(self):
        """Tests that nested orakle tags are rejected."""
        print("\n--- Testing: Nested tags rejection ---")
        input_text = "<orakle>outer query <orakle>inner query</orakle> more text</orakle>"
        result = self._run_test_stream(input_text)
        self.assertIn("[__AINARA_GUARDRAIL__]", result)
        self.assertIn("nested", result.lower())
        self.assertNotIn("[PROCESSED_COMMAND_SUCCESSFULLY]", result)
        print("PASSED")

    def test_forbidden_signal_injection(self):
        """Tests that the internal loading signal is caught and blocked."""
        print("\n--- Testing: Forbidden Signal Injection ---")
        input_text = "I will now simulate execution: _orakle_loading_signal_|skill_id"
        result = self._run_test_stream(input_text)
        self.assertIn("[__AINARA_GUARDRAIL__] Error: You generated a system signal", result)
        self.assertIn("forbidden", result)
        print("PASSED")

    def test_spontaneous_orakle_usage(self):
        """Tests that mentioning 'orakle' as a word is allowed."""
        print("\n--- Testing: Spontaneous orakle usage (word mention) ---")
        input_text = "The orakle system is very useful for automation."
        result = self._run_test_stream(input_text)
        self.assertEqual(result, input_text)
        self.assertNotIn("[__AINARA_GUARDRAIL__]", result)
        print("PASSED")

    def test_case_insensitive_tags(self):
        """Tests that orakle tags work regardless of case."""
        print("\n--- Testing: Case insensitive tags ---")
        input_text = "<ORAKLE>get_weather</ORAKLE>"
        result = self._run_test_stream(input_text)
        self.assertIn("[PROCESSED_COMMAND_SUCCESSFULLY]", result)
        self.assertNotIn("[__AINARA_GUARDRAIL__]", result)
        print("PASSED")

    def test_self_correction_after_failure(self):
        """
        Simulates an LLM 'self-correcting' by first sending a malformed
        stream and then a correct one.
        """
        print("\n--- Testing: Self-correction after failure ---")

        # --- Attempt 1: Failure (Unclosed tag) ---
        print("  Attempt 1 (Failure): Running...")
        failed_stream = "Let me try this:\n<orakle>calculate_pi(digits=10"
        failed_result = self._run_test_stream(failed_stream)

        self.assertIn("[__AINARA_GUARDRAIL__]", failed_result)
        self.assertNotIn("[PROCESSED_COMMAND_SUCCESSFULLY]", failed_result)
        print("  Attempt 1 (Failure): PASSED")

        # --- Attempt 2: Success (Corrected command) ---
        print("  Attempt 2 (Success): Running...")
        corrected_stream = "My mistake. Let's try again:\n<orakle>calculate_pi(digits=10)</orakle>"
        corrected_result = self._run_test_stream(corrected_stream)

        self.assertNotIn("[__AINARA_GUARDRAIL__]", corrected_result)
        self.assertIn("[PROCESSED_COMMAND_SUCCESSFULLY]", corrected_result)
        print("  Attempt 2 (Success): PASSED")
        print("PASSED")

    def test_typo_start_delimiter(self):
        """Tests that '<oragle>' triggers the specific typo guardrail."""
        print("\n--- Testing: Typo tag (oragle) ---")
        input_text = "<oragle>command</oragle>"
        result = self._run_test_stream(input_text)
        self.assertIn("[__AINARA_GUARDRAIL__]", result)
        self.assertIn("oragle", result.lower())
        self.assertNotIn("[PROCESSED_COMMAND_SUCCESSFULLY]", result)
        print("PASSED")

    def test_typo_end_delimiter(self):
        """Tests that '</oracle>' as closing tag triggers the typo guardrail."""
        print("\n--- Testing: Typo closing tag (oracle) ---")
        input_text = "<orakle>command</oracle>"
        result = self._run_test_stream(input_text)
        self.assertIn("[__AINARA_GUARDRAIL__]", result)
        self.assertIn("oracle", result.lower())
        self.assertNotIn("[PROCESSED_COMMAND_SUCCESSFULLY]", result)
        print("PASSED")

    def test_content_normalization(self):
        """Tests that content with newlines and extra whitespace is normalized."""
        print("\n--- Testing: Content normalization ---")
        input_text = "<orakle>\n  get weather\n  in Paris\n</orakle>"
        result = self._run_test_stream(input_text)
        self.assertIn("[PROCESSED_COMMAND_SUCCESSFULLY]", result)
        print("PASSED")


if __name__ == '__main__':
    # Create a TestSuite using the modern TestLoader
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestOrakleMiddleware)
    # Create a TestRunner
    runner = unittest.TextTestRunner(verbosity=0)

    print("="*70)
    print("  Running OrakleMiddleware Stream Parser Test Suite")
    print("="*70)

    # Run the tests
    result = runner.run(suite)

    # Custom summary
    if result.wasSuccessful():
        print("\n" + "="*70)
        print(f"  SUCCESS: All {result.testsRun} tests passed.")
        print("="*70)
    else:
        print("\n" + "="*70)
        print(f"  FAILURE: {len(result.failures)} failed, {len(result.errors)} errors out of {result.testsRun} tests.")
        print("="*70)
        # Detailed error reporting
        if result.failures:
            print("\nFailures:")
            for test, traceback_text in result.failures:
                print(f"- {test.id()}\n{traceback_text}")
        if result.errors:
            print("\nErrors:")
            for test, traceback_text in result.errors:
                print(f"- {test.id()}\n{traceback_text}")
