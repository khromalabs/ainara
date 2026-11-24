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
mirror is stale *by definition* (e.g. collections written before an
epoch-mirror metadata field lack the numeric keys that date-scoped
search filters on, and range operators on ISO-string metadata cannot
work), and the correct response is not to repair it but to delete and
rebuild it from the relational store.

Each consumer family records its own recipe version and model in the
marker file, since families evolve independently and may use different
embedding models:

- "chat": conversation-log collections.
    v2: numeric "timestamp_ts" epoch mirror for date-scoped semantic
    search.
- "profile": GREEN memory collections.
    v3: numeric "created_ts"/"updated_ts" epoch mirrors for
    date-scoped memory retrieval.

A family whose recipe entry is missing or stale must rebuild its
collections before its indexes can be considered current.

The marker is advisory state for the rebuild decision only — no data
lives in it, and losing it merely triggers a (harmless) rebuild.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Per-family metadata schema versions. Bump a family's version whenever
# its vector metadata shape changes; only that family rebuilds.
FAMILY_RECIPES = {
    "chat": 2,
    "profile": 3,
}

MARKER_FILENAME = ".vector_recipe"

# Known consumer families. Values are the config key holding that
# family's embedding model (informational).
FAMILY_MODEL_KEYS = {
    "chat": "memory.vector_storage.embedding_model",
    "profile": "user_profile.vector_storage.embedding_model",
}


def _marker_path(vector_db_path: str) -> Path:
    return Path(vector_db_path) / MARKER_FILENAME


def _family_recipes(marker: Dict) -> Dict:
    """Recipes dict from a marker, with compatibility for the pre-v3
    single-version marker format ({"recipe_version": 2}): only "chat"
    existed at v2 and its schema has not changed since, so "chat" maps
    to the old global version while every other family reads as unset
    (stale)."""
    recipes = marker.get("recipes")
    if isinstance(recipes, dict):
        return recipes
    legacy = marker.get("recipe_version")
    if legacy == 2:
        return {"chat": 2}
    return {}


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
    recipes = _family_recipes(marker)
    if recipes.get(family) != FAMILY_RECIPES.get(family):
        return False
    models = marker.get("models")
    return isinstance(models, dict) and models.get(family) == embedding_model


def mark_current(
    vector_db_path: str, family: str, embedding_model: str
) -> None:
    """Record that the family's collections now follow the current
    recipe. Entries for other families are preserved."""
    marker = read_marker(vector_db_path)
    recipes = _family_recipes(marker)
    models = marker.get("models")
    if not isinstance(models, dict):
        models = {}
    recipes[family] = FAMILY_RECIPES[family]
    models[family] = embedding_model
    marker["recipes"] = recipes
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
    recipes = _family_recipes(marker)
    expected = FAMILY_RECIPES.get(family)
    if recipes.get(family) != expected:
        return (
            f"recipe version {recipes.get(family)!r} != {expected}"
            f" for family {family!r}"
        )
    models = marker.get("models")
    if not isinstance(models, dict) or models.get(family) != embedding_model:
        return f"embedding model for family {family!r} changed"
    return None
