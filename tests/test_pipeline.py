"""End-to-end and unit tests for the spec2cad pipeline.

These run entirely offline against the recorded fixture, so they are
deterministic and cost nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from spec2cad.cad.compiler import compile_design, parameter_table
from spec2cad.cad.executor import UnsupportedOperation, execute, export_step
from spec2cad.fusion.conflict_detector import edge_clearance, minimum_plate_dimension
from spec2cad.knowledge.fastener_tables import FitClass, UnknownThread, clearance_hole
from spec2cad.knowledge.recommendations import recommended_rounded_width
from spec2cad.pipeline import repair, run, verify_exported_step
from spec2cad.preview import render_evidence_preview
from spec2cad.repair.repair_planner import (
    ProposalSafety,
    UnsafeRepairRequiresAcknowledgement,
    apply_repair,
)
from spec2cad.schemas.report import CheckStatus, ConflictClass
from spec2cad.schemas.evidence import SemanticTarget
from spec2cad.validation import measure as M

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "motor_adapter"


@pytest.fixture(scope="module")
def v1():
    return run(
        EXAMPLE / "sketch.png",
        EXAMPLE / "motor_datasheet.pdf",
        EXAMPLE / "requirement.txt",
        backend_override="fixture",
    )


@pytest.fixture(scope="module")
def v2(v1):
    return repair(v1, "widen_to_recommended", approved_by="pytest")


# ---------------------------------------------------------------- arithmetic


def test_clearance_arithmetic_chain():
    """The 2.8 / 42.4 / 5.3 chain the whole demo turns on."""
    assert edge_clearance(40.0, 31.0, 3.4) == pytest.approx(2.8)
    assert minimum_plate_dimension(31.0, 3.4, 4.0) == pytest.approx(42.4)
    assert recommended_rounded_width(42.4).recommended_mm == pytest.approx(45.0)
    assert edge_clearance(45.0, 31.0, 3.4) == pytest.approx(5.3)


def test_iso273_lookup_is_cited_not_guessed():
    lookup = clearance_hole("M3", FitClass.MEDIUM)
    assert lookup.diameter_mm == pytest.approx(3.4)
    assert "ISO 273" in lookup.citation
    with pytest.raises(UnknownThread):
        clearance_hole("M3.7")


def test_recommendation_always_leaves_margin():
    """A minimum landing exactly on an increment steps up rather than sitting on the limit."""
    assert recommended_rounded_width(45.0).recommended_mm == pytest.approx(50.0)
    assert recommended_rounded_width(42.4).extra_width_mm > 0


def test_extra_width_is_not_reported_as_extra_clearance():
    """Width is shared between two edges, so clearance gains half of it.

    Reporting the full 2.6 mm next to a clearance requirement reads as
    clearance margin and overstates the gain by exactly a factor of two.
    """
    rec = recommended_rounded_width(42.4)
    assert rec.recommended_mm == pytest.approx(45.0)
    assert rec.extra_width_mm == pytest.approx(2.6)
    assert rec.extra_clearance_per_side_mm == pytest.approx(1.3)
    assert "1.3 mm additional clearance per side" in rec.describe()
    assert "2.6" not in rec.describe()


def test_recommended_width_lands_on_the_measured_clearance():
    """The advertised per-side gain must reconcile with the final measurement.

    2.8 mm measured at 40 mm, +1.3 mm per side beyond the 4.0 mm minimum, is
    the 5.3 mm the repaired revision actually measures.
    """
    rec = recommended_rounded_width(42.4)
    assert 4.0 + rec.extra_clearance_per_side_mm == pytest.approx(5.3)


# ---------------------------------------------------------------- extraction


def test_datasheet_extraction_has_real_page_and_bbox(v1):
    spacing = [e for e in v1.evidence.items if e.target.value == "hole_spacing_x"]
    assert len(spacing) == 1
    ev = spacing[0]
    assert ev.value == pytest.approx(31.0)
    assert ev.source.page == 3, "the pattern is on page 3 of the datasheet"
    assert ev.source.region is not None and len(ev.source.region) == 4
    x0, y0, x1, y1 = ev.source.region
    assert x1 > x0 and y1 > y0, "bbox must be a real, non-degenerate rectangle"


def test_datasheet_prose_does_not_masquerade_as_a_table_row(v1):
    """Page 4 says 'pilot boss diameter listed in section 3'.

    An unanchored label match scraped '3' out of 'section 3.' and reported it as
    the boss diameter. The value must come from the page-3 table instead.
    """
    boss = [e for e in v1.evidence.items if e.target.value == "motor_boss_diameter"]
    assert len(boss) == 1
    assert boss[0].value == pytest.approx(22.0)
    assert boss[0].source.page == 3


def test_hole_diameter_is_derived_from_a_standard(v1):
    dia = [e for e in v1.evidence.items if e.target.value == "mounting_hole_diameter"][0]
    assert dia.value == pytest.approx(3.4)
    assert dia.extraction_method.value == "knowledge_table"
    assert "ISO 273" in (dia.source.detail or "")
    assert dia.is_explicit_annotation is False, "a derived value is not an annotation"


def test_sketch_evidence_highlights_its_own_annotation(v1):
    """Count and orientation used to point at the same MOTOR SIDE rectangle."""
    by_target = {
        e.target.value: e
        for e in v1.evidence.items
        if e.source.modality.value == "sketch"
    }
    count_region = by_target["mounting_hole_count"].source.region
    orientation_region = by_target["orientation_note"].source.region
    assert count_region is not None
    assert orientation_region is not None
    assert count_region != orientation_region


def test_confidence_and_authority_are_separate_fields(v1):
    process = [e for e in v1.evidence.items
               if e.target.value == "manufacturing_process"][0]
    assert process.authority.value == "advisory"
    assert process.confidence < 1.0
    rule = [e for e in v1.evidence.items
            if e.target.value == "mounting_hole_diameter"][0]
    # high confidence AND definitive, but via different axes
    assert rule.confidence == pytest.approx(1.0)
    assert rule.authority.value == "definitive"


# ---------------------------------------------------------------- fusion


def test_corroborating_sources_are_both_recorded(v1):
    count = v1.revision(1).intent.param("mounting_hole_count")
    assert len(count.provenance) == 2, "sketch and datasheet both state the hole count"


def test_explicit_annotation_beats_inferred_regardless_of_authority():
    from spec2cad.fusion.entity_resolver import resolve_target
    from spec2cad.schemas.evidence import (
        Authority, Evidence, EvidenceKind, ExtractionMethod,
        SemanticTarget, SourceModality, SourceRef,
    )

    def mk(eid, val, explicit, authority):
        return Evidence(
            id=eid, entity="p", kind=EvidenceKind.LINEAR_DIMENSION,
            target=SemanticTarget.HOLE_SPACING_X, value=val, unit="mm",
            source=SourceRef(file="f", modality=SourceModality.SKETCH),
            extraction_method=ExtractionMethod.RULE_PARSER, confidence=0.9,
            authority=authority, is_explicit_annotation=explicit,
        )

    res = resolve_target(SemanticTarget.HOLE_SPACING_X, [
        mk("inferred_definitive", 33.0, False, Authority.DEFINITIVE),
        mk("explicit_supporting", 31.0, True, Authority.SUPPORTING),
    ])
    assert res.value == pytest.approx(31.0)
    assert res.status.value == "confirmed"


def test_two_explicit_disagreeing_sources_are_not_auto_resolved():
    """Authority must never silently discard an explicit annotation."""
    from spec2cad.fusion.entity_resolver import resolve_target
    from spec2cad.schemas.evidence import (
        Authority, Evidence, EvidenceKind, ExtractionMethod,
        SemanticTarget, SourceModality, SourceRef,
    )

    def mk(eid, val, modality, authority):
        return Evidence(
            id=eid, entity="p", kind=EvidenceKind.LINEAR_DIMENSION,
            target=SemanticTarget.HOLE_SPACING_X, value=val, unit="mm",
            source=SourceRef(file="f", modality=modality),
            extraction_method=ExtractionMethod.RULE_PARSER, confidence=0.95,
            authority=authority, is_explicit_annotation=True,
        )

    res = resolve_target(SemanticTarget.HOLE_SPACING_X, [
        mk("sketch", 35.0, SourceModality.SKETCH, Authority.SUPPORTING),
        mk("datasheet", 31.0, SourceModality.DATASHEET, Authority.DEFINITIVE),
    ])
    assert res.status.value == "adjudication_required"
    assert len(res.competing) == 2
    assert {c["value"] for c in res.competing} == {35.0, 31.0}


# ---------------------------------------------------------------- conflicts


def test_headline_failure_is_a_constraint_conflict_not_a_source_conflict(v1):
    check = v1.revision(1).preflight.get("pre_edge_clearance_x")
    assert check.status is CheckStatus.FAIL
    assert check.conflict_class is ConflictClass.CONSTRAINT
    assert set(check.responsible_parameters) == {
        "plate_width", "hole_spacing_x", "mounting_hole_diameter"
    }
    # nobody misread anything
    src = v1.revision(1).preflight.get("pre_source_conflicts")
    assert src.status is CheckStatus.PASS


def test_chamfer_rule_is_in_plane_not_thickness_based():
    """A 1 mm chamfer on a 1.5 mm plate is legal and must not be flagged.

    The kernel builds it as a valid solid -- these chamfers run along vertical
    edges, so plate thickness does not constrain them.
    """
    from spec2cad.fusion.conflict_detector import run_preflight

    intent = _thin_plate_intent(thickness=1.5, chamfer=1.0)
    report = run_preflight(intent)
    assert report.get("pre_chamfer").status is CheckStatus.PASS

    result = execute(compile_design(intent), parameter_table(intent))
    assert result.shape.isValid()


def test_chamfer_larger_than_half_the_plate_is_rejected():
    from spec2cad.fusion.conflict_detector import run_preflight

    intent = _thin_plate_intent(thickness=5.0, chamfer=30.0, width=45.0, height=50.0)
    assert run_preflight(intent).get("pre_chamfer").status is CheckStatus.FAIL


def _thin_plate_intent(thickness: float, chamfer: float,
                       width: float = 45.0, height: float = 50.0):
    from spec2cad.schemas.design_intent import (
        Constraint, DesignIntent, Parameter, PartInfo,
    )

    def p(name, value):
        return Parameter(name=name, value=value, unit="mm")

    return DesignIntent(
        part=PartInfo(name="thin_plate", material="Aluminium"),
        parameters={
            "plate_width": p("plate_width", width),
            "plate_height": p("plate_height", height),
            "plate_thickness": p("plate_thickness", thickness),
            "hole_spacing_x": p("hole_spacing_x", 31.0),
            "hole_spacing_y": p("hole_spacing_y", 31.0),
            "mounting_hole_count": p("mounting_hole_count", 4),
            "mounting_hole_diameter": p("mounting_hole_diameter", 3.4),
            "motor_boss_diameter": p("motor_boss_diameter", 22.0),
            "shaft_opening_diameter": p("shaft_opening_diameter", 22.5),
            "external_chamfer": p("external_chamfer", chamfer),
        },
        constraints=[Constraint(id="c", type="min_hole_edge_clearance", value=4.0)],
    )


# ---------------------------------------------------------------- measurement


def test_measurements_come_from_the_brep_not_the_inputs(v1):
    shape = v1.revision(1).execution.shape
    extents = M.plate_extents(shape)
    assert extents.width == pytest.approx(40.0, abs=1e-6)
    assert extents.thickness == pytest.approx(5.0, abs=1e-6), (
        "measured via face positions; BoundingBox reports 5.007 here"
    )
    mounts = M.features_near_radius(M.circular_features(M.top_face(shape)), 1.7)
    assert len(mounts) == 4
    assert mounts[0].diameter == pytest.approx(3.4, abs=1e-6)
    assert M.hole_spacing(mounts) == pytest.approx((31.0, 31.0), abs=1e-6)


def test_invalid_candidate_is_built_so_the_violation_can_be_measured(v1):
    """v1 must build. Refusing to build would leave only a prediction."""
    rev = v1.revision(1)
    assert rev.build_error is None
    assert rev.execution is not None
    assert rev.execution.shape.isValid()
    measured = rev.measured[-1].get("req_edge_clearance")
    assert measured.measured_value == pytest.approx(2.8, abs=1e-6)


def test_preflight_prediction_agrees_with_measurement(v1, v2):
    for result in (v1.revision(1), v2.revision(2)):
        xcheck = [c for c in result.cross_checks if c.id.startswith("xcheck_")]
        assert xcheck, "the cross-check must actually run"
        assert all(c.status is CheckStatus.PASS for c in xcheck)


def test_volume_check_catches_a_wrong_sized_feature(v1):
    """The analytic volume comparison is not vacuous."""
    shape = v1.revision(1).execution.shape
    honest = M.expected_volume(40.0, 50.0, 5.0, 22.5, 3.4, 4, 1.0)
    assert shape.Volume() == pytest.approx(honest, abs=1e-3)
    wrong = M.expected_volume(40.0, 50.0, 5.0, 22.5, 5.0, 4, 1.0)
    assert abs(shape.Volume() - wrong) > M.VOLUME_TOLERANCE_MM3


# ---------------------------------------------------------------- gate


def test_gate_blocks_v1_and_withholds_step(v1):
    decision = v1.revision(1).decision
    assert decision.step_export_allowed is False
    assert "PROVISIONAL" in decision.mesh_watermark
    assert any("2.8" in r for r in decision.reasons)


def test_gate_authorises_v2(v2):
    rev = v2.revision(2)
    assert rev.revision == 2
    assert rev.decision.step_export_allowed is True
    assert rev.measured[-1].get("req_edge_clearance").measured_value == pytest.approx(
        5.3, abs=1e-6
    )


def test_exported_step_revalidates_after_reimport(v2, tmp_path):
    """Validate the artifact, not just the in-memory result."""
    step = export_step(v2.revision(2).execution, tmp_path / "part.step")
    assert step.stat().st_size > 0
    reports = verify_exported_step(step, v2.revision(2).intent)
    for report in reports:
        assert report.passed, [c.message for c in report.failures]


# ---------------------------------------------------------------- repair


def test_unsafe_proposals_are_never_auto_applied(v1):
    unsafe = [p for p in v1.revision(1).proposals if p.safety is ProposalSafety.UNSAFE]
    assert unsafe, "the unsafe options must still be offered and explained"
    for proposal in unsafe:
        assert proposal.auto_applicable is False
        assert proposal.consequence, "an unsafe option must state what it costs"
        with pytest.raises(UnsafeRepairRequiresAcknowledgement):
            apply_repair(v1.revision(1).intent, proposal, approved_by="test")


def test_safe_proposals_do_not_touch_the_motor_interface(v1):
    safe = [p for p in v1.revision(1).proposals if p.safety is ProposalSafety.SAFE]
    assert len(safe) == 2
    interface = {"hole_spacing_x", "hole_spacing_y", "mounting_hole_diameter",
                 "mounting_hole_count"}
    for proposal in safe:
        assert not (set(proposal.updates) & interface)


def test_repair_creates_an_immutable_revision(v1, v2):
    original, revised = v1.revision(1).intent, v2.revision(2).intent
    assert original.revision == 1 and revised.revision == 2
    assert revised.parent_revision == 1
    assert original.value_of("plate_width") == pytest.approx(40.0), "v1 must survive"
    assert revised.value_of("plate_width") == pytest.approx(45.0)
    assert revised.approved_by == "pytest"
    assert revised.applied_proposal == "widen_to_recommended"
    change = revised.changes[0]
    assert (change.before, change.after) == (40.0, 45.0)


def test_design_intent_cannot_be_mutated_in_place(v1):
    intent = v1.revision(1).intent
    with pytest.raises(Exception):
        intent.revision = 99
    with pytest.raises(Exception):
        intent.parameters["plate_width"].value = 45.0


# ---------------------------------------------------------------- schema


def test_unknown_operation_is_a_hard_stop_not_a_fallback(v1):
    from spec2cad.cad.executor import HANDLERS
    from spec2cad.schemas.cad_ir import ChamferOp

    intent = v1.revision(1).intent
    program, values = compile_design(intent), parameter_table(intent)
    saved = HANDLERS.pop(ChamferOp)
    try:
        with pytest.raises(UnsupportedOperation):
            execute(program, values)
    finally:
        HANDLERS[ChamferOp] = saved


def test_unresolvable_parameter_reference_is_rejected():
    from spec2cad.schemas.cad_ir import UnresolvedReference, ref, resolve

    with pytest.raises(UnresolvedReference):
        resolve(ref("typo_param"), {"plate_width": 45.0})


def test_literal_and_reference_survive_json_round_trip():
    import json

    from spec2cad.schemas.cad_ir import (
        BoxOp, CADProgram, NumberLiteral, ParamRef, lit, ref,
    )

    program = CADProgram(part_name="p", operations=[
        BoxOp(id="b", width=ref("plate_width"), height=lit(50.0), depth=lit(5.0)),
    ])
    restored = CADProgram.model_validate(json.loads(program.model_dump_json()))
    box = restored.operation("b")
    assert isinstance(box.width, ParamRef)
    assert isinstance(box.height, NumberLiteral)


def test_malformed_vision_output_is_rejected():
    from spec2cad.extractors.vision import VisionExtractionError, _parse_payload, _to_evidence

    with pytest.raises(VisionExtractionError):
        _parse_payload("not json at all")
    with pytest.raises(VisionExtractionError):
        _parse_payload('{"wrong_key": []}')
    with pytest.raises(VisionExtractionError):
        _to_evidence(
            [{"target": "made_up_parameter", "kind": "note", "value": 1}],
            Path("sketch.png"), "test-model",
        )


# ---------------------------------------------------------------- honesty


def test_fixture_evidence_cannot_be_scored_as_extraction(v1):
    """A recording must never be reported as extraction accuracy."""
    import json

    from eval.metrics import FixtureEvidenceInMetrics, score_extraction

    truth = json.loads((EXAMPLE / "sketch.truth.json").read_text(encoding="utf-8"))
    sketch_evidence = [
        e for e in v1.evidence.items if e.source.modality.value == "sketch"
    ]
    assert all(e.is_fixture for e in sketch_evidence)
    with pytest.raises(FixtureEvidenceInMetrics):
        score_extraction(sketch_evidence, truth["facts"], backend="fixture")


def test_run_reports_which_backend_produced_the_sketch_evidence(v1):
    assert "fixture" in v1.sketch_backend.lower()
    assert v1.evidence.contains_fixture_data is True


# ----------------------------------------------------------- partial sources


@pytest.mark.parametrize(
    "sources,expected_modality",
    [
        ({"sketch": EXAMPLE / "sketch.png", "backend_override": "fixture"}, "sketch"),
        ({"datasheet": EXAMPLE / "motor_datasheet.pdf"}, "datasheet"),
        ({"requirement": EXAMPLE / "requirement.txt"}, "requirement_text"),
    ],
)
def test_any_single_source_can_start_a_run(sources, expected_modality):
    result = run(**sources)
    assert result.evidence.items
    assert {e.source.modality.value for e in result.evidence.items} >= {
        expected_modality
    }
    assert result.latest.build_error is not None
    assert result.latest.decision.step_export_allowed is False
    assert "Geometry generated" in {
        c.name for report in result.latest.measured for c in report.checks
    }


def test_two_sources_are_fused_without_requiring_the_third():
    result = run(
        datasheet=EXAMPLE / "motor_datasheet.pdf",
        requirement=EXAMPLE / "requirement.txt",
    )
    modalities = {e.source.modality.value for e in result.evidence.items}
    assert {"datasheet", "requirement_text", "engineering_rule"} <= modalities
    assert result.latest.intent.has("plate_thickness")
    assert not result.latest.intent.has("plate_width")
    assert result.latest.decision.step_export_allowed is False


def test_natural_language_text_only_prompt_builds_complete_plate(tmp_path):
    requirement = tmp_path / "requirement.txt"
    requirement.write_text(
        "Create a 60 mm wide, 40 mm high mounting plate from 6 mm aluminium. "
        "Use normal-clearance holes for M4 screws on a 44 mm by 24 mm "
        "rectangular pattern, include a 20 mm centre opening, maintain at least "
        "5 mm from every hole edge to the plate boundary, and add 1 mm chamfers "
        "to the external edges. Manufacture it by machining.",
        encoding="utf-8",
    )

    result = run(requirement=requirement)
    intent = result.latest.intent

    assert intent.part.name == "mounting_plate"
    assert intent.value_of("plate_width") == pytest.approx(60.0)
    assert intent.value_of("plate_height") == pytest.approx(40.0)
    assert intent.value_of("plate_thickness") == pytest.approx(6.0)
    assert intent.value_of("hole_spacing_x") == pytest.approx(44.0)
    assert intent.value_of("hole_spacing_y") == pytest.approx(24.0)
    assert intent.value_of("mounting_hole_count") == pytest.approx(4)
    assert intent.value_of("mounting_hole_diameter") == pytest.approx(4.5)
    assert intent.value_of("shaft_opening_diameter") == pytest.approx(20.0)
    assert result.latest.build_error is None
    assert result.latest.released is True


def test_square_plate_side_length_expands_to_equal_width_and_height(tmp_path):
    requirement = tmp_path / "requirement.txt"
    requirement.write_text(
        "create a square plate of length 30 mm and thickness 3 mm",
        encoding="utf-8",
    )

    result = run(requirement=requirement)
    rev = result.latest

    assert rev.intent.value_of("plate_width") == pytest.approx(30.0)
    assert rev.intent.value_of("plate_height") == pytest.approx(30.0)
    assert rev.intent.value_of("plate_thickness") == pytest.approx(3.0)
    assert [operation.id for operation in rev.program.operations] == ["base_plate"]
    extents = M.plate_extents(rev.execution.shape)
    assert (extents.width, extents.height, extents.thickness) == pytest.approx(
        (30.0, 30.0, 3.0)
    )
    assert rev.released is True


def test_named_plate_dimensions_typo_and_center_hole_are_extracted(tmp_path):
    requirement = tmp_path / "requirement.txt"
    requirement.write_text(
        "create a plate with 25 mm length and 2 mm width and 3 mm thickmess "
        "and hole of 3 mm dia at center",
        encoding="utf-8",
    )

    result = run(requirement=requirement)
    facts = {item.target: item.value for item in result.evidence.items}

    assert facts[SemanticTarget.PLATE_WIDTH] == pytest.approx(25)
    assert facts[SemanticTarget.PLATE_HEIGHT] == pytest.approx(2)
    assert facts[SemanticTarget.PLATE_THICKNESS] == pytest.approx(3)
    assert facts[SemanticTarget.SHAFT_OPENING_DIAMETER] == pytest.approx(3)
    assert result.latest.build_error is None
    assert result.latest.released is False
    assert any(
        "not one piece" in reason or "shaft diameter" in reason
        for reason in result.latest.decision.reasons
    )


def test_named_plate_dimensions_and_center_hole_build_when_feasible(tmp_path):
    requirement = tmp_path / "requirement.txt"
    requirement.write_text(
        "create a plate with 25 mm length and 12 mm width and 3 mm thickness "
        "and hole of 3 mm dia at center",
        encoding="utf-8",
    )

    result = run(requirement=requirement)

    assert result.latest.build_error is None
    assert result.latest.released is True


def test_incomplete_text_prompt_requests_only_dimensions_needed_to_build(tmp_path):
    requirement = tmp_path / "requirement.txt"
    requirement.write_text(
        "Make a mounting plate from 6 mm aluminium.", encoding="utf-8"
    )

    result = run(requirement=requirement)

    assert result.latest.build_error is not None
    assert result.latest.decision.responsible_parameters == [
        "plate_width", "plate_height",
    ]


def test_text_prompt_without_a_centre_opening_still_validates(tmp_path):
    """A plate with mounting holes but no centre opening is a complete design.

    run_dimensions used to read shaft_opening_diameter unconditionally, so this
    prompt raised TypeError out of the pipeline instead of producing a report --
    every existing text-only test happened to ask for a centre opening, so
    nothing covered the feature being absent.
    """
    requirement = tmp_path / "requirement.txt"
    requirement.write_text(
        "A 60 x 40 x 6 mm plate with a 44 mm by 24 mm mounting pattern "
        "for M4 screws, normal clearance.",
        encoding="utf-8",
    )

    result = run(requirement=requirement)
    rev = result.latest

    assert rev.build_error is None
    assert [op.id for op in rev.program.operations] == ["base_plate", "mounting_holes"]
    assert rev.released is True

    shaft = next(c for c in rev.all_checks() if c.id == "dim_shaft_opening")
    assert shaft.status is CheckStatus.SKIPPED

    # The volume comparison is the check that catches a feature built at the
    # wrong size. It must still run here -- a design without a centre opening
    # is not a design that cannot be measured.
    volume = next(c for c in rev.all_checks() if c.id == "top_material_integrity")
    assert volume.status is CheckStatus.PASS


def test_text_prompt_with_no_holes_at_all_still_validates(tmp_path):
    """The same guard, for a design that is only a plate."""
    requirement = tmp_path / "requirement.txt"
    requirement.write_text(
        "A plate 60 mm wide and 40 mm high, made from 6 mm aluminium.",
        encoding="utf-8",
    )

    result = run(requirement=requirement)
    rev = result.latest

    assert rev.build_error is None
    assert [op.id for op in rev.program.operations] == ["base_plate"]

    counted = next(c for c in rev.all_checks() if c.id == "dim_hole_count")
    assert counted.status is CheckStatus.SKIPPED
    assert counted.responsible_parameters == [
        "mounting_hole_diameter", "mounting_hole_count",
    ]

    volume = next(c for c in rev.all_checks() if c.id == "top_material_integrity")
    assert volume.status is CheckStatus.PASS


def test_compact_shorthand_reads_the_envelope_through_a_material_word(tmp_path):
    """"6 mm aluminium plate" states a width just as "6 mm plate" does."""
    requirement = tmp_path / "requirement.txt"
    requirement.write_text(
        "A 60 x 40 x 6 mm aluminium plate with a 44 mm by 24 mm mounting "
        "pattern for M4 screws, normal clearance.",
        encoding="utf-8",
    )

    intent = run(requirement=requirement).latest.intent

    assert intent.value_of("plate_width") == pytest.approx(60.0)
    assert intent.value_of("plate_height") == pytest.approx(40.0)
    assert intent.value_of("plate_thickness") == pytest.approx(6.0)
    assert intent.part.material == "Aluminium"


def test_run_requires_at_least_one_source():
    with pytest.raises(ValueError, match="at least one source"):
        run()


def test_sketch_preview_keeps_full_source_and_highlights_region(v1, tmp_path):
    evidence = next(
        item for item in v1.evidence.items
        if item.source.file == "sketch.png" and item.source.region is not None
    )
    preview_path = render_evidence_preview(evidence, EXAMPLE, tmp_path / "preview.png")

    with Image.open(EXAMPLE / "sketch.png").convert("RGB") as source:
        with Image.open(preview_path).convert("RGB") as preview:
            assert preview.size == source.size
            x0, y0, _, _ = evidence.source.region
            corner = (int(x0), int(y0))
            assert preview.getpixel(corner) != source.getpixel(corner)


# -------------------------------------------------- per-operation measurement


def test_every_operation_is_measured_on_the_intermediate_solid(v1):
    """The feature list must be evidence, not a restatement of the program.

    Without this, a feature row says only what we asked the kernel to do, and
    would look identical if the kernel had silently done nothing.
    """
    ops = v1.latest.program.operations
    measured = v1.latest.execution.measurements
    assert [m.operation_id for m in measured] == [o.id for o in ops]
    assert all(m.is_valid for m in measured)
    assert all(m.solid_count == 1 for m in measured)


def test_no_operation_is_a_silent_no_op(v1):
    """Every feature in the program must actually change the solid."""
    for m in v1.latest.execution.measurements:
        assert not m.no_op, f"{m.operation_id} built but changed no material"


def test_material_removal_matches_the_feature_kind(v1):
    """The first operation adds material; every cut removes it."""
    measured = v1.latest.execution.measurements
    assert measured[0].volume_delta > 0, "base_plate should add material"
    for m in measured[1:]:
        assert m.removed_material, f"{m.operation_id} should remove material"


def test_measured_volumes_are_cumulative_and_end_at_the_part_volume(v1):
    """Intermediate volumes must reconcile with the finished solid."""
    measured = v1.latest.execution.measurements
    running = 0.0
    for m in measured:
        running += m.volume_delta
        assert m.volume == pytest.approx(running, abs=1e-6)
    assert measured[-1].volume == pytest.approx(
        v1.latest.execution.shape.Volume(), abs=1e-6
    )


def test_widening_the_plate_changes_only_the_base_plate_measurement(v1, v2):
    """A width repair must not disturb the features cut into the plate."""
    before = {m.operation_id: m.volume_delta for m in v1.latest.execution.measurements}
    after = {m.operation_id: m.volume_delta for m in v2.latest.execution.measurements}
    assert after["base_plate"] > before["base_plate"]
    for op_id in ("shaft_opening", "mounting_holes", "external_chamfers"):
        assert after[op_id] == pytest.approx(before[op_id], abs=1e-6)
