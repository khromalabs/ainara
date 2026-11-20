# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
#
# This file is dual-licensed under:
# 1. GNU Lesser General Public License v3.0 (LGPL-3.0)
#    (See the included LICENSE_LGPL3.txt file or look into
#    <https://www.gnu.org/licenses/lgpl-3.0.html for details)
# 2. Commercial license
#    (Contact: rgomez@khromalabs.org for licensing options)
#
# You may use, distribute and modify this code under the terms of either license.
# This notice must be preserved in all copies or substantial portions of the code.

"""Orakle capability payload handling for the routing benchmark.

The benchmark consumes a LEAN projection of the Orakle capabilities as
served by ``GET /capabilities?type=llm``: capability id, semantic
description and the parameter contract from ``run_info``.

``matcher_info`` is deliberately EXCLUDED: it is embedding-routing text
("DO NOT use for X. Keywords: ..."), written for the retrieval stage and
actively harmful if surfaced to a chat model. Any enumeration or warming
input must be built from the lean view only.

Snapshots are stored as fixture files so runs are reproducible and
offline-safe after the first fetch.
"""

import hashlib
import json
import logging
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_ORAKLE_URL = "http://localhost:8100"


@dataclass
class Parameter:
    """A single parameter of a capability's contract."""

    name: str
    type: str
    description: str
    required: bool = False
    default: Any = None


@dataclass
class Capability:
    """Lean view of one capability."""

    id: str
    description: str
    parameters: List[Parameter] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "parameters": [
                {
                    "name": p.name,
                    "type": p.type,
                    "description": p.description,
                    "required": p.required,
                    "default": p.default,
                }
                for p in self.parameters
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Capability":
        return cls(
            id=data["id"],
            description=data.get("description", ""),
            parameters=[
                Parameter(
                    name=p["name"],
                    type=p.get("type", "any"),
                    description=p.get("description", ""),
                    required=p.get("required", False),
                    default=p.get("default"),
                )
                for p in data.get("parameters", [])
            ],
        )


def fetch_llm_payload(orakle_url: str = DEFAULT_ORAKLE_URL) -> Dict[str, Any]:
    """Fetch the raw ``type=llm`` payload from a running Orakle server."""
    url = orakle_url.rstrip("/") + "/capabilities?type=llm"
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def lean_from_llm_payload(
    payload: Dict[str, Any],
) -> Dict[str, Capability]:
    """Extract the lean view from a raw ``type=llm`` payload.

    The payload maps capability id -> {description, run_info: {...}}.
    Only the semantic description and the parameter contract survive;
    ``matcher_info`` and everything execution-related are dropped.
    """
    registry: Dict[str, Capability] = {}
    for cap_id, raw in payload.items():
        if not isinstance(raw, dict):
            continue
        run_info = raw.get("run_info") or {}
        raw_params = run_info.get("parameters") or {}
        params: List[Parameter] = []
        for name, p in raw_params.items():
            if not isinstance(p, dict):
                continue
            params.append(
                Parameter(
                    name=name,
                    type=str(p.get("type", "any")),
                    description=p.get("description", "") or "",
                    required=bool(p.get("required", False)),
                    default=p.get("default"),
                )
            )
        registry[cap_id] = Capability(
            id=cap_id,
            description=(raw.get("description") or "").strip(),
            parameters=params,
        )
    return registry


def fingerprint(registry: Dict[str, Capability]) -> str:
    """Stable content hash of a registry (cache-invalidation key).

    Hashes the lean content (ids, descriptions, parameter contracts),
    NOT dict ordering or any rendering decision.
    """
    canonical = {
        cap_id: cap.to_dict() for cap_id, cap in sorted(registry.items())
    }
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def save_snapshot(
    registry: Dict[str, Capability], path: str, source_url: str = ""
) -> None:
    """Persist a registry snapshot as a fixture file."""
    doc = {
        "source_url": source_url,
        "fingerprint": fingerprint(registry),
        "capabilities": {
            cap_id: cap.to_dict() for cap_id, cap in sorted(registry.items())
        },
    }
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True)
    logger.info(
        "Saved snapshot of %d capabilities to %s", len(registry), path
    )


def load_snapshot(path: str) -> Dict[str, Capability]:
    """Load a registry snapshot fixture."""
    with open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    registry = {
        cap_id: Capability.from_dict(data)
        for cap_id, data in doc["capabilities"].items()
    }
    stored = doc.get("fingerprint")
    actual = fingerprint(registry)
    if stored and stored != actual:
        logger.warning(
            "Snapshot fingerprint mismatch in %s (stored=%s actual=%s); "
            "content may have been edited by hand",
            path,
            stored,
            actual,
        )
    return registry


def snapshot_registry(
    orakle_url: str = DEFAULT_ORAKLE_URL,
    out_path: Optional[str] = None,
) -> Dict[str, Capability]:
    """Fetch + extract + (optionally) persist in one step."""
    payload = fetch_llm_payload(orakle_url)
    registry = lean_from_llm_payload(payload)
    if out_path:
        save_snapshot(registry, out_path, source_url=orakle_url)
    return registry
