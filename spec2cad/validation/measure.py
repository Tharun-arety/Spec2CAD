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

import cadquery as cq

# Tolerances for comparing measured geometry against intent.
LINEAR_TOLERANCE_MM = 1e-4
VOLUME_TOLERANCE_MM3 = 1e-3
NORMAL_TOLERANCE = 1e-6


def named_planar_face(shape, name: str):
    """Select a named extremal face while keeping kernel syntax in this adapter."""
    selector = {
        "top": ">Z", "bottom": "<Z", "positive_x": ">X",
        "negative_x": "<X", "positive_y": ">Y", "negative_y": "<Y",
    }[name]
    faces = cq.Workplane(obj=shape).faces(selector).vals()
    if not faces:
        raise ValueError(f"no face matches {name!r}")
    return max(faces, key=lambda face: face.Area())


def face_vertex_span(face) -> float:
    """Largest exact vertex-coordinate extent, without tolerance-padded boxes."""
    vertices = [vertex.Center() for vertex in face.Vertices()]
    if not vertices:
        raise ValueError("selected face has no vertices")
    return max(
        max(getattr(point, axis) for point in vertices)
        - min(getattr(point, axis) for point in vertices)
        for axis in ("x", "y", "z")
    )


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


@dataclass(frozen=True)
class CylindricalExtents:
    outer_diameter: float
    axial_length: float
    inner_diameter: float | None = None


@dataclass(frozen=True)
class SlotFeature:
    x: float
    y: float
    width: float
    length: float

    def key(self, places: int = 4) -> tuple:
        return (
            round(self.x, places), round(self.y, places),
            round(self.width, places), round(self.length, places),
        )


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


def cylindrical_extents(shape) -> CylindricalExtents:
    """Measure an axial cylinder/tube from planar end faces and circular edges."""
    ends = _planar_faces_with_normal(shape, "z")
    if len(ends) < 2:
        raise ValueError("fewer than two planar axial end faces found")
    axial_length = max(face.Center().z for face in ends) - min(
        face.Center().z for face in ends
    )
    circles = circular_features(top_face(shape))
    if not circles:
        raise ValueError("no circular boundary found on axial end face")
    diameters = sorted({round(item.diameter, 9) for item in circles}, reverse=True)
    return CylindricalExtents(
        outer_diameter=diameters[0],
        axial_length=axial_length,
        inner_diameter=diameters[1] if len(diameters) > 1 else None,
    )


def circular_features(face) -> list[CircularFeature]:
    """Circular openings on a face, via the public Edge.radius()."""
    out = []
    for edge in face.Edges():
        if edge.geomType() != "CIRCLE":
            continue
        radius = edge.radius()
        # Fillets and slots also contain circular *arcs*. Only a closed circle
        # is a circular opening; treating every arc as a hole made a slotted
        # bracket appear to have extra mounting holes of the slot radius.
        if abs(edge.Length() - 2.0 * math.pi * radius) > 1e-4:
            continue
        centre = edge.Center()
        out.append(CircularFeature(x=centre.x, y=centre.y, radius=radius))
    return out


def slot_features(face, tol: float = 1e-4) -> list[SlotFeature]:
    """Measure obround slots from their two semicircular boundary arcs."""
    arcs = []
    for edge in face.Edges():
        if edge.geomType() != "CIRCLE":
            continue
        radius = edge.radius()
        if abs(edge.Length() - math.pi * radius) > tol:
            continue
        centre = edge.arcCenter()
        arcs.append((centre.x, centre.y, radius))

    slots: list[SlotFeature] = []
    used: set[int] = set()
    for i, first in enumerate(arcs):
        if i in used:
            continue
        best = None
        best_distance = math.inf
        for j, second in enumerate(arcs):
            if j <= i or j in used or abs(first[2] - second[2]) > tol:
                continue
            distance = math.hypot(first[0] - second[0], first[1] - second[1])
            if distance < best_distance:
                best, best_distance = j, distance
        if best is None:
            continue
        second = arcs[best]
        used.update({i, best})
        slots.append(SlotFeature(
            x=(first[0] + second[0]) / 2.0,
            y=(first[1] + second[1]) / 2.0,
            width=2.0 * first[2],
            length=best_distance + 2.0 * first[2],
        ))
    return slots


def external_corner_fillet_count(shape, radius: float, tol: float = 1e-3) -> int:
    """Count quarter-circle arcs of the requested radius on the outer boundary."""
    extents = plate_extents(shape)
    count = 0
    for edge in top_face(shape).Edges():
        if edge.geomType() != "CIRCLE" or abs(edge.radius() - radius) > tol:
            continue
        if abs(edge.Length() - math.pi * radius / 2.0) > tol:
            continue
        centre = edge.arcCenter()
        on_corner = (
            abs(abs(centre.x) - (extents.width / 2.0 - radius)) <= tol
            and abs(abs(centre.y) - (extents.height / 2.0 - radius)) <= tol
        )
        if on_corner:
            count += 1
    return count


def through_holes(shape) -> tuple[bool, list[CircularFeature | SlotFeature]]:
    """Whether every circular/slot opening passes through, and the openings.

    A through cut appears as the same boundary on both the top and bottom faces.
    A blind or failed cut appears on one only.
    """
    top_circles = circular_features(top_face(shape))
    bottom_circles = circular_features(bottom_face(shape))
    top_slots = slot_features(top_face(shape))
    bottom_slots = slot_features(bottom_face(shape))
    top = sorted([("circle", *f.key()) for f in top_circles]
                 + [("slot", *f.key()) for f in top_slots])
    bottom = sorted([("circle", *f.key()) for f in bottom_circles]
                    + [("slot", *f.key()) for f in bottom_slots])
    return top == bottom, [*top_circles, *top_slots]


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
    slot_width: float = 0.0,
    slot_length: float = 0.0,
    slot_count: int = 0,
    fillet: float = 0.0,
) -> float:
    """Analytic volume of the adapter plate.

    Each of the four external vertical chamfers removes a right-triangular prism
    of cross-section chamfer^2/2 running the full thickness.
    """
    volume = width * height * thickness
    volume -= math.pi * (shaft_diameter / 2.0) ** 2 * thickness
    volume -= hole_count * math.pi * (hole_diameter / 2.0) ** 2 * thickness
    volume -= 4 * (chamfer * chamfer / 2.0) * thickness
    if slot_count and slot_width and slot_length:
        slot_area = (
            (slot_length - slot_width) * slot_width
            + math.pi * (slot_width / 2.0) ** 2
        )
        volume -= slot_count * slot_area * thickness
    if fillet:
        removed_per_corner = fillet * fillet * (1.0 - math.pi / 4.0)
        volume -= 4 * removed_per_corner * thickness
    return volume
