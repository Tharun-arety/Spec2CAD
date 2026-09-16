"""Execute a CADProgram against the CAD kernel.

This is the retained kernel implementation behind the CadQuery adapter. Nothing
upstream produces Python; a model can at most produce schema-valid operations,
and this module decides what each one means. An operation type with no handler
is an error -- there is no permissive fallback, because a fallback here would
mean silently building something other than what was asked for.

Execution is *diagnostic*: it runs even when preflight predicted a violation, so
the violation can be measured on real geometry rather than only predicted. The
decision about whether the result may be exported belongs to the release gate,
not here.
"""

from __future__ import annotations

import time
import math
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Callable, Optional

from spec2cad.backends.cadquery_kernel import cq

from spec2cad.cad.selectors import select_edges, select_face
from spec2cad.schemas.cad_ir import (
    ArcSegment,
    BlowerTransitionDuctOp,
    BooleanMode,
    BoxOp,
    ControllerEnclosureOp,
    CylinderOp,
    CurvedRodOp,
    CurvedStripOp,
    CADProgram,
    ChamferOp,
    FilletOp,
    FlangedCouplingOp,
    HoleOp,
    HydraulicManifoldOp,
    LinearSlotPatternOp,
    LineSegment,
    MotorMountBracketOp,
    ProfileExtrudeOp,
    ProfilePoint,
    ProfileRevolveOp,
    RectangularLoftOp,
    RectangularHolePatternOp,
    SheetMetalBendOp,
    SketchPlane,
    SketchProfile,
    Termination,
    ThreadedBoltOp,
    TubeOp,
    resolve,
)
from spec2cad.schemas.assembly_ir import (
    AssemblyProgram,
    CoincidentOriginMate,
    ConcentricAxisMate,
    OffsetMate,
)


class ExecutionError(RuntimeError):
    """Raised when the kernel cannot build the requested feature."""


class UnsupportedOperation(ExecutionError):
    """Raised for an operation type with no handler."""


@dataclass
class BuildContext:
    """State threaded through the operation handlers."""

    values: dict[str, float]
    width: float = 0.0
    height: float = 0.0
    thickness: float = 0.0
    hole_diameters: list[float] = field(default_factory=list)
    derived: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class OperationMeasurement:
    """What the kernel actually did for one operation.

    The feature list on its own is only a restatement of the program we
    authored: it says what we asked for, and would look identical if the kernel
    had quietly done nothing. These are taken from the intermediate solid after
    each operation, so a feature can be shown as an observation rather than an
    intention -- and an operation that removes no material stops being invisible.
    """

    operation_id: str
    volume: float
    volume_delta: float
    is_valid: bool
    solid_count: int
    seconds: float

    @property
    def removed_material(self) -> bool:
        return self.volume_delta < 0

    @property
    def no_op(self) -> bool:
        """Built without changing the solid. Almost always a bug upstream."""
        return abs(self.volume_delta) < 1e-9


@dataclass
class ExecutionResult:
    solid: cq.Workplane
    program: CADProgram
    context: BuildContext
    operations_applied: list[str]
    measurements: list[OperationMeasurement] = field(default_factory=list)

    @property
    def shape(self):
        return self.solid.val()

    def measurement(self, operation_id: str) -> Optional[OperationMeasurement]:
        for m in self.measurements:
            if m.operation_id == operation_id:
                return m
        return None


# --------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------


def _do_box(wp: Optional[cq.Workplane], op: BoxOp, ctx: BuildContext) -> cq.Workplane:
    ctx.width = resolve(op.width, ctx.values)
    ctx.height = resolve(op.height, ctx.values)
    ctx.thickness = resolve(op.depth, ctx.values)
    for name, value in (("width", ctx.width), ("height", ctx.height),
                        ("depth", ctx.thickness)):
        if value <= 0:
            raise ExecutionError(f"box {name} must be positive, got {value}")
    return cq.Workplane("XY").box(ctx.width, ctx.height, ctx.thickness, centered=op.centered)


def _do_cylinder(
    wp: Optional[cq.Workplane], op: CylinderOp, ctx: BuildContext
) -> cq.Workplane:
    diameter = resolve(op.diameter, ctx.values)
    length = resolve(op.length, ctx.values)
    if diameter <= 0 or length <= 0:
        raise ExecutionError(
            f"cylinder diameter and length must be positive, got {diameter} x {length}"
        )
    ctx.width = ctx.height = diameter
    ctx.thickness = length
    profile = cq.Workplane("XY").circle(diameter / 2.0)
    return profile.extrude(length / 2.0, both=True) if op.centered else profile.extrude(length)


def _do_tube(wp: Optional[cq.Workplane], op: TubeOp, ctx: BuildContext) -> cq.Workplane:
    outer = resolve(op.outer_diameter, ctx.values)
    inner = resolve(op.inner_diameter, ctx.values)
    length = resolve(op.length, ctx.values)
    if not (outer > inner > 0 and length > 0):
        raise ExecutionError(
            "tube dimensions must satisfy outer_diameter > inner_diameter > 0 "
            f"and length > 0, got {outer}, {inner}, {length}"
        )
    ctx.width = ctx.height = outer
    ctx.thickness = length
    profile = cq.Workplane("XY").circle(outer / 2.0).circle(inner / 2.0)
    return profile.extrude(length / 2.0, both=True) if op.centered else profile.extrude(length)


def _do_hole(wp: cq.Workplane, op: HoleOp, ctx: BuildContext) -> cq.Workplane:
    diameter = resolve(op.diameter, ctx.values)
    if diameter <= 0:
        raise ExecutionError(f"hole diameter must be positive, got {diameter}")
    x, y = resolve(op.x, ctx.values), resolve(op.y, ctx.values)
    ctx.hole_diameters.append(diameter)

    plane = select_face(wp, op.support).workplane(origin=(0, 0, 0))
    if op.termination is Termination.THROUGH_ALL:
        return plane.moveTo(x, y).circle(diameter / 2.0).cutThruAll()
    if op.depth is None:
        raise ExecutionError(f"blind hole {op.id!r} has no depth")
    return plane.moveTo(x, y).circle(diameter / 2.0).cutBlind(-resolve(op.depth, ctx.values))


