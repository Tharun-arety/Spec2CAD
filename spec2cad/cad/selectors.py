"""Named selectors: the only place that knows CadQuery selector syntax.

The CAD IR carries names like "external_vertical_edges", never kernel selector
strings. That keeps the IR portable and, more usefully, keeps selector bugs in
one reviewable place instead of scattered through generated programs.

"External" is enforced geometrically rather than assumed. For this part a bare
"|Z" happens to pick exactly the four corner edges, because every internal
feature is cylindrical and so has no straight vertical edges. Relying on that
would be a trap the first time someone adds a rectangular pocket, so the
selector actually tests that an edge lies on the outer boundary.
"""

from __future__ import annotations

import cadquery as cq

from spec2cad.schemas.cad_ir import EdgeSelector, FaceSelector

BOUNDARY_TOLERANCE = 1e-3


class ExternalVerticalEdges(cq.Selector):
    """Straight, Z-parallel edges lying on the plate's outer boundary."""

    def __init__(self, width: float, height: float, tol: float = BOUNDARY_TOLERANCE):
        self.width = width
        self.height = height
        self.tol = tol

    def filter(self, objectList):  # noqa: N803 - CadQuery's interface
        kept = []
        for edge in objectList:
            if edge.geomType() != "LINE":
                continue
            centre = edge.Center()
            on_x = abs(abs(centre.x) - self.width / 2.0) <= self.tol
            on_y = abs(abs(centre.y) - self.height / 2.0) <= self.tol
            if on_x and on_y:
                kept.append(edge)
        return kept


class UnsupportedSelector(ValueError):
    """Raised for a selector name the compiler does not implement."""


def select_edges(
    workplane: cq.Workplane, selector: EdgeSelector, *, width: float, height: float
) -> cq.Workplane:
    """Resolve a named edge selector against a solid."""
    if selector is EdgeSelector.EXTERNAL_VERTICAL_EDGES:
        return workplane.edges("|Z").edges(ExternalVerticalEdges(width, height))
    if selector is EdgeSelector.EXTERNAL_TOP_PERIMETER:
        return workplane.faces(">Z").edges()
    raise UnsupportedSelector(f"no implementation for edge selector {selector!r}")


def select_face(workplane: cq.Workplane, selector: FaceSelector) -> cq.Workplane:
    """Resolve a named face selector against a solid."""
    if selector is FaceSelector.TOP_FACE:
        return workplane.faces(">Z")
    if selector is FaceSelector.BOTTOM_FACE:
        return workplane.faces("<Z")
    raise UnsupportedSelector(f"no implementation for face selector {selector!r}")


# Human-readable equivalents, used by the script writer so the displayed script
# matches what the executor actually did.
EDGE_SELECTOR_SOURCE: dict[EdgeSelector, str] = {
    EdgeSelector.EXTERNAL_VERTICAL_EDGES:
        '.edges("|Z").edges(ExternalVerticalEdges(width, height))',
    EdgeSelector.EXTERNAL_TOP_PERIMETER: '.faces(">Z").edges()',
}

FACE_SELECTOR_SOURCE: dict[FaceSelector, str] = {
    FaceSelector.TOP_FACE: '.faces(">Z")',
    FaceSelector.BOTTOM_FACE: '.faces("<Z")',
}
