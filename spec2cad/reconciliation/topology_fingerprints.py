"""Canonical semantic topology identity independent of native index ordering."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN
import hashlib
import json
import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from spec2cad.cad_state_serialization import csg_content_hash
from spec2cad.schemas.cad_state_graph import (
    CADStateGraph,
    QuantityUnit,
    SemanticTopologyNode,
    TopologyKind,
)
from spec2cad.schemas.feature_ir import StableId


TOPOLOGY_FINGERPRINT_SCHEMA_VERSION = "1.0.0"
TOPOLOGY_FINGERPRINT_POLICY_VERSION = "1.0.0"
_LENGTH_QUANTUM = Decimal("0.01")
_DIRECTION_QUANTUM = Decimal("0.000000001")
_TRANSIENT_ROLE_PATTERN = r"^(?P<base>[a-z][a-z0-9_]*)_[0-9a-f]{16}$"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FingerprintMeasurement(_FrozenModel):
    name: StableId
    value: float = Field(allow_inf_nan=False)
    unit: QuantityUnit


def _semantic_payload(fingerprint: "TopologyFingerprint") -> dict:
    return {
        "policy_version": fingerprint.policy_version,
        "numeric_quantum": fingerprint.numeric_quantum,
        "direction_quantum": fingerprint.direction_quantum,
        "topology_kind": fingerprint.topology_kind.value,
        "semantic_role": fingerprint.semantic_role,
        "geometry_type": fingerprint.geometry_type,
        "centroid_mm": fingerprint.centroid_mm,
        "direction": fingerprint.direction,
        "measurements": [
            item.model_dump(mode="json") for item in fingerprint.measurements
        ],
        "adjacent_semantic_roles": fingerprint.adjacent_semantic_roles,
    }


def _payload_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class TopologyFingerprint(_FrozenModel):
    schema_version: Literal["1.0.0"] = TOPOLOGY_FINGERPRINT_SCHEMA_VERSION
    policy_version: Literal["1.0.0"] = TOPOLOGY_FINGERPRINT_POLICY_VERSION
    numeric_quantum: Literal[0.01] = 0.01
    direction_quantum: Literal[1e-09] = 1e-09
    id: StableId
    source_csg_id: StableId
    source_csg_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_topology_id: StableId
    topology_kind: TopologyKind
    semantic_role: StableId
    geometry_type: StableId
    centroid_mm: tuple[float, float, float] | None = None
    direction: tuple[float, float, float] | None = None
    measurements: tuple[FingerprintMeasurement, ...] = ()
    adjacent_semantic_roles: tuple[StableId, ...] = ()
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_content_identity(self) -> "TopologyFingerprint":
        if self.content_sha256 != _payload_hash(_semantic_payload(self)):
            raise ValueError("topology fingerprint content hash does not match payload")
        if len(self.adjacent_semantic_roles) != len(set(self.adjacent_semantic_roles)):
            raise ValueError("adjacent semantic roles must be unique")
        measurement_keys = [(item.name, item.unit) for item in self.measurements]
        if len(measurement_keys) != len(set(measurement_keys)):
            raise ValueError("fingerprint measurements must be unique by name and unit")
        return self


def _quantize(value: float, quantum: Decimal) -> float:
    result = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_EVEN)
    return 0.0 if result == 0 else float(result)


def _vector(
    value: tuple[float, float, float] | None,
    quantum: Decimal,
    *,
    normalize: bool = False,
) -> tuple[float, float, float] | None:
    if value is None:
        return None
    if normalize:
        magnitude = math.sqrt(sum(component * component for component in value))
        if magnitude == 0:
            raise ValueError("topology direction cannot be a zero vector")
        value = tuple(component / magnitude for component in value)
    return tuple(_quantize(component, quantum) for component in value)


def topology_fingerprints(
    graph: CADStateGraph,
) -> tuple[TopologyFingerprint, ...]:
    """Fingerprint every semantic topology node in deterministic semantic order."""
    topology = {
        item.id: item
        for item in graph.nodes
        if isinstance(item, SemanticTopologyNode)
    }
    normalized = {}
    for node in topology.values():
        measurements = tuple(sorted(
            (
                FingerprintMeasurement(
                    name=item.name,
                    value=_quantize(item.value, _LENGTH_QUANTUM),
                    unit=item.unit,
                )
                for item in node.measurements
            ),
            key=lambda item: (item.name, item.unit.value),
        ))
        direction = _vector(node.direction, _DIRECTION_QUANTUM, normalize=True)
        centroid = _vector(node.centroid_mm, _LENGTH_QUANTUM)
        if node.geometry_type == "cylinder" and centroid and direction:
            axial_offset = sum(
                coordinate * axis for coordinate, axis in zip(centroid, direction)
            )
            centroid = tuple(
                _quantize(coordinate - axial_offset * axis, _LENGTH_QUANTUM)
                for coordinate, axis in zip(centroid, direction)
            )
        normalized[node.id] = {
            "centroid_mm": centroid,
            "direction": direction,
            "measurements": measurements,
        }

    canonical_roles = {}
    transient_groups = {}
    for node in topology.values():
        match = re.fullmatch(_TRANSIENT_ROLE_PATTERN, node.semantic_role)
        if match is None:
            canonical_roles[node.id] = node.semantic_role
        else:
            transient_groups.setdefault(match.group("base"), []).append(node)
    for base, nodes in transient_groups.items():
        nodes.sort(key=lambda node: (
            node.topology_kind.value,
            node.geometry_type,
            normalized[node.id]["centroid_mm"] or (),
            normalized[node.id]["direction"] or (),
            tuple(
                (item.name, item.unit.value, item.value)
                for item in normalized[node.id]["measurements"]
            ),
            node.id,
        ))
        for index, node in enumerate(nodes):
            canonical_roles[node.id] = f"{base}.{index}"

    fingerprints = []
    for node in sorted(
        topology.values(),
        key=lambda item: (canonical_roles[item.id], item.geometry_type, item.id),
    ):
        measurements = normalized[node.id]["measurements"]
        adjacent_roles = tuple(sorted({
            canonical_roles[item] for item in node.adjacent_topology_ids
        }))
        data = {
            "policy_version": TOPOLOGY_FINGERPRINT_POLICY_VERSION,
            "numeric_quantum": float(_LENGTH_QUANTUM),
            "direction_quantum": float(_DIRECTION_QUANTUM),
            "topology_kind": node.topology_kind.value,
            "semantic_role": canonical_roles[node.id],
            "geometry_type": node.geometry_type,
            "centroid_mm": normalized[node.id]["centroid_mm"],
            "direction": normalized[node.id]["direction"],
            "measurements": [item.model_dump(mode="json") for item in measurements],
            "adjacent_semantic_roles": adjacent_roles,
        }
        content_hash = _payload_hash(data)
        fingerprints.append(TopologyFingerprint(
            id=f"fingerprint.{content_hash[:32]}",
            source_csg_id=graph.id,
            source_csg_sha256=csg_content_hash(graph),
            source_topology_id=node.id,
            topology_kind=node.topology_kind,
            semantic_role=canonical_roles[node.id],
            geometry_type=node.geometry_type,
            centroid_mm=data["centroid_mm"],
            direction=data["direction"],
            measurements=measurements,
            adjacent_semantic_roles=adjacent_roles,
            content_sha256=content_hash,
        ))
    return tuple(fingerprints)