def _do_pattern(
    wp: cq.Workplane, op: RectangularHolePatternOp, ctx: BuildContext
) -> cq.Workplane:
    diameter = resolve(op.diameter, ctx.values)
    sx = resolve(op.spacing_x, ctx.values)
    sy = resolve(op.spacing_y, ctx.values)
    if diameter <= 0:
        raise ExecutionError(f"hole diameter must be positive, got {diameter}")
    if op.count != 4:
        raise UnsupportedOperation(
            f"rectangular_hole_pattern supports 4 corner holes in v1, got count={op.count}"
        )
    ctx.hole_diameters.extend([diameter] * op.count)
    return (
        select_face(wp, op.support)
        .workplane()
        .rect(sx, sy, forConstruction=True)
        .vertices()
        .hole(diameter)
    )


def _do_chamfer(wp: cq.Workplane, op: ChamferOp, ctx: BuildContext) -> cq.Workplane:
    distance = resolve(op.distance, ctx.values)
    if distance <= 0:
        raise ExecutionError(f"chamfer distance must be positive, got {distance}")
    selected = select_edges(wp, op.edge_selector, width=ctx.width, height=ctx.height)
    try:
        return selected.chamfer(distance)
    except Exception as exc:  # kernel raises StdFail_NotDone for impossible chamfers
        raise ExecutionError(
            f"chamfer {op.id!r} of {distance} mm could not be built: {exc}"
        ) from exc


def _do_fillet(wp: cq.Workplane, op: FilletOp, ctx: BuildContext) -> cq.Workplane:
    radius = resolve(op.radius, ctx.values)
    if radius <= 0:
        raise ExecutionError(f"fillet radius must be positive, got {radius}")
    selected = select_edges(wp, op.edge_selector, width=ctx.width, height=ctx.height)
    try:
        return selected.fillet(radius)
    except Exception as exc:
        raise ExecutionError(
            f"fillet {op.id!r} of {radius} mm could not be built: {exc}"
        ) from exc


def _do_slot_pattern(
    wp: cq.Workplane, op: LinearSlotPatternOp, ctx: BuildContext
) -> cq.Workplane:
    width = resolve(op.width, ctx.values)
    length = resolve(op.length, ctx.values)
    spacing = resolve(op.spacing, ctx.values)
    angle = resolve(op.angle_degrees, ctx.values)
    if width <= 0 or length <= 0 or length < width:
        raise ExecutionError(
            f"slot length/width must satisfy length >= width > 0, got {length} x {width}"
        )
    if op.count < 1:
        raise ExecutionError(f"slot count must be positive, got {op.count}")
    if op.count > 1 and spacing <= 0:
        raise ExecutionError("a multi-slot pattern needs positive spacing")
    start = -spacing * (op.count - 1) / 2.0
    points = [(start + i * spacing, 0.0) for i in range(op.count)]
    sketch = (
        select_face(wp, op.support).workplane()
        .pushPoints(points)
        .slot2D(length, width, angle)
    )
    if op.termination is Termination.THROUGH_ALL:
        return sketch.cutThruAll()
    if op.depth is None:
        raise ExecutionError(f"blind slot pattern {op.id!r} has no depth")
    return sketch.cutBlind(-resolve(op.depth, ctx.values))


def _point(point: ProfilePoint, ctx: BuildContext) -> tuple[float, float]:
    return resolve(point.x, ctx.values), resolve(point.y, ctx.values)


def _profile_wire(
    profile: SketchProfile, plane: SketchPlane, ctx: BuildContext
) -> cq.Workplane:
    """Convert the kernel-neutral profile into one closed CadQuery wire."""
    start = _point(profile.start, ctx)
    wire = cq.Workplane(plane.value).moveTo(*start)
    for segment in profile.segments:
        if isinstance(segment, LineSegment):
            wire = wire.lineTo(*_point(segment.end, ctx))
        elif isinstance(segment, ArcSegment):
            wire = wire.threePointArc(
                _point(segment.midpoint, ctx), _point(segment.end, ctx)
            )
        else:  # pragma: no cover - the discriminated schema prevents this
            raise UnsupportedOperation(f"unsupported profile segment {type(segment).__name__}")
    try:
        return wire.close()
    except Exception as exc:
        raise ExecutionError(f"profile could not be closed: {exc}") from exc


def _combine(
    existing: Optional[cq.Workplane], feature: cq.Workplane, mode: BooleanMode, op_id: str
) -> cq.Workplane:
    if existing is None:
        if mode is BooleanMode.CUT:
            raise ExecutionError(f"cut operation {op_id!r} has no preceding solid")
        return feature
    try:
        return existing.union(feature) if mode is BooleanMode.ADD else existing.cut(feature)
    except Exception as exc:
        raise ExecutionError(f"boolean {mode.value} for {op_id!r} failed: {exc}") from exc


def _do_profile_extrude(
    wp: Optional[cq.Workplane], op: ProfileExtrudeOp, ctx: BuildContext
) -> cq.Workplane:
    distance = resolve(op.distance, ctx.values)
    if distance <= 0:
        raise ExecutionError(f"profile extrusion distance must be positive, got {distance}")
    profile = _profile_wire(op.profile, op.plane, ctx)
    feature = (
        profile.extrude(distance / 2.0, both=True, combine=False)
        if op.centered else profile.extrude(distance, combine=False)
    )
    return _combine(wp, feature, op.mode, op.id)


def _do_profile_revolve(
    wp: Optional[cq.Workplane], op: ProfileRevolveOp, ctx: BuildContext
) -> cq.Workplane:
    angle = resolve(op.angle_degrees, ctx.values)
    if not (0 < angle <= 360):
        raise ExecutionError(f"revolve angle must be in (0, 360], got {angle}")
    axis_start, axis_end = _point(op.axis_start, ctx), _point(op.axis_end, ctx)
    if axis_start == axis_end:
        raise ExecutionError("revolve axis start and end must differ")
    try:
        feature = _profile_wire(op.profile, op.plane, ctx).revolve(
            angle, axisStart=axis_start, axisEnd=axis_end, combine=False
        )
    except Exception as exc:
        raise ExecutionError(f"profile revolve {op.id!r} failed: {exc}") from exc
    return _combine(wp, feature, op.mode, op.id)


