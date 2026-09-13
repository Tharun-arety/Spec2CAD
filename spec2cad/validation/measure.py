"""Geometric measurement primitives -- public CadQuery API only.

Three rules govern this module, each learned from something that actually went
wrong during development:

1. No private API. An earlier draft read hole radii through
   `face._geomAdaptor().Cylinder().Radius()`. The public `Edge.radius()` returns
   the identical value and does not depend on OCC internals.

2. No bounding boxes for dimensions. `Shape.BoundingBox().zlen` reported 5.007
   for a 5.000 mm plate -- OCC's bounding box carries a tolerance gap. Extents
   are measured from planar face positions instead, which returned exactly
   45.000000 and 5.000000.

3. No exact face counts. Asserting "this solid has exactly 10 planar and 5
   cylindrical faces" breaks the moment a fillet is added and proves little in
   the meantime. Material integrity is checked by comparing the measured volume
   against the analytically expected volume, which agreed to 0.000000 mm3 in
   testing and actually catches a wrong-sized feature.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Tolerances for comparing measured geometry against intent.
LINEAR_TOLERANCE_MM = 1e-4
VOLUME_TOLERANCE_MM3 = 1e-3
NORMAL_TOLERANCE = 1e-6


@dataclass(frozen=True)
class CircularFeature:
    """A circular opening observed on a face."""

    x: float
    y: float
    radius: float

    @property
    def diameter(self) -> float:
        return 2.0 * self.radius

    def key(self, places: int = 4) -> tuple:
        return (round(self.x, places), round(self.y, places), round(self.radius, places))


@dataclass(frozen=True)
class PlateExtents:
    width: float
    height: float
    thickness: float


def _planar_faces_with_normal(shape, axis: str):
    """Planar faces whose normal is parallel to the given axis."""
    out = []
    for face in shape.Faces():
        if face.geomType() != "PLANE":
            continue
        n = face.normalAt()
        component = {"x": n.x, "y": n.y, "z": n.z}[axis]
        if abs(abs(component) - 1.0) <= NORMAL_TOLERANCE:
            out.append(face)
    return out


def plate_extents(shape) -> PlateExtents:
    """Measure the plate's overall dimensions from planar face positions.

    Chamfer faces have normals at 45 degrees in XY and so are excluded
    automatically by the parallel-to-axis test.
    """
    def extent(axis: str) -> float:
        faces = _planar_faces_with_normal(shape, axis)
        if len(faces) < 2:
            raise ValueError(f"cannot measure {axis} extent: found {len(faces)} planar faces")
        centres = [{"x": f.Center().x, "y": f.Center().y, "z": f.Center().z}[axis]
                   for f in faces]
        return max(centres) - min(centres)

    return PlateExtents(width=extent("x"), height=extent("y"), thickness=extent("z"))


def top_face(shape):
    faces = _planar_faces_with_normal(shape, "z")
    if not faces:
        raise ValueError("no horizontal planar faces found")
    return max(faces, key=lambda f: f.Center().z)


def bottom_face(shape):
    faces = _planar_faces_with_normal(shape, "z")
    if not faces:
        raise ValueError("no horizontal planar faces found")
    return min(faces, key=lambda f: f.Center().z)


def circular_features(face) -> list[CircularFeature]:
    """Circular openings on a face, via the public Edge.radius()."""
    out = []
    for edge in face.Edges():
        if edge.geomType() != "CIRCLE":
            continue
        centre = edge.Center()
        out.append(CircularFeature(x=centre.x, y=centre.y, radius=edge.radius()))
    return out


def through_holes(shape) -> tuple[bool, list[CircularFeature]]:
    """Whether every opening passes clean through, and the openings themselves.

    A through hole appears as the same circle on both the top and bottom faces.
    A blind or failed cut appears on one only.
    """
    top = sorted(f.key() for f in circular_features(top_face(shape)))
    bottom = sorted(f.key() for f in circular_features(bottom_face(shape)))
    return top == bottom, circular_features(top_face(shape))


def features_near_radius(
    features: list[CircularFeature], radius: float, tol: float = 1e-3
) -> list[CircularFeature]:
    return [f for f in features if abs(f.radius - radius) <= tol]


def hole_spacing(features: list[CircularFeature]) -> tuple[float, float]:
    """Centre-to-centre spacing of a symmetric rectangular pattern."""
    if len(features) < 2:
        raise ValueError(f"need at least 2 holes to measure spacing, got {len(features)}")
    xs = sorted({round(f.x, 6) for f in features})
    ys = sorted({round(f.y, 6) for f in features})
    return (max(xs) - min(xs), max(ys) - min(ys))


def measured_edge_clearance(
    shape, mounting_radius: float, tol: float = 1e-3
) -> float:
    """Smallest gap between any mounting-hole edge and the plate boundary.

    Measured on the solid: hole positions and radii come from the B-Rep, and the
    boundary comes from the measured plate extents.
    """
    extents = plate_extents(shape)
    holes = features_near_radius(circular_features(top_face(shape)), mounting_radius, tol)
    if not holes:
        raise ValueError(f"no mounting holes of radius {mounting_radius} found")

    worst = math.inf
    for hole in holes:
        worst = min(
            worst,
            extents.width / 2.0 - (abs(hole.x) + hole.radius),
            extents.height / 2.0 - (abs(hole.y) + hole.radius),
        )
    return worst


def expected_volume(
    width: float,
    height: float,
    thickness: float,
    shaft_diameter: float,
    hole_diameter: float,
    hole_count: int,
    chamfer: float,
) -> float:
    """Analytic volume of the adapter plate.

    Each of the four external vertical chamfers removes a right-triangular prism
    of cross-section chamfer^2/2 running the full thickness.
    """
    volume = width * height * thickness
    volume -= math.pi * (shaft_diameter / 2.0) ** 2 * thickness
    volume -= hole_count * math.pi * (hole_diameter / 2.0) ** 2 * thickness
    volume -= 4 * (chamfer * chamfer / 2.0) * thickness
    return volume
