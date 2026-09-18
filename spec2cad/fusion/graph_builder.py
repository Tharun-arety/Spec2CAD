"""Build the EngineeringIntentGraph, and project it back to DesignIntent.

Fusion logic is not duplicated here. `resolve_target` remains the single place
that decides what to believe when sources disagree; this module only decides how
the resolved result is *shaped*. Reimplementing the adjudication rules for the
graph would mean two policies that could drift apart, and the one that matters
is the one with the tests on it.

The projection exists so consumers can migrate without a flag day.
`test_intent_graph.py` asserts the projected intent is identical to the one
`build_design_intent` produces directly. The feature compiler and requirement
predicate compiler now consume the graph; repair policy and several validators
still read DesignIntent. The projection is the compatibility layer that can
eventually be deleted, not the graph.
"""

from __future__ import annotations

from typing import Optional

from spec2cad.fusion.entity_resolver import (
    BOSS_FIT_ALLOWANCE_MM,
    REQUIRED_TARGETS,
    OPTIONAL_PARAMETER_TARGETS,
    Resolution,
    resolve_target,
)
from spec2cad.schemas.design_intent import (
    Constraint,
    ConstraintSeverity,
    DesignIntent,
    Interface,
    Parameter,
    ParameterStatus,
    PartInfo,
)
from spec2cad.schemas.evidence import Authority, EvidenceSet, SemanticTarget
from spec2cad.schemas.advanced_intent import (
    CurvedStripFeatureIntent,
    CurvedRodFeatureIntent,
    ProfileFeatureIntent,
    RectangularLoftFeatureIntent,
    SheetMetalFeatureIntent,
    ThreadedFastenerFeatureIntent,
)
from spec2cad.schemas.intent_graph import (
    AdvancedFeatureNode,
    Edge,
    EdgeKind,
    EngineeringIntentGraph,
    EvidenceNode,
    FeatureNode,
    FeatureType,
    CompatibleInterfaceCounterpart,
    InterfaceCoordinateSystem,
    InterfaceDimensionBinding,
    InterfaceFitKind,
    InterfaceFitSpecification,
    InterfaceGeometryBinding,
    InterfaceGeometryKind,
    InterfaceNode,
    InterfaceType,
    MaterialNode,
    PartNode,
    ProcessNode,
    RequirementNode,
    ReferenceGeometryNode,
    ReferenceSelector,
    ReferenceType,
    DimensionNode,
)

T = SemanticTarget

PART_NODE = "part"
MATERIAL_NODE = "material"
PROCESS_NODE = "process"
INTERFACE_NODE = "iface_motor_mount"
CLEARANCE_NODE = "c_min_hole_edge_clearance"
TOP_FACE_REFERENCE = "ref_top_face"
EXTERNAL_EDGES_REFERENCE = "ref_external_vertical_edges"

# Feature node ids deliberately become CAD operation ids. The compiler derives
# its ordered plan by traversing these nodes; it does not recognise part names.
BASE_SOLID = "base_plate"
OPENING = "shaft_opening"
PATTERN = "mounting_holes"
CHAMFERS = "external_chamfers"
SLOTS = "base_slots"
FILLETS = "external_fillets"
CYLINDRICAL_BASE = "base_cylinder"

# Targets that get a node type of their own rather than a DimensionNode.
_NOT_DIMENSIONS = {
    T.MATERIAL, T.MANUFACTURING_PROCESS, T.MIN_HOLE_EDGE_CLEARANCE, T.PART_TYPE,
}

