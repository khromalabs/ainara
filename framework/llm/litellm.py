import os
from typing import Generator, Union

from litellm import completion

from .base import LLMBackend
from ainara.framework.config import ConfigManager


class LiteLLM(LLMBackend):
    """LiteLLM implementation of LLM backend"""

    def __init__(self):
        self.config = ConfigManager()
        super().__init__(self.config)
        self.completion = completion
        self.provider = self._initialize_provider()

    def _initialize_provider(self) -> dict:
        """Initialize provider configuration"""
        provider = {}

        # Define environment variable mappings
        env_vars = {
            "model": ("AI_API_MODEL", True),  # (env_var_name, required)
            "api_base": ("OPENAI_API_BASE", False),
            "api_key": ("OPENAI_API_KEY", False),
        }

        # First try environment variables
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
                provider[key] = value

        # If we have required env vars, return the provider config
        if "model" in provider:
            return provider

        # If no env vars, try configured providers
        if not self.config.get("providers"):
            raise ValueError("No LLM providers configured")

        # Try each provider until we find one that works
        for p in self.config["providers"]:
            if self.check_provider_availability(p["api_base"]):
                provider.update(p)
                self.logger.info(f"Using LLM provider: {p['api_base']}")
                return provider

        raise RuntimeError("No working LLM providers found")

    def process_text(
        self,
        text: str,
        system_message: str = "",
        chat_history: list = None,
        stream: bool = False,
    ) -> Union[str, Generator]:
        """Process text using LiteLLM"""
        try:
            messages = self._prepare_messages(
                text, system_message, chat_history
            )

            completion_kwargs = {
                "model": self.provider["model"],
                "messages": messages,
                "temperature": 0.2,
                "stream": stream,
                **(
                    {"api_base": self.provider["api_base"]}
                    if "api_base" in self.provider
                    else {}
                ),
                **(
                    {"api_key": self.provider["api_key"]}
                    if "api_key" in self.provider
                    else {}
                ),
                "logger_fn": self.my_custom_logging_fn,
            }

            self.logger.info("Sending completion request...")
            response = self.completion(**completion_kwargs)

            if stream:
                return self._handle_streaming_response(response)
            else:
                return self._handle_normal_response(response)

        except Exception as e:
            self.logger.error(
                f"Unable to get a response from the AI: {str(e)}"
            )
            return ""
