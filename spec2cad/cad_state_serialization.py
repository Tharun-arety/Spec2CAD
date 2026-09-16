"""Canonical identity for immutable CAD State Graph observations."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from spec2cad.schemas.cad_state_graph import CADStateGraph


class CADStateGraphManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    graph_id: str
    graph_schema_version: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_length: int = Field(gt=0)


def canonical_csg_bytes(graph: CADStateGraph) -> bytes:
    return json.dumps(
        graph.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def csg_content_hash(graph: CADStateGraph) -> str:
    return hashlib.sha256(canonical_csg_bytes(graph)).hexdigest()


def csg_manifest(graph: CADStateGraph) -> CADStateGraphManifest:
    payload = canonical_csg_bytes(graph)
    return CADStateGraphManifest(
        graph_id=graph.id,
        graph_schema_version=graph.schema_version,
        content_sha256=hashlib.sha256(payload).hexdigest(),
        byte_length=len(payload),
    )