ADVANCED_TARGETS = {
    T.SHEET_LEG_A, T.SHEET_LEG_B, T.SHEET_WIDTH, T.SHEET_THICKNESS,
    T.INSIDE_BEND_RADIUS, T.BEND_ANGLE, T.K_FACTOR,
    T.ROD_DIAMETER, T.ROD_TOTAL_LENGTH, T.ROD_BEND_START,
    T.ROD_BEND_RADIUS, T.ROD_BEND_ANGLE, T.PROFILE_DEFINITION,
    T.LOFT_START_WIDTH, T.LOFT_START_HEIGHT, T.LOFT_END_WIDTH,
    T.LOFT_END_HEIGHT, T.LOFT_LENGTH,
    T.STRIP_WIDTH, T.STRIP_THICKNESS, T.STRIP_SHANK_LENGTH,
    T.STRIP_BEND_RADIUS, T.STRIP_BEND_ANGLE, T.STRIP_TAIL_LENGTH,
}


def _dim_id(target: SemanticTarget | str) -> str:
    name = target.value if isinstance(target, SemanticTarget) else target
    return f"dim_{name}"


def _derivation(res: Resolution) -> Optional[str]:
    """What `_parameter` in entity_resolver records: an explicit derivation if
    there is one, otherwise the resolution note."""
    return res.note or None


