"""Compile DesignIntent into a typed CADProgram.

This is a separate stage from execution on purpose. The compiler decides *what
features exist and in what order*; the executor decides *how to build them*.
Keeping them apart means the feature plan can be inspected, diffed between
revisions, and validated for satisfiability before a CAD kernel is ever started.

Parameters are referenced, not inlined, so the program for v1 and the program
for v2 are structurally identical and differ only in the parameter table they
resolve against. That is what makes "the same design, one value changed"
literally true rather than a figure of speech.
"""

from __future__ import annotations

from spec2cad.schemas.cad_ir import (
    ArcSegment,
    BooleanMode,
    BoxOp,
    CylinderOp,
    CurvedRodOp,
    CurvedStripOp,
    CADProgram,
    ChamferOp,
    EdgeSelector,
    FaceSelector,
    HoleOp,
    FilletOp,
    LinearSlotPatternOp,
    LineSegment,
    ProfileExtrudeOp,
    ProfilePoint,
    ProfileRevolveOp,
    RectangularLoftOp,
    RectangularHolePatternOp,
    SheetMetalBendOp,
    SketchPlane,
    SketchProfile,
    Termination,
    TubeOp,
    ref,
    lit,
)
from spec2cad.schemas.design_intent import DesignIntent
from spec2cad.schemas.intent_graph import (
    AdvancedFeatureNode,
    EngineeringIntentGraph,
    FeatureNode,
    FeatureType,
    PartNode,
    ReferenceGeometryNode,
    ReferenceSelector,
    EdgeKind,
)
from spec2cad.schemas.advanced_intent import (
    CurvedRodFeatureIntent,
    CurvedStripFeatureIntent,
    ProfileFeatureIntent,
    RectangularLoftFeatureIntent,
    SheetMetalFeatureIntent,
)


class CompilationError(ValueError):
    """Raised when DesignIntent cannot be expressed as a feature plan."""


REQUIRED_FOR_COMPILATION = [
    "plate_width",
    "plate_height",
    "plate_thickness",
]


def compile_design(intent: DesignIntent | EngineeringIntentGraph) -> CADProgram:
    """Compile either the graph source of truth or the flat compatibility view."""
    if isinstance(intent, EngineeringIntentGraph):
        return _compile_graph(intent)
    return _compile_flat_intent(intent)


def _compile_flat_intent(intent: DesignIntent) -> CADProgram:
    """Legacy DesignIntent compiler retained for direct callers during migration."""
    missing = [n for n in REQUIRED_FOR_COMPILATION if not intent.has(n)]
    if missing:
        raise CompilationError(
            f"cannot compile without {', '.join(missing)}; "
            f"these have no value in DesignIntent v{intent.revision}"
        )

    operations: list = [
        BoxOp(
            id="base_plate",
            width=ref("plate_width"),
            height=ref("plate_height"),
            depth=ref("plate_thickness"),
            centered=True,
        )
    ]

    # The plate must clear the motor's pilot boss.
    if intent.has("shaft_opening_diameter"):
        operations.append(
            HoleOp(
                id="shaft_opening",
                support=FaceSelector.TOP_FACE,
                diameter=ref("shaft_opening_diameter"),
                termination=Termination.THROUGH_ALL,
            )
        )

    # The mounting pattern comes from the interface, which the datasheet owns.
    if intent.has("hole_spacing_x") and intent.has("mounting_hole_diameter"):
        count = int(intent.value_of("mounting_hole_count")) if intent.has(
            "mounting_hole_count"
        ) else 4
        operations.append(
            RectangularHolePatternOp(
                id="mounting_holes",
                support=FaceSelector.TOP_FACE,
                diameter=ref("mounting_hole_diameter"),
                spacing_x=ref("hole_spacing_x"),
                spacing_y=ref("hole_spacing_y"),
                count=count,
                termination=Termination.THROUGH_ALL,
            )
        )

    if all(intent.has(name) for name in ("slot_width", "slot_length", "slot_count")):
        slot_count = int(intent.value_of("slot_count"))
        if slot_count == 1 or intent.has("slot_spacing_x"):
            operations.append(
                LinearSlotPatternOp(
                    id="base_slots",
                    support=FaceSelector.TOP_FACE,
                    width=ref("slot_width"),
                    length=ref("slot_length"),
                    spacing=(ref("slot_spacing_x") if intent.has("slot_spacing_x") else lit(0)),
                    count=slot_count,
                    angle_degrees=(ref("slot_angle") if intent.has("slot_angle") else lit(0)),
                    termination=Termination.THROUGH_ALL,
                )
            )

    if intent.has("external_chamfer"):
        operations.append(
            ChamferOp(
                id="external_chamfers",
                edge_selector=EdgeSelector.EXTERNAL_VERTICAL_EDGES,
                distance=ref("external_chamfer"),
            )
        )

    if intent.has("external_fillet"):
        operations.append(
            FilletOp(
                id="external_fillets",
                edge_selector=EdgeSelector.EXTERNAL_VERTICAL_EDGES,
                radius=ref("external_fillet"),
            )
        )

    program = CADProgram(
        part_name=intent.part.name,
        operations=operations,
        design_revision=intent.revision,
    )

    # Fail now, not mid-build, if the plan references something unresolvable.
    unresolvable = [
        name for name in program.referenced_parameters if not intent.has(name)
    ]
    if unresolvable:
        raise CompilationError(
            f"feature plan references parameters with no value: {', '.join(unresolvable)}"
        )
    return program


