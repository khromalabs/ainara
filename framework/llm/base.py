import logging
from abc import ABC, abstractmethod
from typing import Generator, Union

import requests


class LLMBackend(ABC):
    """Base class for LLM backends"""

    def __init__(self, config: dict):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.provider = {}

    def my_custom_logging_fn(self, model_call_dict):
        """Default logging function for model calls"""
        self.logger.debug(f"LLM Call: {model_call_dict}")

    def _handle_streaming_response(self, response) -> Generator:
        """Handle streaming response"""
        for chunk in response:
            if hasattr(chunk.choices[0], "delta"):
                content = chunk.choices[0].delta.content
                if content is not None:
                    yield content
            elif hasattr(chunk.choices[0], "text"):
                yield chunk.choices[0].text

    def _handle_normal_response(self, response) -> str:
        """Handle normal (non-streaming) response"""
        if hasattr(response.choices[0], "message"):
            return response.choices[0].message.content.rstrip("\n")
        elif hasattr(response.choices[0], "text"):
            return response.choices[0].text.rstrip("\n")
        else:
            self.logger.error("Unexpected response format")
            return ""

    def _prepare_messages(
        self, text: str, system_message: str = "", chat_history: list = None
    ) -> list:
        """Prepare messages list for LLM processing"""
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
        return messages

    def check_provider_availability(self, api_base: str) -> bool:
        """Check if a provider endpoint is available"""
        try:
            response = requests.head(api_base)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def is_available(self) -> bool:
        """Check if the backend is available"""
        if "api_base" not in self.provider:
            return False
        return self.check_provider_availability(self.provider["api_base"])

    def get_context_window(self) -> int:
        """Get the context window size for the current model
        
        Returns:
            Maximum number of tokens the model can process
        """
        return 4000  # Default conservative value

    @abstractmethod
    def process_text(
        self,
        text: str,
        system_message: str = "",
        chat_history: list = None,
        stream: bool = False,
    ) -> Union[str, Generator]:
        """Process text using the LLM backend

        Args:
            text: The text to process
            system_message: Optional system message to prepend
            chat_history: Optional list of previous messages
            stream: Whether to stream the response

        Returns:
            Processed text response or generator for streaming
        """
        pass
