# Ainara - Open Source AI Assistant Framework
# Copyright (C) 2025 Rubén Gómez http://www.khromalabs.org

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, see
# <https://www.gnu.org/licenses/>

# import os
import pprint

from typing import Generator, List, Union
from litellm import acompletion, completion, get_max_tokens, token_counter

from ainara.framework.config import ConfigManager

from .base import LLMBackend


class LiteLLM(LLMBackend):
    """LiteLLM implementation of LLM backend"""

    def __init__(self):
        self.config = ConfigManager()
        super().__init__(self.config)
        self.completion = completion
        self.acompletion = acompletion
        self.provider = self._initialize_provider()
        self._context_window = self._get_context_window()

    def _get_context_window(self) -> int:
        """Get the context window size for the current model"""
        try:
            model_name = self.provider.get("model")
            self.logger.info("Using model: " + model_name)
            if not model_name:
                raise ValueError("No model specified")

            # First check if we have a configured context window
            model_contexts = self.config.get("llm.model_contexts", {})
            # self.logger.info("AVAILABLE MODEL CONTEXTS")
            # self.logger.info(pprint.pformat(model_contexts))
            # self.logger.info(type(model_name))
            # self.logger.info(model_name)
            # self.logger.info(list(model_contexts.keys()))
            # for key in model_contexts:
            #     self.logger.info(f"Key: '{key}', Type: '{type(key)}'")

            if model_name in model_contexts:
                # self.logger.info("FOUND")
                context_size = model_contexts[model_name]
                self.logger.info(
                    f"Using configured context window for {model_name}:"
                    f" {context_size} tokens"
                )
                return context_size

            # Otherwise try to get it from LiteLLM
            max_tokens = get_max_tokens(model_name)
            self.logger.info(
                f"Using LiteLLM-provided context window for {model_name}:"
                f" {max_tokens} tokens"
            )
            return max_tokens
        except Exception as e:
            self.logger.warning(f"Unable to get context window size: {str(e)}")
            return 4000  # Conservative default

    def get_context_window(self) -> int:
        """Return the cached context window size"""
        return self._context_window

    def _initialize_provider(self) -> dict:
        """Initialize provider configuration"""
        provider = {}

        # Define environment variable mappings
        # env_vars = {
        #     "model": ("AI_API_MODEL", True),  # (env_var_name, required)
        #     "api_base": ("OPENAI_API_BASE", False),
        #     "api_key": ("OPENAI_API_KEY", False),
        # }

        # # First try environment variables
        # self.logger.info("Checking environment variables:")
        # for key, (env_var, required) in env_vars.items():
        #     value = os.environ.get(env_var)
        #     self.logger.info(
        #         f"{env_var}: {'[SET]' if value else '[MISSING]'}"
        #     )
        #     if required and not value:
        #         raise ValueError(
        #             f"Missing required environment variable: {env_var}"
        #         )
        #     if value:  # Only add to provider if value exists
        #         provider[key] = value
        #
        # # If we have required env vars, return the provider config
        # if "model" in provider:
        #     return provider

        # # If no env vars, try configured providers
        # if not self.config.get("providers"):
        #     raise ValueError("No LLM providers configured")

        # Try each provider until we find one that works
        for p in self.config.get("llm.providers", {}):
            if "api_base" in p and self.check_provider_availability(p["api_base"]):
                provider.update(p)
                self.logger.info(f"Using LLM provider: {p['api_base']}")
                return provider
            else:
                provider.update(p)
                return provider

        raise RuntimeError("No working LLM providers found")

    def prepare_chat(
        self, system_message: str, new_message: str
    ) -> List[dict]:
        """Format chat message for LLM processing"""
        messages = [{"role": "system", "content": system_message}]
        messages.append({"role": "user", "content": new_message})
        return messages

    def _get_token_count(self, text: str, role: str) -> int:
        """Get accurate token count using LiteLLM"""
        if not text:
            return 0

        try:
            count = token_counter(
                model=self.provider["model"],
                messages=[{"role": role, "content": text}],
            )
            return count
        except Exception:
            raise RuntimeError("Can't get the amount of tokens for " + role)

    def add_msg(self, new_message: str, chat_history: List, role: str) -> List[dict]:
        """Format user chat message for LLM processing with token count"""
        token_count = self._get_token_count(new_message, role)
        chat_history.append(
            {"role": role, "content": new_message, "tokens": token_count}
        )
        self.logger.debug(f"Added {role} message with {token_count} tokens")
        return chat_history

    def chat(
        self,
        chat_history: list = None,
        stream: bool = False,
    ) -> Union[str, Generator]:
        """Process text using LiteLLM"""
        try:

            # self.logger.info(" LITELLM ---------------- ")
            # self.logger.info(str(type(chat_history)))
            # self.logger.info(pprint.pformat(chat_history))

            completion_kwargs = {
                "model": self.provider["model"],
                "messages": chat_history,
                "temperature": 0.2,
                "stream": stream,
                # "reasoning": {
                #     "exclude": True
                # },
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

            self.logger.info(
                "Sending completion request to model:"
                f" {self.provider['model']}"
            )
            self.logger.info(
                f"API base: {self.provider.get('api_base', 'default')}"
            )

            try:
                response = self.completion(**completion_kwargs)
                self.logger.info(
                    "Received response from LLM:" + pprint.pformat(response)
                )

                if stream:
                    self.logger.info("Streaming response enabled")
                    return self._handle_streaming_response(response)
                else:
                    self.logger.info("Got complete response")
                    return self._handle_normal_response(response)

            except Exception as e:
                self.logger.error(f"LiteLLM completion error: {str(e)}")
                # Add more detailed error logging
                if hasattr(e, "response"):
                    self.logger.error(
                        "Response status:"
                        f" {e.response.status_code if hasattr(e.response, 'status_code') else 'unknown'}"
                    )
                    self.logger.error(
                        "Response content:"
                        f" {e.response.text if hasattr(e.response, 'text') else 'unknown'}"
                    )

                # Log the actual chat that caused the error
                self.logger.error("chat that caused the error:")
                for i, msg in enumerate(chat_history):
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    self.logger.error(
                        f"Message {i} (role={role}, length={len(content)}):"
                        f" {content[:200]}..."
                    )

                raise

        except Exception as e:
            self.logger.error(
                f"Unable to get a response from the AI: {str(e)}"
            )
            return ""

    async def achat(
        self,
        chat_history: list = None,
        stream: bool = False,
    ) -> Union[str, Generator]:
        """Process text using LiteLLM (async version)"""
        try:
            # Add detailed logging of the chat being sent
            self.logger.info("Preparing to send chat to LLM (async):")
            for i, msg in enumerate(chat_history):
                self.logger.info(
                    f"Message {i}: role={msg.get('role')},"
                    f" content_length={len(msg.get('content', ''))}"
                )
                # Log a preview of the content (first 100 chars)
                content_preview = msg.get("content", "")[:100] + (
                    "..." if len(msg.get("content", "")) > 100 else ""
                )
                self.logger.info(f"Content preview: {content_preview}")

            # Log chat history details if present
            if chat_history:
                self.logger.info(
                    f"Chat history length: {len(chat_history)} chat"
                )
                for i, msg in enumerate(chat_history):
                    self.logger.info(
                        f"History {i}: role={msg.get('role')},"
                        f" content_length={len(msg.get('content', ''))}"
                    )

            completion_kwargs = {
                "model": self.provider["model"],
                "messages": chat_history,
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

            self.logger.info(
                "Sending async completion request to model:"
                f" {self.provider['model']}"
            )
            self.logger.info(
                f"API base: {self.provider.get('api_base', 'default')}"
            )

            try:
                response = await self.acompletion(**completion_kwargs)
                self.logger.info("Received async response from LLM")

                if stream:
                    self.logger.info("Streaming response enabled")
                    return self._handle_streaming_response(response)
                else:
                    self.logger.info("Got complete response")
                    return self._handle_normal_response(response)

            except Exception as e:
                self.logger.error(f"LiteLLM async completion error: {str(e)}")
                # Add more detailed error logging
                if hasattr(e, "response"):
                    self.logger.error(
                        "Response status:"
                        f" {e.response.status_code if hasattr(e.response, 'status_code') else 'unknown'}"
                    )
                    self.logger.error(
                        "Response content:"
                        f" {e.response.text if hasattr(e.response, 'text') else 'unknown'}"
                    )

                # Log the actual message that caused the error
                self.logger.error("chat that caused the error:")
                for i, msg in enumerate(chat_history):
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    self.logger.error(
                        f"Message {i} (role={role}, length={len(content)}):"
                        f" {content[:200]}..."
                    )

                raise

        except Exception as e:
            self.logger.error(
                f"Unable to get a response from the AI: {str(e)}"
            )
            return ""
