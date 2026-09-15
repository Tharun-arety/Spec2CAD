"""CADProgram: a typed, kernel-agnostic feature plan.

This is deliberately *not* Python, and deliberately not a direct serialisation of
DesignIntent. It is the narrow, checkable waist of the pipeline:

  - A model may propose operations, but it can only ever produce values that fit
    this schema. It cannot emit code, so there is no arbitrary Python to sandbox.
  - The executor owns every CAD call. If an operation type is unknown, execution
    fails loudly rather than falling back to something plausible.

Numeric fields use an explicit tagged union -- NumberLiteral or ParamRef -- never
a stringly-typed `float | str` overload where "45" and "plate_width" would be
told apart by guessing at runtime. A reference is a distinct type, and an
unresolvable one is an error at resolve time with the offending name reported.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------
# Numeric values: literal or parameter reference, discriminated explicitly
# --------------------------------------------------------------------------


class NumberLiteral(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["literal"] = "literal"
    value: float = Field(ge=-1_000_000, le=1_000_000, allow_inf_nan=False)


class ParamRef(BaseModel):
    """A reference to a DesignIntent parameter, resolved at execution time."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["param_ref"] = "param_ref"
    ref: str


Numeric = Annotated[Union[NumberLiteral, ParamRef], Field(discriminator="kind")]


def lit(value: float) -> NumberLiteral:
    return NumberLiteral(value=float(value))


def ref(name: str) -> ParamRef:
    return ParamRef(ref=name)


class UnresolvedReference(KeyError):
    """Raised when a ParamRef names a parameter that does not exist."""


def resolve(numeric: NumberLiteral | ParamRef, values: dict[str, float]) -> float:
    """Resolve a Numeric against a parameter table.

    Unknown references raise rather than defaulting, so a typo in a reference
    can never silently become geometry.
    """
    if isinstance(numeric, NumberLiteral):
        return float(numeric.value)
    if numeric.ref not in values:
        raise UnresolvedReference(
            f"CADProgram references unknown parameter {numeric.ref!r}; "
            f"known parameters: {sorted(values)}"
        )
    value = values[numeric.ref]
    if value is None:
        raise UnresolvedReference(f"parameter {numeric.ref!r} has no value")
    return float(value)


# --------------------------------------------------------------------------
# Selectors: named intent, never kernel selector strings
# --------------------------------------------------------------------------


class EdgeSelector(str, Enum):
    """Named edge sets. The IR never carries CadQuery selector syntax; the
    mapping from these names to kernel selectors lives in cad/selectors.py."""

    EXTERNAL_VERTICAL_EDGES = "external_vertical_edges"
    EXTERNAL_TOP_PERIMETER = "external_top_perimeter"


class FaceSelector(str, Enum):
    TOP_FACE = "top_face"
    BOTTOM_FACE = "bottom_face"


class Termination(str, Enum):
    THROUGH_ALL = "through_all"
    BLIND = "blind"


class SketchPlane(str, Enum):
    XY = "XY"
    XZ = "XZ"
    YZ = "YZ"


class ProfilePoint(BaseModel):
    """A point in a sketch plane. Coordinates can reference intent dimensions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    x: Numeric
    y: Numeric


class LineSegment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["line"] = "line"
    end: ProfilePoint


class ArcSegment(BaseModel):
    """A circular arc defined without a kernel-specific radius convention."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["three_point_arc"] = "three_point_arc"
    midpoint: ProfilePoint
    end: ProfilePoint


ProfileSegment = Annotated[
    Union[LineSegment, ArcSegment], Field(discriminator="type")
]


class SketchProfile(BaseModel):
    """A closed, ordered line/arc wire suitable for extrusion or revolution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start: ProfilePoint
    segments: list[ProfileSegment] = Field(min_length=2, max_length=256)


class BooleanMode(str, Enum):
    ADD = "add"
    CUT = "cut"


# --------------------------------------------------------------------------
# Operations
# --------------------------------------------------------------------------


class BoxOp(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["box"] = "box"
    id: str
    width: Numeric
    height: Numeric
    depth: Numeric
    centered: bool = True


class CylinderOp(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["cylinder"] = "cylinder"
    id: str
    diameter: Numeric
    length: Numeric
    centered: bool = True


class TubeOp(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["tube"] = "tube"
    id: str
    outer_diameter: Numeric
    inner_diameter: Numeric
    length: Numeric
    centered: bool = True


class HoleOp(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["hole"] = "hole"
    id: str
    support: FaceSelector = FaceSelector.TOP_FACE
    diameter: Numeric
    x: Numeric = NumberLiteral(value=0.0)
    y: Numeric = NumberLiteral(value=0.0)
    termination: Termination = Termination.THROUGH_ALL
    depth: Optional[Numeric] = None


class RectangularHolePatternOp(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["rectangular_hole_pattern"] = "rectangular_hole_pattern"
    id: str
    support: FaceSelector = FaceSelector.TOP_FACE
    diameter: Numeric
    spacing_x: Numeric
    spacing_y: Numeric
    count: int = 4
    termination: Termination = Termination.THROUGH_ALL


class ChamferOp(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["chamfer"] = "chamfer"
    id: str
    edge_selector: EdgeSelector
    distance: Numeric


class FilletOp(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["fillet"] = "fillet"
    id: str
    edge_selector: EdgeSelector
    radius: Numeric


class LinearSlotPatternOp(BaseModel):
    """One or more identical slots on a face, evenly spaced along local X."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["linear_slot_pattern"] = "linear_slot_pattern"
    id: str
    support: FaceSelector = FaceSelector.TOP_FACE
    width: Numeric
    length: Numeric
    spacing: Numeric = NumberLiteral(value=0.0)
    count: int = 1
    angle_degrees: Numeric = NumberLiteral(value=0.0)
    termination: Termination = Termination.THROUGH_ALL
    depth: Optional[Numeric] = None


