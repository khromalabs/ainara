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
from ainara.framework.storage.langchain_sqlite import \
    LangChainSQLiteStorage
from ainara.framework.storage.langchain_vector import \
    LangChainVectorStorage

# Registry of available text storage backends
TEXT_BACKENDS = {
    "sqlite": LangChainSQLiteStorage,
}

# Registry of available vector storage backends
VECTOR_BACKENDS = {
    "chroma": LangChainVectorStorage,
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
    "register_text_backend",
    "register_vector_backend",
]