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

import json
import os
from typing import Generator, List, Union

import pkg_resources
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
        try:
            self.provider = self.initialize_provider()
        except Exception as e:
            # Create a placeholder provider that's invisible to the external world
            self.provider = {"_placeholder": True, "model": "gpt-3.5-turbo"}
            self.logger.warning(
                "No LLM providers configured. Creating placeholder provider"
                f" for initialization only. Exception: {str(e)}"
            )
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

    def normalize_model_name(self, model: str, provider: str) -> str:
        """Ensure model name follows <provider>/<model> format"""
        if not model or not provider or provider in ["custom", "custom_api"]:
            return model

        provider = provider.lower()
        provider_prefix = f"{provider}/"

        # Case-insensitive check if model already starts with provider
        if model.lower().startswith(provider_prefix):
            return model

        return f"{provider_prefix}{model}"

    def get_available_providers(self):
        """
        Get a list of available LLM providers and their models from LiteLLM's model info file.

        Returns:
            dict: Dictionary of provider information including models, keyed by provider name
        """
        try:
            # Find the path to the LiteLLM package
            litellm_path = pkg_resources.resource_filename("litellm", "")
            model_info_path = os.path.join(
                litellm_path, "model_prices_and_context_window_backup.json"
            )

            self.logger.info(
                f"Loading model information from: {model_info_path}"
            )

            # Load the model information file
            with open(model_info_path, "r") as f:
                model_info = json.load(f)

            # Remove the sample_spec entry which is just documentation
            if "sample_spec" in model_info:
                del model_info["sample_spec"]

            # Organize by provider
            providers = {}

            for model_name, model_data in model_info.items():
                # Skip entries that don't have provider information
                if "litellm_provider" not in model_data:
                    continue

                provider = model_data["litellm_provider"]

                # Initialize provider entry if it doesn't exist
                if provider not in providers:
                    providers[provider] = {"name": provider, "models": []}

                # Get context window size
                context_window = None
                if "max_tokens" in model_data:
                    context_window = model_data["max_tokens"]
                elif "max_input_tokens" in model_data:
                    context_window = model_data["max_input_tokens"]

                # Add model information
                providers[provider]["models"].append(
                    {
                        "name": model_name,
                        "full_name": model_name,
                        "context_window": context_window,
                        "mode": model_data.get("mode", "unknown"),
                        "supports_vision": model_data.get(
                            "supports_vision", False
                        ),
                        "supports_function_calling": model_data.get(
                            "supports_function_calling", False
                        ),
                    }
                )

            self.logger.info(
                f"Retrieved {len(providers)} providers with"
                f" {sum(len(p['models']) for p in providers.values())} models from"
                " LiteLLM"
            )
            return providers

        except Exception as e:
            self.logger.error(
                "Error getting available providers from LiteLLM model info"
                f" file: {str(e)}"
            )
            import traceback

            self.logger.error(traceback.format_exc())
            return {}

    def initialize_provider(self, config=None) -> dict:
        """Initialize provider configuration"""
        provider = {}

        self.logger.info("initialize_provider")

        config = config or self.config

        # Try each provider until we find one that works
        for p in config.get("llm.providers", {}):
            config_selected_provider = config.get("llm.selected_provider")
            # Check if this is the selected provider
            if config_selected_provider == p.get("model"):
                provider.update(p)
                self.logger.info(
                    f"Using selected LLM provider: {p.get('model', 'unknown')}"
                )
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

    def add_msg(
        self, new_message: str, chat_history: List, role: str
    ) -> List[dict]:
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
        provider: dict = None,
    ) -> Union[str, Generator]:
        """Process text using LiteLLM"""
        # Check if we're using the placeholder provider
        if not provider and self.provider.get("_placeholder", False):
            self.logger.error("Cannot chat: No LLM providers configured")
            return ""

        try:
            # self.logger.info(" LITELLM ---------------- ")
            # self.logger.info(str(type(chat_history)))
            # self.logger.info(pprint.pformat(chat_history))

            # Create a clean copy of chat history without 'tokens' field
            clean_messages = []
            for msg in chat_history:
                clean_msg = {k: v for k, v in msg.items() if k != "tokens"}
                clean_messages.append(clean_msg)

            if not provider:
                provider = self.provider

            completion_kwargs = {
                "model": provider["model"],
                "messages": clean_messages,
                "temperature": 0.2,
                "stream": stream,
                **(
                    {"api_base": provider["api_base"]}
                    if "api_base" in provider
                    else {}
                ),
                **(
                    {"api_key": provider["api_key"]}
                    if "api_key" in provider
                    else {"api_key": "nokey"}
                ),
                "logger_fn": self.my_custom_logging_fn,
            }

            self.logger.info(
                f"Sending completion request to model: {provider['model']}"
            )
            self.logger.info(
                f"API base: {provider.get('api_base', 'default')}"
            )

            try:
                response = self.completion(**completion_kwargs)
                # self.logger.info(
                #     "Received response from LLM:" + pprint.pformat(response)
                # )

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

                # # Log the actual chat that caused the error
                # self.logger.error("chat that caused the error:")
                # for i, msg in enumerate(chat_history):
                #     role = msg.get("role", "unknown")
                #     content = msg.get("content", "")
                #     self.logger.error(
                #         f"Message {i} (role={role}, length={len(content)}):"
                #         f" {content[:200]}..."
                #     )

                raise

        except Exception as e:
            msg_error = f"Error: Unable to get a response from the AI: {str(e)}"
            self.logger.error(msg_error)
            raise ValueError(msg_error)

    async def achat(
        self,
        chat_history: list = None,
        stream: bool = False,
        provider: dict = None,
    ) -> Union[str, Generator]:
        """Process text using LiteLLM (async version)"""
        # Check if we're using the placeholder provider
        if not provider and self.provider.get("_placeholder", False):
            self.logger.error("Cannot chat: No LLM providers configured")
            return ""

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

            # Create a clean copy of chat history without 'tokens' field
            clean_messages = []
            for msg in chat_history:
                clean_msg = {k: v for k, v in msg.items() if k != "tokens"}
                clean_messages.append(clean_msg)

            if not provider:
                provider = self.provider

            completion_kwargs = {
                "model": provider["model"],
                "messages": clean_messages,
                "temperature": 0.2,
                "stream": stream,
                **(
                    {"api_base": provider["api_base"]}
                    if "api_base" in provider
                    else {}
                ),
                **(
                    {"api_key": provider["api_key"]}
                    if "api_key" in provider
                    else {}
                ),
                "logger_fn": self.my_custom_logging_fn,
            }

            self.logger.info(
                "Sending async completion request to model:"
                f" {provider['model']}"
            )
            self.logger.info(
                f"API base: {provider.get('api_base', 'default')}"
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