def _compile_graph(graph: EngineeringIntentGraph) -> CADProgram:
    """Synthesize a CADProgram by traversing semantic features and relations.

    There is deliberately no part-name or part-family switch here. A mounting
    plate and a slotted bracket differ because their graphs contain different
    features, not because the compiler recognises either noun.
    """

    def dimension(feature: FeatureNode, role: str, *, optional: bool = False):
        found = graph.defining_dimension(feature.id, role)
        if found is None or not isinstance(found.value, (int, float)):
            if optional:
                return None
            raise CompilationError(
                f"feature {feature.id!r} has no numeric dimension for role {role!r}"
            )
        return found

    def face_support(feature: FeatureNode) -> FaceSelector:
        located = graph.out_edges(feature.id, EdgeKind.LOCATED_RELATIVE_TO, role="support")
        if not located:
            return FaceSelector.TOP_FACE
        reference = graph.node(located[0].target)
        if not isinstance(reference, ReferenceGeometryNode):
            raise CompilationError(f"feature {feature.id!r} support is not reference geometry")
        mapping = {ReferenceSelector.TOP_FACE: FaceSelector.TOP_FACE}
        try:
            return mapping[reference.selector]
        except KeyError as exc:
            raise CompilationError(
                f"no CAD face selector for {reference.selector.value!r}"
            ) from exc

    def edge_support(feature: FeatureNode) -> EdgeSelector:
        located = graph.out_edges(feature.id, EdgeKind.LOCATED_RELATIVE_TO, role="edges")
        if not located:
            return EdgeSelector.EXTERNAL_VERTICAL_EDGES
        reference = graph.node(located[0].target)
        if not isinstance(reference, ReferenceGeometryNode):
            raise CompilationError(f"feature {feature.id!r} edge set is not reference geometry")
        mapping = {
            ReferenceSelector.EXTERNAL_VERTICAL_EDGES:
                EdgeSelector.EXTERNAL_VERTICAL_EDGES,
        }
        try:
            return mapping[reference.selector]
        except KeyError as exc:
            raise CompilationError(
                f"no CAD edge selector for {reference.selector.value!r}"
            ) from exc

    def profile_from_intent(request: ProfileFeatureIntent) -> SketchProfile:
        def point(value):
            return ProfilePoint(x=lit(value.x), y=lit(value.y))

        segments = []
        for segment in request.segments:
            if segment.type == "line":
                segments.append(LineSegment(end=point(segment.end)))
            else:
                segments.append(ArcSegment(
                    midpoint=point(segment.midpoint), end=point(segment.end)
                ))
        return SketchProfile(start=point(request.start), segments=segments)

    operations = []
    for node in graph.nodes:
        if isinstance(node, AdvancedFeatureNode):
            request = node.request
            def advanced_ref(role: str):
                found = graph.defining_dimension(node.id, role)
                if found is None or not isinstance(found.value, (int, float)):
                    raise CompilationError(
                        f"advanced feature {node.id!r} has no numeric dimension for {role!r}"
                    )
                return ref(found.name)

            if isinstance(request, ProfileFeatureIntent):
                common = dict(
                    id=node.id, profile=profile_from_intent(request),
                    plane=SketchPlane(request.plane), mode=BooleanMode(request.mode),
                )
                if request.type == "profile_extrude":
                    operations.append(ProfileExtrudeOp(
                        **common, distance=lit(request.distance), centered=request.centered,
                    ))
                else:
                    operations.append(ProfileRevolveOp(
                        **common, axis_start=ProfilePoint(
                            x=lit(request.axis_start.x), y=lit(request.axis_start.y)
                        ), axis_end=ProfilePoint(
                            x=lit(request.axis_end.x), y=lit(request.axis_end.y)
                        ), angle_degrees=lit(request.angle_degrees),
                    ))
            elif isinstance(request, SheetMetalFeatureIntent):
                operations.append(SheetMetalBendOp(
                    id=node.id, leg_a=advanced_ref("leg_a"),
                    leg_b=advanced_ref("leg_b"), width=advanced_ref("width"),
                    thickness=advanced_ref("thickness"),
                    inside_radius=advanced_ref("inside_radius"),
                    angle_degrees=advanced_ref("angle_degrees"),
                    k_factor=advanced_ref("k_factor"),
                ))
            elif isinstance(request, CurvedRodFeatureIntent):
                operations.append(CurvedRodOp(
                    id=node.id, diameter=advanced_ref("diameter"),
                    total_length=advanced_ref("total_length"),
                    bend_start=advanced_ref("bend_start"),
                    bend_radius=advanced_ref("bend_radius"),
                    bend_angle_degrees=advanced_ref("bend_angle_degrees"),
                    plane=SketchPlane(request.plane),
                ))
            elif isinstance(request, RectangularLoftFeatureIntent):
                operations.append(RectangularLoftOp(
                    id=node.id,
                    start_width=advanced_ref("start_width"),
                    start_height=advanced_ref("start_height"),
                    end_width=advanced_ref("end_width"),
                    end_height=advanced_ref("end_height"),
                    length=advanced_ref("length"),
                    plane=SketchPlane(request.plane),
                ))
            elif isinstance(request, CurvedStripFeatureIntent):
                operations.append(CurvedStripOp(
                    id=node.id,
                    strip_width=advanced_ref("strip_width"),
                    extrusion_thickness=advanced_ref("extrusion_thickness"),
                    shank_length=advanced_ref("shank_length"),
                    bend_radius=advanced_ref("bend_radius"),
                    bend_angle_degrees=advanced_ref("bend_angle_degrees"),
                    tail_length=advanced_ref("tail_length"),
                    plane=SketchPlane(request.plane),
                ))
            continue
        if not isinstance(node, FeatureNode):
            continue

        if node.feature_type is FeatureType.BASE_SOLID:
            operations.append(BoxOp(
                id=node.id,
                width=ref(dimension(node, "width").name),
                height=ref(dimension(node, "height").name),
                depth=ref(dimension(node, "depth").name),
                centered=True,
            ))
        elif node.feature_type is FeatureType.CYLINDER_BASE:
            operations.append(CylinderOp(
                id=node.id,
                diameter=ref(dimension(node, "diameter").name),
                length=ref(dimension(node, "length").name),
                centered=True,
            ))
        elif node.feature_type is FeatureType.TUBE_BASE:
            operations.append(TubeOp(
                id=node.id,
                outer_diameter=ref(dimension(node, "outer_diameter").name),
                inner_diameter=ref(dimension(node, "inner_diameter").name),
                length=ref(dimension(node, "length").name),
                centered=True,
            ))
        elif node.feature_type is FeatureType.OPENING:
            operations.append(HoleOp(
                id=node.id, support=face_support(node),
                diameter=ref(dimension(node, "diameter").name),
                termination=Termination.THROUGH_ALL,
            ))
        elif node.feature_type is FeatureType.HOLE_PATTERN:
            count = dimension(node, "count", optional=True)
            operations.append(RectangularHolePatternOp(
                id=node.id, support=face_support(node),
                diameter=ref(dimension(node, "diameter").name),
                spacing_x=ref(dimension(node, "spacing_x").name),
                spacing_y=ref(dimension(node, "spacing_y").name),
                count=int(count.value) if count else 4,
                termination=Termination.THROUGH_ALL,
            ))
        elif node.feature_type is FeatureType.SLOT_PATTERN:
            count = dimension(node, "count")
            spacing = dimension(node, "spacing_x", optional=True)
            angle = dimension(node, "angle", optional=True)
            operations.append(LinearSlotPatternOp(
                id=node.id, support=face_support(node),
                width=ref(dimension(node, "width").name),
                length=ref(dimension(node, "length").name),
                spacing=ref(spacing.name) if spacing else lit(0),
                count=int(count.value),
                angle_degrees=ref(angle.name) if angle else lit(0),
                termination=Termination.THROUGH_ALL,
            ))
        elif node.feature_type is FeatureType.EDGE_TREATMENT:
            operations.append(ChamferOp(
                id=node.id, edge_selector=edge_support(node),
                distance=ref(dimension(node, "distance").name),
            ))
        elif node.feature_type is FeatureType.FILLET:
            operations.append(FilletOp(
                id=node.id, edge_selector=edge_support(node),
                radius=ref(dimension(node, "radius").name),
            ))
        else:
            raise CompilationError(
                f"no feature planner for {node.feature_type.value!r} ({node.id!r})"
            )

    part = next((n for n in graph.nodes if isinstance(n, PartNode)), None)
    if part is None:
        raise CompilationError("intent graph has no part node")
    program = CADProgram(
        part_name=part.name,
        operations=operations,
        design_revision=graph.revision,
    )
    if not operations or not (
        isinstance(operations[0], (
            BoxOp, CylinderOp, TubeOp, SheetMetalBendOp, CurvedRodOp,
            RectangularLoftOp,
            CurvedStripOp,
        ))
        or isinstance(operations[0], (ProfileExtrudeOp, ProfileRevolveOp))
        and operations[0].mode is BooleanMode.ADD
    ):
        raise CompilationError("intent graph must begin with a base solid feature")
    return program


def parameter_table(intent: DesignIntent) -> dict[str, float]:
    """The numeric table a CADProgram resolves its references against."""
    return {
        name: float(p.value)
        for name, p in intent.parameters.items()
        if isinstance(p.value, (int, float))
    }
