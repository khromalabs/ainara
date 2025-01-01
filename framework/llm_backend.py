import logging
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
        import os

        # import litellm
        # litellm.set_verbose = True
        from litellm import completion

        # from litellm import completion, completion_cost

        self.completion = completion
        # self.completion_cost = completion_cost

        # Validate required environment variables
        required_vars = {
            "model": "AI_API_MODEL",
            "api_base": "OPENAI_API_BASE",
            "api_key": "OPENAI_API_KEY",
        }

        self.provider = {}
        self.logger = logging.getLogger(__name__)
        self.logger.debug("Checking environment variables:")
        for key, env_var in required_vars.items():
            value = os.environ.get(env_var)
            self.logger.debug(
                f"{env_var}: {'[SET]' if value else '[MISSING]'}"
            )
            if not value:
                raise ValueError(
                    f"Missing required environment variable: {env_var}"
                )
            self.provider[key] = value

    def my_custom_logging_fn(self, model_call_dict):
        self.logger.debug(f"LiteLLM: {model_call_dict}")

    def process_text(self, text: str, system_message: str = "") -> str:
        """Process text using LiteLLM"""
        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": text},
        ]

        try:
            completion_kwargs = {
                "model": self.provider["model"],
                "messages": messages,
                "temperature": 0.2,
                "stream": False,
                "api_base": self.provider["api_base"],
                "api_key": self.provider["api_key"],
                "logger_fn": self.my_custom_logging_fn,
            }

            self.logger.info(
                f"{__name__}.{self.__class__.__name__} Sending completion"
                " request..."
            )
            response = self.completion(**completion_kwargs)
            # cost = self.completion_cost(completion_response=response)
            # formatted_string = f"${float(cost):.10f}"
            # self.logger.info(f"{__name__} cost: {formatted_string}")

            if hasattr(response.choices[0], "message"):
                answer = response.choices[0].message.content
            else:
                answer = response.choices[0].text

            return answer.rstrip("\n")

        except Exception as e:
            self.logger.error(
                f"Unable to get a response from the AI: {str(e)}"
            )
            return ""