class ProfileExtrudeOp(BaseModel):
    """Extrude any closed line/arc profile, adding or removing material."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["profile_extrude"] = "profile_extrude"
    id: str
    profile: SketchProfile
    distance: Numeric
    plane: SketchPlane = SketchPlane.XY
    mode: BooleanMode = BooleanMode.ADD
    centered: bool = True


class ProfileRevolveOp(BaseModel):
    """Revolve a closed line/arc profile around an axis in its sketch plane."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["profile_revolve"] = "profile_revolve"
    id: str
    profile: SketchProfile
    plane: SketchPlane = SketchPlane.XY
    axis_start: ProfilePoint = ProfilePoint(x=NumberLiteral(value=0), y=NumberLiteral(value=0))
    axis_end: ProfilePoint = ProfilePoint(x=NumberLiteral(value=0), y=NumberLiteral(value=1))
    angle_degrees: Numeric = NumberLiteral(value=360)
    mode: BooleanMode = BooleanMode.ADD


class SheetMetalBendOp(BaseModel):
    """A constant-thickness 90-degree bent sheet with a true radiused bend.

    Leg dimensions are outside envelope dimensions. The executor also records
    bend allowance and developed flat length from the neutral axis.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["sheet_metal_bend"] = "sheet_metal_bend"
    id: str
    leg_a: Numeric
    leg_b: Numeric
    width: Numeric
    thickness: Numeric
    inside_radius: Numeric
    angle_degrees: Numeric = NumberLiteral(value=90)
    k_factor: Numeric = NumberLiteral(value=0.44)


class CurvedRodOp(BaseModel):
    """Sweep a circular rod along a straight–arc–straight centerline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["curved_rod"] = "curved_rod"
    id: str
    diameter: Numeric
    total_length: Numeric
    bend_start: Numeric
    bend_radius: Numeric
    bend_angle_degrees: Numeric
    plane: SketchPlane = SketchPlane.XY


class RectangularLoftOp(BaseModel):
    """Loft between two centered rectangular sections."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["rectangular_loft"] = "rectangular_loft"
    id: str
    start_width: Numeric
    start_height: Numeric
    end_width: Numeric
    end_height: Numeric
    length: Numeric
    plane: SketchPlane = SketchPlane.XY
    ruled: bool = False


class CurvedStripOp(BaseModel):
    """Rectangular-section sweep along a straight–arc–straight centerline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["curved_strip"] = "curved_strip"
    id: str
    strip_width: Numeric
    extrusion_thickness: Numeric
    shank_length: Numeric
    bend_radius: Numeric
    bend_angle_degrees: Numeric
    tail_length: Numeric
    plane: SketchPlane = SketchPlane.XY


class ThreadedBoltOp(BaseModel):
    """Metric flange bolt with a swept helical external V-thread."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["threaded_bolt"] = "threaded_bolt"
    id: str
    major_diameter: Numeric
    pitch: Numeric
    thread_length: Numeric
    shank_length: Numeric
    head_across_flats: Numeric
    head_height: Numeric
    flange_diameter: Numeric
    flange_thickness: Numeric


class FlangedCouplingOp(BaseModel):
    """One half of a keyed rigid flange coupling."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["flanged_coupling"] = "flanged_coupling"
    id: str
    flange_diameter: Numeric
    flange_thickness: Numeric
    hub_diameter: Numeric
    hub_length: Numeric
    bore_diameter: Numeric
    bolt_circle_diameter: Numeric
    bolt_hole_diameter: Numeric
    bolt_count: int = Field(ge=3)
    keyway_width: Numeric
    keyway_depth: Numeric
    entry_chamfer: Numeric
    set_screw_depth: Numeric