def _do_rectangular_loft(
    wp: Optional[cq.Workplane], op: RectangularLoftOp, ctx: BuildContext
) -> cq.Workplane:
    if wp is not None:
        raise ExecutionError("rectangular_loft is a base feature and must be first")
    sw = resolve(op.start_width, ctx.values)
    sh = resolve(op.start_height, ctx.values)
    ew = resolve(op.end_width, ctx.values)
    eh = resolve(op.end_height, ctx.values)
    length = resolve(op.length, ctx.values)
    if min(sw, sh, ew, eh, length) <= 0:
        raise ExecutionError("loft section dimensions and length must be positive")
    try:
        result = (
            cq.Workplane(op.plane.value)
            .workplane(offset=-length / 2.0)
            .rect(sw, sh)
            .workplane(offset=length)
            .rect(ew, eh)
            .loft(ruled=op.ruled, combine=False)
        )
    except Exception as exc:
        raise ExecutionError(f"rectangular loft {op.id!r} failed: {exc}") from exc
    ctx.width = max(sw, ew)
    ctx.height = max(sh, eh)
    ctx.thickness = length
    ctx.derived[f"{op.id}.start_area"] = sw * sh
    ctx.derived[f"{op.id}.end_area"] = ew * eh
    return result


def _do_sheet_metal_bend(
    wp: Optional[cq.Workplane], op: SheetMetalBendOp, ctx: BuildContext
) -> cq.Workplane:
    if wp is not None:
        raise ExecutionError("sheet_metal_bend is a base feature and must be first")
    leg_a = resolve(op.leg_a, ctx.values)
    leg_b = resolve(op.leg_b, ctx.values)
    width = resolve(op.width, ctx.values)
    thickness = resolve(op.thickness, ctx.values)
    radius = resolve(op.inside_radius, ctx.values)
    angle = resolve(op.angle_degrees, ctx.values)
    k_factor = resolve(op.k_factor, ctx.values)
    if min(leg_a, leg_b, width, thickness) <= 0 or radius < 0:
        raise ExecutionError("sheet-metal legs, width and thickness must be positive")
    if abs(angle - 90.0) > 1e-9:
        raise UnsupportedOperation(
            f"sheet_metal_bend currently supports a verified 90 degree bend, got {angle}"
        )
    if not (0 <= k_factor <= 1):
        raise ExecutionError(f"K-factor must be between 0 and 1, got {k_factor}")
    outside_radius = radius + thickness
    if leg_a <= outside_radius or leg_b <= outside_radius:
        raise ExecutionError(
            "sheet-metal legs must extend beyond the outside bend radius"
        )

    # Closed XZ cross-section bounded by concentric inner and outer bend arcs.
    inner_mid = (
        outside_radius - radius / 2**0.5,
        outside_radius - radius / 2**0.5,
    )
    outer_mid = (
        outside_radius - outside_radius / 2**0.5,
        outside_radius - outside_radius / 2**0.5,
    )
    profile = (
        cq.Workplane("XZ")
        .moveTo(outside_radius, 0)
        .lineTo(leg_a, 0)
        .lineTo(leg_a, thickness)
        .lineTo(outside_radius, thickness)
        .threePointArc(inner_mid, (thickness, outside_radius))
        .lineTo(thickness, leg_b)
        .lineTo(0, leg_b)
        .lineTo(0, outside_radius)
        .threePointArc(outer_mid, (outside_radius, 0))
        .close()
    )
    result = profile.extrude(width / 2.0, both=True)
    bend_allowance = 3.141592653589793 / 2.0 * (radius + k_factor * thickness)
    setback = outside_radius
    ctx.derived[f"{op.id}.bend_allowance"] = bend_allowance
    ctx.derived[f"{op.id}.flat_length"] = (
        leg_a - setback + leg_b - setback + bend_allowance
    )
    cross_section_area = (
        thickness * (leg_a - outside_radius + leg_b - outside_radius)
        + 3.141592653589793 / 4.0 * (outside_radius**2 - radius**2)
    )
    ctx.derived[f"{op.id}.expected_volume"] = cross_section_area * width
    ctx.width, ctx.height, ctx.thickness = leg_a, width, leg_b
    return result


def _do_curved_rod(
    wp: Optional[cq.Workplane], op: CurvedRodOp, ctx: BuildContext
) -> cq.Workplane:
    if wp is not None:
        raise ExecutionError("curved_rod is a base feature and must be first")
    diameter = resolve(op.diameter, ctx.values)
    total = resolve(op.total_length, ctx.values)
    bend_start = resolve(op.bend_start, ctx.values)
    radius = resolve(op.bend_radius, ctx.values)
    angle = resolve(op.bend_angle_degrees, ctx.values)
    if op.plane is not SketchPlane.XY:
        raise UnsupportedOperation(
            f"curved_rod currently supports the verified XY bend plane, got {op.plane.value}"
        )
    if diameter <= 0 or total <= 0 or bend_start < 0 or radius <= 0:
        raise ExecutionError("curved-rod diameter/length/radius must be positive")
    if not (0 < angle < 360):
        raise ExecutionError(f"curved-rod bend angle must be in (0, 360), got {angle}")
    if radius <= diameter / 2.0:
        raise ExecutionError(
            "curved-rod centerline radius must exceed the rod radius to avoid self-intersection"
        )
    arc_length = radius * math.radians(angle)
    tail_length = total - bend_start - arc_length
    if tail_length < -1e-9:
        raise ExecutionError(
            f"total rod length {total:g} mm is shorter than bend_start + arc_length "
            f"({bend_start + arc_length:.6g} mm)"
        )
    tail_length = max(0.0, tail_length)

    edges = []
    if bend_start > 0:
        edges.append(cq.Edge.makeLine(
            cq.Vector(0, 0, 0), cq.Vector(bend_start, 0, 0)
        ))
    center = cq.Vector(bend_start, radius, 0)
    arc = cq.Edge.makeCircle(
        radius, center, cq.Vector(0, 0, 1), -90, -90 + angle
    )
    edges.append(arc)
    if tail_length > 0:
        endpoint = arc.endPoint()
        tangent = math.radians(angle)
        tail_end = cq.Vector(
            endpoint.x + tail_length * math.cos(tangent),
            endpoint.y + tail_length * math.sin(tangent),
            0,
        )
        edges.append(cq.Edge.makeLine(endpoint, tail_end))
    path_wire = cq.Wire.assembleEdges(edges)
    try:
        result = (
            cq.Workplane("YZ").circle(diameter / 2.0)
            .sweep(cq.Workplane(obj=path_wire), isFrenet=True)
        )
    except Exception as exc:
        raise ExecutionError(f"curved-rod sweep {op.id!r} failed: {exc}") from exc

    ctx.width = ctx.height = diameter
    ctx.thickness = total
    ctx.derived[f"{op.id}.arc_length"] = arc_length
    ctx.derived[f"{op.id}.tail_length"] = tail_length
    ctx.derived[f"{op.id}.expected_volume"] = math.pi * (diameter / 2.0) ** 2 * total
    return result


