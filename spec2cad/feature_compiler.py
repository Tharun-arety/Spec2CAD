"""Compile the bounded motor/plate EIG slice into backend-neutral Feature IR."""

from __future__ import annotations

import re

from spec2cad.schemas.feature_ir import (
    BinaryExpression,
    BinaryOperator,
    ChamferFeature,
    DatumPlane,
    DatumPlaneReference,
    EdgeSetSelector,
    FeatureEdgeSetReference,
    FeatureIR,
    FeatureIRBody,
    FeatureIRInterface,
    FeatureIRParameter,
    FeatureIRPart,
    FeatureSurfaceReference,
    FilletFeature,
    FixedConstraint,
    IntentLink,
    IntentRelation,
    LinearSlotPatternFeature,
    PadFeature,
    ParameterKind,
    Point2D,
    PocketFeature,
    RectangularPatternFeature,
    SketchCircle,
    SketchDefinition,
    SketchFeature,
    SketchLine,
    SketchProfile,
    SurfaceSelector,
    literal,
    parameter,
    validate_eig_provenance,
)
from spec2cad.schemas.intent_graph import (
    DimensionNode,
    EdgeKind,
    EngineeringIntentGraph,
    FeatureNode,
    FeatureType,
    InterfaceNode,
    PartNode,
)
from spec2cad.feature_validation import require_valid_feature_ir


class FeatureIRCompilationError(ValueError):
    """The EIG cannot be expressed by the bounded Feature IR compiler."""


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "part"


def _link(node_id: str, relation: IntentRelation) -> tuple[IntentLink, ...]:
    return (IntentLink(eig_node_id=node_id, relation=relation),)


def _subtract(left, right):
    return BinaryExpression(operator=BinaryOperator.SUBTRACT, left=left, right=right)


def _divide(left, right):
    return BinaryExpression(operator=BinaryOperator.DIVIDE, left=left, right=right)


def _negative_half(parameter_id: str):
    return _subtract(literal(0), _divide(parameter(parameter_id), literal(2)))


def _positive_half(parameter_id: str):
    return _divide(parameter(parameter_id), literal(2))


def _parameter_kind(node: DimensionNode) -> tuple[ParameterKind, str]:
    if "count" in node.name:
        return ParameterKind.COUNT, "none"
    if "angle" in node.name:
        return ParameterKind.ANGLE, "degree"
    if node.name == "k_factor":
        return ParameterKind.RATIO, "none"
    return ParameterKind.LENGTH, "mm"


