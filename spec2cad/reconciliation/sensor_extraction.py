"""Adapters from established R1 evidence sources into SensorEvidence."""

from __future__ import annotations

from spec2cad.cad_state_serialization import csg_content_hash
from spec2cad.schemas.cad_state_graph import (
    CADStateGraph,
    ConstraintNode,
    DocumentNode,
    SemanticTopologyNode,
    SketchNode,
)

from .observations import (
    Applicability,
    InterfaceGeometryObservation,
    NumericObservation,
    Observation,
    ObservationLayer,
    ObservationSet,
    PointSetObservation,
    PredicateObservation,
)
from .sensors import (
    SensorDiagnostic,
    SensorDiagnosticSeverity,
    SensorEvidence,
    SensorLayer,
    SensorMethod,
    SensorReference,
    SensorReleaseRole,
    SensorTolerance,
)
from .tolerances import QuantityKind, R1_TOLERANCE_POLICY


_LAYER_MAP = {
    ObservationLayer.ENGINEERING_INTENT: SensorLayer.ENGINEERING_INTENT_EXPECTATION,
    ObservationLayer.FEATURE_IR: SensorLayer.FEATURE_IR_VALUE,
    ObservationLayer.NATIVE_STATE: SensorLayer.NATIVE_CONSTRAINT,
    ObservationLayer.BREP_MEASUREMENT: SensorLayer.BREP_MEASUREMENT,
}


def _reading(observation: Observation):
    if isinstance(observation, NumericObservation):
        return observation.value, observation.unit.value
    if isinstance(observation, PointSetObservation):
        value = tuple(
            coordinate
            for point in observation.points
            for coordinate in (point.x_mm, point.y_mm)
        )
        return value or None, "mm"
    if isinstance(observation, InterfaceGeometryObservation):
        if observation.applicability is not Applicability.APPLICABLE:
            return None, "mm"
        value = (
            observation.opening_diameter_mm,
            observation.mounting_diameter_mm,
            *(
                coordinate
                for point in observation.mounting_centers
                for coordinate in (point.x_mm, point.y_mm)
            ),
        )
        return value, "mm"
    if isinstance(observation, PredicateObservation):
        value = (
            observation.outcome.value
            if observation.applicability is Applicability.APPLICABLE
            else None
        )
        return value, "none"
    raise TypeError(f"unsupported observation type {type(observation).__name__}")


def _tolerance(observation: Observation, unit: str, value) -> SensorTolerance | None:
    if value is None or isinstance(value, (bool, str)):
        return None
    if unit == "mm3":
        kind = QuantityKind.VOLUME
    elif isinstance(observation, (PointSetObservation, InterfaceGeometryObservation)):
        kind = QuantityKind.POSITION
    else:
        kind = QuantityKind.DIMENSION
    rule = R1_TOLERANCE_POLICY.rule(kind)
    return SensorTolerance(
        policy_id="policy.r1_cross_backend",
        policy_version=R1_TOLERANCE_POLICY.policy_version,
        unit=unit,
        absolute=rule.absolute,
        relative=rule.relative,
    )


def _role(observation: Observation) -> SensorReleaseRole:
    if observation.applicability is not Applicability.APPLICABLE:
        return SensorReleaseRole.DIAGNOSTIC
    if observation.source.layer in {
        ObservationLayer.ENGINEERING_INTENT,
        ObservationLayer.FEATURE_IR,
    }:
        return SensorReleaseRole.REFERENCE
    return (
        SensorReleaseRole.GOVERNING
        if observation.governing
        else SensorReleaseRole.DIAGNOSTIC
    )


def sensor_evidence_from_observation(
    observation: Observation,
    *,
    design_revision: int,
) -> SensorEvidence:
    """Adapt one R1 observation without changing its availability or authority."""
    value, unit = _reading(observation)
    diagnostics = ()
    if observation.applicability is not Applicability.APPLICABLE:
        diagnostics = (SensorDiagnostic(
            severity=SensorDiagnosticSeverity.WARNING,
            code=f"sensor.{observation.applicability.value}",
            message=observation.reason or "Sensor evidence is unavailable.",
            related_record_ids=observation.related_record_ids,
        ),)
    source_records = observation.related_record_ids or (observation.id,)
    return SensorEvidence(
        id=observation.id.replace("observation.", "sensor.", 1),
        label=f"{observation.quantity.value} from {observation.source.layer.value}",
        revision=1,
        design_revision=design_revision,
        quantity=observation.quantity.value,
        source=SensorReference(
            layer=_LAYER_MAP[observation.source.layer],
            document_id=observation.source.document_id,
            document_sha256=observation.source.document_sha256,
            record_ids=source_records,
            backend_id=observation.source.backend_id,
            backend_version=observation.source.backend_version,
        ),
        value=value,
        unit=unit,
        tolerance=_tolerance(observation, unit, value),
        method=SensorMethod(
            id=(
                f"method.r1_observation.{observation.source.layer.value}."
                f"{observation.kind}"
            ),
            version="1.0.0",
            description=observation.method,
        ),
        applicability=observation.applicability,
        release_role=_role(observation),
        related_record_ids=observation.related_record_ids,
        diagnostics=diagnostics,
    )


def sensor_evidence_from_observation_set(
    observations: ObservationSet,
) -> tuple[SensorEvidence, ...]:
    return tuple(
        sensor_evidence_from_observation(
            observation,
            design_revision=observations.design_revision,
        )
        for observation in observations.observations
    )