def _do_curved_strip(
    wp: Optional[cq.Workplane], op: CurvedStripOp, ctx: BuildContext
) -> cq.Workplane:
    if wp is not None:
        raise ExecutionError("curved_strip is a base feature and must be first")
    width = resolve(op.strip_width, ctx.values)
    thickness = resolve(op.extrusion_thickness, ctx.values)
    shank = resolve(op.shank_length, ctx.values)
    radius = resolve(op.bend_radius, ctx.values)
    angle = resolve(op.bend_angle_degrees, ctx.values)
    tail = resolve(op.tail_length, ctx.values)
    if op.plane is not SketchPlane.XY:
        raise UnsupportedOperation("curved_strip currently supports the verified XY path")
    if min(width, thickness, radius) <= 0 or shank < 0 or tail < 0:
        raise ExecutionError("curved-strip section/radius must be positive and lengths non-negative")
    if radius <= width / 2.0:
        raise ExecutionError("curved-strip centerline radius must exceed half its strip width")
    if not (0 < angle < 360):
        raise ExecutionError(f"curved-strip bend angle must be in (0, 360), got {angle}")

    edges = []
    if shank > 0:
        edges.append(cq.Edge.makeLine(cq.Vector(0, 0, 0), cq.Vector(shank, 0, 0)))
    center = cq.Vector(shank, radius, 0)
    arc = cq.Edge.makeCircle(radius, center, cq.Vector(0, 0, 1), -90, -90 + angle)
    edges.append(arc)
    if tail > 0:
        endpoint = arc.endPoint()
        tangent = math.radians(angle)
        tail_end = cq.Vector(
            endpoint.x + tail * math.cos(tangent),
            endpoint.y + tail * math.sin(tangent), 0,
        )
        edges.append(cq.Edge.makeLine(endpoint, tail_end))
    path_wire = cq.Wire.assembleEdges(edges)
    try:
        result = (
            cq.Workplane("YZ").rect(width, thickness)
            .sweep(cq.Workplane(obj=path_wire), isFrenet=True)
        )
    except Exception as exc:
        raise ExecutionError(f"curved-strip sweep {op.id!r} failed: {exc}") from exc

    arc_length = radius * math.radians(angle)
    centerline_length = shank + arc_length + tail
    ctx.derived[f"{op.id}.arc_length"] = arc_length
    ctx.derived[f"{op.id}.centerline_length"] = centerline_length
    ctx.derived[f"{op.id}.expected_volume"] = width * thickness * centerline_length
    ctx.width = width
    ctx.height = thickness
    ctx.thickness = centerline_length
    return result


def _do_threaded_bolt(
    wp: Optional[cq.Workplane], op: ThreadedBoltOp, ctx: BuildContext
) -> cq.Workplane:
    """Build a flanged hex-head bolt with a swept ISO-style V-thread cut."""
    if wp is not None:
        raise ExecutionError("threaded_bolt is a base feature and must be first")

    major = resolve(op.major_diameter, ctx.values)
    pitch = resolve(op.pitch, ctx.values)
    thread_length = resolve(op.thread_length, ctx.values)
    shank_length = resolve(op.shank_length, ctx.values)
    across_flats = resolve(op.head_across_flats, ctx.values)
    head_height = resolve(op.head_height, ctx.values)
    flange_diameter = resolve(op.flange_diameter, ctx.values)
    flange_thickness = resolve(op.flange_thickness, ctx.values)

    if min(
        major, pitch, thread_length, across_flats, head_height,
        flange_diameter, flange_thickness,
    ) <= 0 or shank_length < 0:
        raise ExecutionError(
            "thread dimensions, head dimensions and flange dimensions must be positive"
        )
    if across_flats <= major:
        raise ExecutionError("hex-head across-flats size must exceed the thread diameter")
    if flange_diameter <= across_flats:
        raise ExecutionError("flange diameter must exceed the hex-head across-flats size")

    root_diameter = major - 1.22687 * pitch
    if root_diameter <= 0:
        raise ExecutionError("thread pitch is too large for the specified major diameter")

    under_head_length = thread_length + shank_length
    shaft = cq.Workplane("XY").circle(major / 2.0).extrude(under_head_length)
    helix = cq.Wire.makeHelix(pitch, thread_length, major / 2.0)
    crest_allowance = 0.4
    half_profile = pitch * 0.3
    cutter_profile = (
        cq.Workplane("XZ")
        .moveTo(root_diameter / 2.0, 0)
        .lineTo(major / 2.0 + crest_allowance, -half_profile)
        .lineTo(major / 2.0 + crest_allowance, half_profile)
        .close()
    )
    try:
        thread_cutter = cutter_profile.sweep(
            cq.Workplane(obj=helix), isFrenet=True
        )
        threaded_shaft = shaft.cut(thread_cutter)
        flange = (
            cq.Workplane("XY").workplane(offset=under_head_length)
            .circle(flange_diameter / 2.0).extrude(flange_thickness)
        )
        circumscribed_head_diameter = across_flats / math.cos(math.pi / 6.0)
        head = (
            cq.Workplane("XY")
            .workplane(offset=under_head_length + flange_thickness)
            .polygon(6, circumscribed_head_diameter)
            .extrude(head_height)
        )
        result = threaded_shaft.union(flange).union(head)
    except Exception as exc:
        raise ExecutionError(f"threaded bolt {op.id!r} failed: {exc}") from exc

    overall_length = under_head_length + flange_thickness + head_height
    ctx.derived[f"{op.id}.thread_turns"] = thread_length / pitch
    ctx.derived[f"{op.id}.thread_root_diameter"] = root_diameter
    ctx.derived[f"{op.id}.under_head_length"] = under_head_length
    ctx.derived[f"{op.id}.overall_length"] = overall_length
    ctx.width = ctx.height = flange_diameter
    ctx.thickness = overall_length
    return result


