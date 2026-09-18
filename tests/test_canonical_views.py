"""Canonical engineering views are deterministic and revision-bound."""

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from spec2cad.backends import BuildRequest, BuildStatus
from spec2cad.backends.cadquery_adapter import CadQueryAdapter
from spec2cad.cad_state_serialization import csg_content_hash
from spec2cad.canonical_views import (
    CanonicalViewKind,
    CanonicalViewRequest,
    GovernedSection,
    render_cadquery_views,
)
from spec2cad.feature_compiler import compile_feature_ir
from spec2cad.feature_serialization import feature_ir_manifest
from spec2cad.pipeline import repair, run


ROOT = Path(__file__).resolve().parents[1]
MOTOR = ROOT / "examples" / "motor_adapter"


def built_motor():
    result = run(
        MOTOR / "sketch.png",
        MOTOR / "motor_datasheet.pdf",
        MOTOR / "requirement.txt",
        backend_override="fixture",
    )
    revision = repair(
        result, "widen_to_recommended", approved_by="canonical-view-test"
    ).latest
    feature_ir = compile_feature_ir(revision.intent_graph)
    adapter = CadQueryAdapter()
    built = adapter.build(BuildRequest(
        request_id="build:cadquery:canonical_views",
        backend_id="cadquery",
        feature_ir=feature_ir,
        feature_ir_manifest=feature_ir_manifest(feature_ir),
    ))
    assert built.status is BuildStatus.SUCCEEDED
    return revision, feature_ir, adapter, built


def request_for(revision, feature_ir, graph):
    return CanonicalViewRequest(
        id="views.motor.r2",
        design_revision=revision.revision,
        build_request_id=graph.build_request_id,
        backend_id=graph.backend_id,
        backend_version=graph.backend_version,
        feature_ir_sha256=feature_ir_manifest(feature_ir).content_sha256,
        csg_id=graph.id,
        csg_sha256=csg_content_hash(graph),
        section=GovernedSection(
            id="section.motor_center_xz",
            label="Motor interface center section",
            plane="XZ",
            offset_mm=0.0,
            governed_by_ids=(feature_ir.interfaces[0].id,),
        ),
    )


def test_real_motor_produces_complete_revision_bound_svg_bundle(tmp_path):
    revision, feature_ir, adapter, built = built_motor()
    graph = adapter.csg_for(built.snapshot)
    request = request_for(revision, feature_ir, graph)
    bundle = render_cadquery_views(
        adapter.execution_for(built.snapshot).shape,
        graph,
        request,
        tmp_path,
    )

    assert {item.kind for item in bundle.artifacts} == set(CanonicalViewKind)
    assert bundle.request == request
    for artifact in bundle.artifacts:
        path = tmp_path / artifact.filename
        payload = path.read_bytes()
        assert payload.startswith(b"<?xml")
        assert artifact.media_type == "image/svg+xml"
        assert artifact.byte_length == len(payload)
        assert artifact.content_sha256 == hashlib.sha256(payload).hexdigest()
        assert artifact.design_revision == revision.revision
        assert artifact.build_request_id == graph.build_request_id
        assert artifact.csg_sha256 == csg_content_hash(graph)
    section = next(
        item for item in bundle.artifacts
        if item.kind is CanonicalViewKind.GOVERNED_SECTION
    )
    assert section.section_id == request.section.id


def test_repeated_render_has_identical_artifact_hashes(tmp_path):
    revision, feature_ir, adapter, built = built_motor()
    graph = adapter.csg_for(built.snapshot)
    request = request_for(revision, feature_ir, graph)
    first = render_cadquery_views(
        adapter.execution_for(built.snapshot).shape,
        graph,
        request,
        tmp_path / "first",
    )
    second = render_cadquery_views(
        adapter.execution_for(built.snapshot).shape,
        graph,
        request,
        tmp_path / "second",
    )

    assert [(item.kind, item.content_sha256) for item in first.artifacts] == [
        (item.kind, item.content_sha256) for item in second.artifacts
    ]


def test_view_request_and_source_identity_fail_closed(tmp_path):
    revision, feature_ir, adapter, built = built_motor()
    graph = adapter.csg_for(built.snapshot)
    request = request_for(revision, feature_ir, graph)
    with pytest.raises(ValidationError, match="view kinds must be unique"):
        CanonicalViewRequest.model_validate({
            **request.model_dump(),
            "views": (CanonicalViewKind.TOP, CanonicalViewKind.TOP),
        })
    with pytest.raises(ValidationError, match="governed section definition"):
        CanonicalViewRequest.model_validate({
            **request.model_dump(),
            "section": None,
        })
    mismatched = request.model_copy(update={"csg_sha256": "f" * 64})
    with pytest.raises(ValueError, match="CSG identity"):
        render_cadquery_views(
            adapter.execution_for(built.snapshot).shape,
            graph,
            mismatched,
            tmp_path,
        )


def test_governed_section_requires_traceable_governing_records():
    with pytest.raises(ValidationError):
        GovernedSection(
            id="section.untraceable",
            label="Untraceable section",
            plane="XZ",
            governed_by_ids=(),
        )
