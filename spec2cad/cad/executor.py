"""Execute a CADProgram against the CAD kernel.

This is the ONLY module in the project that imports cadquery. Nothing upstream
produces Python; a model can at most produce schema-valid operations, and this
module decides what each one means. An operation type with no handler is an
error -- there is no permissive fallback, because a fallback here would mean
silently building something other than what was asked for.

Execution is *diagnostic*: it runs even when preflight predicted a violation, so
the violation can be measured on real geometry rather than only predicted. The
decision about whether the result may be exported belongs to the release gate,
not here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import cadquery as cq

from spec2cad.cad.selectors import select_edges
from spec2cad.schemas.cad_ir import (
    BoxOp,
    CADProgram,
    ChamferOp,
    HoleOp,
    RectangularHolePatternOp,
    Termination,
    resolve,
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


def _do_hole(wp: cq.Workplane, op: HoleOp, ctx: BuildContext) -> cq.Workplane:
    diameter = resolve(op.diameter, ctx.values)
    if diameter <= 0:
        raise ExecutionError(f"hole diameter must be positive, got {diameter}")
    x, y = resolve(op.x, ctx.values), resolve(op.y, ctx.values)
    ctx.hole_diameters.append(diameter)

    plane = wp.faces(">Z").workplane(origin=(0, 0, 0))
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
        wp.faces(">Z")
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


HANDLERS: dict[type, Callable] = {
    BoxOp: _do_box,
    HoleOp: _do_hole,
    RectangularHolePatternOp: _do_pattern,
    ChamferOp: _do_chamfer,
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
        if wp is None and not isinstance(op, BoxOp):
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