def _do_flanged_coupling(
    wp: Optional[cq.Workplane], op: FlangedCouplingOp, ctx: BuildContext
) -> cq.Workplane:
    if wp is not None:
        raise ExecutionError("flanged_coupling is a base feature and must be first")
    flange_d = resolve(op.flange_diameter, ctx.values)
    flange_t = resolve(op.flange_thickness, ctx.values)
    hub_d = resolve(op.hub_diameter, ctx.values)
    hub_l = resolve(op.hub_length, ctx.values)
    bore_d = resolve(op.bore_diameter, ctx.values)
    bolt_circle = resolve(op.bolt_circle_diameter, ctx.values)
    bolt_d = resolve(op.bolt_hole_diameter, ctx.values)
    key_w = resolve(op.keyway_width, ctx.values)
    key_d = resolve(op.keyway_depth, ctx.values)
    chamfer = resolve(op.entry_chamfer, ctx.values)
    set_screw_depth = resolve(op.set_screw_depth, ctx.values)
    if min(flange_d, flange_t, hub_d, hub_l, bore_d, bolt_circle, bolt_d, key_w, key_d) <= 0:
        raise ExecutionError("coupling dimensions must be positive")
    if bore_d + 2 * key_d >= hub_d:
        raise ExecutionError("bore and keyway leave no hub wall")
    if bolt_circle + bolt_d >= flange_d:
        raise ExecutionError("bolt holes extend beyond the flange")

    total = flange_t + hub_l
    flange = cq.Workplane("XY").circle(flange_d / 2).extrude(flange_t)
    hub = cq.Workplane("XY").workplane(offset=flange_t).circle(hub_d / 2).extrude(hub_l)
    result = flange.union(hub)
    result = result.cut(cq.Workplane("XY").workplane(offset=-1).circle(bore_d / 2).extrude(total + 2))
    keyway = (
        cq.Workplane("XY").workplane(offset=-1)
        .center(0, bore_d / 2 + key_d / 2)
        .rect(key_w, key_d).extrude(total + 2)
    )
    result = result.cut(keyway)
    points = [
        (
            bolt_circle / 2 * math.cos(2 * math.pi * index / op.bolt_count),
            bolt_circle / 2 * math.sin(2 * math.pi * index / op.bolt_count),
        )
        for index in range(op.bolt_count)
    ]
    result = result.faces(">Z").workplane().pushPoints(points).hole(bolt_d)
    if chamfer > 0:
        entry = (
            cq.Workplane("XY").workplane(offset=total - chamfer)
            .circle(bore_d / 2 + chamfer).workplane(offset=chamfer + 0.1)
            .circle(bore_d / 2).loft(combine=False)
        )
        result = result.cut(entry)
    if set_screw_depth > 0:
        # M5 coarse-thread tap-drill representation.  The optional radial feature
        # is omitted from an unresolved v1 and added only after its depth is
        # explicitly approved.
        set_screw = cq.Solid.makeCylinder(
            2.1,
            set_screw_depth + 0.2,
            cq.Vector(hub_d / 2 + 0.1, 0, flange_t + hub_l / 2),
            cq.Vector(-1, 0, 0),
        )
        result = result.cut(cq.Workplane(obj=set_screw))
    ctx.width = ctx.height = flange_d
    ctx.thickness = total
    ctx.derived[f"{op.id}.hub_wall_at_keyway"] = (hub_d - bore_d) / 2 - key_d
    ctx.derived[f"{op.id}.bolt_circle_radius"] = bolt_circle / 2
    ctx.derived[f"{op.id}.set_screw_depth"] = set_screw_depth
    return result


def _do_controller_enclosure(
    wp: Optional[cq.Workplane], op: ControllerEnclosureOp, ctx: BuildContext
) -> cq.Workplane:
    if wp is not None:
        raise ExecutionError("controller_enclosure is a base feature and must be first")
    length = resolve(op.length, ctx.values)
    width = resolve(op.width, ctx.values)
    height = resolve(op.height, ctx.values)
    thickness = resolve(op.thickness, ctx.values)
    cable_gland_x = resolve(op.cable_gland_x, ctx.values)
    cable_gland_diameter = resolve(op.cable_gland_diameter, ctx.values)
    if min(length, width, height, thickness) <= 0 or 2 * thickness >= min(length, width):
        raise ExecutionError("enclosure envelope and sheet thickness are invalid")
    outer = cq.Workplane("XY").box(length, width, height, centered=(True, True, False))
    cavity = (
        cq.Workplane("XY").workplane(offset=thickness)
        .box(length - 2 * thickness, width - 2 * thickness, height + 1,
             centered=(True, True, False))
    )
    result = outer.cut(cavity)
    display = cq.Workplane("XY").box(44, 2 * thickness + 2, 18).translate(
        (0, -width / 2, height * 0.58)
    )
    result = result.cut(display)
    for index in range(op.vent_count):
        z = 12 + index * min(6.0, (height - 16) / max(op.vent_count, 1))
        vent = cq.Workplane("YZ").circle(1.8).extrude(2 * thickness + 2, both=True).translate(
            (length / 2, 0, z)
        )
        result = result.cut(vent)
    if cable_gland_diameter > 0:
        if abs(cable_gland_x) + cable_gland_diameter / 2 >= length / 2:
            raise ExecutionError("cable-gland cut-out extends beyond the enclosure wall")
        cable_gland = cq.Solid.makeCylinder(
            cable_gland_diameter / 2,
            2 * thickness + 2,
            cq.Vector(cable_gland_x, -width / 2 - 1, 16),
            cq.Vector(0, 1, 0),
        )
        result = result.cut(cq.Workplane(obj=cable_gland))
    ctx.width, ctx.height, ctx.thickness = length, width, height
    ctx.derived[f"{op.id}.developed_perimeter"] = 2 * (length + width)
    ctx.derived[f"{op.id}.constant_wall_thickness"] = thickness
    ctx.derived[f"{op.id}.cable_gland_x"] = cable_gland_x
    ctx.derived[f"{op.id}.cable_gland_diameter"] = cable_gland_diameter
    return result


