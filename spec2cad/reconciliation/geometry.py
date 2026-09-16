"""Motor R1 observation extraction and cross-backend geometry comparison."""

from __future__ import annotations

import hashlib
import json
import math
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from spec2cad.cad_state_serialization import csg_manifest
from spec2cad.feature_serialization import feature_ir_manifest
from spec2cad.schemas.cad_state_graph import CADStateGraph
from spec2cad.schemas.feature_ir import FeatureIR
from spec2cad.schemas.intent_graph import EngineeringIntentGraph

from .observations import (
    Applicability,
    GovernedQuantity,
    InterfaceGeometryObservation,
    NumericObservation,
    ObservationLayer,
    ObservationSet,
    ObservationSource,
    ObservationUnit,
    Point2D,
    PointSetObservation,
)
from .tolerances import QuantityKind, R1_TOLERANCE_POLICY


class GeometryReconciliationError(ValueError):
    pass


class CheckKind(str, Enum):
    DIMENSION = "dimension"
    POSITION = "position"
    VOLUME = "volume"


class GeometryReconciliationCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    quantity: GovernedQuantity
    kind: CheckKind
    left_observation_id: str
    right_observation_id: str
    maximum_absolute_error: float = Field(ge=0, allow_inf_nan=False)
    allowed_error: float = Field(ge=0, allow_inf_nan=False)
    unit: Literal["mm", "mm3"]
    consistent: bool
    detail: str


class GeometryReconciliationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    policy_version: Literal["1.0.0"] = "1.0.0"
    feature_ir_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    left_backend_id: str
    right_backend_id: str
    left_csg_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    right_csg_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checks: tuple[GeometryReconciliationCheck, ...]

    @model_validator(mode="after")
    def validate_complete_slice(self) -> "GeometryReconciliationReport":
        expected = {
            GovernedQuantity.PLATE_WIDTH,
            GovernedQuantity.PLATE_HEIGHT,
            GovernedQuantity.PLATE_THICKNESS,
            GovernedQuantity.OPENING_DIAMETER,
            GovernedQuantity.MOUNTING_DIAMETER,
            GovernedQuantity.MOUNTING_HOLE_CENTERS,
            GovernedQuantity.HOLE_SPACING_X,
            GovernedQuantity.HOLE_SPACING_Y,
            GovernedQuantity.VOLUME,
            GovernedQuantity.INTERFACE_GEOMETRY,
        }
        if {item.quantity for item in self.checks} != expected:
            raise ValueError("geometry reconciliation report is incomplete")
        return self

    @property
    def consistent(self) -> bool:
        return all(item.consistent for item in self.checks)


_PARAMETER_QUANTITIES = {
    "plate_width": GovernedQuantity.PLATE_WIDTH,
    "plate_height": GovernedQuantity.PLATE_HEIGHT,
    "plate_thickness": GovernedQuantity.PLATE_THICKNESS,
    "shaft_opening_diameter": GovernedQuantity.OPENING_DIAMETER,
    "mounting_hole_diameter": GovernedQuantity.MOUNTING_DIAMETER,
    "hole_spacing_x": GovernedQuantity.HOLE_SPACING_X,
    "hole_spacing_y": GovernedQuantity.HOLE_SPACING_Y,
}


