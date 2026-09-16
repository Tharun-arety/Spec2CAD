"""Execute deterministic benchmark B.R1 against the two real CAD backends."""

from __future__ import annotations

import json
import hashlib
import tempfile
from pathlib import Path

from spec2cad.backends import (
    ArtifactKind,
    BuildRequest,
    BuildStatus,
    OperationStatus,
    ReimportVerificationRequest,
)
from spec2cad.backends.cadquery_adapter import CadQueryAdapter
from spec2cad.backends.freecad_adapter import FreeCADAdapter
from spec2cad.backends.freecad_worker import discover_freecad_cmd
from spec2cad.cad_state_serialization import csg_manifest
from spec2cad.feature_compiler import compile_feature_ir
from spec2cad.feature_serialization import feature_ir_manifest
from spec2cad.pipeline import repair, run
from spec2cad.reconciliation import (
    ReconciliationClassification,
    classify_reconciliation,
    extract_motor_observations,
    observe_requirement_predicates,
    reconcile_motor_geometry,
    reconcile_predicates,
)
from spec2cad.validation.gate import evaluate_release


ROOT = Path(__file__).resolve().parents[1]
MOTOR = ROOT / "examples" / "motor_adapter"
MANIFEST = MOTOR / "r1_benchmark_manifest.json"
REPORT = ROOT / "eval" / "r1_native_foundation_report.json"


def _request(backend, feature_ir, revision, purpose="benchmark"):
    return BuildRequest(
        request_id=f"build:{backend}:{purpose}:r{revision}",
        backend_id=backend,
        feature_ir=feature_ir,
        feature_ir_manifest=feature_ir_manifest(feature_ir),
    )


def _native_traceability(graph):
    critical = {
        node.id for node in graph.nodes if node.kind == "native_feature"
    }
    feature_links = {
        item.source.id for item in graph.relationships
        if item.source.namespace.value == "cad_state_graph"
        and item.target.namespace.value == "feature_ir"
        and item.kind.value == "realizes_feature_ir"
    }
    intent_links = {
        item.source.id for item in graph.relationships
        if item.source.namespace.value == "cad_state_graph"
        and item.target.namespace.value == "engineering_intent_graph"
        and item.kind.value == "realizes_intent"
    }
    return {
        "critical_feature_ids": sorted(critical),
        "all_trace_to_feature_ir": critical <= feature_links,
        "all_trace_to_eig": critical <= intent_links,
    }