def _do_motor_mount_bracket(
    wp: Optional[cq.Workplane], op: MotorMountBracketOp, ctx: BuildContext
) -> cq.Workplane:
    if wp is not None:
        raise ExecutionError("motor_mount_bracket is a base feature and must be first")
    width = resolve(op.bracket_width, ctx.values)
    depth = resolve(op.base_depth, ctx.values)
    thickness = resolve(op.base_thickness, ctx.values)
    face_height = resolve(op.face_height, ctx.values)
    spacing = resolve(op.motor_spacing, ctx.values)
    hole_d = resolve(op.mounting_hole_diameter, ctx.values)
    shaft_d = resolve(op.shaft_hole_diameter, ctx.values)
    slot_w = resolve(op.slot_width, ctx.values)
    slot_l = resolve(op.slot_length, ctx.values)
    gusset_t = resolve(op.gusset_thickness, ctx.values)
    if min(width, depth, thickness, face_height, spacing, hole_d, shaft_d, slot_w, slot_l, gusset_t) <= 0:
        raise ExecutionError("motor-bracket dimensions must be positive")

    base = cq.Workplane("XY").box(width, depth, thickness, centered=(True, True, False))
    wall_y = depth / 2 - thickness / 2
    wall = cq.Workplane("XY").box(
        width, thickness, face_height + 0.5, centered=(True, True, False)
    ).translate(
        (0, wall_y, thickness - 0.5)
    )
    result = base.union(wall)
    face_z = thickness + face_height / 2
    y_start = depth / 2 - 2 * thickness
    cutters = [cq.Solid.makeCylinder(shaft_d / 2, 4 * thickness, cq.Vector(0, y_start, face_z), cq.Vector(0, 1, 0))]
    for x in (-spacing / 2, spacing / 2):
        for z in (face_z - spacing / 2, face_z + spacing / 2):
            cutters.append(cq.Solid.makeCylinder(hole_d / 2, 4 * thickness, cq.Vector(x, y_start, z), cq.Vector(0, 1, 0)))
    for cutter in cutters:
        result = result.cut(cq.Workplane(obj=cutter))
    slot_points = [(-width * 0.28, -depth * 0.2), (width * 0.28, -depth * 0.2)]
    result = (
        result.faces(">Z").workplane().pushPoints(slot_points)
        .slot2D(slot_l, slot_w, 90).cutThruAll()
    )
    for x in (-width / 2 + 2 * gusset_t, width / 2 - 2 * gusset_t):
        root_y = wall_y - thickness / 2 + 0.5
        root_z = thickness - 0.5
        gusset = (
            cq.Workplane("YZ").moveTo(root_y, root_z)
            .lineTo(root_y, thickness + 25)
            .lineTo(root_y - 25, root_z).close()
            .extrude(gusset_t / 2, both=True).translate((x, 0, 0))
        )
        result = result.union(gusset)
    edge_clearance = (width - spacing - hole_d) / 2
    ctx.width, ctx.height, ctx.thickness = width, depth, face_height + thickness
    ctx.derived[f"{op.id}.motor_hole_edge_clearance"] = edge_clearance
    ctx.derived[f"{op.id}.minimum_feasible_width"] = spacing + hole_d + 8
    return result


def _internal_thread_cut(
    x: float, y: float, z0: float, major: float, minor: float, pitch: float, depth: float
) -> cq.Workplane:
    bore = (
        cq.Workplane("XY").workplane(offset=z0).center(x, y)
        .circle(minor / 2).extrude(depth + 0.5)
    )
    helix = cq.Wire.makeHelix(pitch, depth, minor / 2).translate(cq.Vector(x, y, z0))
    profile = (
        cq.Workplane("XZ").transformed(offset=(x, y, z0))
        .moveTo(minor / 2, 0)
        .lineTo(major / 2 + 0.2, -pitch * 0.3)
        .lineTo(major / 2 + 0.2, pitch * 0.3).close()
    )
    return bore.union(profile.sweep(cq.Workplane(obj=helix), isFrenet=True))


