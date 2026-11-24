# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
#
# This file is dual-licensed under:
# 1. GNU Lesser General Public License v3.0 (LGPL-3.0)
#    (See the included LICENSE_LGPL3.txt file or look into
#    <https://www.gnu.org/licenses/lgpl-3.0.html for details)
# 2. Commercial license
#    (Contact: rgomez@khromalabs.org for licensing)
#
# You may use, distribute and modify this code under the terms of either license.
# This notice must be preserved in all copies or substantial portions of the code.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.

"""Vector mirror recipe gate.

The vector store (Chroma) is a disposable mirror: every collection in
it is derivable from the relational source of truth (chat messages,
user memories) plus the derivation "recipe" — the metadata schema
version and the embedding model. When the recipe changes, the existing
mirror is stale *by definition* (e.g. collections written before
recipe v2 lack the numeric "timestamp_ts" metadata that date-scoped
semantic search filters on, and range operators on the old ISO-string
metadata cannot work), and the correct response is not to repair it
but to delete and rebuild it from the relational store.

Each consumer family ("chat" history collections, "profile" memory
collections) records its own model in the marker file, since they may
use different embedding models. A family whose recipe entry is missing
or stale must rebuild its collections before its indexes can be
considered current.

The marker is advisory state for the rebuild decision only — no data
lives in it, and losing it merely triggers a (harmless) rebuild.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# v1: pre-recipe mirrors (ISO-string "timestamp" metadata only).
# v2: adds numeric "timestamp_ts" epoch metadata for native date
# filtering in vector stores.
RECIPE_VERSION = 2

MARKER_FILENAME = ".vector_recipe"

# Known consumer families. Values are the config key holding that
# family's embedding model (informational).
FAMILIES = {
    "chat": "memory.vector_storage.embedding_model",
    "profile": "user_profile.vector_storage.embedding_model",
}


def _marker_path(vector_db_path: str) -> Path:
    return Path(vector_db_path) / MARKER_FILENAME


def read_marker(vector_db_path: str) -> Dict:
    """Read the recipe marker, returning {} when absent/corrupt."""
    try:
        raw = _marker_path(vector_db_path).read_text(encoding="utf-8")
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def is_current(
    vector_db_path: str, family: str, embedding_model: str
) -> bool:
    """Whether the family's collections were built with the current
    recipe (schema version + embedding model)."""
    marker = read_marker(vector_db_path)
    if marker.get("recipe_version") != RECIPE_VERSION:
        return False
    models = marker.get("models")
    return isinstance(models, dict) and models.get(family) == embedding_model


def mark_current(
    vector_db_path: str, family: str, embedding_model: str
) -> None:
    """Record that the family's collections now follow the current
    recipe. Missing keys for other families are preserved."""
    marker = read_marker(vector_db_path)
    models = marker.get("models")
    if not isinstance(models, dict):
        models = {}
    models[family] = embedding_model
    marker["recipe_version"] = RECIPE_VERSION
    marker["models"] = models
    try:
        path = _marker_path(vector_db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(marker, indent=2, sort_keys=True), encoding="utf-8"
        )
    except OSError as e:
        logger.warning(f"Could not write vector recipe marker: {e}")


def stale_reason(
    vector_db_path: str, family: str, embedding_model: str
) -> Optional[str]:
    """Human-readable reason the mirror is stale, or None when current."""
    marker = read_marker(vector_db_path)
    if marker.get("recipe_version") != RECIPE_VERSION:
        return (
            f"recipe version {marker.get('recipe_version')!r} !="
            f" {RECIPE_VERSION}"
        )
    models = marker.get("models")
    if not isinstance(models, dict) or models.get(family) != embedding_model:
        return f"embedding model for family {family!r} changed"
    return None
