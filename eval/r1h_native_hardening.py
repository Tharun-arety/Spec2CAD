"""Versioned R1H multi-family, dual-backend hardening benchmark."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spec2cad.backends import BuildRequest, BuildStatus
from spec2cad.backends.cadquery_adapter import CadQueryAdapter
from spec2cad.backends.freecad_adapter import FreeCADAdapter
from spec2cad.backends.freecad_worker import discover_freecad_cmd
from spec2cad.cad_state_serialization import csg_manifest
from spec2cad.feature_compiler import compile_feature_ir
from spec2cad.feature_serialization import feature_ir_manifest
from spec2cad.fusion.graph_builder import build_intent_graph
from spec2cad.pipeline import repair, run
from spec2cad.schemas.evidence import (
    Authority, Evidence, EvidenceKind, EvidenceSet, ExtractionMethod,
    SemanticTarget, SourceModality, SourceRef,
)
from spec2cad.schemas.feature_ir import EdgeSetSelector, FilletFeature


REPORT = ROOT / "eval/r1h_native_hardening_report.json"


def _cylindrical(name: str, wall: float | None):
    source = SourceRef(file=f"{name}.txt", modality=SourceModality.REQUIREMENT_TEXT)
    facts = [
        (SemanticTarget.PART_TYPE, EvidenceKind.FEATURE_CALLOUT, name, None),
        (SemanticTarget.OUTER_DIAMETER, EvidenceKind.DIAMETER, 28.0, "mm"),
        (SemanticTarget.BODY_LENGTH, EvidenceKind.LINEAR_DIMENSION, 36.0, "mm"),
    ]
    if wall is not None:
        facts.append((
            SemanticTarget.WALL_THICKNESS, EvidenceKind.LINEAR_DIMENSION, wall, "mm"
        ))
    evidence = EvidenceSet(items=[
        Evidence(
            id=f"ev_{name}_{target.value}", entity=name, kind=kind,
            target=target, value=value, unit=unit, source=source,
            extraction_method=ExtractionMethod.RULE_PARSER,
            confidence=1.0, authority=Authority.DEFINITIVE,
            is_explicit_annotation=True,
        )
        for target, kind, value, unit in facts
    ])
    graph, _ = build_intent_graph(evidence, part_name=name)
    return compile_feature_ir(graph)


def _families():
    motor_root = ROOT / "examples/motor_adapter"
    motor = run(
        motor_root / "sketch.png", motor_root / "motor_datasheet.pdf",
        motor_root / "requirement.txt", backend_override="fixture",
    )
    motor = repair(motor, "widen_to_recommended", approved_by="r1h-benchmark").latest
    bracket = run(
        requirement=ROOT / "examples/mounting_bracket/requirement.txt"
    ).latest
    return {
        "interface_plate": compile_feature_ir(motor.intent_graph),
        "slotted_bracket": compile_feature_ir(bracket.intent_graph),
        "solid_cylinder": _cylindrical("solid_cylinder", None),
        "hollow_tube": _cylindrical("hollow_tube", 3.0),
    }


def _request(backend: str, name: str, document, iteration: int):
    return BuildRequest(
        request_id=f"benchmark:r1h:{backend}:{name}:{iteration}",
        backend_id=backend, feature_ir=document,
        feature_ir_manifest=feature_ir_manifest(document),
    )


def _timed_build(adapter, request):
    started = perf_counter()
    result = adapter.build(request)
    return result, round(perf_counter() - started, 6)


def run_benchmark(artifact_root: Path) -> dict:
    cadquery = CadQueryAdapter(artifact_root / "cadquery")
    freecad = FreeCADAdapter(
        artifact_root / "freecad", executable=discover_freecad_cmd()
    )
    records = []
    initial_bracket = None
    bracket_document = None
    for name, document in _families().items():
        backend_records = {}
        for backend_name, adapter in (("cadquery", cadquery), ("freecad", freecad)):
            results = []
            for iteration in (1, 2):
                result, seconds = _timed_build(
                    adapter, _request(backend_name, name, document, iteration)
                )
                semantic_sha256 = None
                if result.snapshot is not None:
                    graph = adapter.csg_for(result.snapshot).model_copy(update={
                        "build_request_id": "benchmark:r1h:normalized",
                        "nodes": tuple(
                            node for node in adapter.csg_for(result.snapshot).nodes
                            if node.kind != "artifact"
                        ),
                    })
                    semantic_sha256 = csg_manifest(graph).content_sha256
                results.append({
                    "status": result.status.value,
                    "seconds": seconds,
                    "csg_sha256": (
                        result.snapshot.state_graph_sha256 if result.snapshot else None
                    ),
                    "semantic_sha256": semantic_sha256,
                    "artifact_count": len(result.artifacts),
                })
                if name == "slotted_bracket" and backend_name == "freecad" and iteration == 1:
                    initial_bracket = result
                    bracket_document = document
            backend_records[backend_name] = {
                "runs": results,
                "expected_artifact_count": 0 if backend_name == "cadquery" else 3,
                "repeatable_csg": results[0]["csg_sha256"] == results[1]["csg_sha256"],
                "repeatable_semantics": (
                    results[0]["semantic_sha256"] == results[1]["semantic_sha256"]
                ),
                "failure_count": sum(item["status"] != "succeeded" for item in results),
            }
        records.append({"family": name, "backends": backend_records})

    count = next(
        item for item in bracket_document.parameters if item.name == "slot_count"
    )
    changed = count.model_copy(update={"value": count.value + 1})
    edited_document = bracket_document.model_copy(update={
        "parameters": tuple(
            changed if item.id == count.id else item
            for item in bracket_document.parameters
        )
    })
    started = perf_counter()
    edited = freecad.edit_parameter(
        initial_bracket.snapshot,
        _request("freecad", "slotted_bracket_edit", edited_document, 1),
        parameter_id=count.id, parameter_value=changed.value,
    )
    edit_seconds = round(perf_counter() - started, 6)
    before_graph = freecad.csg_for(initial_bracket.snapshot)
    after_graph = freecad.csg_for(edited.snapshot) if edited.snapshot else None
    before_curves = max(
        len(node.geometry_ids) for node in before_graph.nodes if node.kind == "sketch"
    )
    after_curves = max(
        len(node.geometry_ids) for node in after_graph.nodes if node.kind == "sketch"
    ) if after_graph else 0

    fillet = next(
        item for item in bracket_document.features if isinstance(item, FilletFeature)
    )
    invalid_fillet = fillet.model_copy(update={
        "edges": fillet.edges.model_copy(update={
            "selector": EdgeSetSelector.EXTERNAL_PERIMETER
        })
    })
    unsupported_document = bracket_document.model_copy(update={
        "features": tuple(
            invalid_fillet if item.id == fillet.id else item
            for item in bracket_document.features
        )
    })
    refusals = {}
    for backend_name, adapter in (("cadquery", cadquery), ("freecad", freecad)):
        refused, seconds = _timed_build(
            adapter, _request(backend_name, "unsupported_selector", unsupported_document, 1)
        )
        refusals[backend_name] = {
            "status": refused.status.value,
            "seconds": seconds,
            "diagnostic_codes": [item.code.value for item in refused.diagnostics],
        }

    all_passed = all(
        run["status"] == "succeeded"
        and run["artifact_count"] == backend["expected_artifact_count"]
        for record in records
        for backend in record["backends"].values()
        for run in backend["runs"]
    ) and all(
        backend["repeatable_semantics"] and backend["failure_count"] == 0
        for record in records for backend in record["backends"].values()
    ) and (
        edited.status is BuildStatus.SUCCEEDED
        and after_curves == before_curves + 4
        and all(item["status"] == "unsupported" for item in refusals.values())
    )
    return {
        "schema_version": "1.0.0",
        "benchmark": "B.R1H",
        "scope": "bounded primitive and feature vocabulary; not universal CAD",
        "freecad_version": freecad.descriptor.backend_version,
        "families": records,
        "topology_edit": {
            "parameter_id": count.id, "before": count.value, "after": changed.value,
            "before_curves": before_curves, "after_curves": after_curves,
            "seconds": edit_seconds, "status": edited.status.value,
        },
        "typed_refusals": refusals,
        "all_passed": all_passed,
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cadaico-r1h-") as directory:
        report = run_benchmark(Path(directory))
    REPORT.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"B.R1H: {'PASS' if report['all_passed'] else 'FAIL'} -> {REPORT}")
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