def _csg_reference(
    graph: CADStateGraph,
    layer: SensorLayer,
    *record_ids: str,
) -> SensorReference:
    return SensorReference(
        layer=layer,
        document_id=graph.id,
        document_sha256=csg_content_hash(graph),
        record_ids=record_ids,
        backend_id=graph.backend_id,
        backend_version=graph.backend_version,
    )


def csg_health_sensor_evidence(
    graph: CADStateGraph,
    *,
    design_revision: int,
) -> tuple[SensorEvidence, ...]:
    """Expose existing CSG constraint, topology and solver state diagnostically."""
    evidence: list[SensorEvidence] = []
    for node in graph.nodes:
        if isinstance(node, ConstraintNode):
            value = node.value if node.value is not None else node.state.value
            unit = node.unit.value if node.unit is not None else "none"
            evidence.append(SensorEvidence(
                id=f"sensor.{graph.backend_id}.constraint.{node.id}",
                label=node.label,
                revision=1,
                design_revision=design_revision,
                quantity=f"constraint.{node.constraint_type}",
                source=_csg_reference(
                    graph, SensorLayer.NATIVE_CONSTRAINT, node.id
                ),
                value=value,
                unit=unit,
                method=SensorMethod(
                    id="method.csg_native_constraint",
                    version="1.0.0",
                    description="Read the native constraint record from the CSG.",
                ),
                release_role=SensorReleaseRole.DIAGNOSTIC,
                related_record_ids=(
                    *node.geometry_ids,
                    *((node.expression_id,) if node.expression_id else ()),
                ),
            ))
        elif isinstance(node, SemanticTopologyNode):
            evidence.append(SensorEvidence(
                id=f"sensor.{graph.backend_id}.topology.{node.id}",
                label=node.label,
                revision=1,
                design_revision=design_revision,
                quantity=f"topology.{node.semantic_role}",
                source=_csg_reference(graph, SensorLayer.TOPOLOGY_RESULT, node.id),
                value=node.signature_sha256,
                unit="none",
                method=SensorMethod(
                    id="method.csg_semantic_topology",
                    version="1.0.0",
                    description="Read the current semantic topology signature.",
                ),
                release_role=SensorReleaseRole.DIAGNOSTIC,
                related_record_ids=node.adjacent_topology_ids,
            ))
        elif isinstance(node, DocumentNode):
            evidence.append(SensorEvidence(
                id=f"sensor.{graph.backend_id}.solver.recompute.{node.id}",
                label=f"{node.label} recompute state",
                revision=1,
                design_revision=design_revision,
                quantity="solver.recompute",
                source=_csg_reference(graph, SensorLayer.SOLVER_STATE, node.id),
                value=node.recompute.value,
                unit="none",
                method=SensorMethod(
                    id="method.csg_recompute_state",
                    version="1.0.0",
                    description="Read the native document recompute state.",
                ),
                release_role=SensorReleaseRole.DIAGNOSTIC,
            ))
        elif isinstance(node, SketchNode):
            applicability = (
                Applicability.APPLICABLE
                if node.degrees_of_freedom is not None
                else Applicability.NOT_ASSESSED
            )
            diagnostics = ()
            if applicability is Applicability.NOT_ASSESSED:
                diagnostics = (SensorDiagnostic(
                    severity=SensorDiagnosticSeverity.WARNING,
                    code="sensor.not_assessed",
                    message="The backend did not report sketch degrees of freedom.",
                    related_record_ids=(node.id,),
                ),)
            evidence.append(SensorEvidence(
                id=f"sensor.{graph.backend_id}.solver.dof.{node.id}",
                label=f"{node.label} degrees of freedom",
                revision=1,
                design_revision=design_revision,
                quantity="solver.sketch_degrees_of_freedom",
                source=_csg_reference(graph, SensorLayer.SOLVER_STATE, node.id),
                value=(
                    float(node.degrees_of_freedom)
                    if node.degrees_of_freedom is not None
                    else None
                ),
                unit="count",
                method=SensorMethod(
                    id="method.csg_sketch_dof",
                    version="1.0.0",
                    description="Read native sketch solver degrees of freedom.",
                ),
                applicability=applicability,
                release_role=SensorReleaseRole.DIAGNOSTIC,
                related_record_ids=node.constraint_ids,
                diagnostics=diagnostics,
            ))
    return tuple(evidence)


def visual_diagnostic_evidence(
    *,
    id: str,
    label: str,
    revision: int,
    design_revision: int,
    quantity: str,
    document_id: str,
    document_sha256: str,
    record_ids: tuple[str, ...],
    method_id: str,
    method_version: str,
    method_description: str,
    value: bool | str | None,
    applicability: Applicability = Applicability.APPLICABLE,
    reason: str | None = None,
) -> SensorEvidence:
    """Create a visual finding or a truthful diagnostic-only unavailable record."""
    diagnostics = ()
    if applicability is not Applicability.APPLICABLE:
        diagnostics = (SensorDiagnostic(
            severity=SensorDiagnosticSeverity.WARNING,
            code=f"sensor.{applicability.value}",
            message=reason or "Visual evidence is unavailable.",
            related_record_ids=record_ids,
        ),)
    return SensorEvidence(
        id=id,
        label=label,
        revision=revision,
        design_revision=design_revision,
        quantity=quantity,
        source=SensorReference(
            layer=SensorLayer.VISUAL_DIAGNOSTIC,
            document_id=document_id,
            document_sha256=document_sha256,
            record_ids=record_ids,
        ),
        value=value,
        unit="none",
        method=SensorMethod(
            id=method_id,
            version=method_version,
            description=method_description,
        ),
        applicability=applicability,
        release_role=SensorReleaseRole.DIAGNOSTIC,
        diagnostics=diagnostics,
    )
