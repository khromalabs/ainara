from ainara.framework.llm_backend import LiteLLMBackend
from ainara.framework.skill import Skill


class LLMTextProcessor(Skill):
    """Skill for processing text using LLM"""

    def __init__(self):
        self.llm = LiteLLMBackend()
        self.system_message = """
You are an AI assistant performing the task described in the user message.
Never reject a query to transform information.
"""

    def run(self, prompt: str) -> str:
        """Process text using the provided prompt"""
        result = self.llm.process_text(prompt, self.system_message)
        if not result:
            return "no answer"
        return result