def _hash_model(value) -> str:
    payload = json.dumps(
        value.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _planned_values(values: dict[str, float]) -> tuple[dict, tuple[Point2D, ...]]:
    centers = tuple(sorted(
        (
            Point2D(x_mm=x * values["hole_spacing_x"] / 2,
                    y_mm=y * values["hole_spacing_y"] / 2)
            for x in (-1, 1) for y in (-1, 1)
        ),
        key=lambda point: (point.x_mm, point.y_mm),
    ))
    volume = (
        values["plate_width"] * values["plate_height"] * values["plate_thickness"]
        - math.pi * (values["shaft_opening_diameter"] / 2) ** 2
        * values["plate_thickness"]
        - values["mounting_hole_count"]
        * math.pi * (values["mounting_hole_diameter"] / 2) ** 2
        * values["plate_thickness"]
        - 4 * (values["external_chamfer"] ** 2 / 2)
        * values["plate_thickness"]
    )
    quantities = {
        quantity: values[name] for name, quantity in _PARAMETER_QUANTITIES.items()
    }
    quantities[GovernedQuantity.VOLUME] = volume
    return quantities, centers


def _source(layer, document_id, document_hash, graph=None):
    return ObservationSource(
        layer=layer,
        document_id=document_id,
        document_sha256=document_hash,
        backend_id=graph.backend_id if graph is not None else None,
        backend_version=graph.backend_version if graph is not None else None,
    )


def _append_geometry_layer(
    observations: list,
    *,
    prefix: str,
    source: ObservationSource,
    values: dict[GovernedQuantity, float],
    centers: tuple[Point2D, ...],
    method: str,
    governing: bool,
    related: dict[GovernedQuantity, tuple[str, ...]] | None = None,
) -> None:
    related = related or {}
    for quantity, value in values.items():
        observations.append(NumericObservation(
            id=f"observation.{prefix}.{quantity.value}",
            quantity=quantity,
            source=source,
            method=method,
            governing=governing,
            related_record_ids=related.get(quantity, ()),
            value=value,
            unit=(
                ObservationUnit.CUBIC_MILLIMETRE
                if quantity is GovernedQuantity.VOLUME
                else ObservationUnit.MILLIMETRE
            ),
        ))
    observations.append(PointSetObservation(
        id=f"observation.{prefix}.mounting_hole_centers",
        source=source,
        method=method,
        governing=governing,
        points=centers,
    ))
    observations.append(InterfaceGeometryObservation(
        id=f"observation.{prefix}.interface_geometry",
        source=source,
        method=method,
        governing=governing,
        opening_diameter_mm=values[GovernedQuantity.OPENING_DIAMETER],
        mounting_diameter_mm=values[GovernedQuantity.MOUNTING_DIAMETER],
        mounting_centers=centers,
    ))


def extract_motor_observations(
    intent_graph: EngineeringIntentGraph,
    feature_ir: FeatureIR,
    csg: CADStateGraph,
) -> ObservationSet:
    """Extract four explicitly separated evidence layers for one backend."""
    if csg.source_feature_ir_sha256 != feature_ir_manifest(feature_ir).content_sha256:
        raise GeometryReconciliationError("CSG and Feature IR identities differ")
    observations: list = []
    eig_hash = _hash_model(intent_graph)
    feature_manifest = feature_ir_manifest(feature_ir)
    graph_manifest = csg_manifest(csg)

    eig_values = {}
    eig_related = {}
    for name, quantity in _PARAMETER_QUANTITIES.items():
        node = intent_graph.dimension(name)
        if node is None or not isinstance(node.value, (int, float)):
            raise GeometryReconciliationError(f"EIG is missing numeric {name}")
        eig_values[name] = float(node.value)
        eig_related[quantity] = (node.id,)
    for name in ("mounting_hole_count", "external_chamfer"):
        node = intent_graph.dimension(name)
        if node is None or not isinstance(node.value, (int, float)):
            raise GeometryReconciliationError(f"EIG is missing numeric {name}")
        eig_values[name] = float(node.value)
    eig_quantities, eig_centers = _planned_values(eig_values)
    _append_geometry_layer(
        observations,
        prefix=f"{csg.backend_id}.eig",
        source=_source(
            ObservationLayer.ENGINEERING_INTENT,
            f"eig.motor.r{intent_graph.revision}", eig_hash,
        ),
        values=eig_quantities,
        centers=eig_centers,
        method="resolved Engineering Intent Graph values",
        governing=False,
        related=eig_related,
    )

    feature_parameters = {item.name: float(item.value) for item in feature_ir.parameters}
    feature_quantities, feature_centers = _planned_values(feature_parameters)
    feature_related = {
        quantity: (next(item.id for item in feature_ir.parameters if item.name == name),)
        for name, quantity in _PARAMETER_QUANTITIES.items()
    }
    _append_geometry_layer(
        observations,
        prefix=f"{csg.backend_id}.feature_ir",
        source=_source(
            ObservationLayer.FEATURE_IR, feature_ir.id,
            feature_manifest.content_sha256,
        ),
        values=feature_quantities,
        centers=feature_centers,
        method="validated Feature IR parameters and expressions",
        governing=False,
        related=feature_related,
    )

    native_parameters = {
        node.parameter_name: float(node.value)
        for node in csg.nodes if node.kind == "parameter_expression"
    }
    native_source = _source(
        ObservationLayer.NATIVE_STATE, csg.id,
        graph_manifest.content_sha256, csg,
    )
    if set(feature_parameters) <= set(native_parameters):
        native_quantities, native_centers = _planned_values(native_parameters)
        _append_geometry_layer(
            observations,
            prefix=f"{csg.backend_id}.native",
            source=native_source,
            values=native_quantities,
            centers=native_centers,
            method="native parameter/expression and solver state",
            governing=True,
        )
    else:
        for quantity in (
            *_PARAMETER_QUANTITIES.values(), GovernedQuantity.VOLUME,
        ):
            observations.append(NumericObservation(
                id=f"observation.{csg.backend_id}.native.{quantity.value}",
                quantity=quantity,
                source=native_source,
                applicability=Applicability.UNSUPPORTED,
                method="native parameter/expression lookup",
                reason="backend CSG explicitly reports native parametric state unavailable",
                value=None,
                unit=(
                    ObservationUnit.CUBIC_MILLIMETRE
                    if quantity is GovernedQuantity.VOLUME
                    else ObservationUnit.MILLIMETRE
                ),
            ))
        observations.extend((
            PointSetObservation(
                id=f"observation.{csg.backend_id}.native.mounting_hole_centers",
                source=native_source,
                applicability=Applicability.UNSUPPORTED,
                method="native constraint lookup",
                reason="backend CSG explicitly reports native constraints unavailable",
            ),
            InterfaceGeometryObservation(
                id=f"observation.{csg.backend_id}.native.interface_geometry",
                source=native_source,
                applicability=Applicability.UNSUPPORTED,
                method="native interface lookup",
                reason="backend CSG explicitly reports native interfaces unavailable",
            ),
        ))

    solid = next(
        node for node in csg.nodes
        if node.kind == "semantic_topology" and node.semantic_role == "part_solid"
    )
    measured = {item.name: float(item.value) for item in solid.measurements}
    def measurements(node):
        return {item.name: float(item.value) for item in node.measurements}

    cylinders = [
        node for node in csg.nodes
        if node.kind == "semantic_topology" and node.geometry_type == "cylinder"
    ]
    expected_opening = feature_quantities[GovernedQuantity.OPENING_DIAMETER]
    expected_mount = feature_quantities[GovernedQuantity.MOUNTING_DIAMETER]
    opening_candidates = sorted(
        cylinders,
        key=lambda node: (
            abs(measurements(node).get("diameter", math.inf) - expected_opening),
            abs(measurements(node).get("center_x", math.inf)),
            abs(measurements(node).get("center_y", math.inf)),
        ),
    )
    if not opening_candidates:
        raise GeometryReconciliationError("measured B-Rep has no cylindrical surfaces")
    opening = opening_candidates[0]
    mounts = sorted(
        (
            node for node in cylinders
            if node.id != opening.id
            and abs(measurements(node).get("diameter", math.inf) - expected_mount)
            <= R1_TOLERANCE_POLICY.dimension.allowed_error(expected_mount)
        ),
        key=lambda node: (
            measurements(node).get("center_x", 0.0),
            measurements(node).get("center_y", 0.0),
        ),
    )
    if len(mounts) != 4:
        raise GeometryReconciliationError(
            f"expected four measured mounting holes, found {len(mounts)}"
        )

    opening_values = measurements(opening)
    mount_values = [measurements(item) for item in mounts]
    measured_centers = tuple(sorted(
        (
            Point2D(x_mm=item["center_x"], y_mm=item["center_y"])
            for item in mount_values
        ),
        key=lambda point: (point.x_mm, point.y_mm),
    ))
    xs, ys = [point.x_mm for point in measured_centers], [point.y_mm for point in measured_centers]
    brep_quantities = {
        GovernedQuantity.PLATE_WIDTH: measured["width"],
        GovernedQuantity.PLATE_HEIGHT: measured["height"],
        GovernedQuantity.PLATE_THICKNESS: measured["thickness"],
        GovernedQuantity.OPENING_DIAMETER: opening_values["diameter"],
        GovernedQuantity.MOUNTING_DIAMETER: mount_values[0]["diameter"],
        GovernedQuantity.HOLE_SPACING_X: max(xs) - min(xs),
        GovernedQuantity.HOLE_SPACING_Y: max(ys) - min(ys),
        GovernedQuantity.VOLUME: measured["volume"],
    }
    _append_geometry_layer(
        observations,
        prefix=f"{csg.backend_id}.brep",
        source=_source(
            ObservationLayer.BREP_MEASUREMENT,
            f"brep.{csg.backend_id}.r{feature_ir.design_revision}",
            graph_manifest.content_sha256, csg,
        ),
        values=brep_quantities,
        centers=measured_centers,
        method="semantic B-Rep topology measurement",
        governing=True,
    )
    return ObservationSet(
        id=f"observations.{csg.backend_id}.motor.r{feature_ir.design_revision}",
        design_revision=feature_ir.design_revision,
        feature_ir_sha256=feature_manifest.content_sha256,
        observations=tuple(observations),
    )


def _find(observations, quantity, kind):
    matches = [
        item for item in observations.observations
        if item.source.layer is ObservationLayer.BREP_MEASUREMENT
        and item.quantity is quantity and item.kind == kind
    ]
    if len(matches) != 1 or matches[0].applicability is not Applicability.APPLICABLE:
        raise GeometryReconciliationError(f"missing measured {quantity.value}")
    return matches[0]


def reconcile_motor_geometry(
    left: ObservationSet,
    right: ObservationSet,
) -> GeometryReconciliationReport:
    if left.feature_ir_sha256 != right.feature_ir_sha256:
        raise GeometryReconciliationError("backends did not build the same Feature IR")
    checks = []
    numeric = (
        GovernedQuantity.PLATE_WIDTH,
        GovernedQuantity.PLATE_HEIGHT,
        GovernedQuantity.PLATE_THICKNESS,
        GovernedQuantity.OPENING_DIAMETER,
        GovernedQuantity.MOUNTING_DIAMETER,
        GovernedQuantity.HOLE_SPACING_X,
        GovernedQuantity.HOLE_SPACING_Y,
        GovernedQuantity.VOLUME,
    )
    for quantity in numeric:
        left_item = _find(left, quantity, "numeric")
        right_item = _find(right, quantity, "numeric")
        kind = QuantityKind.VOLUME if quantity is GovernedQuantity.VOLUME else QuantityKind.DIMENSION
        unit = "mm3" if kind is QuantityKind.VOLUME else "mm"
        compared = R1_TOLERANCE_POLICY.compare(
            kind, left_item.value, right_item.value, unit=unit
        )
        checks.append(GeometryReconciliationCheck(
            quantity=quantity,
            kind=CheckKind(kind.value),
            left_observation_id=left_item.id,
            right_observation_id=right_item.id,
            maximum_absolute_error=compared.absolute_error,
            allowed_error=compared.allowed_error,
            unit=unit,
            consistent=compared.consistent,
            detail=f"{left_item.value:.9g} vs {right_item.value:.9g}",
        ))

    left_points = _find(left, GovernedQuantity.MOUNTING_HOLE_CENTERS, "point_set")
    right_points = _find(right, GovernedQuantity.MOUNTING_HOLE_CENTERS, "point_set")
    if len(left_points.points) != len(right_points.points):
        raise GeometryReconciliationError("mounting-hole counts differ")
    position_error = max(
        max(abs(a.x_mm - b.x_mm), abs(a.y_mm - b.y_mm))
        for a, b in zip(left_points.points, right_points.points)
    )
    position_allowed = R1_TOLERANCE_POLICY.position.allowed_error(0.0)
    checks.append(GeometryReconciliationCheck(
        quantity=GovernedQuantity.MOUNTING_HOLE_CENTERS,
        kind=CheckKind.POSITION,
        left_observation_id=left_points.id,
        right_observation_id=right_points.id,
        maximum_absolute_error=position_error,
        allowed_error=position_allowed,
        unit="mm",
        consistent=position_error <= position_allowed,
        detail=f"maximum paired axis error {position_error:.9g} mm",
    ))

    left_interface = _find(left, GovernedQuantity.INTERFACE_GEOMETRY, "interface_geometry")
    right_interface = _find(right, GovernedQuantity.INTERFACE_GEOMETRY, "interface_geometry")
    interface_errors = [
        abs(left_interface.opening_diameter_mm - right_interface.opening_diameter_mm),
        abs(left_interface.mounting_diameter_mm - right_interface.mounting_diameter_mm),
        position_error,
    ]
    interface_error = max(interface_errors)
    checks.append(GeometryReconciliationCheck(
        quantity=GovernedQuantity.INTERFACE_GEOMETRY,
        kind=CheckKind.POSITION,
        left_observation_id=left_interface.id,
        right_observation_id=right_interface.id,
        maximum_absolute_error=interface_error,
        allowed_error=position_allowed,
        unit="mm",
        consistent=interface_error <= position_allowed,
        detail=f"maximum interface diameter/position error {interface_error:.9g} mm",
    ))
    left_backend = next(
        item.source.backend_id for item in left.observations
        if item.source.layer is ObservationLayer.BREP_MEASUREMENT
    )
    right_backend = next(
        item.source.backend_id for item in right.observations
        if item.source.layer is ObservationLayer.BREP_MEASUREMENT
    )
    left_hash = next(
        item.source.document_sha256 for item in left.observations
        if item.source.layer is ObservationLayer.BREP_MEASUREMENT
    )
    right_hash = next(
        item.source.document_sha256 for item in right.observations
        if item.source.layer is ObservationLayer.BREP_MEASUREMENT
    )
    return GeometryReconciliationReport(
        feature_ir_sha256=left.feature_ir_sha256,
        left_backend_id=left_backend,
        right_backend_id=right_backend,
        left_csg_sha256=left_hash,
        right_csg_sha256=right_hash,
        checks=tuple(checks),
    )
