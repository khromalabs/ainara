from orakle.framework.llm_backend import LiteLLMBackend
from orakle.framework.skill import Skill


class TextProcessor(Skill):
    """Skill for processing text using LLM"""

    def __init__(self):
        self.llm = LiteLLMBackend()
        self.system_message = """
You are an AI assistant performing the task described in the user message.
Never reject a query to transform information.
"""

    def extract_code_blocks(self, text):
        blocks = []
        in_block = False
        current_block = []

        for line in text.split("\n"):
            if line.strip().startswith("```"):
                if in_block:
                    in_block = False
                else:
                    in_block = True
                continue

            if in_block:
                current_block.append(line)
            elif current_block:
                blocks.append("\n".join(current_block))
                current_block = []

        if current_block:
            blocks.append("\n".join(current_block))

        return "\n\n".join(blocks)

    def run(self, prompt: str) -> str:
        """Process text using the provided prompt"""
        result = self.llm.process_text(prompt, self.system_message)
        if not result:
            return "no answer"
        return result

        # # Extract code blocks
        # result_strip = self.extract_code_blocks(result)
        # final_result = result_strip if result_strip else result
        #
        # # Handle escaped characters, newlines and Unicode
        # try:
        #     # First try unicode_escape decoding
        #     final_result = bytes(final_result, "utf-8").decode(
        #         "unicode_escape"
        #     )
        # except UnicodeDecodeError:
        #     # If that fails, keep original string
        #     pass
        #
        # # Replace escaped newlines
        # final_result = final_result.replace("\\n", "\n")
        #
        # # Ensure proper UTF-8 encoding/decoding
        # final_result = final_result.encode("utf-8").decode(
        #     "utf-8", errors="replace"
        # )
        #
        # return final_result