def _do_hydraulic_manifold(
    wp: Optional[cq.Workplane], op: HydraulicManifoldOp, ctx: BuildContext
) -> cq.Workplane:
    if wp is not None:
        raise ExecutionError("hydraulic_manifold is a base feature and must be first")
    length = resolve(op.length, ctx.values)
    width = resolve(op.width, ctx.values)
    height = resolve(op.height, ctx.values)
    major = resolve(op.port_major_diameter, ctx.values)
    minor = resolve(op.port_minor_diameter, ctx.values)
    pitch = resolve(op.port_pitch, ctx.values)
    tapping = resolve(op.tapping_depth, ctx.values)
    passage_d = resolve(op.passage_diameter, ctx.values)
    spacing = resolve(op.port_spacing, ctx.values)
    if min(length, width, height, major, minor, pitch, tapping, passage_d, spacing) <= 0:
        raise ExecutionError("manifold dimensions must be positive")
    if minor >= major or tapping >= height:
        raise ExecutionError("thread or tapping-depth geometry is invalid")
    result = cq.Workplane("XY").box(length, width, height)
    top = height / 2
    for x in (-spacing / 2, spacing / 2):
        thread = _internal_thread_cut(x, 0, top - tapping, major, minor, pitch, tapping + 0.5)
        result = result.cut(thread)
        down = cq.Solid.makeCylinder(
            passage_d / 2, height / 2 + 1, cq.Vector(x, 0, -1), cq.Vector(0, 0, 1)
        )
        result = result.cut(cq.Workplane(obj=down))
    cross = cq.Solid.makeCylinder(
        passage_d / 2, spacing, cq.Vector(-spacing / 2, 0, 0), cq.Vector(1, 0, 0)
    )
    outlet = cq.Solid.makeCylinder(
        passage_d / 2, width / 2 + 1, cq.Vector(0, -width / 2 - 1, 0), cq.Vector(0, 1, 0)
    )
    result = result.cut(cq.Workplane(obj=cross)).cut(cq.Workplane(obj=outlet))
    mounting = [(-length * 0.4, -width * 0.35), (length * 0.4, -width * 0.35),
                (-length * 0.4, width * 0.35), (length * 0.4, width * 0.35)]
    result = result.faces(">Z").workplane().pushPoints(mounting).hole(5)
    min_wall = min((length - spacing - major) / 2, (width - major) / 2)
    ctx.width, ctx.height, ctx.thickness = length, width, height
    ctx.derived[f"{op.id}.minimum_port_wall"] = min_wall
    ctx.derived[f"{op.id}.thread_turns"] = tapping / pitch
    ctx.derived[f"{op.id}.connected_ports"] = 3
    return result


def _do_blower_transition_duct(
    wp: Optional[cq.Workplane], op: BlowerTransitionDuctOp, ctx: BuildContext
) -> cq.Workplane:
    if wp is not None:
        raise ExecutionError("blower_transition_duct is a base feature and must be first")
    inlet_w = resolve(op.inlet_width, ctx.values)
    inlet_h = resolve(op.inlet_height, ctx.values)
    outlet_d = resolve(op.outlet_diameter, ctx.values)
    length = resolve(op.transition_length, ctx.values)
    wall = resolve(op.wall_thickness, ctx.values)
    flange_w = resolve(op.flange_width, ctx.values)
    if min(inlet_w, inlet_h, outlet_d, length, wall, flange_w) <= 0:
        raise ExecutionError("duct dimensions must be positive")
    if 2 * wall >= min(inlet_w, inlet_h, outlet_d):
        raise ExecutionError("wall thickness consumes the flow section")
    outer = (
        cq.Workplane("XY").rect(inlet_w, inlet_h)
        .workplane(offset=length).circle(outlet_d / 2).loft(combine=False)
    )
    inner = (
        cq.Workplane("XY").workplane(offset=-1)
        .rect(inlet_w - 2 * wall, inlet_h - 2 * wall)
        .workplane(offset=length + 2).circle(outlet_d / 2 - wall).loft(combine=False)
    )
    result = outer.cut(inner)
    inlet_flange = (
        cq.Workplane("XY").box(inlet_w + 2 * flange_w, inlet_h + 2 * flange_w, 5,
                               centered=(True, True, False))
        .cut(cq.Workplane("XY").workplane(offset=-1)
             .box(inlet_w - 2 * wall, inlet_h - 2 * wall, 7, centered=(True, True, False)))
    )
    outlet_flange = (
        cq.Workplane("XY").workplane(offset=length)
        .circle(outlet_d / 2 + flange_w).extrude(5)
        .cut(cq.Workplane("XY").workplane(offset=length - 1)
             .circle(outlet_d / 2 - wall).extrude(7))
    )
    result = result.union(inlet_flange).union(outlet_flange)
    half_diagonal = math.hypot(inlet_w / 2, inlet_h / 2)
    transition_angle = math.degrees(math.atan2(abs(half_diagonal - outlet_d / 2), length))
    ctx.width, ctx.height, ctx.thickness = inlet_w + 2 * flange_w, inlet_h + 2 * flange_w, length + 5
    ctx.derived[f"{op.id}.maximum_transition_angle"] = transition_angle
    ctx.derived[f"{op.id}.constant_wall_thickness"] = wall
    ctx.derived[f"{op.id}.flow_area_ratio"] = (
        math.pi * (outlet_d / 2 - wall) ** 2
        / ((inlet_w - 2 * wall) * (inlet_h - 2 * wall))
    )
    return result


HANDLERS: dict[type, Callable] = {
    BoxOp: _do_box,
    CylinderOp: _do_cylinder,
    TubeOp: _do_tube,
    HoleOp: _do_hole,
    RectangularHolePatternOp: _do_pattern,
    LinearSlotPatternOp: _do_slot_pattern,
    ChamferOp: _do_chamfer,
    FilletOp: _do_fillet,
    ProfileExtrudeOp: _do_profile_extrude,
    ProfileRevolveOp: _do_profile_revolve,
    SheetMetalBendOp: _do_sheet_metal_bend,
    CurvedRodOp: _do_curved_rod,
    RectangularLoftOp: _do_rectangular_loft,
    CurvedStripOp: _do_curved_strip,
    ThreadedBoltOp: _do_threaded_bolt,
    FlangedCouplingOp: _do_flanged_coupling,
    ControllerEnclosureOp: _do_controller_enclosure,
    MotorMountBracketOp: _do_motor_mount_bracket,
    HydraulicManifoldOp: _do_hydraulic_manifold,
    BlowerTransitionDuctOp: _do_blower_transition_duct,
}


# --------------------------------------------------------------------------


