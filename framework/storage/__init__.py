# Ainara - Open Source AI Assistant Framework
# Copyright (C) 2025 Rubén Gómez - khromalabs.org

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.

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
