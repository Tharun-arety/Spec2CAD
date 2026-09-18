"""Deterministic, revision-bound engineering view artifacts."""

from __future__ import annotations

from enum import Enum
import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from spec2cad.backends.cadquery_kernel import cq
from spec2cad.cad_state_serialization import csg_content_hash
from spec2cad.schemas.cad_state_graph import CADStateGraph
from spec2cad.schemas.feature_ir import StableId


CANONICAL_VIEW_SCHEMA_VERSION = "1.0.0"
Sha256 = str


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CanonicalViewKind(str, Enum):
    TOP = "top"
    FRONT = "front"
    RIGHT = "right"
    ISOMETRIC = "isometric"
    GOVERNED_SECTION = "governed_section"


class GovernedSection(_FrozenModel):
    id: StableId
    label: str = Field(min_length=1)
    plane: Literal["XY", "XZ", "YZ"]
    offset_mm: float = Field(default=0.0, allow_inf_nan=False)
    governed_by_ids: tuple[StableId, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_governing_records(self) -> "GovernedSection":
        if len(self.governed_by_ids) != len(set(self.governed_by_ids)):
            raise ValueError("governed section record ids must be unique")
        return self


class CanonicalViewRequest(_FrozenModel):
    schema_version: Literal["1.0.0"] = CANONICAL_VIEW_SCHEMA_VERSION
    id: StableId
    design_revision: int = Field(ge=1)
    build_request_id: str = Field(min_length=1)
    backend_id: StableId
    backend_version: str = Field(min_length=1)
    feature_ir_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    csg_id: StableId
    csg_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    width_px: int = Field(default=960, ge=320, le=4096)
    height_px: int = Field(default=720, ge=240, le=4096)
    views: tuple[CanonicalViewKind, ...] = tuple(CanonicalViewKind)
    section: GovernedSection | None = None

    @model_validator(mode="after")
    def validate_views(self) -> "CanonicalViewRequest":
        if not self.views:
            raise ValueError("at least one canonical view is required")
        if len(self.views) != len(set(self.views)):
            raise ValueError("view kinds must be unique")
        wants_section = CanonicalViewKind.GOVERNED_SECTION in self.views
        if wants_section != (self.section is not None):
            raise ValueError("governed section definition must match requested view")
        return self


class CanonicalViewArtifact(_FrozenModel):
    schema_version: Literal["1.0.0"] = CANONICAL_VIEW_SCHEMA_VERSION
    id: StableId
    kind: CanonicalViewKind
    request_id: StableId
    design_revision: int = Field(ge=1)
    build_request_id: str = Field(min_length=1)
    backend_id: StableId
    backend_version: str = Field(min_length=1)
    feature_ir_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    csg_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    filename: str = Field(min_length=5, pattern=r"^[^/\\]+\.svg$")
    media_type: Literal["image/svg+xml"] = "image/svg+xml"
    content_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    byte_length: int = Field(gt=0)
    projection_direction: tuple[float, float, float]
    section_id: StableId | None = None

    @model_validator(mode="after")
    def validate_section_identity(self) -> "CanonicalViewArtifact":
        is_section = self.kind is CanonicalViewKind.GOVERNED_SECTION
        if is_section != (self.section_id is not None):
            raise ValueError("section artifact requires exactly one section id")
        return self


class CanonicalViewBundle(_FrozenModel):
    schema_version: Literal["1.0.0"] = CANONICAL_VIEW_SCHEMA_VERSION
    request: CanonicalViewRequest
    artifacts: tuple[CanonicalViewArtifact, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_complete_bundle(self) -> "CanonicalViewBundle":
        if tuple(item.kind for item in self.artifacts) != self.request.views:
            raise ValueError("canonical view artifacts must match requested order")
        if any(item.request_id != self.request.id for item in self.artifacts):
            raise ValueError("canonical view artifact references another request")
        return self


_PROJECTIONS = {
    CanonicalViewKind.TOP: (0.0, 0.0, 1.0),
    CanonicalViewKind.FRONT: (0.0, -1.0, 0.0),
    CanonicalViewKind.RIGHT: (1.0, 0.0, 0.0),
    CanonicalViewKind.ISOMETRIC: (1.0, -1.0, 1.0),
}
_SECTION_PROJECTIONS = {
    "XY": (0.0, 0.0, 1.0),
    "XZ": (0.0, -1.0, 0.0),
    "YZ": (1.0, 0.0, 0.0),
}


def _validate_source(graph: CADStateGraph, request: CanonicalViewRequest) -> None:
    identity = (
        request.csg_id == graph.id
        and request.csg_sha256 == csg_content_hash(graph)
        and request.build_request_id == graph.build_request_id
        and request.backend_id == graph.backend_id
        and request.backend_version == graph.backend_version
        and request.feature_ir_sha256 == graph.source_feature_ir_sha256
    )
    if not identity:
        raise ValueError("canonical view request and CSG identity differ")


def render_cadquery_views(
    shape,
    graph: CADStateGraph,
    request: CanonicalViewRequest,
    output_dir: Path,
) -> CanonicalViewBundle:
    """Render fixed SVG projections through the sole CadQuery import boundary."""
    _validate_source(graph, request)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for kind in request.views:
        section_id = None
        rendered_shape = shape
        if kind is CanonicalViewKind.GOVERNED_SECTION:
            section = request.section
            if section is None:
                raise ValueError("governed section definition is missing")
            workplane = cq.Workplane(section.plane).newObject([shape]).section(
                section.offset_mm
            )
            if workplane.size() == 0:
                raise ValueError("governed section does not intersect the CAD shape")
            rendered_shape = workplane.val()
            projection = _SECTION_PROJECTIONS[section.plane]
            section_id = section.id
        else:
            projection = _PROJECTIONS[kind]
        svg = cq.exporters.getSVG(rendered_shape, {
            "width": request.width_px,
            "height": request.height_px,
            "marginLeft": 24,
            "marginTop": 24,
            "projectionDir": projection,
            "showAxes": False,
            "showHidden": False,
            "strokeWidth": 0.7,
        }).replace("\r\n", "\n")
        payload = svg.encode("utf-8")
        filename = f"{request.id}.{kind.value}.svg"
        (output_dir / filename).write_bytes(payload)
        content_hash = hashlib.sha256(payload).hexdigest()
        artifacts.append(CanonicalViewArtifact(
            id=f"view.{request.id}.{kind.value}",
            kind=kind,
            request_id=request.id,
            design_revision=request.design_revision,
            build_request_id=request.build_request_id,
            backend_id=request.backend_id,
            backend_version=request.backend_version,
            feature_ir_sha256=request.feature_ir_sha256,
            csg_sha256=request.csg_sha256,
            filename=filename,
            content_sha256=content_hash,
            byte_length=len(payload),
            projection_direction=projection,
            section_id=section_id,
        ))
    return CanonicalViewBundle(request=request, artifacts=tuple(artifacts))
