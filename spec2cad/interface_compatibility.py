"""Assembly-free compatibility checks for authoritative interface contracts.

This module compares intrinsic interface declarations only. It does not place
parts, solve mates, inspect contact, or authorize release.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from numbers import Real
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from spec2cad.schemas.intent_graph import (
    DimensionNode,
    EngineeringIntentGraph,
    EvidenceNode,
    InterfaceNode,
)


INTERFACE_COMPATIBILITY_SCHEMA_VERSION = "1.0.0"
INTERFACE_COMPATIBILITY_METHOD_VERSION = "1.0.0"
DEFAULT_DIMENSION_TOLERANCE_MM = 0.01


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InterfaceCompatibilityStatus(str, Enum):
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    NOT_ASSESSED = "not_assessed"


class InterfaceCompatibilityCheck(_FrozenModel):
    id: str = Field(min_length=1)
    status: InterfaceCompatibilityStatus
    message: str = Field(min_length=1)
    left_record_ids: tuple[str, ...] = ()
    right_record_ids: tuple[str, ...] = ()


class InterfaceCompatibilityAssessment(_FrozenModel):
    schema_version: Literal["1.0.0"] = INTERFACE_COMPATIBILITY_SCHEMA_VERSION
    method_version: Literal["1.0.0"] = INTERFACE_COMPATIBILITY_METHOD_VERSION
    left_interface_id: str = Field(min_length=1)
    right_interface_id: str = Field(min_length=1)
    left_design_revision: int = Field(ge=1)
    right_design_revision: int = Field(ge=1)
    dimension_tolerance_mm: float = Field(ge=0, allow_inf_nan=False)
    status: InterfaceCompatibilityStatus
    checks: tuple[InterfaceCompatibilityCheck, ...] = Field(min_length=1)
    left_evidence_ids: tuple[str, ...] = ()
    right_evidence_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def status_matches_checks(self):
        expected = _reduce_status(tuple(item.status for item in self.checks))
        if self.status is not expected:
            raise ValueError("compatibility status must be derived from checks")
        return self


def _reduce_status(
    statuses: tuple[InterfaceCompatibilityStatus, ...],
) -> InterfaceCompatibilityStatus:
    if InterfaceCompatibilityStatus.INCOMPATIBLE in statuses:
        return InterfaceCompatibilityStatus.INCOMPATIBLE
    if InterfaceCompatibilityStatus.NOT_ASSESSED in statuses:
        return InterfaceCompatibilityStatus.NOT_ASSESSED
    return InterfaceCompatibilityStatus.COMPATIBLE


def _check(
    check_id: str,
    passed: bool | None,
    message: str,
    *,
    left_ids: tuple[str, ...] = (),
    right_ids: tuple[str, ...] = (),
) -> InterfaceCompatibilityCheck:
    status = (
        InterfaceCompatibilityStatus.NOT_ASSESSED
        if passed is None
        else (
            InterfaceCompatibilityStatus.COMPATIBLE
            if passed else InterfaceCompatibilityStatus.INCOMPATIBLE
        )
    )
    return InterfaceCompatibilityCheck(
        id=check_id,
        status=status,
        message=message,
        left_record_ids=left_ids,
        right_record_ids=right_ids,
    )


def _interface(
    graph: EngineeringIntentGraph, interface_id: str
) -> InterfaceNode | None:
    try:
        node = graph.node(interface_id)
    except KeyError:
        return None
    return node if isinstance(node, InterfaceNode) else None


def _evidence_ids(
    graph: EngineeringIntentGraph, interface: InterfaceNode
) -> tuple[str, ...]:
    ids = set(interface.compatible_counterpart.source_evidence_ids)
    ids.update(graph.supporting_evidence(interface.id))
    for binding in interface.governed_dimensions:
        ids.update(graph.supporting_evidence(binding.dimension_id))
    return tuple(sorted(
        item for item in ids if isinstance(graph.node(item), EvidenceNode)
    ))


def _dimension_map(
    graph: EngineeringIntentGraph, interface: InterfaceNode
) -> dict[str, DimensionNode]:
    return {
        binding.role: graph.node(binding.dimension_id)
        for binding in interface.governed_dimensions
    }


def _complete_assessment(
    *,
    left_graph: EngineeringIntentGraph,
    left_interface_id: str,
    right_graph: EngineeringIntentGraph,
    right_interface_id: str,
    tolerance: float,
    checks: list[InterfaceCompatibilityCheck],
    left_evidence_ids: tuple[str, ...] = (),
    right_evidence_ids: tuple[str, ...] = (),
) -> InterfaceCompatibilityAssessment:
    statuses = tuple(item.status for item in checks)
    return InterfaceCompatibilityAssessment(
        left_interface_id=left_interface_id,
        right_interface_id=right_interface_id,
        left_design_revision=left_graph.revision,
        right_design_revision=right_graph.revision,
        dimension_tolerance_mm=tolerance,
        status=_reduce_status(statuses),
        checks=tuple(checks),
        left_evidence_ids=left_evidence_ids,
        right_evidence_ids=right_evidence_ids,
    )


def assess_interface_compatibility(
    left_graph: EngineeringIntentGraph,
    left_interface_id: str,
    right_graph: EngineeringIntentGraph,
    right_interface_id: str,
    *,
    dimension_tolerance_mm: float = DEFAULT_DIMENSION_TOLERANCE_MM,
) -> InterfaceCompatibilityAssessment:
    """Compare two intrinsic interface contracts without constructing an assembly."""
    if dimension_tolerance_mm < 0:
        raise ValueError("dimension tolerance must be non-negative")
    left = _interface(left_graph, left_interface_id)
    right = _interface(right_graph, right_interface_id)
    checks: list[InterfaceCompatibilityCheck] = []
    if left is None or right is None:
        checks.append(_check(
            "check.interface_presence",
            None,
            "both interface records are required before compatibility can be assessed",
            left_ids=(left_interface_id,),
            right_ids=(right_interface_id,),
        ))
        return _complete_assessment(
            left_graph=left_graph,
            left_interface_id=left_interface_id,
            right_graph=right_graph,
            right_interface_id=right_interface_id,
            tolerance=dimension_tolerance_mm,
            checks=checks,
        )
    if not left.contract_complete or not right.contract_complete:
        checks.append(_check(
            "check.contract_completeness",
            None,
            "both interfaces require complete first-class contracts",
            left_ids=(left.id,),
            right_ids=(right.id,),
        ))
        return _complete_assessment(
            left_graph=left_graph,
            left_interface_id=left_interface_id,
            right_graph=right_graph,
            right_interface_id=right_interface_id,
            tolerance=dimension_tolerance_mm,
            checks=checks,
        )

    checks.append(_check(
        "check.counterpart_identity",
        (
            left.compatible_counterpart.id == right.id
            and right.compatible_counterpart.id == left.id
        ),
        "counterpart identities must be reciprocal",
        left_ids=(left.id, left.compatible_counterpart.id),
        right_ids=(right.id, right.compatible_counterpart.id),
    ))
    checks.append(_check(
        "check.interface_type",
        left.interface_type is right.interface_type,
        "interface types must match",
        left_ids=(left.id,),
        right_ids=(right.id,),
    ))
    left_axes = (
        left.coordinate_system.x_axis,
        left.coordinate_system.y_axis,
        left.coordinate_system.z_axis,
    )
    right_axes = (
        right.coordinate_system.x_axis,
        right.coordinate_system.y_axis,
        right.coordinate_system.z_axis,
    )
    axes_match = all(
        abs(left_value - right_value) <= 1e-9
        for left_axis, right_axis in zip(left_axes, right_axes)
        for left_value, right_value in zip(left_axis, right_axis)
    )
    checks.append(_check(
        "check.coordinate_convention",
        axes_match,
        "local interface axis conventions must match; origins are not placed here",
        left_ids=(left.coordinate_system.id,),
        right_ids=(right.coordinate_system.id,),
    ))

    left_geometry = {
        item.role: item.geometry_kind for item in left.governed_geometry
    }
    right_geometry = {
        item.role: item.geometry_kind for item in right.governed_geometry
    }
    checks.append(_check(
        "check.geometry_roles",
        left_geometry == right_geometry,
        "governed geometry roles and kinds must match",
        left_ids=tuple(item.node_id for item in left.governed_geometry),
        right_ids=tuple(item.node_id for item in right.governed_geometry),
    ))

    left_dimensions = _dimension_map(left_graph, left)
    right_dimensions = _dimension_map(right_graph, right)
    checks.append(_check(
        "check.dimension_roles",
        set(left_dimensions) == set(right_dimensions),
        "protected dimension roles must match",
        left_ids=tuple(item.id for item in left_dimensions.values()),
        right_ids=tuple(item.id for item in right_dimensions.values()),
    ))
    if set(left_dimensions) == set(right_dimensions):
        for role in sorted(left_dimensions):
            left_dimension = left_dimensions[role]
            right_dimension = right_dimensions[role]
            values = (left_dimension.value, right_dimension.value)
            if not all(isinstance(value, Real) for value in values):
                compatible = None
                message = f"dimension role {role} has unavailable numeric values"
            elif left_dimension.unit != right_dimension.unit:
                compatible = False
                message = f"dimension role {role} uses incompatible units"
            elif left_dimension.unit == "mm":
                compatible = (
                    abs(float(values[0]) - float(values[1]))
                    <= dimension_tolerance_mm
                )
                message = (
                    f"dimension role {role} must agree within "
                    f"{dimension_tolerance_mm:g} mm"
                )
            else:
                compatible = float(values[0]) == float(values[1])
                message = f"dimension role {role} must match exactly"
            checks.append(_check(
                f"check.dimension.{role}",
                compatible,
                message,
                left_ids=(left_dimension.id,),
                right_ids=(right_dimension.id,),
            ))

    left_fit = left.fit
    right_fit = right.fit
    checks.append(_check(
        "check.fit_policy",
        (
            left_fit.fit_kind is right_fit.fit_kind
            and left_fit.tolerance_policy_id == right_fit.tolerance_policy_id
            and left_fit.tolerance_policy_version
            == right_fit.tolerance_policy_version
            and left_fit.minimum_clearance_mm == right_fit.minimum_clearance_mm
            and left_fit.maximum_clearance_mm == right_fit.maximum_clearance_mm
        ),
        "fit kind, versioned tolerance policy, and declared bounds must match",
        left_ids=(left.id,),
        right_ids=(right.id,),
    ))

    left_evidence = _evidence_ids(left_graph, left)
    right_evidence = _evidence_ids(right_graph, right)
    checks.append(_check(
        "check.provenance",
        bool(left_evidence) and bool(right_evidence),
        "both compatibility claims require resolvable EIG evidence provenance",
        left_ids=left_evidence,
        right_ids=right_evidence,
    ))
    return _complete_assessment(
        left_graph=left_graph,
        left_interface_id=left_interface_id,
        right_graph=right_graph,
        right_interface_id=right_interface_id,
        tolerance=dimension_tolerance_mm,
        checks=checks,
        left_evidence_ids=left_evidence,
        right_evidence_ids=right_evidence,
    )


def interface_compatibility_hash(
    assessment: InterfaceCompatibilityAssessment,
) -> str:
    payload = json.dumps(
        assessment.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
