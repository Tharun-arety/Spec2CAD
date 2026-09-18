"""Closed translation-only mate solver for one fixed and one movable interface."""

from __future__ import annotations

import hashlib
import json
import math
from enum import Enum
from typing import Annotated, Literal, Mapping, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from spec2cad.assembly_placement import (
    PlacedInterface,
    PlacementStatus,
    RigidTransform,
    SemanticPlacementAssessment,
    SemanticPlacementRequest,
    resolve_semantic_world_frame,
    validate_semantic_placement,
)
from spec2cad.schemas.intent_graph import EngineeringIntentGraph


MATE_SOLVER_SCHEMA_VERSION = "1.0.0"
MATE_SOLVER_METHOD_VERSION = "1.0.0"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ConcentricInterfaceMate(_FrozenModel):
    type: Literal["concentric"] = "concentric"
    id: str = Field(min_length=1)
    component_a: str = Field(min_length=1)
    component_b: str = Field(min_length=1)


class CoincidentInterfacePlaneMate(_FrozenModel):
    type: Literal["coincident"] = "coincident"
    id: str = Field(min_length=1)
    component_a: str = Field(min_length=1)
    component_b: str = Field(min_length=1)


class OffsetInterfacePlaneMate(_FrozenModel):
    type: Literal["offset"] = "offset"
    id: str = Field(min_length=1)
    component_a: str = Field(min_length=1)
    component_b: str = Field(min_length=1)
    distance_mm: float = Field(allow_inf_nan=False)


BoundedInterfaceMate = Annotated[
    Union[
        ConcentricInterfaceMate,
        CoincidentInterfacePlaneMate,
        OffsetInterfacePlaneMate,
    ],
    Field(discriminator="type"),
]


class BoundedMateSolveRequest(_FrozenModel):
    schema_version: Literal["1.0.0"] = MATE_SOLVER_SCHEMA_VERSION
    id: str = Field(min_length=1)
    placement: SemanticPlacementRequest
    fixed_component_id: str = Field(min_length=1)
    movable_component_id: str = Field(min_length=1)
    mates: tuple[BoundedInterfaceMate, BoundedInterfaceMate]

    @model_validator(mode="after")
    def validate_closed_bounded_case(self):
        component_ids = {
            item.component_id for item in self.placement.components
        }
        if {
            self.fixed_component_id, self.movable_component_id
        } != component_ids:
            raise ValueError("fixed and movable ids must name the two components")
        if self.fixed_component_id == self.movable_component_id:
            raise ValueError("fixed and movable components must differ")
        if len({item.id for item in self.mates}) != 2:
            raise ValueError("mate ids must be unique")
        axis_mates = [
            item for item in self.mates
            if isinstance(item, ConcentricInterfaceMate)
        ]
        plane_mates = [
            item for item in self.mates
            if isinstance(
                item, (CoincidentInterfacePlaneMate, OffsetInterfacePlaneMate)
            )
        ]
        if len(axis_mates) != 1 or len(plane_mates) != 1:
            raise ValueError(
                "bounded solve requires one concentric and one plane mate"
            )
        for mate in self.mates:
            if {mate.component_a, mate.component_b} != component_ids:
                raise ValueError("each mate must reference both components")
        return self


class MateSolveStatus(str, Enum):
    SOLVED = "solved"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class BoundedMateSolveResult(_FrozenModel):
    schema_version: Literal["1.0.0"] = MATE_SOLVER_SCHEMA_VERSION
    method_version: Literal["1.0.0"] = MATE_SOLVER_METHOD_VERSION
    request_id: str
    status: MateSolveStatus
    message: str = Field(min_length=1)
    solved_placement: SemanticPlacementRequest | None = None
    validation: SemanticPlacementAssessment | None = None

    @model_validator(mode="after")
    def result_payload_matches_status(self):
        solved = self.status is MateSolveStatus.SOLVED
        if solved != (
            self.solved_placement is not None and self.validation is not None
        ):
            raise ValueError("solved mate result requires placement and validation")
        if solved and self.validation.status is not PlacementStatus.PASS:
            raise ValueError("solved mate result requires passing validation")
        return self


