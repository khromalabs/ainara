from .base import LLMBackend
from .litellm import LiteLLM


def create_llm_backend(config: dict) -> LLMBackend:
    """Factory function to create LLM backend instance

    Args:
        config: Configuration dictionary for LLM backend

    Returns:
        Configured LLM backend instance
    """
    backend_type = config.get("backend", "litellm")

    if backend_type == "litellm":
        return LiteLLM()
    else:
        raise ValueError(f"Unsupported LLM backend type: {backend_type}")
