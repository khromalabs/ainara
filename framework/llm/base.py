# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
#
# This file is dual-licensed under:
# 1. GNU Lesser General Public License v3.0 (LGPL-3.0)
#    (See the included LICENSE_LGPL3.txt file or look into
#    <https://www.gnu.org/licenses/lgpl-3.0.html> for details)
# 2. Commercial license
#    (Contact: rgomez@khromalabs.org for licensing options)
#
# You may use, distribute and modify this code under the terms of either license.
# This notice must be preserved in all copies or substantial portions of the code.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.

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
        content = ""
        if hasattr(response.choices[0], "message"):
            content = response.choices[0].message.content
        elif hasattr(response.choices[0], "text"):
            content = response.choices[0].text
        else:
            self.logger.error("Unexpected response format")
            return ""

        # Clean up the response
        content = content.strip()
        # Remove markdown code block if present
        if content.startswith("```") and content.endswith("```"):
            # Extract language if specified
            lines = content.split("\n")
            if len(lines) > 2:
                # Remove first and last lines (``` markers)
                content = "\n".join(lines[1:-1])
            else:
                # Just remove the ``` markers
                content = content.replace("```", "")

        return content.strip()

    # def _prepare_messages(
    #     self, text: str, system_message: str = "", chat_history: list = None
    # ) -> list:
    #     """Prepare messages list for LLM processing"""
    #     messages = [{"role": "system", "content": system_message}]
    #
    #     # Add chat history if provided
    #     if chat_history:
    #         for i in range(0, len(chat_history), 2):
    #             messages.append({"role": "user", "content": chat_history[i]})
    #             if i + 1 < len(chat_history):
    #                 messages.append(
    #                     {"role": "assistant", "content": chat_history[i + 1]}
    #                 )
    #
    #     # Add current message
    #     messages.append({"role": "user", "content": text})
    #     return messages

    def check_provider_availability(self, api_base: str) -> bool:
        """Check if a provider endpoint is available"""
        try:
            response = requests.head(api_base)
            return response.status_code == 200
        except requests.RequestException:
            return False

    # TODO add proper health check
    # def is_available(self) -> bool:
    #     """Check if the backend is available"""
    #     if "api_base" not in self.provider:
    #         return False
    #     return self.check_provider_availability(self.provider["api_base"])

    @abstractmethod
    def get_available_providers(self):
        """
        Get a list of available LLM providers and their models.

        Returns:
            list: List of provider information including models
        """
        pass

    @abstractmethod
    def get_context_window(self) -> int:
        """Get the context window size for the current model

        Returns:
            Maximum number of tokens the model can process
        """
        pass
        # return 4000  # Default conservative value

    @abstractmethod
    async def chat(
        self,
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