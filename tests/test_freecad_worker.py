"""The FreeCAD process boundary is fixed, typed and fail-closed."""

import json
import hashlib
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from spec2cad.backends import (
    BuildRequest,
    FreeCADWorkerOperation,
    FreeCADWorkerRequest,
    FreeCADWorkerResponse,
    WorkerStatus,
)
from spec2cad.backends import freecad_worker as worker
from spec2cad.backends.freecad_worker_generic import main as worker_main
from spec2cad.feature_compiler import compile_feature_ir
from spec2cad.feature_serialization import feature_ir_manifest
from spec2cad.cad_state_serialization import (
    canonical_csg_bytes,
    csg_content_hash,
    csg_manifest,
)
from spec2cad.pipeline import repair, run
from spec2cad.schemas.cad_state_graph import (
    RelationshipKind,
    validate_csg_provenance,
)
from spec2cad.schemas.feature_ir import EdgeSetSelector, FilletFeature


ROOT = Path(__file__).resolve().parents[1]
MOTOR = ROOT / "examples" / "motor_adapter"


def request():
    return FreeCADWorkerRequest(request_id="worker:ping", operation="ping")


def test_worker_messages_are_strict_versioned_and_json_portable():
    message = request()
    assert FreeCADWorkerRequest.model_validate_json(message.model_dump_json()) == message
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        FreeCADWorkerRequest(
            request_id="worker:ping", operation="ping", python="import os"
        )
    with pytest.raises(ValidationError):
        FreeCADWorkerRequest(request_id="worker:bad", operation="eval")


def test_fixed_entrypoint_rejects_unknown_raw_operation_before_freecad_import(tmp_path):
    request_path, response_path = tmp_path / "request.json", tmp_path / "response.json"
    request_path.write_text(json.dumps({
        "schema_version": "1.0.0",
        "request_id": "worker:unknown",
        "operation": "eval",
    }), encoding="utf-8")
    assert worker_main([
        "--request", str(request_path), "--response", str(response_path)
    ]) == 2
    payload = json.loads(response_path.read_text(encoding="utf-8"))
    assert payload["status"] == "unsupported"
    assert payload["diagnostics"][0]["code"] == "unsupported_capability"


def test_launcher_uses_argument_list_no_shell_and_validates_response(monkeypatch):
    executable = Path(r"C:\isolated\FreeCADCmd.exe")
    monkeypatch.setattr(worker, "discover_freecad_cmd", lambda explicit=None: executable)

    def fake_run(arguments, **options):
        assert arguments[0] == str(executable)
        assert arguments[1:] == ["-c", worker.WORKER_BOOTSTRAP]
        assert options["shell"] is False
        assert options["env"]["FREECAD_USER_HOME"]
        assert str(executable.parent.parent) in options["env"]["PATH"]
        assert len(arguments) == 3
        assert options["env"]["CADAICO_FREECAD_REQUEST"]
        response_path = Path(options["env"]["CADAICO_FREECAD_RESPONSE"])
        response_path.write_text(FreeCADWorkerResponse(
            request_id="worker:ping",
            operation=FreeCADWorkerOperation.PING,
            status=WorkerStatus.SUCCEEDED,
            freecad_version="1.0.2",
        ).model_dump_json(), encoding="utf-8")
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    response = worker.run_freecad_worker(request(), executable=executable)
    assert response.status is WorkerStatus.SUCCEEDED
    assert response.freecad_version == "1.0.2"


def test_timeout_and_missing_response_become_typed_failures(monkeypatch):
    executable = Path(r"C:\isolated\FreeCADCmd.exe")
    monkeypatch.setattr(worker, "discover_freecad_cmd", lambda explicit=None: executable)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(worker.subprocess, "run", timeout)
    response = worker.run_freecad_worker(request(), timeout_seconds=0.01)
    assert response.status is WorkerStatus.FAILED
    assert response.diagnostics[0].code == "timeout"

    monkeypatch.setattr(
        worker.subprocess,
        "run",
        lambda arguments, **options: subprocess.CompletedProcess(arguments, 3, "", "boom"),
    )
    response = worker.run_freecad_worker(request())
    assert response.status is WorkerStatus.FAILED
    assert response.diagnostics[0].code == "worker_failure"


def test_real_freecad_worker_ping_when_runtime_is_available():
    try:
        executable = worker.discover_freecad_cmd()
    except worker.FreeCADWorkerUnavailable:
        pytest.skip("FreeCAD runtime is not installed")
    response = worker.run_freecad_worker(request(), executable=executable, timeout_seconds=60)
    assert response.status is WorkerStatus.SUCCEEDED
    assert response.freecad_version


