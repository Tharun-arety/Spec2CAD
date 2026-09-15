"""Independently measure GD&T controls from the finished B-Rep."""

from __future__ import annotations

import math
from dataclasses import dataclass

from spec2cad.schemas.gdt_ir import (
    CircularFeatureSelector,
    FlatnessTolerance,
    InspectionProgram,
    PerpendicularityTolerance,
    PositionTolerance,
    SizeTolerance,
)
from spec2cad.validation import measure as M


@dataclass(frozen=True)
class InspectionResult:
    id: str
    control_type: str
    passed: bool
    actual: float | None
    lower_limit: float | None
    upper_limit: float
    unit: str
    message: str


def _face(shape, name: str):
    return M.named_planar_face(shape, name)


def _circle(shape, selector: CircularFeatureSelector):
    candidates = M.circular_features(M.top_face(shape))
    if not candidates:
        raise ValueError("no circular feature is measurable on the top face")
    return min(
        candidates,
        key=lambda feature: (
            abs(2 * feature.radius - selector.nominal_diameter),
            math.hypot(feature.x - selector.nominal_x, feature.y - selector.nominal_y),
        ),
    )


def inspect_gdt(shape, program: InspectionProgram) -> list[InspectionResult]:
    datum_faces = {datum.id: _face(shape, datum.face) for datum in program.datums}
    results: list[InspectionResult] = []

    for control in program.controls:
        if isinstance(control, SizeTolerance):
            feature = _circle(shape, control.feature)
            actual = 2 * feature.radius
            passed = control.lower_limit <= actual <= control.upper_limit
            results.append(InspectionResult(
                control.id, control.type, passed, actual, control.lower_limit,
                control.upper_limit, "mm",
                f"measured diameter {actual:.6g} mm",
            ))
        elif isinstance(control, PositionTolerance):
            feature = _circle(shape, control.feature)
            actual = 2 * math.hypot(
                feature.x - control.feature.nominal_x,
                feature.y - control.feature.nominal_y,
            )
            results.append(InspectionResult(
                control.id, control.type, actual <= control.tolerance_diameter,
                actual, None, control.tolerance_diameter, "mm",
                f"true-position diametral error {actual:.6g} mm",
            ))
        elif isinstance(control, FlatnessTolerance):
            face = _face(shape, control.face)
            # Exact analytic planes have zero form error. Non-planar faces are
            # not silently accepted as a flatness measurement.
            actual = 0.0 if face.geomType() == "PLANE" else None
            results.append(InspectionResult(
                control.id, control.type,
                actual is not None and actual <= control.tolerance,
                actual, None, control.tolerance, "mm",
                "analytic planar face" if actual == 0 else "selected face is not planar",
            ))
        elif isinstance(control, PerpendicularityTolerance):
            face = _face(shape, control.face)
            datum = datum_faces[control.datum]
            if face.geomType() != "PLANE" or datum.geomType() != "PLANE":
                actual = None
            else:
                a, b = face.normalAt(), datum.normalAt()
                dot = abs(a.x * b.x + a.y * b.y + a.z * b.z)
                dot = max(0.0, min(1.0, dot))
                angular_error = math.asin(dot)  # zero when normals are perpendicular
                span = M.face_vertex_span(face)
                actual = span * math.tan(angular_error)
            results.append(InspectionResult(
                control.id, control.type,
                actual is not None and actual <= control.tolerance,
                actual, None, control.tolerance, "mm",
                (
                    f"parallel-plane-zone deviation {actual:.6g} mm"
                    if actual is not None else "selected face or datum is not planar"
                ),
            ))
    return results