def run_benchmark(artifact_root: Path) -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "1.0.0":
        raise ValueError("unsupported B.R1 manifest schema")
    pipeline = run(
        MOTOR / "sketch.png", MOTOR / "motor_datasheet.pdf",
        MOTOR / "requirement.txt", backend_override="fixture", create_messages=False,
    )
    pipeline = repair(
        pipeline, "widen_to_recommended", approved_by="benchmark-b-r1"
    )
    v1, v2 = pipeline.revisions
    fir1, fir2 = compile_feature_ir(v1.intent_graph), compile_feature_ir(v2.intent_graph)
    cadquery = CadQueryAdapter()
    freecad = FreeCADAdapter(artifact_root, executable=discover_freecad_cmd())

    cq1 = cadquery.build(_request("cadquery", fir1, 1))
    cq2 = cadquery.build(_request("cadquery", fir2, 2))
    fc1 = freecad.build(_request("freecad", fir1, 1))
    changed_parameter = next(
        after for before, after in zip(fir1.parameters, fir2.parameters)
        if before.value != after.value
    )
    fc2 = freecad.edit_parameter(
        fc1.snapshot, _request("freecad", fir2, 2, "native-edit"),
        parameter_id=changed_parameter.id, parameter_value=changed_parameter.value,
    )
    if any(item.status is not BuildStatus.SUCCEEDED for item in (cq1, cq2, fc1, fc2)):
        raise RuntimeError("B.R1 backend build failed")

    revisions = []
    classified_by_revision = {}
    for revision, feature_ir, cq_build, fc_build in (
        (v1, fir1, cq1, fc1), (v2, fir2, cq2, fc2),
    ):
        cq_graph = cadquery.csg_for(cq_build.snapshot)
        fc_graph = freecad.csg_for(fc_build.snapshot)
        cq_observations = extract_motor_observations(
            revision.intent_graph, feature_ir, cq_graph
        )
        fc_observations = extract_motor_observations(
            revision.intent_graph, feature_ir, fc_graph
        )
        geometry = reconcile_motor_geometry(cq_observations, fc_observations)
        predicates = reconcile_predicates(
            observe_requirement_predicates(cq_observations, revision.intent_graph),
            observe_requirement_predicates(fc_observations, revision.intent_graph),
            feature_ir_sha256=feature_ir_manifest(feature_ir).content_sha256,
        )
        classified = classify_reconciliation(
            cq_observations, fc_observations, geometry, predicates
        )
        classified_by_revision[revision.revision] = classified
        decision = evaluate_release(
            revision.intent, revision.measured,
            governing_reconciliation=classified,
        )
        sketches = [node for node in fc_graph.nodes if node.kind == "sketch"]
        diagnostics = [node for node in fc_graph.nodes if node.kind == "diagnostic"]
        native_features = [node for node in fc_graph.nodes if node.kind == "native_feature"]
        revisions.append({
            "revision": revision.revision,
            "eig_revision": revision.intent_graph.revision,
            "feature_ir_sha256": feature_ir_manifest(feature_ir).content_sha256,
            "cadquery_csg_sha256": csg_manifest(cq_graph).content_sha256,
            "freecad_csg_sha256": csg_manifest(fc_graph).content_sha256,
            "geometry_checks": [item.model_dump(mode="json") for item in geometry.checks],
            "predicate_checks": [item.model_dump(mode="json") for item in predicates.checks],
            "classification": classified.classification.value,
            "release": decision.status.value,
            "native_traceability": _native_traceability(fc_graph),
            "freecad": {
                "sketch_degrees_of_freedom": {
                    item.label: item.degrees_of_freedom for item in sketches
                },
                "recompute_errors": [
                    item.message for item in diagnostics if item.severity.value == "error"
                ],
                "critical_feature_names": [item.backend_native_id for item in native_features],
                "artifacts": [item.model_dump(mode="json") for item in fc_build.artifacts],
            },
        })

    neutral = next(
        item for item in fc2.artifacts if item.kind is ArtifactKind.NEUTRAL_MODEL
    )
    reimport = freecad.verify_reimport(ReimportVerificationRequest(
        request_id="verify:freecad:benchmark:r2",
        artifact=neutral,
        expected_feature_ir_sha256=feature_ir_manifest(fir2).content_sha256,
    ))
    all_passed = all((
        all(item["classification"] == ReconciliationClassification.CONSISTENT.value
            for item in revisions),
        revisions[0]["release"] == "blocked",
        revisions[1]["release"] == "authorised",
        all(check["left_outcome"] == check["right_outcome"]
            for item in revisions for check in item["predicate_checks"]),
        all(check["consistent"] for item in revisions for check in item["geometry_checks"]),
        all(item["native_traceability"]["all_trace_to_feature_ir"] for item in revisions),
        all(item["native_traceability"]["all_trace_to_eig"] for item in revisions),
        all(value == 0 for item in revisions
            for value in item["freecad"]["sketch_degrees_of_freedom"].values()),
        all(not item["freecad"]["recompute_errors"] for item in revisions),
        all(all(item["freecad"]["critical_feature_names"]) for item in revisions),
        reimport.status is OperationStatus.SUCCEEDED,
        reimport.reimport_verified is True,
    ))
    return {
        "schema_version": "1.0.0",
        "benchmark_case": manifest["case_id"],
        "manifest": str(MANIFEST.relative_to(ROOT)).replace("\\", "/"),
        "inputs_sha256": {
            name: hashlib.sha256((MOTOR / name).read_bytes()).hexdigest()
            for name in manifest["inputs"]
        },
        "freecad_version": freecad.descriptor.backend_version,
        "native_parameter_edit": {
            "source_revision": 1, "result_revision": 2,
            "parameter_id": changed_parameter.id,
            "value": changed_parameter.value,
            "recomputed": fc2.snapshot.recompute_state.value == "succeeded",
            "updated_csg": fc2.snapshot.state_graph_sha256 != fc1.snapshot.state_graph_sha256,
        },
        "step_round_trip_verified": reimport.reimport_verified is True,
        "revisions": revisions,
        "all_passed": all_passed,
    }


def main():
    with tempfile.TemporaryDirectory(prefix="cadaico-b-r1-") as directory:
        report = run_benchmark(Path(directory))
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"B.R1: {'PASS' if report['all_passed'] else 'FAIL'} -> {REPORT}")
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
