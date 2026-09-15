"""The intent graph must reproduce DesignIntent exactly before anything trusts it.

These tests are the whole point of adopting the graph this way round. The graph
is only interesting if it carries strictly more than the parameter table; it is
only *safe* if what it carries includes everything the table did. So: parity
first, then the four relationships the table could not express.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from spec2cad.cad.compiler import compile_design
from spec2cad.fusion.entity_resolver import build_design_intent
from spec2cad.fusion.graph_builder import (
    BASE_SOLID,
    CLEARANCE_NODE,
    INTERFACE_NODE,
    PATTERN,
    build_intent_graph,
    project_to_design_intent,
)
from spec2cad.pipeline import gather_evidence
from spec2cad.schemas.evidence import SemanticTarget as T
from spec2cad.schemas.intent_graph import (
    DimensionNode,
    EdgeKind,
    FeatureNode,
    FeatureType,
)

EXAMPLE = Path("examples/motor_adapter")

# created_at is a wall-clock default; every other field must match exactly.
VOLATILE = {"created_at"}


def _both(evidence, part_name="motor_adapter_plate"):
    direct, _ = build_design_intent(evidence, part_name=part_name)
    graph, _ = build_intent_graph(evidence, part_name=part_name)
    return direct, graph, project_to_design_intent(graph)


def _evidence_from_text(tmp_path: Path, text: str):
    requirement = tmp_path / "requirement.txt"
    requirement.write_text(text, encoding="utf-8")
    evidence, _ = gather_evidence(requirement=requirement)
    return evidence


# --------------------------------------------------------------------------
# parity
# --------------------------------------------------------------------------

def test_projection_matches_the_flat_intent_for_the_motor_adapter():
    evidence, _ = gather_evidence(
        sketch=EXAMPLE / "sketch.png",
        datasheet=EXAMPLE / "motor_datasheet.pdf",
        requirement=EXAMPLE / "requirement.txt",
    )
    direct, _, projected = _both(evidence)

    assert projected.model_dump(exclude=VOLATILE) == direct.model_dump(exclude=VOLATILE)


@pytest.mark.parametrize("prompt", [
    # a full text-only design
    "A plate 80 mm wide and 50 mm high, made from 8 mm steel, with a 25 mm "
    "centre opening and a 60 mm by 30 mm mounting pattern of four "
    "normal-clearance holes for M5 screws. Add 1.5 mm chamfers to the external "
    "edges. Every hole must sit at least 4 mm from every hole edge.",
    # holes but no centre opening
    "A 60 x 40 x 6 mm plate with a 44 mm by 24 mm mounting pattern for M4 "
    "screws, normal clearance.",
    # a plate and nothing else
    "A plate 60 mm wide and 40 mm high, made from 6 mm aluminium.",
    # nothing usable at all
    "A rectangle with a small hole in the corner.",
    # a second part identity and feature vocabulary
    "A slotted mounting bracket 80 x 50 x 4 mm aluminium bracket with four "
    "Ø5 mm through holes on a 60 x 30 mm mounting pattern, two 8 x 20 mm "
    "slots spaced 50 mm apart, and 3 mm corner fillets.",
])
def test_projection_matches_the_flat_intent_for_text_prompts(tmp_path, prompt):
    evidence = _evidence_from_text(tmp_path, prompt)
    direct, _, projected = _both(evidence, part_name="mounting_plate")

    assert projected.model_dump(exclude=VOLATILE) == direct.model_dump(exclude=VOLATILE)


def test_graph_features_match_the_compiler_plan(tmp_path):
    """The compiler plan is the ordered projection of graph feature nodes."""
    evidence = _evidence_from_text(
        tmp_path,
        "A plate 80 mm wide and 50 mm high, made from 8 mm steel, with a 25 mm "
        "centre opening and a 60 mm by 30 mm mounting pattern of four "
        "normal-clearance holes for M5 screws. Add 1.5 mm chamfers to the "
        "external edges.",
    )
    direct, graph, _ = _both(evidence, part_name="mounting_plate")

    compiled = [op.id for op in compile_design(graph).operations]
    assert graph.feature_ids() == compiled


def test_graph_has_no_dangling_edges(tmp_path):
    evidence = _evidence_from_text(
        tmp_path,
        "A 60 x 40 x 6 mm plate with a 44 mm by 24 mm mounting pattern for M4 "
        "screws, normal clearance.",
    )
    _, graph, _ = _both(evidence, part_name="mounting_plate")
    assert graph.validate_edges() == []


# --------------------------------------------------------------------------
# what the parameter table could not express
# --------------------------------------------------------------------------

def test_derived_opening_is_an_edge_not_a_sentence():
    """`shaft_opening = boss + 0.5` was only ever readable as prose."""
    evidence, _ = gather_evidence(
        sketch=EXAMPLE / "sketch.png",
        datasheet=EXAMPLE / "motor_datasheet.pdf",
        requirement=EXAMPLE / "requirement.txt",
    )
    _, graph, _ = _both(evidence)

    opening = graph.dimension(T.SHAFT_OPENING_DIAMETER.value)
    derived = graph.out_edges(opening.id, EdgeKind.DERIVED_FROM)
    assert len(derived) == 1

    source = graph.node(derived[0].target)
    assert isinstance(source, DimensionNode)
    assert source.name == T.MOTOR_BOSS_DIAMETER.value
    # and the arithmetic is still traversable, not just stated
    assert opening.value == pytest.approx(float(source.value) + 0.5)


def test_interface_and_pattern_share_one_dimension_node(tmp_path):
    """Interface.spacing_x used to be a copied float that could drift."""
    evidence = _evidence_from_text(
        tmp_path,
        "A 60 x 40 x 6 mm plate with a 44 mm by 24 mm mounting pattern for M4 "
        "screws, normal clearance.",
    )
    _, graph, _ = _both(evidence, part_name="mounting_plate")

    via_interface = graph.defining_dimension(INTERFACE_NODE, "spacing_x")
    via_pattern = graph.defining_dimension(PATTERN, "spacing_x")
    assert via_interface is not None
    assert via_interface.id == via_pattern.id


def test_requirement_points_at_the_feature_it_governs(tmp_path):
    """The seed of a requirement predicate IR: not a magic string any more."""
    evidence = _evidence_from_text(
        tmp_path,
        "A plate 50 mm wide and 30 mm high, made from 5 mm aluminium, with a "
        "44 mm by 24 mm mounting pattern of four normal-clearance holes for M4 "
        "screws, at least 4 mm from every hole edge.",
    )
    _, graph, _ = _both(evidence, part_name="mounting_plate")

    governed = graph.out_edges(CLEARANCE_NODE, EdgeKind.CONSTRAINS)
    assert [e.target for e in governed] == [PATTERN]

    feature = graph.node(PATTERN)
    assert isinstance(feature, FeatureNode)
    assert feature.feature_type is FeatureType.HOLE_PATTERN


def test_clearance_requirement_is_unattached_when_there_is_no_pattern(tmp_path):
    """Stated clearance, no holes to apply it to. It governs nothing, and says so
    rather than being pointed at the plate -- which is what the measured check
    reports as SKIPPED."""
    evidence = _evidence_from_text(
        tmp_path,
        "A plate 60 mm wide and 40 mm high from 6 mm aluminium, at least 4 mm "
        "from every hole edge.",
    )
    _, graph, _ = _both(evidence, part_name="mounting_plate")

    assert graph.has_node(CLEARANCE_NODE)
    assert graph.out_edges(CLEARANCE_NODE, EdgeKind.CONSTRAINS) == []


def test_thread_spec_survives_into_the_graph(tmp_path):
    """The parameter table drops "M4" once ISO 273 has turned it into 4.5 mm."""
    evidence = _evidence_from_text(
        tmp_path,
        "A 60 x 40 x 6 mm plate with a 44 mm by 24 mm mounting pattern for M4 "
        "screws, normal clearance.",
    )
    direct, graph, _ = _both(evidence, part_name="mounting_plate")

    assert T.MOUNTING_THREAD_SPEC.value not in direct.parameters
    thread = graph.dimension(T.MOUNTING_THREAD_SPEC.value)
    assert thread is not None and thread.value == "M4"


def test_every_dimension_carries_its_evidence_as_edges(tmp_path):
    evidence = _evidence_from_text(
        tmp_path,
        "A 60 x 40 x 6 mm plate with a 44 mm by 24 mm mounting pattern for M4 "
        "screws, normal clearance.",
    )
    _, graph, projected = _both(evidence, part_name="mounting_plate")

    width = graph.dimension(T.PLATE_WIDTH.value)
    supporting = graph.supporting_evidence(width.id)
    assert supporting, "plate_width came from somewhere"
    # the flat view is reconstructed from those edges, not stored twice
    assert projected.param(T.PLATE_WIDTH.value).provenance == supporting
    for ev_id in supporting:
        assert graph.has_node(ev_id)


def test_base_solid_is_always_present_and_dimensioned(tmp_path):
    evidence = _evidence_from_text(
        tmp_path, "A plate 60 mm wide and 40 mm high, made from 6 mm aluminium."
    )
    _, graph, _ = _both(evidence, part_name="mounting_plate")

    assert graph.defining_dimension(BASE_SOLID, "width").value == pytest.approx(60.0)
    assert graph.defining_dimension(BASE_SOLID, "height").value == pytest.approx(40.0)
    assert graph.defining_dimension(BASE_SOLID, "depth").value == pytest.approx(6.0)
