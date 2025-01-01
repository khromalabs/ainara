from abc import ABC, abstractmethod


class LLMBackend(ABC):
    """Abstract base class for LLM backends"""

    @abstractmethod
    def process_text(self, text: str, system_message: str = "") -> str:
        """Process text using the LLM backend"""
        pass


class LiteLLMBackend(LLMBackend):
    """LiteLLM implementation of LLM backend"""

    def __init__(self):
        from litellm import completion
        import os

        self.completion = completion
        
        # Validate required environment variables
        required_vars = {
            "model": "AI_API_MODEL",
            "api_base": "OPENAI_API_BASE", 
            "api_key": "OPENAI_API_KEY"
        }
        
        self.provider = {}
        logger = logging.getLogger(__name__)
        logger.info("Checking environment variables:")
        for key, env_var in required_vars.items():
            value = os.environ.get(env_var)
            logger.info(f"{env_var}: {'[SET]' if value else '[MISSING]'}")
            if not value:
                raise ValueError(f"Missing required environment variable: {env_var}")
            self.provider[key] = value

    def process_text(self, text: str, system_message: str = "") -> str:
        """Process text using LiteLLM"""
        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": text}
        ]

        try:
            completion_kwargs = {
                "model": self.provider["model"],
                "messages": messages,
                "temperature": 0.2,
                "stream": False,
                "api_base": self.provider["api_base"],
                "api_key": self.provider["api_key"]
            }

            response = self.completion(**completion_kwargs)

            if hasattr(response.choices[0], "message"):
                answer = response.choices[0].message.content
            else:
                answer = response.choices[0].text

            return answer.rstrip("\n")

        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Unable to get a response from the AI: {str(e)}")
            return ""