def execute(program: CADProgram, values: dict[str, float]) -> ExecutionResult:
    """Build the program. Runs regardless of preflight findings."""
    missing = [n for n in program.referenced_parameters if n not in values]
    if missing:
        raise ExecutionError(
            f"cannot execute: no value supplied for {', '.join(sorted(missing))}"
        )

    ctx = BuildContext(values=dict(values))
    wp: Optional[cq.Workplane] = None
    applied: list[str] = []
    measurements: list[OperationMeasurement] = []
    previous_volume = 0.0

    for op in program.operations:
        handler = HANDLERS.get(type(op))
        if handler is None:
            # No permissive fallback: an unknown operation is a hard stop.
            raise UnsupportedOperation(
                f"no handler for operation type {type(op).__name__} (id={op.id!r})"
            )
        if wp is None and not (
            isinstance(op, (
                BoxOp, CylinderOp, TubeOp, SheetMetalBendOp, CurvedRodOp,
                RectangularLoftOp,
                CurvedStripOp,
                ThreadedBoltOp,
                FlangedCouplingOp,
                ControllerEnclosureOp,
                MotorMountBracketOp,
                HydraulicManifoldOp,
                BlowerTransitionDuctOp,
            ))
            or isinstance(op, (ProfileExtrudeOp, ProfileRevolveOp))
            and op.mode is BooleanMode.ADD
        ):
            raise ExecutionError(
                f"first operation must create a solid; got {op.type!r} ({op.id!r})"
            )
        try:
            wp = handler(wp, op, ctx)
        except ExecutionError:
            raise
        except Exception as exc:
            raise ExecutionError(f"operation {op.id!r} ({op.type}) failed: {exc}") from exc
        applied.append(op.id)

        # Observe the intermediate solid. Public APIs only, in keeping with the
        # rest of the measurement layer. The intermediate is measured and then
        # released rather than retained: 40 retained solids measured +3.4 MB
        # RSS, which is affordable, but nothing downstream needs them.
        started = time.perf_counter()
        try:
            intermediate = wp.val()
            volume = float(intermediate.Volume())
            measurements.append(OperationMeasurement(
                operation_id=op.id,
                volume=volume,
                volume_delta=volume - previous_volume,
                is_valid=bool(intermediate.isValid()),
                solid_count=len(wp.solids().vals()),
                seconds=time.perf_counter() - started,
            ))
            previous_volume = volume
        except Exception as exc:
            # A solid whose volume the kernel cannot compute is not a solid we
            # should carry forward. Stopping here names the operation that went
            # wrong; continuing would fail later against the whole part, with
            # nothing to say about which feature caused it.
            raise ExecutionError(
                f"operation {op.id!r} built but could not be measured: {exc}"
            ) from exc

    if wp is None:
        raise ExecutionError("program produced no geometry")

    return ExecutionResult(
        solid=wp, program=program, context=ctx,
        operations_applied=applied, measurements=measurements,
    )


def export_step(result: ExecutionResult, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(result.shape, str(path), exportType="STEP")
    return path


def export_stl(result: ExecutionResult, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(result.shape, str(path), exportType="STL")
    return path


def import_step(path: str | Path):
    """Re-import an exported STEP so the artifact itself can be validated."""
    return cq.importers.importStep(str(path)).val()


# Assembly execution stays in this kernel adapter: no upstream module imports
# CadQuery or gets access to kernel selector syntax.


@dataclass(frozen=True)
class AssemblyCheck:
    id: str
    passed: bool
    actual: float
    limit: float
    unit: str
    message: str


@dataclass
class AssemblyResult:
    program: AssemblyProgram
    components: dict[str, ExecutionResult]
    placed_shapes: dict[str, object]
    checks: list[AssemblyCheck] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


def _unit_vector(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(sum(value * value for value in vector))
    if length <= 1e-12:
        raise ValueError("mate axis must be non-zero")
    return tuple(value / length for value in vector)


def execute_assembly(program: AssemblyProgram) -> AssemblyResult:
    components: dict[str, ExecutionResult] = {}
    placed: dict[str, object] = {}
    transforms = {component.id: component.transform for component in program.components}
    checks: list[AssemblyCheck] = []

    for component in program.components:
        result = execute(component.program, component.parameters)
        transform = component.transform
        location = cq.Location(
            cq.Vector(*transform.translation),
            cq.Vector(*transform.rotation_axis),
            transform.rotation_degrees,
        )
        components[component.id] = result
        placed[component.id] = result.shape.moved(location)

    for mate in program.mates:
        ta, tb = transforms[mate.component_a], transforms[mate.component_b]
        if isinstance(mate, CoincidentOriginMate):
            error = math.dist(ta.translation, tb.translation)
            checks.append(AssemblyCheck(
                mate.id, error <= mate.tolerance_mm, error, mate.tolerance_mm, "mm",
                f"component origin separation is {error:.6g} mm",
            ))
        elif isinstance(mate, OffsetMate):
            index = {"x": 0, "y": 1, "z": 2}[mate.axis]
            actual = tb.translation[index] - ta.translation[index]
            error = abs(actual - mate.distance_mm)
            checks.append(AssemblyCheck(
                mate.id, error <= mate.tolerance_mm, actual, mate.distance_mm, "mm",
                f"{mate.axis}-offset is {actual:.6g} mm; error {error:.6g} mm",
            ))
        elif isinstance(mate, ConcentricAxisMate):
            axis_a, axis_b = _unit_vector(mate.axis_a), _unit_vector(mate.axis_b)
            dot = max(-1.0, min(1.0, abs(sum(
                left * right for left, right in zip(axis_a, axis_b)
            ))))
            angle = math.degrees(math.acos(dot))
            delta = tuple(
                right - left for left, right in zip(ta.translation, tb.translation)
            )
            projection = sum(value * axis for value, axis in zip(delta, axis_a))
            radial = math.sqrt(max(
                0.0, sum(value * value for value in delta) - projection**2
            ))
            passed = (
                radial <= mate.tolerance_mm
                and angle <= mate.angular_tolerance_degrees
            )
            checks.append(AssemblyCheck(
                mate.id, passed, radial, mate.tolerance_mm, "mm",
                f"axis radial offset {radial:.6g} mm; angular error {angle:.6g} deg",
            ))

    if program.check_collisions:
        for left, right in combinations(sorted(placed), 2):
            pair = frozenset((left, right))
            overlap = float(placed[left].intersect(placed[right]).Volume())
            allowed = pair in program.allowed_contacts
            checks.append(AssemblyCheck(
                f"collision_{left}_{right}", overlap <= 1e-6 or allowed,
                overlap, 1e-6, "mm3",
                f"overlap volume is {overlap:.6g} mm3"
                + (" (allowed)" if allowed else ""),
            ))

    return AssemblyResult(program, components, placed, checks)