def test_real_worker_builds_native_editable_motor_document(tmp_path):
    try:
        executable = worker.discover_freecad_cmd()
    except worker.FreeCADWorkerUnavailable:
        pytest.skip("FreeCAD runtime is not installed")
    run_result = run(
        MOTOR / "sketch.png", MOTOR / "motor_datasheet.pdf",
        MOTOR / "requirement.txt", backend_override="fixture",
    )
    revision = repair(
        run_result, "widen_to_recommended", approved_by="freecad-native-test"
    ).latest
    document = compile_feature_ir(revision.intent_graph)
    build_request = BuildRequest(
        request_id="build:freecad:motor:r2",
        backend_id="freecad",
        feature_ir=document,
        feature_ir_manifest=feature_ir_manifest(document),
    )
    response = worker.run_freecad_worker(
        FreeCADWorkerRequest(
            request_id="worker:build:motor:r2",
            operation="build",
            build_request=build_request,
            artifact_root=str(tmp_path.resolve()),
        ),
        executable=executable,
        timeout_seconds=120,
    )
    assert response.status is WorkerStatus.SUCCEEDED, response.diagnostics
    summary = response.native_build
    assert Path(summary.document_path).is_file()
    assert set(summary.parameter_names) >= {
        "plate_width", "plate_height", "plate_thickness", "shaft_opening_diameter",
        "mounting_hole_diameter", "hole_spacing_x", "hole_spacing_y",
        "external_chamfer",
    }
    assert all(item.fully_constrained for item in summary.sketches)
    assert all(item.degrees_of_freedom == 0 for item in summary.sketches)
    assert len(summary.features) == 4
    assert all(item.name.startswith("FeatureFir") for item in summary.features)
    assert summary.recompute_errors == ()
    assert summary.solid_count == 1
    assert summary.volume_mm3 > 0
    csg = response.cad_state_graph
    validate_csg_provenance(
        csg, intent_graph=revision.intent_graph, feature_ir=document
    )
    assert csg.backend_id == "freecad"
    assert csg.source_feature_ir_sha256 == feature_ir_manifest(document).content_sha256
    assert csg_manifest(csg).byte_length == len(canonical_csg_bytes(csg))
    assert csg_content_hash(csg) == csg_manifest(csg).content_sha256
    assert {node.kind for node in csg.nodes} >= {
        "document", "body", "parameter_expression", "sketch_geometry",
        "constraint", "sketch", "native_feature", "semantic_topology",
        "diagnostic",
    }
    assert {item.kind for item in csg.relationships} >= {
        RelationshipKind.REALIZES_INTENT,
        RelationshipKind.REALIZES_FEATURE_IR,
        RelationshipKind.DEPENDS_ON,
        RelationshipKind.REFERENCES,
        RelationshipKind.CONSTRAINED_BY,
        RelationshipKind.CONSUMES_PROFILE,
        RelationshipKind.PRODUCES_TOPOLOGY,
        RelationshipKind.CORRESPONDS_TO_INTERFACE,
    }
    sketches = [node for node in csg.nodes if node.kind == "sketch"]
    assert all(node.fully_constrained and node.degrees_of_freedom == 0 for node in sketches)
    parameters = [node for node in csg.nodes if node.kind == "parameter_expression"]
    assert all(node.native_expression for node in parameters)
    topology = [node for node in csg.nodes if node.kind == "semantic_topology"]
    assert len(topology) >= 6
    assert all(not (node.backend_native_id or "").startswith("Face") for node in topology)
    assert {artifact.kind.value for artifact in response.artifacts} == {
        "native_model", "neutral_model", "preview_model"
    }
    for artifact in response.artifacts:
        artifact_path = tmp_path / artifact.filename
        payload = artifact_path.read_bytes()
        assert len(payload) == artifact.byte_length
        assert hashlib.sha256(payload).hexdigest() == artifact.content_sha256
        assert artifact.source_feature_ir_sha256 == feature_ir_manifest(
            document
        ).content_sha256
    csg_artifact_ids = {
        node.id for node in csg.nodes if node.kind == "artifact"
    }
    assert csg_artifact_ids == {item.id for item in response.artifacts}


def test_real_worker_returns_typed_refusal_for_unsupported_selector(tmp_path):
    try:
        executable = worker.discover_freecad_cmd()
    except worker.FreeCADWorkerUnavailable:
        pytest.skip("FreeCAD runtime is not installed")
    revision = run(
        MOTOR / "sketch.png", MOTOR / "motor_datasheet.pdf",
        MOTOR / "requirement.txt", backend_override="fixture",
    ).latest
    document = compile_feature_ir(revision.intent_graph)
    chamfer = document.features[-1]
    fillet = FilletFeature(
        id=chamfer.id,
        label=chamfer.label,
        intent_links=chamfer.intent_links,
        edges=chamfer.edges.model_copy(update={
            "selector": EdgeSetSelector.EXTERNAL_PERIMETER
        }),
        radius=chamfer.distance,
    )
    document = document.model_copy(update={
        "features": (*document.features[:-1], fillet)
    })
    build_request = BuildRequest(
        request_id="build:freecad:motor:unsupported",
        backend_id="freecad",
        feature_ir=document,
        feature_ir_manifest=feature_ir_manifest(document),
    )
    response = worker.run_freecad_worker(
        FreeCADWorkerRequest(
            request_id="worker:build:motor:unsupported",
            operation="build",
            build_request=build_request,
            artifact_root=str(tmp_path.resolve()),
        ),
        executable=executable,
        timeout_seconds=60,
    )
    assert response.status is WorkerStatus.UNSUPPORTED
    assert response.diagnostics[0].code == "unsupported_capability"