def build_intent_graph(
    evidence: EvidenceSet, part_name: Optional[str] = "motor_adapter_plate"
) -> tuple[EngineeringIntentGraph, list[Resolution]]:
    """Fuse evidence into an intent graph, returning the resolutions too."""
    resolutions: dict[SemanticTarget, Resolution] = {
        target: resolve_target(target, evidence.by_target(target)) for target in T
    }
    advanced_requested = bool(evidence.feature_requests) or any(
        item.target in ADVANCED_TARGETS for item in evidence.items
    )

    nodes: list = []
    edges: list[Edge] = []

    def add_support(node_id: str, evidence_ids: list[str]) -> None:
        for ev_id in evidence_ids:
            edges.append(Edge(source=node_id, target=ev_id,
                              kind=EdgeKind.SUPPORTED_BY))

    # ---- evidence ------------------------------------------------------
    for item in evidence.items:
        nodes.append(EvidenceNode(
            id=item.id, label=item.describe(),
            target=item.target.value, modality=item.source.modality.value,
        ))

    # ---- dimensions ----------------------------------------------------
    # Every resolved target with a value becomes a node, not only the ones the
    # flat parameter table happens to carry. mounting_thread_spec is the case
    # that matters: "M4" is real design intent that the parameter table drops on
    # the floor once ISO 273 has turned it into a diameter.
    for target in T:
        if target in _NOT_DIMENSIONS:
            continue
        res = resolutions[target]
        required = (
            not advanced_requested
            and (target in REQUIRED_TARGETS or target is T.SHAFT_OPENING_DIAMETER)
        )
        if res.value is None and not required:
            continue
        nodes.append(DimensionNode(
            id=_dim_id(target), label=target.value, name=target.value,
            value=res.value, unit=res.unit, status=res.status,
            authority=res.authority, is_explicit=res.is_explicit,
            derivation=_derivation(res), competing_values=res.competing,
        ))
        add_support(_dim_id(target), res.provenance)

    # Sources that each state a value outright and disagree. The conflict is
    # between the observations, not between a value and itself, so the edge
    # joins the evidence rather than hanging off the dimension.
    for target in T:
        competing = resolutions[target].competing
        if len(competing) < 2:
            continue
        winner = competing[0].get("evidence_id")
        for other in competing[1:]:
            rival = other.get("evidence_id")
            if winner and rival:
                edges.append(Edge(source=winner, target=rival,
                                  kind=EdgeKind.CONFLICTS_WITH,
                                  role=target.value))

    # ---- the derived centre opening ------------------------------------
    opening = resolutions[T.SHAFT_OPENING_DIAMETER]
    boss = resolutions[T.MOTOR_BOSS_DIAMETER]
    if not isinstance(opening.value, (int, float)) and isinstance(boss.value, (int, float)):
        # The relationship that used to live only inside a sentence.
        derived = DimensionNode(
            id=_dim_id(T.SHAFT_OPENING_DIAMETER),
            label=T.SHAFT_OPENING_DIAMETER.value,
            name=T.SHAFT_OPENING_DIAMETER.value,
            value=round(float(boss.value) + BOSS_FIT_ALLOWANCE_MM, 4),
            unit="mm",
            status=ParameterStatus.INFERRED,
            authority=Authority.DEFINITIVE,
            is_explicit=False,
            derivation=f"pilot boss {boss.value} mm + {BOSS_FIT_ALLOWANCE_MM} mm fit allowance",
        )
        nodes = [n for n in nodes if n.id != derived.id] + [derived]
        edges = [e for e in edges if e.source != derived.id]
        add_support(derived.id, boss.provenance)
        edges.append(Edge(source=derived.id, target=_dim_id(T.MOTOR_BOSS_DIAMETER),
                          kind=EdgeKind.DERIVED_FROM, role="fit_allowance"))
    elif not isinstance(opening.value, (int, float)) and not advanced_requested:
        missing = DimensionNode(
            id=_dim_id(T.SHAFT_OPENING_DIAMETER),
            label=T.SHAFT_OPENING_DIAMETER.value,
            name=T.SHAFT_OPENING_DIAMETER.value,
            value=None, status=ParameterStatus.MISSING,
            derivation="requires the motor pilot boss diameter",
        )
        nodes = [n for n in nodes if n.id != missing.id] + [missing]
        edges = [e for e in edges if e.source != missing.id]

    # ---- cylindrical wall derivation ----------------------------------
    # A tube may be specified by OD + wall thickness instead of ID. Keep the
    # relationship explicit in the graph rather than teaching the CAD planner
    # a prompt-specific arithmetic rule.
    outer = resolutions[T.OUTER_DIAMETER]
    inner = resolutions[T.INNER_DIAMETER]
    wall = resolutions[T.WALL_THICKNESS]
    if (
        not isinstance(inner.value, (int, float))
        and isinstance(outer.value, (int, float))
        and isinstance(wall.value, (int, float))
    ):
        derived_inner = float(outer.value) - 2.0 * float(wall.value)
        nodes.append(DimensionNode(
            id=_dim_id(T.INNER_DIAMETER), label=T.INNER_DIAMETER.value,
            name=T.INNER_DIAMETER.value, value=derived_inner, unit="mm",
            status=ParameterStatus.INFERRED, authority=Authority.DEFINITIVE,
            is_explicit=False,
            derivation="outer diameter - 2 x wall thickness",
        ))
        edges.append(Edge(
            source=_dim_id(T.INNER_DIAMETER), target=_dim_id(T.OUTER_DIAMETER),
            kind=EdgeKind.DERIVED_FROM, role="outer_diameter",
        ))
        edges.append(Edge(
            source=_dim_id(T.INNER_DIAMETER), target=_dim_id(T.WALL_THICKNESS),
            kind=EdgeKind.DERIVED_FROM, role="wall_thickness",
        ))

    # ---- part, material, process ---------------------------------------
    material = resolutions[T.MATERIAL]
    process = resolutions[T.MANUFACTURING_PROCESS]
    part_type = resolutions[T.PART_TYPE]
    resolved_part_name = (
        part_name or (str(part_type.value) if part_type.value else "mounting_plate")
    )
    nodes.append(PartNode(
        id=PART_NODE, label=resolved_part_name, name=resolved_part_name,
        part_type=str(part_type.value or "mounting_plate"),
    ))
    add_support(
        PART_NODE,
        list(material.provenance) + list(process.provenance) + list(part_type.provenance),
    )

    if isinstance(material.value, str):
        nodes.append(MaterialNode(id=MATERIAL_NODE, label=material.value,
                                  name=material.value))
        edges.append(Edge(source=PART_NODE, target=MATERIAL_NODE,
                          kind=EdgeKind.MADE_OF))
        add_support(MATERIAL_NODE, material.provenance)
    if isinstance(process.value, str):
        nodes.append(ProcessNode(id=PROCESS_NODE, label=process.value,
                                 name=process.value))
        edges.append(Edge(source=PART_NODE, target=PROCESS_NODE,
                          kind=EdgeKind.PRODUCED_BY))
        add_support(PROCESS_NODE, process.provenance)

    # ---- features -------------------------------------------------------
    def has(target: SemanticTarget) -> bool:
        return resolutions[target].value is not None

    def defines(target: SemanticTarget, feature_id: str, role: str) -> None:
        if has(target):
            edges.append(Edge(source=_dim_id(target), target=feature_id,
                              kind=EdgeKind.DEFINES, role=role))

    nodes.append(ReferenceGeometryNode(
        id=TOP_FACE_REFERENCE, label="top face",
        reference_type=ReferenceType.FACE,
        selector=ReferenceSelector.TOP_FACE,
    ))
    nodes.append(ReferenceGeometryNode(
        id=EXTERNAL_EDGES_REFERENCE, label="external vertical edges",
        reference_type=ReferenceType.EDGE_SET,
        selector=ReferenceSelector.EXTERNAL_VERTICAL_EDGES,
    ))

    def locate(feature_id: str, reference_id: str, role: str = "support") -> None:
        edges.append(Edge(
            source=feature_id, target=reference_id,
            kind=EdgeKind.LOCATED_RELATIVE_TO, role=role,
        ))

    advanced_base = bool(evidence.feature_requests)
    cylindrical = has(T.OUTER_DIAMETER) and has(T.BODY_LENGTH) and not advanced_base
    derived_inner_node = next(
        (n for n in nodes if isinstance(n, DimensionNode)
         and n.name == T.INNER_DIAMETER.value and isinstance(n.value, (int, float))),
        None,
    )
    if cylindrical:
        tube = derived_inner_node is not None
        nodes.append(FeatureNode(
            id=CYLINDRICAL_BASE,
            label="tube base" if tube else "cylinder base",
            feature_type=FeatureType.TUBE_BASE if tube else FeatureType.CYLINDER_BASE,
        ))
        edges.append(Edge(
            source=PART_NODE, target=CYLINDRICAL_BASE, kind=EdgeKind.HAS_FEATURE,
        ))
        if tube:
            defines(T.OUTER_DIAMETER, CYLINDRICAL_BASE, "outer_diameter")
            edges.append(Edge(
                source=_dim_id(T.INNER_DIAMETER), target=CYLINDRICAL_BASE,
                kind=EdgeKind.DEFINES, role="inner_diameter",
            ))
        else:
            defines(T.OUTER_DIAMETER, CYLINDRICAL_BASE, "diameter")
        defines(T.BODY_LENGTH, CYLINDRICAL_BASE, "length")
    elif not advanced_base:
        nodes.append(FeatureNode(id=BASE_SOLID, label="base plate",
                                 feature_type=FeatureType.BASE_SOLID))
        edges.append(Edge(source=PART_NODE, target=BASE_SOLID, kind=EdgeKind.HAS_FEATURE))
        defines(T.PLATE_WIDTH, BASE_SOLID, "width")
        defines(T.PLATE_HEIGHT, BASE_SOLID, "height")
        defines(T.PLATE_THICKNESS, BASE_SOLID, "depth")

    for request in evidence.feature_requests:
        nodes.append(AdvancedFeatureNode(
            id=request.id, label=request.type.replace("_", " "), request=request,
        ))
        edges.append(Edge(
            source=PART_NODE, target=request.id, kind=EdgeKind.HAS_FEATURE,
        ))
        if isinstance(request, SheetMetalFeatureIntent):
            for target, role in (
                (T.SHEET_LEG_A, "leg_a"), (T.SHEET_LEG_B, "leg_b"),
                (T.SHEET_WIDTH, "width"), (T.SHEET_THICKNESS, "thickness"),
                (T.INSIDE_BEND_RADIUS, "inside_radius"),
                (T.BEND_ANGLE, "angle_degrees"), (T.K_FACTOR, "k_factor"),
            ):
                defines(target, request.id, role)
        elif isinstance(request, CurvedRodFeatureIntent):
            for target, role in (
                (T.ROD_DIAMETER, "diameter"),
                (T.ROD_TOTAL_LENGTH, "total_length"),
                (T.ROD_BEND_START, "bend_start"),
                (T.ROD_BEND_RADIUS, "bend_radius"),
                (T.ROD_BEND_ANGLE, "bend_angle_degrees"),
            ):
                defines(target, request.id, role)
        elif isinstance(request, RectangularLoftFeatureIntent):
            for target, role in (
                (T.LOFT_START_WIDTH, "start_width"),
                (T.LOFT_START_HEIGHT, "start_height"),
                (T.LOFT_END_WIDTH, "end_width"),
                (T.LOFT_END_HEIGHT, "end_height"),
                (T.LOFT_LENGTH, "length"),
            ):
                defines(target, request.id, role)
        elif isinstance(request, CurvedStripFeatureIntent):
            for target, role in (
                (T.STRIP_WIDTH, "strip_width"),
                (T.STRIP_THICKNESS, "extrusion_thickness"),
                (T.STRIP_SHANK_LENGTH, "shank_length"),
                (T.STRIP_BEND_RADIUS, "bend_radius"),
                (T.STRIP_BEND_ANGLE, "bend_angle_degrees"),
                (T.STRIP_TAIL_LENGTH, "tail_length"),
            ):
                defines(target, request.id, role)
        elif isinstance(request, ThreadedFastenerFeatureIntent):
            for target, role in (
                (T.FASTENER_MAJOR_DIAMETER, "major_diameter"),
                (T.THREAD_PITCH, "pitch"),
                (T.THREADED_LENGTH, "thread_length"),
                (T.FASTENER_SHANK_LENGTH, "shank_length"),
                (T.HEAD_ACROSS_FLATS, "head_across_flats"),
                (T.HEAD_HEIGHT, "head_height"),
                (T.FLANGE_DIAMETER, "flange_diameter"),
                (T.FLANGE_THICKNESS, "flange_thickness"),
            ):
                defines(target, request.id, role)
        elif isinstance(request, ProfileFeatureIntent):
            defines(T.PROFILE_DEFINITION, request.id, "profile")

    # Read the opening back off the graph rather than off the resolution: it may
    # have been derived from the boss a moment ago, and the compiler builds the
    # feature for a derived value exactly as it does for a stated one.
    shaft_node = next(
        (n for n in nodes if n.id == _dim_id(T.SHAFT_OPENING_DIAMETER)), None
    )
    if shaft_node is not None and isinstance(shaft_node.value, (int, float)):
        nodes.append(FeatureNode(id=OPENING, label="shaft opening",
                                 feature_type=FeatureType.OPENING))
        edges.append(Edge(source=PART_NODE, target=OPENING, kind=EdgeKind.HAS_FEATURE))
        edges.append(Edge(source=_dim_id(T.SHAFT_OPENING_DIAMETER), target=OPENING,
                          kind=EdgeKind.DEFINES, role="diameter"))
        locate(OPENING, TOP_FACE_REFERENCE)

    pattern_built = has(T.HOLE_SPACING_X) and has(T.MOUNTING_HOLE_DIAMETER)
    if pattern_built:
        nodes.append(FeatureNode(id=PATTERN, label="mounting holes",
                                 feature_type=FeatureType.HOLE_PATTERN))
        edges.append(Edge(source=PART_NODE, target=PATTERN, kind=EdgeKind.HAS_FEATURE))
        defines(T.MOUNTING_HOLE_DIAMETER, PATTERN, "diameter")
        defines(T.HOLE_SPACING_X, PATTERN, "spacing_x")
        defines(T.HOLE_SPACING_Y, PATTERN, "spacing_y")
        defines(T.MOUNTING_HOLE_COUNT, PATTERN, "count")
        locate(PATTERN, TOP_FACE_REFERENCE)

    slot_values = (
        T.SLOT_WIDTH, T.SLOT_LENGTH, T.SLOT_COUNT,
    )
    if all(has(target) for target in slot_values):
        count_value = int(resolutions[T.SLOT_COUNT].value)
        spacing_ready = count_value == 1 or has(T.SLOT_SPACING_X)
        if spacing_ready:
            nodes.append(FeatureNode(
                id=SLOTS, label="base slots", feature_type=FeatureType.SLOT_PATTERN,
            ))
            edges.append(Edge(
                source=PART_NODE, target=SLOTS, kind=EdgeKind.HAS_FEATURE,
            ))
            defines(T.SLOT_WIDTH, SLOTS, "width")
            defines(T.SLOT_LENGTH, SLOTS, "length")
            defines(T.SLOT_COUNT, SLOTS, "count")
            defines(T.SLOT_SPACING_X, SLOTS, "spacing_x")
            defines(T.SLOT_ANGLE, SLOTS, "angle")
            locate(SLOTS, TOP_FACE_REFERENCE)

    if has(T.EXTERNAL_CHAMFER):
        nodes.append(FeatureNode(id=CHAMFERS, label="external chamfers",
                                 feature_type=FeatureType.EDGE_TREATMENT))
        edges.append(Edge(source=PART_NODE, target=CHAMFERS, kind=EdgeKind.HAS_FEATURE))
        defines(T.EXTERNAL_CHAMFER, CHAMFERS, "distance")
        locate(CHAMFERS, EXTERNAL_EDGES_REFERENCE, role="edges")

    if has(T.EXTERNAL_FILLET):
        nodes.append(FeatureNode(
            id=FILLETS, label="external fillets", feature_type=FeatureType.FILLET,
        ))
        edges.append(Edge(
            source=PART_NODE, target=FILLETS, kind=EdgeKind.HAS_FEATURE,
        ))
        defines(T.EXTERNAL_FILLET, FILLETS, "radius")
        locate(FILLETS, EXTERNAL_EDGES_REFERENCE, role="edges")

    # ---- interface ------------------------------------------------------
    sx, sy = resolutions[T.HOLE_SPACING_X], resolutions[T.HOLE_SPACING_Y]
    count, dia = resolutions[T.MOUNTING_HOLE_COUNT], resolutions[T.MOUNTING_HOLE_DIAMETER]
    if all(isinstance(r.value, (int, float)) for r in (sx, sy, count, dia)):
        opening_available = (
            shaft_node is not None and isinstance(shaft_node.value, (int, float))
        )
        interface_evidence = tuple(dict.fromkeys(
            list(sx.provenance) + list(sy.provenance)
            + list(count.provenance) + list(dia.provenance)
        ))
        dimension_bindings = [
            InterfaceDimensionBinding(
                role=role, dimension_id=_dim_id(target), protected=True
            )
            for target, role in (
                (T.MOUNTING_HOLE_COUNT, "hole_count"),
                (T.MOUNTING_HOLE_DIAMETER, "hole_diameter"),
                (T.HOLE_SPACING_X, "spacing_x"),
                (T.HOLE_SPACING_Y, "spacing_y"),
            )
        ]
        geometry_bindings = [InterfaceGeometryBinding(
            role="mounting_pattern",
            node_id=PATTERN,
            geometry_kind=InterfaceGeometryKind.HOLE_PATTERN,
        )]
        if opening_available:
            dimension_bindings.append(InterfaceDimensionBinding(
                role="opening_diameter",
                dimension_id=_dim_id(T.SHAFT_OPENING_DIAMETER),
                protected=True,
            ))
            geometry_bindings.append(InterfaceGeometryBinding(
                role="pilot_opening",
                node_id=OPENING,
                geometry_kind=InterfaceGeometryKind.BORE,
            ))
        nodes.append(InterfaceNode(
            id=INTERFACE_NODE,
            label="motor_mount",
            name="motor_mount",
            contract_version="1.0.0",
            interface_type=InterfaceType.MOUNTING_PATTERN,
            coordinate_system=InterfaceCoordinateSystem(
                id="coordinate.iface_motor_mount",
                label="Motor mount interface frame",
                origin_mm=(0.0, 0.0, 0.0),
                x_axis=(1.0, 0.0, 0.0),
                y_axis=(0.0, 1.0, 0.0),
                z_axis=(0.0, 0.0, 1.0),
            ),
            governed_geometry=tuple(geometry_bindings),
            governed_dimensions=tuple(dimension_bindings),
            fit=InterfaceFitSpecification(
                fit_kind=InterfaceFitKind.CLEARANCE,
                tolerance_policy_id="policy.interface.iso_273",
                tolerance_policy_version="1.0.0",
                designation=dia.note or "ISO 273 normal clearance",
            ),
            compatible_counterpart=CompatibleInterfaceCounterpart(
                id="counterpart.motor_mount",
                label="Motor mounting pattern",
                interface_type=InterfaceType.MOUNTING_PATTERN,
                source_evidence_ids=interface_evidence,
            ),
            protected_parameter_ids=tuple(sorted(
                item.dimension_id for item in dimension_bindings
            )),
        ))
        edges.append(Edge(source=PART_NODE, target=INTERFACE_NODE,
                          kind=EdgeKind.HAS_INTERFACE))
        # The interface points at the same dimensions the pattern does, rather
        # than copying their values as Interface.spacing_x used to.
        defines(T.MOUNTING_HOLE_COUNT, INTERFACE_NODE, "hole_count")
        defines(T.MOUNTING_HOLE_DIAMETER, INTERFACE_NODE, "hole_diameter")
        defines(T.HOLE_SPACING_X, INTERFACE_NODE, "spacing_x")
        defines(T.HOLE_SPACING_Y, INTERFACE_NODE, "spacing_y")
        if opening_available:
            edges.append(Edge(
                source=_dim_id(T.SHAFT_OPENING_DIAMETER),
                target=INTERFACE_NODE,
                kind=EdgeKind.DEFINES,
                role="opening_diameter",
            ))
        add_support(INTERFACE_NODE, list(interface_evidence))

    # ---- requirements ---------------------------------------------------
    clearance = resolutions[T.MIN_HOLE_EDGE_CLEARANCE]
    if isinstance(clearance.value, (int, float)):
        nodes.append(RequirementNode(
            id=CLEARANCE_NODE, label="min hole edge clearance",
            requirement_type="min_hole_edge_clearance",
            value=float(clearance.value), unit=clearance.unit or "mm",
            severity=ConstraintSeverity.HARD,
            description=(
                "minimum material between any mounting-hole edge and the plate boundary"
            ),
        ))
        add_support(CLEARANCE_NODE, clearance.provenance)
        # Attached to the feature it governs. Where there is no pattern there is
        # nothing to govern, and the requirement is left unattached rather than
        # pointed at the plate, which is what the measured check reports as
        # SKIPPED rather than failing.
        if pattern_built:
            edges.append(Edge(source=CLEARANCE_NODE, target=PATTERN,
                              kind=EdgeKind.CONSTRAINS, role="edge_distance"))

    graph = EngineeringIntentGraph(revision=1, nodes=nodes, edges=edges)
    problems = graph.validate_edges()
    if problems:
        raise ValueError("intent graph has dangling edges: " + "; ".join(problems))
    return graph, [resolutions[t] for t in T]


