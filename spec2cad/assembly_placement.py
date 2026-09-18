"""Validate one explicit two-component placement from semantic interface frames.

The transforms are supplied by the caller. This module never searches for or
solves a placement and never invokes a CAD kernel.
"""

from __future__ import annotations

import hashlib
import json
import math
from enum import Enum
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from spec2cad.schemas.intent_graph import EngineeringIntentGraph, InterfaceNode


PLACEMENT_SCHEMA_VERSION = "1.0.0"
PLACEMENT_METHOD_VERSION = "1.0.0"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RigidTransform(_FrozenModel):
    translation_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation_axis: tuple[float, float, float] = (0.0, 0.0, 1.0)
    rotation_degrees: float = 0.0

    @model_validator(mode="after")
    def validate_finite_rigid_transform(self):
        values = (
            *self.translation_mm,
            *self.rotation_axis,
            self.rotation_degrees,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("rigid transform values must be finite")
        if sum(value * value for value in self.rotation_axis) <= 1e-18:
            raise ValueError("rotation axis must be non-zero")
        return self


class PlacedInterface(_FrozenModel):
    component_id: str = Field(min_length=1)
    interface_id: str = Field(min_length=1)
    design_revision: int = Field(ge=1)
    transform: RigidTransform = RigidTransform()


class SemanticPlacementRequest(_FrozenModel):
    schema_version: Literal["1.0.0"] = PLACEMENT_SCHEMA_VERSION
    id: str = Field(min_length=1)
    components: tuple[PlacedInterface, PlacedInterface]
    radial_tolerance_mm: float = Field(default=0.01, gt=0, allow_inf_nan=False)
    plane_tolerance_mm: float = Field(default=0.01, gt=0, allow_inf_nan=False)
    angular_tolerance_degrees: float = Field(
        default=0.01, gt=0, allow_inf_nan=False
    )
    plane_offset_mm: float = Field(default=0.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def component_ids_are_unique(self):
        ids = tuple(item.component_id for item in self.components)
        if len(set(ids)) != 2:
            raise ValueError("semantic placement requires exactly two components")
        return self


class PlacementStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_ASSESSED = "not_assessed"


class SemanticPlacementCheck(_FrozenModel):
    id: str = Field(min_length=1)
    status: PlacementStatus
    actual: float | None = Field(default=None, allow_inf_nan=False)
    limit: float | None = Field(default=None, allow_inf_nan=False)
    unit: Literal["mm", "degree", "none"]
    message: str = Field(min_length=1)
    record_ids: tuple[str, ...] = ()


class SemanticPlacementAssessment(_FrozenModel):
    schema_version: Literal["1.0.0"] = PLACEMENT_SCHEMA_VERSION
    method_version: Literal["1.0.0"] = PLACEMENT_METHOD_VERSION
    request_id: str
    status: PlacementStatus
    checks: tuple[SemanticPlacementCheck, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def status_matches_checks(self):
        expected = _reduce_status(tuple(item.status for item in self.checks))
        if self.status is not expected:
            raise ValueError("placement status must be derived from checks")
        return self


class SemanticWorldFrame(_FrozenModel):
    origin_mm: tuple[float, float, float]
    z_axis: tuple[float, float, float]
    interface_id: str
    coordinate_system_id: str


def _reduce_status(statuses: tuple[PlacementStatus, ...]) -> PlacementStatus:
    if PlacementStatus.FAIL in statuses:
        return PlacementStatus.FAIL
    if PlacementStatus.NOT_ASSESSED in statuses:
        return PlacementStatus.NOT_ASSESSED
    return PlacementStatus.PASS


def _unit(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude <= 1e-12:
        raise ValueError("semantic axis must be non-zero")
    return tuple(value / magnitude for value in vector)


def _rotate(
    vector: tuple[float, float, float], transform: RigidTransform
) -> tuple[float, float, float]:
    axis = _unit(transform.rotation_axis)
    angle = math.radians(transform.rotation_degrees)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    dot = sum(left * right for left, right in zip(axis, vector))
    cross = (
        axis[1] * vector[2] - axis[2] * vector[1],
        axis[2] * vector[0] - axis[0] * vector[2],
        axis[0] * vector[1] - axis[1] * vector[0],
    )
    return tuple(
        vector[index] * cosine
        + cross[index] * sine
        + axis[index] * dot * (1 - cosine)
        for index in range(3)
    )


def _transform_point(
    point: tuple[float, float, float], transform: RigidTransform
) -> tuple[float, float, float]:
    rotated = _rotate(point, transform)
    return tuple(
        rotated[index] + transform.translation_mm[index] for index in range(3)
    )


def _not_assessed(
    request: SemanticPlacementRequest,
    message: str,
    record_ids: tuple[str, ...],
) -> SemanticPlacementAssessment:
    check = SemanticPlacementCheck(
        id="check.semantic_frames",
        status=PlacementStatus.NOT_ASSESSED,
        unit="none",
        message=message,
        record_ids=record_ids,
    )
    return SemanticPlacementAssessment(
        request_id=request.id,
        status=PlacementStatus.NOT_ASSESSED,
        checks=(check,),
    )


def resolve_semantic_world_frame(
    component: PlacedInterface,
    graph: EngineeringIntentGraph,
) -> SemanticWorldFrame:
    """Resolve one revision-bound interface frame into assembly coordinates."""
    if graph.revision != component.design_revision:
        raise ValueError("component design revision does not match")
    try:
        interface = graph.node(component.interface_id)
    except KeyError as exc:
        raise ValueError("component interface is missing") from exc
    if (
        not isinstance(interface, InterfaceNode)
        or not interface.contract_complete
        or interface.coordinate_system is None
    ):
        raise ValueError("component has no complete semantic frame")
    frame = interface.coordinate_system
    return SemanticWorldFrame(
        origin_mm=_transform_point(frame.origin_mm, component.transform),
        z_axis=_unit(_rotate(frame.z_axis, component.transform)),
        interface_id=interface.id,
        coordinate_system_id=frame.id,
    )


def validate_semantic_placement(
    request: SemanticPlacementRequest,
    graphs_by_component: Mapping[str, EngineeringIntentGraph],
) -> SemanticPlacementAssessment:
    """Validate supplied transforms against two semantic interface Z/XY frames."""
    frames = []
    for component in request.components:
        graph = graphs_by_component.get(component.component_id)
        if graph is None:
            return _not_assessed(
                request,
                f"component {component.component_id} has no authoritative EIG",
                (component.component_id, component.interface_id),
            )
        try:
            frame = resolve_semantic_world_frame(component, graph)
        except ValueError as exc:
            return _not_assessed(
                request,
                f"component {component.component_id} {exc}",
                (component.interface_id,),
            )
        frames.append(frame)

    left_frame, right_frame = frames
    left_origin, left_axis = left_frame.origin_mm, left_frame.z_axis
    right_origin, right_axis = right_frame.origin_mm, right_frame.z_axis
    dot = max(-1.0, min(1.0, abs(sum(
        left * right for left, right in zip(left_axis, right_axis)
    ))))
    angular_error = math.degrees(math.acos(dot))
    delta = tuple(
        right - left for left, right in zip(left_origin, right_origin)
    )
    axial = sum(value * axis for value, axis in zip(delta, left_axis))
    radial = math.sqrt(max(
        0.0, sum(value * value for value in delta) - axial * axial
    ))
    plane_offset_error = abs(axial - request.plane_offset_mm)
    record_ids = (
        left_frame.interface_id,
        left_frame.coordinate_system_id,
        right_frame.interface_id,
        right_frame.coordinate_system_id,
    )
    checks = (
        SemanticPlacementCheck(
            id="check.semantic_axis_angle",
            status=(
                PlacementStatus.PASS
                if angular_error <= request.angular_tolerance_degrees
                else PlacementStatus.FAIL
            ),
            actual=angular_error,
            limit=request.angular_tolerance_degrees,
            unit="degree",
            message="transformed semantic Z axes must be parallel or antiparallel",
            record_ids=record_ids,
        ),
        SemanticPlacementCheck(
            id="check.semantic_axis_radial_offset",
            status=(
                PlacementStatus.PASS
                if radial <= request.radial_tolerance_mm
                else PlacementStatus.FAIL
            ),
            actual=radial,
            limit=request.radial_tolerance_mm,
            unit="mm",
            message="transformed semantic Z axes must be concentric",
            record_ids=record_ids,
        ),
        SemanticPlacementCheck(
            id="check.semantic_plane_separation",
            status=(
                PlacementStatus.PASS
                if plane_offset_error <= request.plane_tolerance_mm
                else PlacementStatus.FAIL
            ),
            actual=plane_offset_error,
            limit=request.plane_tolerance_mm,
            unit="mm",
            message=(
                "transformed semantic XY planes must match the signed offset "
                f"{request.plane_offset_mm:g} mm"
            ),
            record_ids=record_ids,
        ),
    )
    return SemanticPlacementAssessment(
        request_id=request.id,
        status=_reduce_status(tuple(item.status for item in checks)),
        checks=checks,
    )


def semantic_placement_hash(assessment: SemanticPlacementAssessment) -> str:
    payload = json.dumps(
        assessment.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
