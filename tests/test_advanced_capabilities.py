"""Capability tests for generic profiles, sheet metal, assemblies, GD&T and analyses."""

from __future__ import annotations

import math

import cadquery as cq
import pytest

from spec2cad.analysis import run_analyses
from spec2cad.cad.assembly import execute_assembly
from spec2cad.cad.executor import execute, export_step, import_step
from spec2cad.schemas.analysis_ir import (
    AnalysisProgram,
    AxialStressRequest,
    FitRequest,
    MassPropertiesRequest,
    MaterialProperties,
    ThermalExpansionRequest,
)
from spec2cad.schemas.assembly_ir import (
    AssemblyProgram,
    ComponentInstance,
    OffsetMate,
    Transform,
)
from spec2cad.schemas.cad_ir import (
    ArcSegment,
    BooleanMode,
    BoxOp,
    CADProgram,
    CurvedRodOp,
    CurvedStripOp,
    LineSegment,
    ProfileExtrudeOp,
    ProfilePoint,
    ProfileRevolveOp,
    RectangularLoftOp,
    SheetMetalBendOp,
    SketchPlane,
    SketchProfile,
    ThreadedBoltOp,
    lit,
)
from spec2cad.schemas.gdt_ir import (
    CircularFeatureSelector,
    DatumPlane,
    FlatnessTolerance,
    InspectionProgram,
    PerpendicularityTolerance,
    PositionTolerance,
    SizeTolerance,
)
from spec2cad.validation.gdt import inspect_gdt


def point(x: float, y: float) -> ProfilePoint:
    return ProfilePoint(x=lit(x), y=lit(y))


def polygon(points: list[tuple[float, float]]) -> SketchProfile:
    return SketchProfile(
        start=point(*points[0]),
        segments=[LineSegment(end=point(*value)) for value in points[1:]],
    )


def test_arbitrary_profile_extrude_and_pocket_change_the_brep():
    outer = polygon([(-10, -5), (10, -5), (7, 5), (-10, 5)])
    pocket = polygon([(-2, -2), (2, -2), (2, 2), (-2, 2)])
    program = CADProgram(
        part_name="profile_part",
        operations=[
            ProfileExtrudeOp(id="body", profile=outer, distance=lit(6)),
            ProfileExtrudeOp(
                id="pocket", profile=pocket, distance=lit(10),
                mode=BooleanMode.CUT,
            ),
        ],
    )
    result = execute(program, {})
    assert result.shape.isValid()
    assert len(result.shape.Solids()) == 1
    assert result.measurement("body").volume_delta > 0
    assert result.measurement("pocket").volume_delta < 0


def test_line_and_arc_profile_revolves_without_a_part_template():
    # Annular turned profile: local x is radius and local y is axial position.
    profile = SketchProfile(
        start=point(5, -10),
        segments=[
            LineSegment(end=point(10, -10)),
            ArcSegment(midpoint=point(12, 0), end=point(10, 10)),
            LineSegment(end=point(5, 10)),
        ],
    )
    program = CADProgram(
        part_name="turned_profile",
        operations=[ProfileRevolveOp(
            id="revolve", profile=profile, plane=SketchPlane.XZ,
            axis_start=point(0, 0), axis_end=point(0, 1),
        )],
    )
    result = execute(program, {})
    assert result.shape.isValid()
    assert result.shape.Volume() > 0


def test_sheet_metal_bend_has_radius_bend_allowance_and_flat_length():
    op = SheetMetalBendOp(
        id="bend", leg_a=lit(50), leg_b=lit(40), width=lit(30),
        thickness=lit(2), inside_radius=lit(3), k_factor=lit(0.42),
    )
    result = execute(CADProgram(part_name="bent_bracket", operations=[op]), {})
    assert result.shape.isValid()
    assert len(result.shape.Solids()) == 1
    expected_ba = math.pi / 2 * (3 + 0.42 * 2)
    assert result.context.derived["bend.bend_allowance"] == pytest.approx(expected_ba)
    assert result.context.derived["bend.flat_length"] == pytest.approx(50 - 5 + 40 - 5 + expected_ba)


def test_curved_rod_sweeps_requested_centerline_and_checks_volume():
    op = CurvedRodOp(
        id="curved_rod", diameter=lit(3), total_length=lit(20),
        bend_start=lit(3), bend_radius=lit(3), bend_angle_degrees=lit(270),
    )
    result = execute(CADProgram(part_name="curved_rod", operations=[op]), {})
    assert result.shape.isValid()
    assert len(result.shape.Solids()) == 1
    assert result.context.derived["curved_rod.arc_length"] == pytest.approx(3 * math.pi * 1.5)
    assert result.context.derived["curved_rod.tail_length"] == pytest.approx(
        20 - 3 - 3 * math.pi * 1.5
    )
    assert result.shape.Volume() == pytest.approx(
        result.context.derived["curved_rod.expected_volume"], abs=1e-3
    )


def test_rectangular_loft_builds_a_real_taper_without_part_name_logic():
    op = RectangularLoftOp(
        id="transition", start_width=lit(25), start_height=lit(5),
        end_width=lit(9), end_height=lit(3), length=lit(20),
    )
    result = execute(CADProgram(part_name="anything", operations=[op]), {})
    box = result.shape.BoundingBox()
    assert result.shape.isValid()
    assert len(result.shape.Solids()) == 1
    assert (box.xlen, box.ylen, box.zlen) == pytest.approx((25, 5, 20), abs=1e-5)
    assert result.context.derived == {
        "transition.start_area": 125.0,
        "transition.end_area": 27.0,
    }


