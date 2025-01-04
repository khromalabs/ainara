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

        # Initialize provider dictionary and logger
        self.provider = {}
        self.logger = logging.getLogger(__name__)
        
        # Define environment variable mappings
        env_vars = {
            "model": ("AI_API_MODEL", True),  # (env_var_name, required)
            "api_base": ("OPENAI_API_BASE", False),
            "api_key": ("OPENAI_API_KEY", False),
        }

        self.logger.debug("Checking environment variables:")
        for key, (env_var, required) in env_vars.items():
            value = os.environ.get(env_var)
            self.logger.debug(
                f"{env_var}: {'[SET]' if value else '[MISSING]'}"
            )
            if required and not value:
                raise ValueError(
                    f"Missing required environment variable: {env_var}"
                )
            if value:  # Only add to provider if value exists
                self.provider[key] = value

    def my_custom_logging_fn(self, model_call_dict):
        self.logger.debug(f"LiteLLM: {model_call_dict}")

    def process_text(
        self,
        text: str,
        system_message: str = "",
        chat_history: list = None,
        stream: bool = False,
    ) -> str:
        """Process text using LiteLLM

        Args:
            text: The text to process
            system_message: Optional system message to prepend
            chat_history: Optional list of previous messages in
                          [user_msg, assistant_msg] pairs
            stream: Whether to stream the response
        """
        messages = [{"role": "system", "content": system_message}]

        # Add chat history if provided
        if chat_history:
            for i in range(0, len(chat_history), 2):
                messages.append({"role": "user", "content": chat_history[i]})
                if i + 1 < len(chat_history):
                    messages.append(
                        {"role": "assistant", "content": chat_history[i + 1]}
                    )

        # Add current message
        messages.append({"role": "user", "content": text})

        try:
            completion_kwargs = {
                "model": self.provider["model"],
                "messages": messages,
                "temperature": 0.2,
                "stream": stream,
                **({"api_base": self.provider["api_base"]} if "api_base" in self.provider else {}),
                **({"api_key": self.provider["api_key"]} if "api_key" in self.provider else {}),
                "logger_fn": self.my_custom_logging_fn,
            }

            self.logger.info(
                f"{__name__}.{self.__class__.__name__} Sending completion"
                " request..."
            )
            response = self.completion(**completion_kwargs)

            if stream:
                answer = ""
                for chunk in response:
                    if (
                        hasattr(chunk.choices[0], "delta")
                        and chunk.choices[0].delta.content is not None
                    ):
                        content = chunk.choices[0].delta.content
                    elif hasattr(chunk.choices[0], "text"):
                        content = chunk.choices[0].text
                    else:
                        continue

                    print(content, end="", flush=True)
                    answer += content
            else:
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