def project_to_design_intent(graph: EngineeringIntentGraph) -> DesignIntent:
    """Flatten the graph into the DesignIntent every current consumer reads."""

    def parameter_for(name: str) -> Parameter:
        node = graph.dimension(name)
        if node is None:
            return Parameter(name=name, value=None, status=ParameterStatus.MISSING)
        return Parameter(
            name=node.name, value=node.value, unit=node.unit, status=node.status,
            provenance=graph.supporting_evidence(node.id),
            authority=node.authority, is_explicit=node.is_explicit,
            derivation=node.derivation, competing_values=node.competing_values,
        )

    advanced = (
        any(isinstance(node, AdvancedFeatureNode) for node in graph.nodes)
        or any(
            isinstance(node, DimensionNode) and node.name in {
                target.value for target in ADVANCED_TARGETS
            }
            for node in graph.nodes
        )
    )
    if advanced:
        parameters = {
            node.name: parameter_for(node.name)
            for node in graph.nodes
            if isinstance(node, DimensionNode) and node.value is not None
        }
    else:
        parameters = {t.value: parameter_for(t.value) for t in REQUIRED_TARGETS}
        for target in OPTIONAL_PARAMETER_TARGETS:
            node = graph.dimension(target.value)
            if node is not None and node.value is not None:
                parameters[target.value] = parameter_for(target.value)
        parameters[T.SHAFT_OPENING_DIAMETER.value] = parameter_for(
            T.SHAFT_OPENING_DIAMETER.value
        )

    part_node = graph.node(PART_NODE)
    material = graph.node(MATERIAL_NODE) if graph.has_node(MATERIAL_NODE) else None
    process = graph.node(PROCESS_NODE) if graph.has_node(PROCESS_NODE) else None
    part = PartInfo(
        name=part_node.name,
        material=material.name if material else None,
        manufacturing_process=process.name if process else None,
        provenance=graph.supporting_evidence(PART_NODE),
    )

    interfaces: list[Interface] = []
    for node in graph.nodes:
        if not isinstance(node, InterfaceNode):
            continue
        count = graph.defining_dimension(node.id, "hole_count")
        dia = graph.defining_dimension(node.id, "hole_diameter")
        sx = graph.defining_dimension(node.id, "spacing_x")
        sy = graph.defining_dimension(node.id, "spacing_y")
        if not all((count, dia, sx, sy)):
            continue
        interfaces.append(Interface(
            name=node.name,
            hole_count=int(count.value), hole_diameter=float(dia.value),
            spacing_x=float(sx.value), spacing_y=float(sy.value),
            placement=node.placement, unit=node.unit,
            provenance=graph.supporting_evidence(node.id),
        ))

    constraints: list[Constraint] = []
    for node in graph.nodes:
        if not isinstance(node, RequirementNode):
            continue
        constraints.append(Constraint(
            id=node.id, type=node.requirement_type, value=node.value,
            unit=node.unit, severity=node.severity, description=node.description,
            provenance=graph.supporting_evidence(node.id),
        ))

    return DesignIntent(
        revision=graph.revision, part=part, parameters=parameters,
        interfaces=interfaces, constraints=constraints,
    )


def graph_for_revision(
    graph: EngineeringIntentGraph, intent: DesignIntent
) -> EngineeringIntentGraph:
    """Carry an immutable graph through a flat compatibility-layer revision.

    Repairs and manual edits still derive DesignIntent today. This synchronises
    their changed scalar nodes back into the graph without rebuilding evidence,
    feature identity, or relationships. It can be deleted when revisions derive
    graphs directly.
    """
    nodes = []
    for node in graph.nodes:
        if isinstance(node, DimensionNode) and node.name in intent.parameters:
            parameter = intent.parameters[node.name]
            node = node.model_copy(update={
                "value": parameter.value,
                "unit": parameter.unit,
                "status": parameter.status,
                "authority": parameter.authority,
                "is_explicit": parameter.is_explicit,
                "derivation": parameter.derivation,
                "competing_values": parameter.competing_values,
            })
        elif isinstance(node, PartNode):
            node = node.model_copy(update={"name": intent.part.name, "label": intent.part.name})
        nodes.append(node)
    return graph.model_copy(update={"revision": intent.revision, "nodes": nodes})