def solve_bounded_interface_mates(
    request: BoundedMateSolveRequest,
    graphs_by_component: Mapping[str, EngineeringIntentGraph],
) -> BoundedMateSolveResult:
    """Solve radial and axial translation; never search or change orientation."""
    components = {
        item.component_id: item for item in request.placement.components
    }
    fixed = components[request.fixed_component_id]
    movable = components[request.movable_component_id]
    fixed_graph = graphs_by_component.get(fixed.component_id)
    movable_graph = graphs_by_component.get(movable.component_id)
    if fixed_graph is None or movable_graph is None:
        return BoundedMateSolveResult(
            request_id=request.id,
            status=MateSolveStatus.FAILED,
            message="both authoritative component graphs are required",
        )
    try:
        fixed_frame = resolve_semantic_world_frame(fixed, fixed_graph)
        movable_frame = resolve_semantic_world_frame(movable, movable_graph)
    except ValueError as exc:
        return BoundedMateSolveResult(
            request_id=request.id,
            status=MateSolveStatus.FAILED,
            message=str(exc),
        )

    dot = max(-1.0, min(1.0, abs(sum(
        left * right
        for left, right in zip(fixed_frame.z_axis, movable_frame.z_axis)
    ))))
    angular_error = math.degrees(math.acos(dot))
    if angular_error > request.placement.angular_tolerance_degrees:
        return BoundedMateSolveResult(
            request_id=request.id,
            status=MateSolveStatus.UNSUPPORTED,
            message=(
                "bounded solver does not search rotations; semantic axes differ by "
                f"{angular_error:.6g} degrees"
            ),
        )

    plane_mate = next(
        item for item in request.mates
        if isinstance(
            item, (CoincidentInterfacePlaneMate, OffsetInterfacePlaneMate)
        )
    )
    desired_offset = (
        plane_mate.distance_mm
        if isinstance(plane_mate, OffsetInterfacePlaneMate)
        else 0.0
    )
    delta = tuple(
        movable_value - fixed_value
        for fixed_value, movable_value in zip(
            fixed_frame.origin_mm, movable_frame.origin_mm
        )
    )
    axial = sum(
        value * axis for value, axis in zip(delta, fixed_frame.z_axis)
    )
    radial = tuple(
        value - axial * axis
        for value, axis in zip(delta, fixed_frame.z_axis)
    )
    correction = tuple(
        -radial[index]
        + (desired_offset - axial) * fixed_frame.z_axis[index]
        for index in range(3)
    )
    solved_transform = RigidTransform(
        translation_mm=tuple(
            movable.transform.translation_mm[index] + correction[index]
            for index in range(3)
        ),
        rotation_axis=movable.transform.rotation_axis,
        rotation_degrees=movable.transform.rotation_degrees,
    )
    solved_movable = movable.model_copy(update={"transform": solved_transform})
    solved_components = tuple(
        solved_movable if item.component_id == movable.component_id else item
        for item in request.placement.components
    )
    solved_placement = request.placement.model_copy(update={
        "components": solved_components,
        "plane_offset_mm": desired_offset,
    })
    validation = validate_semantic_placement(
        solved_placement, graphs_by_component
    )
    if validation.status is not PlacementStatus.PASS:
        return BoundedMateSolveResult(
            request_id=request.id,
            status=MateSolveStatus.FAILED,
            message="computed bounded placement did not pass semantic validation",
        )
    return BoundedMateSolveResult(
        request_id=request.id,
        status=MateSolveStatus.SOLVED,
        message="bounded concentric and plane mates solved by translation",
        solved_placement=solved_placement,
        validation=validation,
    )


def bounded_mate_result_hash(result: BoundedMateSolveResult) -> str:
    payload = json.dumps(
        result.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