def test_curved_strip_sweeps_rectangular_section_without_a_part_template():
    op = CurvedStripOp(
        id="sweep", strip_width=lit(5), extrusion_thickness=lit(4),
        shank_length=lit(20), bend_radius=lit(10),
        bend_angle_degrees=lit(220), tail_length=lit(6),
    )
    result = execute(CADProgram(part_name="generic_curved_bar", operations=[op]), {})
    assert result.shape.isValid()
    assert len(result.shape.Solids()) == 1
    assert result.shape.Volume() == pytest.approx(
        result.context.derived["sweep.expected_volume"], rel=0.02
    )


def test_threaded_bolt_builds_a_real_helix_cut_and_hex_flange_head():
    op = ThreadedBoltOp(
        id="fastener", major_diameter=lit(12), pitch=lit(1.75),
        thread_length=lit(30), shank_length=lit(15),
        head_across_flats=lit(18), head_height=lit(7.5),
        flange_diameter=lit(22), flange_thickness=lit(3),
    )
    result = execute(CADProgram(part_name="m12_flange_bolt", operations=[op]), {})
    assert result.shape.isValid()
    assert len(result.shape.Solids()) == 1
    assert len(result.shape.Faces()) > 20
    assert result.context.derived["fastener.thread_turns"] == pytest.approx(30 / 1.75)
    assert result.context.derived["fastener.thread_root_diameter"] == pytest.approx(
        12 - 1.22687 * 1.75
    )
    assert result.context.derived["fastener.under_head_length"] == 45


def _box_program(name: str) -> CADProgram:
    return CADProgram(
        part_name=name,
        operations=[BoxOp(id="body", width=lit(10), height=lit(10), depth=lit(10))],
    )


def test_assembly_places_components_validates_mates_and_checks_collisions():
    program = AssemblyProgram(
        name="two_blocks",
        components=[
            ComponentInstance(id="a", program=_box_program("a")),
            ComponentInstance(
                id="b", program=_box_program("b"),
                transform=Transform(translation=(15, 0, 0)),
            ),
        ],
        mates=[OffsetMate(
            id="spacing", component_a="a", component_b="b",
            axis="x", distance_mm=15,
        )],
    )
    result = execute_assembly(program)
    assert result.passed
    assert result.checks[0].id == "spacing"
    assert result.checks[-1].id == "collision_a_b"
    assert result.checks[-1].actual == 0


def test_assembly_collision_is_a_failure_not_a_rendering_detail():
    program = AssemblyProgram(
        name="collision",
        components=[
            ComponentInstance(id="a", program=_box_program("a")),
            ComponentInstance(
                id="b", program=_box_program("b"),
                transform=Transform(translation=(5, 0, 0)),
            ),
        ],
    )
    result = execute_assembly(program)
    assert not result.passed
    assert result.checks[-1].actual == pytest.approx(500)


def test_gdt_size_position_flatness_and_perpendicularity_are_measured():
    shape = (
        cq.Workplane("XY").box(30, 20, 5)
        .faces(">Z").workplane().moveTo(2, -1).hole(5).val()
    )
    inspection = InspectionProgram(
        datums=[DatumPlane(id="A", face="top")],
        controls=[
            SizeTolerance(
                id="size", feature=CircularFeatureSelector(
                    nominal_diameter=5, nominal_x=2, nominal_y=-1,
                ), lower_limit=4.9, upper_limit=5.1,
            ),
            PositionTolerance(
                id="position", feature=CircularFeatureSelector(
                    nominal_diameter=5, nominal_x=2, nominal_y=-1,
                ), tolerance_diameter=0.1, datum_references=["A"],
            ),
            FlatnessTolerance(id="flatness", face="top", tolerance=0.01),
            PerpendicularityTolerance(
                id="perpendicular", face="positive_x", datum="A", tolerance=0.01,
            ),
        ],
    )
    results = inspect_gdt(shape, inspection)
    assert [item.control_type for item in results] == [
        "size", "position", "flatness", "perpendicularity",
    ]
    assert all(item.passed for item in results)
    assert results[0].actual == pytest.approx(5)
    assert results[1].actual == pytest.approx(0)


def test_mass_strength_thermal_and_fit_analyses_use_explicit_assumptions():
    shape = cq.Workplane("XY").box(10, 20, 30).val()
    material = MaterialProperties(
        name="6061-T6 aluminium", density_kg_m3=2700,
        yield_strength_mpa=276, elastic_modulus_gpa=68.9,
        thermal_expansion_per_c=23.6e-6,
    )
    program = AnalysisProgram(material=material, requests=[
        MassPropertiesRequest(),
        AxialStressRequest(
            id="axial", force_n=1000, load_path_length_mm=30,
            required_safety_factor=2,
        ),
        ThermalExpansionRequest(
            id="thermal", original_length_mm=100, temperature_change_c=50,
        ),
        FitRequest(
            id="fit", hole_nominal_mm=10.1, hole_tolerance_mm=0.02,
            shaft_nominal_mm=10, shaft_tolerance_mm=0.01,
        ),
    ])
    results = run_analyses(shape, program)
    assert results[0].values["mass_kg"] == pytest.approx(0.0162)
    assert results[1].passed is True
    assert results[2].values["length_change_mm"] == pytest.approx(0.118)
    assert results[3].passed is True


def test_advanced_profile_survives_step_round_trip(tmp_path):
    profile = polygon([(-8, -4), (8, -4), (6, 4), (-8, 4)])
    program = CADProgram(
        part_name="round_trip_profile",
        operations=[ProfileExtrudeOp(id="body", profile=profile, distance=lit(7))],
    )
    execution = execute(program, {})
    path = export_step(execution, tmp_path / "advanced.step")
    restored = import_step(path)
    assert restored.isValid()
    assert len(restored.Solids()) == 1
    assert restored.Volume() == pytest.approx(execution.shape.Volume(), abs=1e-5)