class ControllerEnclosureOp(BaseModel):
    """Open-top folded controller enclosure with vents and panel cut-outs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["controller_enclosure"] = "controller_enclosure"
    id: str
    length: Numeric
    width: Numeric
    height: Numeric
    thickness: Numeric
    vent_count: int = Field(ge=1)
    cable_gland_x: Numeric
    cable_gland_diameter: Numeric


class MotorMountBracketOp(BaseModel):
    """Gusseted right-angle motor bracket with base slots and motor pattern."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["motor_mount_bracket"] = "motor_mount_bracket"
    id: str
    bracket_width: Numeric
    base_depth: Numeric
    base_thickness: Numeric
    face_height: Numeric
    motor_spacing: Numeric
    mounting_hole_diameter: Numeric
    shaft_hole_diameter: Numeric
    slot_width: Numeric
    slot_length: Numeric
    gusset_thickness: Numeric


class HydraulicManifoldOp(BaseModel):
    """Cross-drilled manifold with two modeled threaded inlets and one outlet."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["hydraulic_manifold"] = "hydraulic_manifold"
    id: str
    length: Numeric
    width: Numeric
    height: Numeric
    port_major_diameter: Numeric
    port_minor_diameter: Numeric
    port_pitch: Numeric
    tapping_depth: Numeric
    passage_diameter: Numeric
    port_spacing: Numeric


class BlowerTransitionDuctOp(BaseModel):
    """Thin-wall rectangle-to-round blower transition with end flanges."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["blower_transition_duct"] = "blower_transition_duct"
    id: str
    inlet_width: Numeric
    inlet_height: Numeric
    outlet_diameter: Numeric
    transition_length: Numeric
    wall_thickness: Numeric
    flange_width: Numeric


Operation = Annotated[
    Union[
        BoxOp, CylinderOp, TubeOp, HoleOp,
        RectangularHolePatternOp, LinearSlotPatternOp,
        ChamferOp, FilletOp, ProfileExtrudeOp, ProfileRevolveOp,
        SheetMetalBendOp, CurvedRodOp, RectangularLoftOp, CurvedStripOp,
        ThreadedBoltOp, FlangedCouplingOp, ControllerEnclosureOp,
        MotorMountBracketOp, HydraulicManifoldOp, BlowerTransitionDuctOp,
    ],
    Field(discriminator="type"),
]


class CADProgram(BaseModel):
    """An ordered feature plan. Execution order is list order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    part_name: str
    units: Literal["mm"] = "mm"
    operations: list[Operation] = Field(default_factory=list, max_length=64)
    design_revision: int = Field(
        default=1, description="the DesignIntent revision this program was compiled from"
    )

    def operation(self, op_id: str) -> Operation:
        for op in self.operations:
            if op.id == op_id:
                return op
        raise KeyError(f"no operation {op_id!r}")

    @property
    def referenced_parameters(self) -> set[str]:
        """Every parameter name this program depends on. Used by schema
        validation to check the program is satisfiable before execution."""
        names: set[str] = set()

        def walk(value: object) -> None:
            if isinstance(value, ParamRef):
                names.add(value.ref)
            elif isinstance(value, BaseModel):
                for field in type(value).model_fields:
                    walk(getattr(value, field))
            elif isinstance(value, (list, tuple)):
                for item in value:
                    walk(item)

        for op in self.operations:
            walk(op)
        return names

    def feature_sequence(self) -> list[str]:
        return [f"{op.id} ({op.type})" for op in self.operations]

    def describe(self, values: dict[str, float]) -> list[dict]:
        """Each operation with its numeric fields resolved.

        Returned so a caller can show what a feature actually is -- the value
        used, and the parameter it came from -- rather than just its name.
        """
        def jsonish(value):
            if isinstance(value, BaseModel):
                return value.model_dump(mode="json")
            if isinstance(value, (list, tuple)):
                return [jsonish(item) for item in value]
            if isinstance(value, dict):
                return {key: jsonish(item) for key, item in value.items()}
            return value.value if hasattr(value, "value") else value

        out: list[dict] = []
        for op in self.operations:
            fields: list[dict] = []
            for name in type(op).model_fields:
                if name in ("id", "type"):
                    continue
                value = getattr(op, name)
                if isinstance(value, (NumberLiteral, ParamRef)):
                    try:
                        resolved = resolve(value, values)
                    except UnresolvedReference:
                        resolved = None
                    fields.append({
                        "name": name,
                        "value": resolved,
                        "parameter": value.ref if isinstance(value, ParamRef) else None,
                    })
                elif value is None:
                    continue
                else:
                    fields.append({
                        "name": name,
                        "value": jsonish(value),
                        "parameter": None,
                    })
            out.append({"id": op.id, "type": op.type, "fields": fields})
        return out
