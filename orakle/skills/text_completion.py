from ainara.framework.llm_backend import LiteLLMBackend
from ainara.framework.skill import Skill


class TextCompletion(Skill):
    """Skill for processing text using LLM"""
    hiddenCapability = True  # Hide this skill from capabilities listing

    def __init__(self):
        self.llm = LiteLLMBackend()
        self.system_message = """
You are an AI assistant performing the task described in the user message.
Never reject a query to transform information.
"""

    def run(self, prompt: str) -> str:
        """Process text using the provided prompt"""
        result = self.llm.process_text(
            text=prompt,
            system_message=self.system_message,
            stream=False
        )
        if not result:
            return "no answer"
        return result
