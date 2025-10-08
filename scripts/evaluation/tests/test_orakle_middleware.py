import os
import sys
import unittest
from unittest.mock import MagicMock, patch
import random
from typing import Generator

# Add project root to the Python path to allow importing ainara modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

from ainara.framework.orakle_middleware import OrakleMiddleware

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
                capabilities=[] # No capabilities needed for parser logic
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
        input_text = "Here is a command:\n<<<ORAKLE\nget_weather(location='New York')\nORAKLE\nAnd some text after."
        expected_output = "Here is a command:\n[PROCESSED_COMMAND_SUCCESSFULLY]\nAnd some text after."
        result = self._run_test_stream(input_text)
        self.assertEqual(result, expected_output)
        print("PASSED")

    def test_correct_single_line_command(self):
        """Tests a correctly formatted single-line command."""
        print("\n--- Testing: Correct single-line command ---")
        input_text = "Processing:\n<<<ORAKLE get_time() ORAKLE;\nDone."
        expected_output = "Processing:\n[PROCESSED_COMMAND_SUCCESSFULLY]\nDone."
        result = self._run_test_stream(input_text)
        self.assertEqual(result, expected_output)
        print("PASSED")

    def test_malformed_start_delimiter_inline(self):
        """Tests that a start delimiter on the same line as text triggers a guardrail."""
        print("\n--- Testing: Malformed start delimiter (inline) ---")
        input_text = "This is an error <<<ORAKLE\ncommand\nORAKLE"
        result = self._run_test_stream(input_text)
        self.assertIn("[AINARA GUARDRAIL] Error: Malformed ORAKLE command detected.", result)
        self.assertNotIn("[PROCESSED_COMMAND_SUCCESSFULLY]", result)
        print("PASSED")

    def test_malformed_end_delimiter_inline(self):
        """Tests that an end delimiter on the same line as text triggers a guardrail."""
        print("\n--- Testing: Malformed end delimiter (inline) ---")
        input_text = "<<<ORAKLE\ncommand ORAKLE"
        result = self._run_test_stream(input_text)
        self.assertIn("[AINARA GUARDRAIL] Error: Malformed ORAKLE command detected.", result)
        self.assertNotIn("[PROCESSED_COMMAND_SUCCESSFULLY]", result)
        # The parser should yield back the buffered content upon failure
        self.assertIn("command ORAKLE", result)
        print("PASSED")

    def test_unterminated_command(self):
        """Tests that a stream ending mid-command triggers a guardrail."""
        print("\n--- Testing: Unterminated command ---")
        input_text = "Here is a command:\n<<<ORAKLE\nget_weather(location='New York')"
        result = self._run_test_stream(input_text)
        self.assertIn("[AINARA GUARDRAIL] Error: Stream ended with an unterminated ORAKLE command.", result)
        self.assertNotIn("[PROCESSED_COMMAND_SUCCESSFULLY]", result)
        self.assertIn("get_weather(location='New York')", result) # Should return the buffer
        print("PASSED")

    def test_empty_command(self):
        """Tests that an empty command block does not get processed."""
        print("\n--- Testing: Empty command block ---")
        input_text = "<<<ORAKLE\n\nORAKLE"
        # The mock is never called, so the result is an empty string.
        result = self._run_test_stream(input_text)
        self.assertEqual(result, "")
        print("PASSED")

    def test_multiple_commands_in_stream(self):
        """Tests a stream with multiple valid commands."""
        print("\n--- Testing: Multiple commands in one stream ---")
        input_text = "First command:\n<<<ORAKLE cmd1 ORAKLE;\nSecond command:\n<<<ORAKLE\ncmd2\nORAKLE\nDone."
        expected_output = "First command:\n[PROCESSED_COMMAND_SUCCESSFULLY]\nSecond command:\n[PROCESSED_COMMAND_SUCCESSFULLY]\nDone."
        result = self._run_test_stream(input_text)
        self.assertEqual(result, expected_output)
        print("PASSED")

    def test_self_correction_after_failure(self):
        """
        Simulates an LLM 'self-correcting' by first sending a malformed
        stream and then a correct one.
        """
        print("\n--- Testing: Self-correction after failure ---")
        
        # --- Attempt 1: Failure (Unterminated command) ---
        print("  Attempt 1 (Failure): Running...")
        failed_stream = "Let me try this:\n<<<ORAKLE\ncalculate_pi(digits=10"
        failed_result = self._run_test_stream(failed_stream)
        
        # Verify failure
        self.assertIn("unterminated ORAKLE command", failed_result)
        self.assertNotIn("[PROCESSED_COMMAND_SUCCESSFULLY]", failed_result)
        print("  Attempt 1 (Failure): PASSED")

        # --- Attempt 2: Success (Corrected command) ---
        print("  Attempt 2 (Success): Running...")
        corrected_stream = "My mistake. Let's try again:\n<<<ORAKLE\ncalculate_pi(digits=10)\nORAKLE"
        corrected_result = self._run_test_stream(corrected_stream)

        # Verify success
        self.assertNotIn("unterminated ORAKLE command", corrected_result)
        self.assertIn("[PROCESSED_COMMAND_SUCCESSFULLY]", corrected_result)
        self.assertIn("My mistake. Let's try again:", corrected_result)
        print("  Attempt 2 (Success): PASSED")
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
