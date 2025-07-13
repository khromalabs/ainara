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

from ainara.framework.config import config as config_manager

from .base import LLMBackend
from .litellm import LiteLLM
from .ollama import OllamaLLM

logger = logging.getLogger(__name__)


def create_llm_backend(
    llm_config: dict = None, selected_provider: str = None
) -> LLMBackend:
    """Factory function to create LLM backend instance

    Args:
        llm_config: Full LLM configuration dictionary (optional if using config_manager)
        selected_provider: Specific provider/model identifier to use

    Returns:
        Configured LLM backend instance
    """
    # Use provided config or get from config manager
    if llm_config is None:
        llm_config = config_manager.get("llm", {})

    # Determine which provider to use
    selected_provider_identifier = selected_provider or llm_config.get(
        "selected_provider"
    )

    if not selected_provider_identifier:
        logger.info(
            "No LLM provider selected in config. Defaulting to LiteLLM."
        )
        return LiteLLM(config_manager)

    # Find the specific provider configuration
    provider_config = None
    for provider in llm_config.get("providers", []):
        if (
            provider.get("model") == selected_provider_identifier
            or provider.get("name") == selected_provider_identifier
        ):
            provider_config = provider
            break

    if not provider_config:
        logger.warning(
            f"Provider '{selected_provider_identifier}' not found in config."
            " Using default LiteLLM."
        )
        return LiteLLM(config_manager)

    # Determine backend type based on provider identifier or provider config
    backend_to_use = provider_config.get(
        "provider", llm_config.get("selected_backend", "litellm")
    )
    if selected_provider_identifier.startswith("ollama/"):
        backend_to_use = "ollama"

    logger.info(
        f"Selected LLM backend type: '{backend_to_use}' for provider:"
        f" '{selected_provider_identifier}'"
    )

    if backend_to_use == "ollama":
        return OllamaLLM(config_manager, provider_config=provider_config)
    elif backend_to_use == "litellm":
        return LiteLLM(provider_config=provider_config)
    else:
        logger.warning(
            f"Unknown LLM backend type '{backend_to_use}'. Defaulting to"
            " LiteLLM."
        )
        return LiteLLM(provider_config=provider_config)
