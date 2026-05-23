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


from ainara.framework.storage.base import StorageBackend
from ainara.framework.storage.sqlite import SQLiteStorage
from ainara.framework.storage.chroma import ChromaVectorStorage

# Registry of available text storage backends
TEXT_BACKENDS = {
    "sqlite": SQLiteStorage,
}

# Registry of available vector storage backends
VECTOR_BACKENDS = {
    "chroma": ChromaVectorStorage,
}


def get_text_backend(backend_type, **config):
    """Get a text storage backend instance by type"""
    if backend_type not in TEXT_BACKENDS:
        raise ValueError(f"Unknown text backend type: {backend_type}")
    return TEXT_BACKENDS[backend_type](**config)


def get_vector_backend(backend_type, **config):
    """Get a vector storage backend instance by type"""
    if backend_type not in VECTOR_BACKENDS:
        raise ValueError(f"Unknown vector backend type: {backend_type}")
    return VECTOR_BACKENDS[backend_type](**config)


def create_system_storage():
    """
    Creates and returns the configured text storage backend.
    This allows the storage to be instantiated independently of ChatMemory,
    enabling its use for system-wide features like Authentication.
    """
    import os
    from ainara.framework.config import config

    # Get text storage configuration
    text_type = config.get("memory.text_storage.type", "sqlite")
    text_path = config.get(
        "memory.text_storage.storage_path",
        os.path.join(config.get("data.directory"), "chat_memory.db"),
    )

    # Ensure path is expanded
    text_path = os.path.expanduser(text_path)

    # Default context (matches ChatMemory default)
    context = config.get("memory.default_context", {"persona": "default"})
    context_id = "_".join(f"{k}-{v}" for k, v in sorted(context.items()))

    return get_text_backend(
        text_type, db_path=text_path, context_id=context_id
    )


def register_text_backend(name, backend_class):
    """Register a custom text backend"""
    TEXT_BACKENDS[name] = backend_class


def register_vector_backend(name, backend_class):
    """Register a custom vector backend"""
    VECTOR_BACKENDS[name] = backend_class


__all__ = [
    "StorageBackend",
    "TEXT_BACKENDS",
    "VECTOR_BACKENDS",
    "get_text_backend",
    "get_vector_backend",
    "create_system_storage",
    "register_text_backend",
    "register_vector_backend",
]
