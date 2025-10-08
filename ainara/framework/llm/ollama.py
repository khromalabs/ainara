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
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, Generator, List, Optional, Union

import ollama
from litellm import token_counter

from ainara.framework.config import ConfigManager

from .base import LLMBackend

logger = logging.getLogger(__name__)


class OllamaLLM(LLMBackend):
    """
    Direct Ollama LLM backend implementation using the official 'ollama' Python library.
    Uses /api/chat for primary interaction
    """

    def __init__(
        self, config_manager: ConfigManager, provider_config: dict = None
    ):
        self.config_manager = config_manager
        super().__init__(self.config_manager)

        if provider_config:
            # Use the specific provider config passed in
            self.provider_config = provider_config
            self.logger.info(
                "Using provided provider config:"
                f" {provider_config.get('name', provider_config.get('model'))}"
            )
        else:
            # Fallback to getting config from config manager
            self.provider_config = self._get_ollama_provider_config_entry()
            if not self.provider_config:
                selected_provider_id = self.config_manager.get(
                    "llm.selected_provider", ""
                )
                if selected_provider_id.startswith("ollama/"):
                    logger.warning(
                        "No specific provider entry for"
                        f" '{selected_provider_id}'. Trying generic Ollama"
                        " config."
                    )
                    self.provider_config = self.config_manager.get(
                        "llm.providers_config.ollama", {}
                    )
                    if not self.provider_config:
                        raise ValueError(
                            "Ollama provider configuration not found for"
                            f" '{selected_provider_id}' and no generic config"
                            " available."
                        )
                    self.provider_config.setdefault(
                        "api_base", "http://localhost:11434"
                    )  # Default if not in generic
                else:
                    raise ValueError(
                        "Ollama provider configuration not found for selected"
                        " provider."
                    )

        self.api_base = self.provider_config.get(
            "api_base", "http://localhost:11434"
        )

        # Extract model name from the provider config
        model_identifier = self.provider_config.get("model", "")
        if model_identifier.startswith("ollama/"):
            self.model_name_for_api = model_identifier.split("/", 1)[1]
        else:
            self.model_name_for_api = model_identifier

        if not self.model_name_for_api:
            raise ValueError(
                "Ollama model name could not be determined from configuration."
            )

        self.request_timeout = float(
            self.provider_config.get("request_timeout", 120.0)
        )  # ollama lib uses 'timeout'
        self.keep_alive = self.provider_config.get("keep_alive", "5m")
        self.ollama_options = self.provider_config.get("options", {})

        # Initialize Ollama clients to check model capabilities before setting all params
        # The 'host' parameter in ollama.Client corresponds to api_base
        # The 'timeout' parameter is for the HTTP request timeout
        self.client = ollama.Client(
            host=self.api_base, timeout=self.request_timeout
        )
        self.async_client = ollama.AsyncClient(
            host=self.api_base, timeout=self.request_timeout
        )

        # Set 'thinking' capability. Default to False if not explicitly configured.
        self.enable_thinking = self.provider_config.get(
            "enable_thinking", False
        )
        self.thinking_available = self._check_model_thinking_capability(
            self.model_name_for_api
        )

        self._context_window = self._initialize_context_window(
            model_name=self.model_name_for_api,
            provider_config=self.provider_config,
        )

        logger.info(
            f"OllamaLLM initialized for model '{self.model_name_for_api}' at"
            f" {self.api_base} using 'ollama' library. Context:"
            f" {self._context_window}. Options: {self.ollama_options}."
            f" Thinking enabled: {self.enable_thinking}."
            f" Thinking available: {self.thinking_available}."
        )

    def _check_model_thinking_capability(self, model_name: str) -> bool:
        """
        Check if the Ollama model supports 'thinking' by making a test call.
        """
        try:
            logger.info(
                f"Testing model '{model_name}' for 'thinking' capability..."
            )
            # Perform a minimal, non-streaming chat call with thinking enabled.
            self.client.chat(
                model=model_name,
                messages=[{"role": "user", "content": "hello"}],
                stream=False,
                think=True,
                options={"num_predict": 1},  # Minimize generation
            )
            logger.info(
                f"Model '{model_name}' supports 'thinking'. Enabling by"
                " default."
            )
            return True
        except ollama.ResponseError as e:
            # Check if the error indicates that the model does not support thinking
            if "does not support thinking" in e.error.lower():
                logger.info(
                    f"Model '{model_name}' does not support 'thinking'."
                    " Disabling by default."
                )
                return False
            else:
                # Some other API error occurred
                logger.warning(
                    "Ollama API error while testing for 'thinking' capability"
                    f" for {model_name}: {e}. Disabling by default."
                )
                return False
        except Exception as e:
            logger.warning(
                "Unexpected error while testing for 'thinking' capability"
                f" for {model_name}: {e}. Disabling by default."
            )
            return False

    def _get_token_count(self, text: str, role: str) -> int:
        """Get accurate token count using LiteLLM"""
        if not text:
            return 0

        try:
            count = token_counter(
                model=self.model_name_for_api,
                messages=[{"role": role, "content": text}],
            )
            return count
        except Exception:
            raise RuntimeError("Can't get the amount of tokens for " + role)

    def add_msg(
        self, new_message: str, chat_history: List, role: str
    ) -> List[dict]:
        """Format user chat message for LLM processing with token count"""
        timestamp = datetime.now()
        new_message_ts = f"[{timestamp.strftime("%H:%M")}] {new_message}"
        token_count = self._get_token_count(new_message_ts, role)
        chat_history.append(
            {"role": role, "content": new_message_ts, "tokens": token_count}
        )
        self.logger.debug(f"Added {role} message with {token_count} tokens")
        return chat_history

    def _get_ollama_provider_config_entry(self) -> Optional[Dict[str, Any]]:
        llm_config = self.config_manager.get("llm", {})
        selected_provider_identifier = llm_config.get("selected_provider")
        if not selected_provider_identifier:
            return None
        for provider_conf in llm_config.get("providers", []):
            if provider_conf.get("model") == selected_provider_identifier:
                is_ollama_prefixed = selected_provider_identifier.startswith(
                    "ollama/"
                )
                provider_type = provider_conf.get("provider_type", "").lower()
                if (
                    provider_type
                    and provider_type != "ollama"
                    and not is_ollama_prefixed
                ):
                    return None
                logger.info(
                    "Found Ollama configuration for:"
                    f" {selected_provider_identifier}"
                )
                return provider_conf
        return None

    def _fetch_backend_context_window(self, model_name: str) -> Optional[int]:
        """Fetch context window from Ollama model details."""
        try:
            details = self.client.show(model=model_name)
            params_str = details.get("parameters", "")
            for line in params_str.split("\n"):
                if "num_ctx" in line:
                    try:
                        return int(line.split()[-1])
                    except (ValueError, IndexError):
                        self.logger.warning(
                            f"Could not parse num_ctx from line: {line}"
                        )
            return None
        except Exception as e:
            self.logger.error(
                f"Error getting context window for {model_name} using ollama"
                f" lib: {e}."
            )
            return None

    def get_context_window(self) -> int:
        return self._context_window

    def _prepare_messages_for_ollama(
        self, chat_history: List[Dict]
    ) -> List[Dict]:
        messages = []
        for msg in chat_history:
            if "role" in msg and "content" in msg:
                messages.append(
                    {"role": msg["role"], "content": msg["content"]}
                )
        return messages

    def chat(
        self,
        chat_history: List[Dict],
        stream: bool = True,
        provider: Optional[Dict] = None,
        reasoning_level: Optional[float] = None,
    ) -> Union[str, Generator[str, None, None]]:
        messages = self._prepare_messages_for_ollama(chat_history)

        logger.info(
            "Sending request to ollama.chat for model"
            f" {self.model_name_for_api}, reasoning_level: {reasoning_level}."
        )
        logger.debug(
            f"Ollama chat options: {self.ollama_options}, keep_alive:"
            f" {self.keep_alive}"
        )

        use_thinking = self.enable_thinking or (
            self.thinking_available
            and reasoning_level is not None
            and reasoning_level > 0
        )
        if use_thinking:
            logger.info(
                f"Requesting thinking for model {self.model_name_for_api}"
            )
        else:
            logger.info(
                f"Avoiding thinking for model {self.model_name_for_api}"
            )

        try:
            if stream:

                def stream_generator():
                    response_stream = self.client.chat(
                        model=self.model_name_for_api,
                        messages=messages,
                        stream=True,
                        think=use_thinking,
                        options=self.ollama_options,
                        keep_alive=self.keep_alive,
                    )
                    for chunk in response_stream:
                        content_part = chunk.get("message", {}).get("content")
                        if content_part is not None:
                            yield content_part

                return stream_generator()
            else:  # Non-streaming sync
                response_data = self.client.chat(
                    model=self.model_name_for_api,
                    messages=messages,
                    stream=False,
                    think=use_thinking,
                    options=self.ollama_options,
                    keep_alive=self.keep_alive,
                )
                message = response_data.get("message", {})
                content = message.get("content", "")
                thinking = message.get("thinking")
                logger.debug(f"Ollama thinking content: {thinking}")
                # thinking is not returned anymore
                return content

        except ollama.ResponseError as e:
            logger.error(
                f"Ollama API error (ollama.chat): {e.status_code} - {e.error}"
            )
            raise ValueError(f"Ollama API error: {e.error}") from e
        except Exception as e:
            logger.error(f"Error in Ollama chat (ollama.chat): {str(e)}")
            raise ValueError(
                f"Error communicating with Ollama: {str(e)}"
            ) from e

    async def achat(
        self,
        chat_history: List[Dict],
        stream: bool = True,
        provider: Optional[Dict] = None,
        reasoning_level: Optional[float] = None,
    ) -> Union[str, AsyncGenerator[str, None]]:
        messages = self._prepare_messages_for_ollama(chat_history)

        logger.info(
            "Sending async request to ollama.chat for model"
            f" {self.model_name_for_api}. Stream: {stream}. reasoning_level:"
            f" {reasoning_level}"
        )
        logger.debug(
            f"Ollama async chat options: {self.ollama_options}, keep_alive:"
            f" {self.keep_alive}"
        )

        use_thinking = (
            self.enable_thinking
            and reasoning_level is not None
            and reasoning_level > 0
        )
        if use_thinking:
            logger.info(
                "Requesting thinking for model"
                f" {self.model_name_for_api} (async)"
            )

        try:
            if stream:

                async def stream_generator():
                    response_stream = await self.async_client.chat(
                        model=self.model_name_for_api,
                        messages=messages,
                        stream=stream,
                        think=use_thinking,
                        options=self.ollama_options,
                        keep_alive=self.keep_alive,
                    )
                    # Each item in stream is like:
                    # {'model': '...', 'created_at': '...', 'message': {'role': 'assistant', 'content': '...'}, 'done': False}
                    # Final item has 'done': True and full stats
                    async for chunk in response_stream:
                        content_part = chunk.get("message", {}).get("content")
                        if content_part is not None:
                            yield content_part

                return stream_generator()
            else:  # Non-streaming async
                response_data = await self.async_client.chat(
                    model=self.model_name_for_api,
                    messages=messages,
                    stream=False,
                    think=use_thinking,
                    options=self.ollama_options,
                    keep_alive=self.keep_alive,
                )
                message = response_data.get("message", {})
                content = message.get("content", "")
                thinking = message.get("thinking")
                logger.debug(f"Ollama async thinking content: {thinking}")
                # thinking is not returned anymore
                return content

        except ollama.ResponseError as e:
            logger.error(
                f"Ollama API async error (ollama.chat): {e.status_code} -"
                f" {e.error}"
            )
            raise ValueError(f"Ollama API async error: {e.error}") from e
        except Exception as e:
            logger.error(f"Error in Ollama async chat (ollama.chat): {str(e)}")
            raise ValueError(
                f"Error communicating with Ollama (async): {str(e)}"
            ) from e

    def get_available_models(self) -> List[Dict[str, Any]]:
        try:
            models_data = (
                self.client.list()
            )  # ollama.list() returns a list of model details
            available_models = []
            for model_info in models_data.get(
                "models", []
            ):  # ollama.list() structure is {'models': [...]}
                model_api_name = model_info.get("name")
                available_models.append(
                    {
                        "name": f"ollama/{model_api_name}",
                        "model_name_for_api": model_api_name,
                        "modified_at": model_info.get("modified_at"),
                        "size": model_info.get("size"),
                        "provider": "ollama",
                        "provider_type": "ollama",
                        "api_base": self.api_base,
                    }
                )
            logger.info(
                f"Found {len(available_models)} models on Ollama instance"
                f" {self.api_base} using ollama lib."
            )
            return available_models
        except Exception as e:  # Catch ollama.ResponseError and others
            logger.error(
                "Could not retrieve models from Ollama instance"
                f" {self.api_base} using ollama lib: {e}"
            )
            return []

    def normalize_model_name(
        self, model: str, provider: str = "ollama"
    ) -> str:
        if model.startswith("ollama/"):
            return model.split("/", 1)[1]
        return model

    def initialize_provider(
        self, config_manager_override: Optional[ConfigManager] = None
    ) -> dict:
        # Re-initialize if an override config manager is provided, as settings might change.
        if config_manager_override:
            original_cm = self.config_manager
            self.config_manager = config_manager_override  # Temporarily switch

            self.provider_config = self._get_ollama_provider_config_entry()
            if not self.provider_config:
                selected_provider_id = self.config_manager.get(
                    "llm.selected_provider", ""
                )
                if selected_provider_id.startswith("ollama/"):
                    self.provider_config = self.config_manager.get(
                        "llm.providers_config.ollama", {}
                    )
                    self.provider_config.setdefault(
                        "api_base", "http://localhost:11434"
                    )
                else:  # Should not happen if factory logic is correct
                    self.config_manager = original_cm  # Revert
                    raise RuntimeError(
                        "Ollama provider configuration could not be"
                        " re-initialized with override."
                    )

            self.api_base = self.provider_config.get("api_base", self.api_base)
            selected_provider_id = self.config_manager.get(
                "llm.selected_provider", ""
            )
            self.model_name_for_api = self.provider_config.get(
                "model_name_for_api",
                (
                    selected_provider_id.split("/", 1)[1]
                    if selected_provider_id.startswith("ollama/")
                    else selected_provider_id
                ),
            )
            self.request_timeout = float(
                self.provider_config.get(
                    "request_timeout", self.request_timeout
                )
            )
            self.ollama_options = self.provider_config.get(
                "options", self.ollama_options
            )

            # Re-initialize clients with potentially new api_base or timeout
            self.client = ollama.Client(
                host=self.api_base, timeout=self.request_timeout
            )
            self.async_client = ollama.AsyncClient(
                host=self.api_base, timeout=self.request_timeout
            )

            self.config_manager = original_cm  # Revert to original CM

            self.thinking_available = self._check_model_thinking_capability(
                self.model_name_for_api
            )

        return {
            "model": self.model_name_for_api,
            "api_base": self.api_base,
            "ollama_options": self.ollama_options,
            "keep_alive": self.keep_alive,
        }
