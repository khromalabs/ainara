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

from .base import LLMBackend
from .litellm import LiteLLM


def create_llm_backend(config: dict) -> LLMBackend:
    """Factory function to create LLM backend instance

    Args:
        config: Configuration dictionary for LLM backend

    Returns:
        Configured LLM backend instance
    """
    # The 'config' parameter here is the specific dictionary for one LLM provider
    # from the evaluation loop, or the general llm config during normal app use.
    # For evaluation, 'provider' key usually indicates the type (e.g., 'litellm').
    # For general use, 'backend' key in the main llm config block indicates the type.
    backend_type = config.get("provider", config.get("backend", "litellm"))

    if backend_type == "litellm":
        # Pass the specific provider_config to LiteLLM
        # If 'config' is from the evaluator, it's already a specific provider_config.
        # If 'config' is the global llm config, LiteLLM's constructor will handle it.
        return LiteLLM(provider_config=config if "model" in config else None)
    else:
        raise ValueError(f"Unsupported LLM backend type: {backend_type}")