def compile_feature_ir(graph: EngineeringIntentGraph) -> FeatureIR:
    """Compile one plate/motor graph without switching on the part name."""
    part_node = next(
        (node for node in graph.nodes if isinstance(node, PartNode)), None
    )
    if part_node is None:
        raise FeatureIRCompilationError("EIG has no part node")

    interface_nodes = [
        node for node in graph.nodes if isinstance(node, InterfaceNode)
    ]
    protected_dimension_ids = {
        edge.source
        for interface in interface_nodes
        for edge in graph.in_edges(interface.id, EdgeKind.DEFINES)
    }
    parameters = []
    for node in graph.nodes:
        if not isinstance(node, DimensionNode) or not isinstance(node.value, (int, float)):
            continue
        kind, unit = _parameter_kind(node)
        parameters.append(FeatureIRParameter(
            id=node.id,
            name=node.name,
            label=node.label or node.name.replace("_", " "),
            intent_links=_link(node.id, IntentRelation.PARAMETERIZES),
            kind=kind,
            value=float(node.value),
            unit=unit,
            protected=node.id in protected_dimension_ids,
        ))

    features = []
    base_pad_id: str | None = None
    mounting_pattern_id: str | None = None

    def defining(feature: FeatureNode, role: str) -> DimensionNode:
        found = graph.defining_dimension(feature.id, role)
        if found is None or not isinstance(found.value, (int, float)):
            raise FeatureIRCompilationError(
                f"feature {feature.id!r} lacks numeric dimension role {role!r}"
            )
        return found

    for node in graph.nodes:
        if not isinstance(node, FeatureNode):
            continue
        provenance = _link(node.id, IntentRelation.REALIZES)

        if node.feature_type is FeatureType.BASE_SOLID:
            width = defining(node, "width").id
            height = defining(node, "height").id
            depth = defining(node, "depth").id
            sketch_id = f"fir_{node.id}_sketch"
            profile_id = f"fir_{node.id}_profile"
            lines = (
                SketchLine(
                    id=f"{sketch_id}_bottom",
                    start=Point2D(x=_negative_half(width), y=_negative_half(height)),
                    end=Point2D(x=_positive_half(width), y=_negative_half(height)),
                ),
                SketchLine(
                    id=f"{sketch_id}_right",
                    start=Point2D(x=_positive_half(width), y=_negative_half(height)),
                    end=Point2D(x=_positive_half(width), y=_positive_half(height)),
                ),
                SketchLine(
                    id=f"{sketch_id}_top",
                    start=Point2D(x=_positive_half(width), y=_positive_half(height)),
                    end=Point2D(x=_negative_half(width), y=_positive_half(height)),
                ),
                SketchLine(
                    id=f"{sketch_id}_left",
                    start=Point2D(x=_negative_half(width), y=_positive_half(height)),
                    end=Point2D(x=_negative_half(width), y=_negative_half(height)),
                ),
            )
            features.append(SketchFeature(
                id=sketch_id,
                label=f"{node.label} sketch",
                intent_links=provenance,
                sketch=SketchDefinition(
                    support=DatumPlaneReference(plane=DatumPlane.XY),
                    geometry=lines,
                    profiles=(SketchProfile(
                        id=profile_id,
                        label=f"{node.label} outline",
                        geometry_ids=tuple(line.id for line in lines),
                    ),),
                    constraints=(FixedConstraint(
                        id=f"{sketch_id}_fully_constrained",
                        geometry_ids=tuple(line.id for line in lines),
                    ),),
                ),
            ))
            base_pad_id = f"fir_{node.id}_pad"
            features.append(PadFeature(
                id=base_pad_id,
                label=f"{node.label} pad",
                intent_links=provenance,
                sketch_id=sketch_id,
                profile_id=profile_id,
                length=parameter(depth),
                symmetric=True,
            ))
            continue

        if node.feature_type in {FeatureType.CYLINDER_BASE, FeatureType.TUBE_BASE}:
            length = defining(node, "length").id
            diameter_roles = (
                (("outer_diameter", "outer"), ("inner_diameter", "inner"))
                if node.feature_type is FeatureType.TUBE_BASE
                else (("diameter", "outer"),)
            )
            sketch_id = f"fir_{node.id}_sketch"
            profile_id = f"fir_{node.id}_profile"
            circles = tuple(
                SketchCircle(
                    id=f"{sketch_id}_{suffix}",
                    center=Point2D(x=literal(0), y=literal(0)),
                    diameter=parameter(defining(node, role).id),
                )
                for role, suffix in diameter_roles
            )
            features.append(SketchFeature(
                id=sketch_id,
                label=f"{node.label} sketch",
                intent_links=provenance,
                sketch=SketchDefinition(
                    support=DatumPlaneReference(plane=DatumPlane.XY),
                    geometry=circles,
                    profiles=(SketchProfile(
                        id=profile_id,
                        label=f"{node.label} profile",
                        geometry_ids=tuple(circle.id for circle in circles),
                    ),),
                    constraints=(FixedConstraint(
                        id=f"{sketch_id}_fully_constrained",
                        geometry_ids=tuple(circle.id for circle in circles),
                    ),),
                ),
            ))
            base_pad_id = f"fir_{node.id}_pad"
            features.append(PadFeature(
                id=base_pad_id,
                label=f"{node.label} pad",
                intent_links=provenance,
                sketch_id=sketch_id,
                profile_id=profile_id,
                length=parameter(length),
                symmetric=True,
            ))
            continue

        if base_pad_id is None:
            raise FeatureIRCompilationError(
                f"feature {node.id!r} appears before the base solid"
            )

        if node.feature_type is FeatureType.OPENING:
            diameter = defining(node, "diameter").id
            sketch_id = f"fir_{node.id}_sketch"
            geometry_id = f"{sketch_id}_circle"
            profile_id = f"fir_{node.id}_profile"
            features.append(SketchFeature(
                id=sketch_id,
                label=f"{node.label} sketch",
                intent_links=provenance,
                sketch=SketchDefinition(
                    support=FeatureSurfaceReference(
                        feature_id=base_pad_id,
                        selector=SurfaceSelector.POSITIVE_NORMAL,
                    ),
                    geometry=(SketchCircle(
                        id=geometry_id,
                        center=Point2D(x=literal(0), y=literal(0)),
                        diameter=parameter(diameter),
                    ),),
                    profiles=(SketchProfile(
                        id=profile_id,
                        label=node.label,
                        geometry_ids=(geometry_id,),
                    ),),
                    constraints=(FixedConstraint(
                        id=f"{sketch_id}_fully_constrained",
                        geometry_ids=(geometry_id,),
                    ),),
                ),
            ))
            features.append(PocketFeature(
                id=f"fir_{node.id}_pocket",
                label=f"{node.label} pocket",
                intent_links=provenance,
                sketch_id=sketch_id,
                profile_id=profile_id,
            ))
            continue

        if node.feature_type is FeatureType.HOLE_PATTERN:
            diameter = defining(node, "diameter").id
            spacing_x = defining(node, "spacing_x").id
            spacing_y = defining(node, "spacing_y").id
            count = defining(node, "count")
            if int(count.value) != 4:
                raise FeatureIRCompilationError(
                    f"feature {node.id!r} requires unsupported {count.value}-hole pattern"
                )
            sketch_id = f"fir_{node.id}_seed_sketch"
            geometry_id = f"{sketch_id}_circle"
            profile_id = f"fir_{node.id}_seed_profile"
            features.append(SketchFeature(
                id=sketch_id,
                label=f"{node.label} seed sketch",
                intent_links=provenance,
                sketch=SketchDefinition(
                    support=FeatureSurfaceReference(
                        feature_id=base_pad_id,
                        selector=SurfaceSelector.POSITIVE_NORMAL,
                    ),
                    geometry=(SketchCircle(
                        id=geometry_id,
                        center=Point2D(
                            x=_negative_half(spacing_x),
                            y=_negative_half(spacing_y),
                        ),
                        diameter=parameter(diameter),
                    ),),
                    profiles=(SketchProfile(
                        id=profile_id,
                        label=f"{node.label} seed",
                        geometry_ids=(geometry_id,),
                    ),),
                    constraints=(FixedConstraint(
                        id=f"{sketch_id}_fully_constrained",
                        geometry_ids=(geometry_id,),
                    ),),
                ),
            ))
            seed_id = f"fir_{node.id}_seed_pocket"
            features.append(PocketFeature(
                id=seed_id,
                label=f"{node.label} seed pocket",
                intent_links=provenance,
                sketch_id=sketch_id,
                profile_id=profile_id,
            ))
            mounting_pattern_id = f"fir_{node.id}_pattern"
            features.append(RectangularPatternFeature(
                id=mounting_pattern_id,
                label=node.label,
                intent_links=provenance,
                source_feature_id=seed_id,
                count_x=literal(2),
                count_y=literal(2),
                spacing_x=parameter(spacing_x),
                spacing_y=parameter(spacing_y),
            ))
            continue

        if node.feature_type is FeatureType.SLOT_PATTERN:
            count = defining(node, "count")
            spacing = graph.defining_dimension(node.id, "spacing_x")
            angle = graph.defining_dimension(node.id, "angle")
            features.append(LinearSlotPatternFeature(
                id=f"fir_{node.id}",
                label=node.label,
                intent_links=provenance,
                support=FeatureSurfaceReference(
                    feature_id=base_pad_id,
                    selector=SurfaceSelector.POSITIVE_NORMAL,
                ),
                width=parameter(defining(node, "width").id),
                length=parameter(defining(node, "length").id),
                spacing=(
                    parameter(spacing.id)
                    if spacing is not None else literal(0)
                ),
                count=parameter(count.id),
                angle_degrees=(
                    parameter(angle.id)
                    if angle is not None else literal(0)
                ),
            ))
            continue

        if node.feature_type is FeatureType.EDGE_TREATMENT:
            distance = defining(node, "distance").id
            features.append(ChamferFeature(
                id=f"fir_{node.id}",
                label=node.label,
                intent_links=provenance,
                edges=FeatureEdgeSetReference(
                    feature_id=base_pad_id,
                    selector=EdgeSetSelector.PARALLEL_TO_AXIS,
                    direction={"x": 0, "y": 0, "z": 1},
                ),
                distance=parameter(distance),
            ))
            continue

        if node.feature_type is FeatureType.FILLET:
            radius = defining(node, "radius").id
            features.append(FilletFeature(
                id=f"fir_{node.id}",
                label=node.label,
                intent_links=provenance,
                edges=FeatureEdgeSetReference(
                    feature_id=base_pad_id,
                    selector=EdgeSetSelector.PARALLEL_TO_AXIS,
                    direction={"x": 0, "y": 0, "z": 1},
                ),
                radius=parameter(radius),
            ))
            continue

        raise FeatureIRCompilationError(
            f"feature {node.id!r} has unsupported Feature IR type "
            f"{node.feature_type.value!r}"
        )

    if base_pad_id is None:
        raise FeatureIRCompilationError("EIG does not contain a supported base solid")

    interfaces = []
    for interface in interface_nodes:
        incoming = graph.in_edges(interface.id, EdgeKind.DEFINES)
        feature_ids = (mounting_pattern_id,) if mounting_pattern_id else (base_pad_id,)
        interfaces.append(FeatureIRInterface(
            id=f"fir_{interface.id}",
            label=interface.label or interface.name,
            intent_links=_link(interface.id, IntentRelation.CORRESPONDS_TO),
            reference=FeatureSurfaceReference(
                feature_id=base_pad_id,
                selector=SurfaceSelector.POSITIVE_NORMAL,
            ),
            feature_ids=feature_ids,
            parameter_ids=tuple(edge.source for edge in incoming),
        ))

    body_id = "fir_body_main"
    document = FeatureIR(
        id=f"fir_{_slug(part_node.name)}_r{graph.revision}",
        label=part_node.label or part_node.name,
        design_revision=graph.revision,
        part=FeatureIRPart(
            id="fir_part",
            name=_slug(part_node.name),
            label=part_node.label or part_node.name,
            intent_links=_link(part_node.id, IntentRelation.REALIZES),
            body_ids=(body_id,),
            interface_ids=tuple(item.id for item in interfaces),
        ),
        bodies=(FeatureIRBody(
            id=body_id,
            label="Main body",
            intent_links=_link(part_node.id, IntentRelation.GROUPS),
            feature_ids=tuple(item.id for item in features),
        ),),
        parameters=tuple(parameters),
        features=tuple(features),
        interfaces=tuple(interfaces),
    )
    validate_eig_provenance(document, graph)
    require_valid_feature_ir(document)
    return document
