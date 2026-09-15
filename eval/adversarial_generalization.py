"""Adversarial, stage-separated generalization evaluation for Spec2CAD.

This module is an external harness. It does not register features, change the
planner, or teach the pipeline any part name. Cases vary only evidence and use
the public graph/compiler/executor/validation seams. Faults are injected by
temporarily replacing an executor handler or a symbolic report in this process.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import spec2cad.cad.executor as cad_executor
from spec2cad.cad.compiler import compile_design, parameter_table
from spec2cad.cad.executor import execute, export_step
from spec2cad.extractors.text import extract_requirement
from spec2cad.fusion.graph_builder import build_intent_graph, project_to_design_intent
from spec2cad.pipeline import evaluate_revision, repair, run, verify_exported_step
from spec2cad.schemas.cad_ir import BoxOp, lit, resolve
from spec2cad.schemas.evidence import EvidenceSet
from spec2cad.schemas.report import CheckStatus, ConflictClass, Report
from spec2cad.store import Store
from spec2cad.validation import measure as M
from spec2cad.validation.dimensions import run_dimensions
from spec2cad.validation.predicate_compiler import compile_requirement_predicates
from spec2cad.validation.requirements import compare_prediction_to_measurement

ROOT = Path(__file__).resolve().parents[1]
MOTOR = ROOT / "examples" / "motor_adapter"
BRACKET = ROOT / "examples" / "mounting_bracket"


class Level(str, Enum):
    REGRESSION = "regression"
    PERTURBATION = "perturbation"
    UNSEEN_COMPOSITION = "unseen_composition"
    FAULT_INJECTION = "fault_injection"


class Metric(str, Enum):
    GRAPH_CONSTRUCTION = "graph_construction"
    FEATURE_PLANNING = "feature_planning"
    CAD_EXECUTION = "cad_execution"
    GEOMETRIC_VALIDATION = "geometric_validation"
    REQUIREMENT_VALIDATION = "requirement_validation"
    CONFLICT_REFUSAL = "conflict_refusal_correctness"
    STEP_ROUND_TRIP = "step_round_trip"


@dataclass(frozen=True)
class Outcome:
    case: str
    level: str
    metric: str
    assertion: str
    expected: Any
    actual: Any
    passed: bool
    correct_refusal: bool = False
    note: str = ""


@dataclass(frozen=True)
class MetricSummary:
    metric: str
    passed: int
    total: int

    @property
    def rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


@dataclass
class GeneralizationReport:
    outcomes: list[Outcome] = field(default_factory=list)

    def check(
        self,
        *,
        case: str,
        level: Level,
        metric: Metric,
        assertion: str,
        expected: Any,
        actual: Any,
        tolerance: Optional[float] = None,
        correct_refusal: bool = False,
        note: str = "",
    ) -> bool:
        if (
            tolerance is not None
            and isinstance(expected, (int, float))
            and isinstance(actual, (int, float))
        ):
            passed = abs(float(expected) - float(actual)) <= tolerance
        else:
            passed = expected == actual
        self.outcomes.append(Outcome(
            case=case,
            level=level.value,
            metric=metric.value,
            assertion=assertion,
            expected=expected,
            actual=actual,
            passed=passed,
            correct_refusal=bool(correct_refusal and passed),
            note=note,
        ))
        return passed

    @property
    def all_passed(self) -> bool:
        return all(outcome.passed for outcome in self.outcomes)

    def summary_for(self, metric: Metric) -> MetricSummary:
        selected = [o for o in self.outcomes if o.metric == metric.value]
        return MetricSummary(
            metric=metric.value,
            passed=sum(o.passed for o in selected),
            total=len(selected),
        )

    @property
    def summaries(self) -> list[MetricSummary]:
        return [self.summary_for(metric) for metric in Metric]

    @property
    def correct_refusals(self) -> int:
        return len({outcome.case for outcome in self.outcomes if outcome.correct_refusal})

    def to_json(self) -> dict:
        return {
            "all_passed": self.all_passed,
            "correct_refusals": self.correct_refusals,
            "metrics": [
                {**asdict(summary), "rate": summary.rate}
                for summary in self.summaries
            ],
            "outcomes": [asdict(outcome) for outcome in self.outcomes],
        }


@dataclass(frozen=True)
class EvaluatedCase:
    evidence: EvidenceSet
    graph: Any
    intent: Any
    revision: Any


def _evaluate_text(text: str, *, part_name: str) -> EvaluatedCase:
    evidence = EvidenceSet(
        items=extract_requirement(text, source_name=f"{part_name}.txt"),
        backend_used="deterministic requirement parser",
    )
    graph, _ = build_intent_graph(evidence, part_name=part_name)
    intent = project_to_design_intent(graph)
    return EvaluatedCase(evidence, graph, intent, evaluate_revision(intent, graph))


def _prefix_evidence(items, prefix: str, filename: str):
    return [
        item.model_copy(update={
            "id": f"{prefix}_{item.id}",
            "source": item.source.model_copy(update={"file": filename}),
        })
        for item in items
    ]


def _evaluate_contradiction() -> EvaluatedCase:
    common_a = (
        "A plate 70 mm wide and 50 mm high, made from 6 mm aluminium, with a "
        "25 mm diameter central opening and a 50 mm by 30 mm mounting pattern "
        "of four normal-clearance holes for M5 screws. Add 4 mm corner fillets. "
        "Maintain at least 5 mm from every hole edge."
    )
    common_b = common_a.replace("70 mm wide", "74 mm wide")
    a = _prefix_evidence(extract_requirement(common_a, "source_a.txt"), "a", "source_a.txt")
    b = _prefix_evidence(extract_requirement(common_b, "source_b.txt"), "b", "source_b.txt")
    evidence = EvidenceSet(items=[*a, *b], backend_used="two explicit text sources")
    graph, _ = build_intent_graph(evidence, part_name="contradictory_flange")
    intent = project_to_design_intent(graph)
    return EvaluatedCase(evidence, graph, intent, evaluate_revision(intent, graph))


FLANGE_TEXT = (
    "Create a rectangular flange from a 70 x 50 x 6 mm aluminium plate. "
    "Add a 25 mm diameter central opening and four Ø5 mm through holes on a "
    "50 x 30 mm mounting pattern. Add 4 mm corner fillets. Maintain at least "
    "5 mm from every hole edge."
)


def _record_graph(report: GeneralizationReport, case: str, level: Level, evaluated) -> None:
    report.check(
        case=case, level=level, metric=Metric.GRAPH_CONSTRUCTION,
        assertion="graph has no dangling relationships",
        expected=[], actual=evaluated.graph.validate_edges(),
    )


def _record_execution(report: GeneralizationReport, case: str, level: Level, revision) -> None:
    report.check(
        case=case, level=level, metric=Metric.CAD_EXECUTION,
        assertion="kernel produced one valid solid",
        expected=(True, 1),
        actual=(
            bool(revision.execution and revision.execution.shape.isValid()),
            len(revision.execution.shape.Solids()) if revision.execution else 0,
        ),
    )
    report.check(
        case=case, level=level, metric=Metric.CAD_EXECUTION,
        assertion="every planned operation changed geometry",
        expected=True,
        actual=bool(
            revision.execution
            and all(not item.no_op for item in revision.execution.measurements)
        ),
    )


def _record_measured_passes(
    report: GeneralizationReport, case: str, level: Level, revision
) -> None:
    geometric = revision.measured[:2]
    report.check(
        case=case, level=level, metric=Metric.GEOMETRIC_VALIDATION,
        assertion="topology and dimensional reports pass",
        expected=True,
        actual=all(item.passed for item in geometric),
    )


def _round_trip(
    report: GeneralizationReport, case: str, level: Level, revision
) -> None:
    with tempfile.TemporaryDirectory(prefix="spec2cad-step-") as directory:
        path = export_step(revision.execution, Path(directory) / f"{case}.step")
        reports = verify_exported_step(path, revision.intent, revision.intent_graph)
        report.check(
            case=case, level=level, metric=Metric.STEP_ROUND_TRIP,
            assertion="exported STEP independently re-imports and revalidates",
            expected=True, actual=all(item.passed for item in reports),
        )


def run_suite() -> GeneralizationReport:
    report = GeneralizationReport()

    # ------------------------------------------------------------------
    # 1. Regression
    # ------------------------------------------------------------------
    motor = run(
        MOTOR / "sketch.png", MOTOR / "motor_datasheet.pdf",
        MOTOR / "requirement.txt", backend_override="fixture",
    )
    motor_v1 = motor.latest
    _record_graph(report, "motor_adapter", Level.REGRESSION,
                  EvaluatedCase(motor.evidence, motor_v1.intent_graph, motor_v1.intent, motor_v1))
    report.check(
        case="motor_adapter", level=Level.REGRESSION,
        metric=Metric.FEATURE_PLANNING, assertion="original feature sequence is stable",
        expected=["base_plate", "shaft_opening", "mounting_holes", "external_chamfers"],
        actual=[operation.id for operation in motor_v1.program.operations],
    )
    _record_execution(report, "motor_adapter", Level.REGRESSION, motor_v1)
    report.check(
        case="motor_adapter", level=Level.REGRESSION,
        metric=Metric.CONFLICT_REFUSAL,
        assertion="known unsatisfiable v1 is correctly refused",
        expected=False, actual=motor_v1.released, correct_refusal=True,
    )
    repaired_motor = repair(motor, "widen_to_recommended", approved_by="adversarial-eval")
    motor_v2 = repaired_motor.latest
    report.check(
        case="motor_adapter", level=Level.REGRESSION,
        metric=Metric.REQUIREMENT_VALIDATION,
        assertion="approved repair restores measured clearance",
        expected=5.3,
        actual=motor_v2.measured[-1].get("req_edge_clearance").measured_value,
        tolerance=1e-6,
    )
    _round_trip(report, "motor_adapter", Level.REGRESSION, motor_v2)

    bracket = run(requirement=BRACKET / "requirement.txt").latest
    _record_graph(report, "slotted_mounting_bracket", Level.REGRESSION,
                  EvaluatedCase(None, bracket.intent_graph, bracket.intent, bracket))
    report.check(
        case="slotted_mounting_bracket", level=Level.REGRESSION,
        metric=Metric.FEATURE_PLANNING, assertion="bracket feature sequence is stable",
        expected=["base_plate", "mounting_holes", "base_slots", "external_fillets"],
        actual=[operation.id for operation in bracket.program.operations],
    )
    _record_execution(report, "slotted_mounting_bracket", Level.REGRESSION, bracket)
    _record_measured_passes(report, "slotted_mounting_bracket", Level.REGRESSION, bracket)
    _round_trip(report, "slotted_mounting_bracket", Level.REGRESSION, bracket)

    # ------------------------------------------------------------------
    # 2. Perturbations
    # ------------------------------------------------------------------
    changed = _evaluate_text(
        "Create a 90 x 60 x 8 mm aluminium plate with a 30 mm diameter central "
        "opening and four Ø6 mm through holes on a 70 x 40 mm mounting pattern. "
        "Add 5 mm corner fillets. Maintain at least 5 mm from every hole edge.",
        part_name="changed_dimensions",
    )
    _record_graph(report, "changed_dimensions", Level.PERTURBATION, changed)
    report.check(
        case="changed_dimensions", level=Level.PERTURBATION,
        metric=Metric.FEATURE_PLANNING,
        assertion="dimension changes do not change feature composition",
        expected=["box", "hole", "rectangular_hole_pattern", "fillet"],
        actual=[operation.type for operation in changed.revision.program.operations],
    )
    _record_execution(report, "changed_dimensions", Level.PERTURBATION, changed.revision)
    _record_measured_passes(report, "changed_dimensions", Level.PERTURBATION, changed.revision)
    report.check(
        case="changed_dimensions", level=Level.PERTURBATION,
        metric=Metric.GEOMETRIC_VALIDATION, assertion="changed envelope is measured",
        expected=(90.0, 60.0, 8.0),
        actual=tuple(asdict(M.plate_extents(changed.revision.execution.shape)).values()),
    )

    missing = _evaluate_text(
        "Create a plate 70 mm wide and 50 mm high with four Ø5 mm through holes "
        "on a 50 x 30 mm mounting pattern.",
        part_name="missing_thickness",
    )
    _record_graph(report, "missing_dimensions", Level.PERTURBATION, missing)
    report.check(
        case="missing_dimensions", level=Level.PERTURBATION,
        metric=Metric.FEATURE_PLANNING,
        assertion="planner refuses an incomplete base solid",
        expected=(True, True, False),
        actual=(
            bool(missing.revision.build_error),
            "plate_thickness" in missing.revision.decision.responsible_parameters,
            missing.revision.released,
        ),
    )
    report.check(
        case="missing_dimensions", level=Level.PERTURBATION,
        metric=Metric.CONFLICT_REFUSAL,
        assertion="missing evidence blocks release",
        expected=False, actual=missing.revision.released, correct_refusal=True,
    )

    contradiction = _evaluate_contradiction()
    _record_graph(report, "contradictory_sources", Level.PERTURBATION, contradiction)
    width = contradiction.intent.param("plate_width")
    report.check(
        case="contradictory_sources", level=Level.PERTURBATION,
        metric=Metric.CONFLICT_REFUSAL,
        assertion="explicit disagreement remains unresolved",
        expected=("adjudication_required", 2),
        actual=(width.status.value, len(width.competing_values)),
    )
    report.check(
        case="contradictory_sources", level=Level.PERTURBATION,
        metric=Metric.CONFLICT_REFUSAL,
        assertion="unadjudicated evidence blocks release as source conflict",
        expected=(False, "source_conflict"),
        actual=(
            contradiction.revision.released,
            next(
                item.conflict_class.value for item in contradiction.revision.decision.blocking
                if item.conflict_class is ConflictClass.SOURCE
            ),
        ),
        correct_refusal=True,
    )

    inches = _evaluate_text(
        "Create a 2.7559055 x 1.9685039 x 0.2362205 in aluminium plate with a "
        "0.984252 in diameter central opening and four Ø0.1968504 in through holes "
        "on a 1.9685039 x 1.1811024 in mounting pattern. Add 0.1574803 in corner "
        "fillets. Maintain at least 0.1968504 in from every hole edge.",
        part_name="inch_normalized_flange",
    )
    _record_graph(report, "inch_mm_normalization", Level.PERTURBATION, inches)
    report.check(
        case="inch_mm_normalization", level=Level.PERTURBATION,
        metric=Metric.GRAPH_CONSTRUCTION,
        assertion="inch evidence is normalized into millimetres",
        expected=(70.0, 50.0, 6.0, 25.0, 5.0, 4.0),
        actual=tuple(
            inches.intent.value_of(name) for name in (
                "plate_width", "plate_height", "plate_thickness",
                "shaft_opening_diameter", "mounting_hole_diameter", "external_fillet",
            )
        ),
        tolerance=1e-3,
    )
    _record_execution(report, "inch_mm_normalization", Level.PERTURBATION, inches.revision)
    _record_measured_passes(report, "inch_mm_normalization", Level.PERTURBATION, inches.revision)

    removed = _evaluate_text(
        "Create a 70 x 50 x 6 mm aluminium plate with four Ø5 mm through holes "
        "on a 50 x 30 mm mounting pattern.",
        part_name="removed_optional_features",
    )
    _record_graph(report, "removed_features", Level.PERTURBATION, removed)
    report.check(
        case="removed_features", level=Level.PERTURBATION,
        metric=Metric.FEATURE_PLANNING,
        assertion="absent optional features are not invented",
        expected=["base_plate", "mounting_holes"],
        actual=[operation.id for operation in removed.revision.program.operations],
    )
    _record_execution(report, "removed_features", Level.PERTURBATION, removed.revision)
    _record_measured_passes(report, "removed_features", Level.PERTURBATION, removed.revision)

    reordered_text = (
        "Maintain at least 5 mm from every hole edge. Add 4 mm corner fillets. "
        "Place four Ø5 mm through holes on a 50 x 30 mm mounting pattern. "
        "Add a 25 mm diameter central opening. Create a rectangular flange from "
        "a 70 x 50 x 6 mm aluminium plate."
    )
    ordered = _evaluate_text(FLANGE_TEXT, part_name="reordered_features")
    reordered = _evaluate_text(reordered_text, part_name="reordered_features")
    _record_graph(report, "reordered_features", Level.PERTURBATION, reordered)
    report.check(
        case="reordered_features", level=Level.PERTURBATION,
        metric=Metric.FEATURE_PLANNING,
        assertion="source sentence order does not change CAD IR",
        expected=ordered.revision.program.model_dump(),
        actual=reordered.revision.program.model_dump(),
    )

    impossible = _evaluate_text(
        "Create a 50 x 40 x 6 mm aluminium plate with four Ø5 mm through holes "
        "on a 44 x 34 mm mounting pattern. Maintain at least 5 mm from every "
        "hole edge.",
        part_name="unsatisfiable_clearance",
    )
    _record_graph(report, "unsatisfiable_requirement", Level.PERTURBATION, impossible)
    _record_execution(report, "unsatisfiable_requirement", Level.PERTURBATION,
                      impossible.revision)
    requirement = impossible.revision.measured[-1].get("req_edge_clearance")
    report.check(
        case="unsatisfiable_requirement", level=Level.PERTURBATION,
        metric=Metric.REQUIREMENT_VALIDATION,
        assertion="unsatisfiable clearance is measured rather than guessed",
        expected=("fail", 0.5, "constraint_conflict"),
        actual=(
            requirement.status.value, requirement.measured_value,
            requirement.conflict_class.value,
        ),
    )
    report.check(
        case="unsatisfiable_requirement", level=Level.PERTURBATION,
        metric=Metric.CONFLICT_REFUSAL,
        assertion="measured hard-requirement failure blocks release",
        expected=False, actual=impossible.revision.released, correct_refusal=True,
    )

    # ------------------------------------------------------------------
    # 3. Unseen composition: existing nodes/features only
    # ------------------------------------------------------------------
    flange = _evaluate_text(FLANGE_TEXT, part_name="rectangular_flange")
    _record_graph(report, "unseen_rectangular_flange", Level.UNSEEN_COMPOSITION, flange)
    report.check(
        case="unseen_rectangular_flange", level=Level.UNSEEN_COMPOSITION,
        metric=Metric.FEATURE_PLANNING,
        assertion="existing features compose the unseen flange",
        expected=["box", "hole", "rectangular_hole_pattern", "fillet"],
        actual=[operation.type for operation in flange.revision.program.operations],
    )
    renamed_nodes = [
        node.model_copy(update={"name": "opaque_part_name", "label": "opaque_part_name"})
        if getattr(getattr(node, "kind", None), "value", None) == "part" else node
        for node in flange.graph.nodes
    ]
    renamed_graph = flange.graph.model_copy(update={"nodes": renamed_nodes})
    report.check(
        case="unseen_rectangular_flange", level=Level.UNSEEN_COMPOSITION,
        metric=Metric.FEATURE_PLANNING,
        assertion="renaming the part leaves every operation unchanged",
        expected=[op.model_dump() for op in flange.revision.program.operations],
        actual=[op.model_dump() for op in compile_design(renamed_graph).operations],
    )
    _record_execution(report, "unseen_rectangular_flange", Level.UNSEEN_COMPOSITION,
                      flange.revision)
    _record_measured_passes(report, "unseen_rectangular_flange",
                            Level.UNSEEN_COMPOSITION, flange.revision)
    flange_checks = {item.id: item for item in flange.revision.all_checks()}
    report.check(
        case="unseen_rectangular_flange", level=Level.UNSEEN_COMPOSITION,
        metric=Metric.GEOMETRIC_VALIDATION,
        assertion="central and mounting openings plus R4 fillets are measured",
        expected=(25.0, 5.0, 50.0, 30.0, 4),
        actual=(
            flange_checks["dim_shaft_opening"].measured_value,
            flange_checks["dim_hole_diameter"].measured_value,
            flange_checks["dim_hole_spacing_x"].measured_value,
            flange_checks["dim_hole_spacing_y"].measured_value,
            int(flange_checks["dim_external_fillet"].measured_value),
        ),
    )
    predicate_program = compile_requirement_predicates(flange.graph)
    flange_requirement = flange.revision.measured[-1].get("req_edge_clearance")
    report.check(
        case="unseen_rectangular_flange", level=Level.UNSEEN_COMPOSITION,
        metric=Metric.REQUIREMENT_VALIDATION,
        assertion="graph relation compiles and measures the >=5 mm predicate",
        expected=(1, "pass", 7.5),
        actual=(
            len(predicate_program.predicates), flange_requirement.status.value,
            flange_requirement.measured_value,
        ),
    )
    _round_trip(report, "unseen_rectangular_flange", Level.UNSEEN_COMPOSITION,
                flange.revision)

    # ------------------------------------------------------------------
    # Fault injection
    # ------------------------------------------------------------------
    original_box_handler = cad_executor.HANDLERS[BoxOp]

    def wrong_width_handler(workplane, operation, context):
        wrong_width = resolve(operation.width, context.values) - 1.0
        return original_box_handler(
            workplane, operation.model_copy(update={"width": lit(wrong_width)}), context
        )

    cad_executor.HANDLERS[BoxOp] = wrong_width_handler
    try:
        faulty_execution = execute(
            flange.revision.program, parameter_table(flange.intent)
        )
    finally:
        cad_executor.HANDLERS[BoxOp] = original_box_handler
    faulty_dimensions = run_dimensions(faulty_execution.shape, flange.intent)
    caught = faulty_dimensions.get("dim_plate_width")
    report.check(
        case="wrong_executor_dimension", level=Level.FAULT_INJECTION,
        metric=Metric.GEOMETRIC_VALIDATION,
        assertion="B-Rep validation catches executor width corruption",
        expected=("fail", 69.0, "execution"),
        actual=(
            caught.status.value, caught.measured_value,
            caught.conflict_class.value,
        ),
    )

    symbolic_checks = [
        item.model_copy(update={"measured_value": item.measured_value - 1.0})
        if item.id == "pre_edge_clearance_x" else item
        for item in flange.revision.preflight.checks
    ]
    faulty_symbolic = Report(
        stage=flange.revision.preflight.stage,
        design_revision=flange.intent.revision,
        checks=symbolic_checks,
    )
    inconsistency = compare_prediction_to_measurement(
        faulty_symbolic, flange.revision.measured[-1]
    )[0]
    report.check(
        case="symbolic_measurement_disagreement", level=Level.FAULT_INJECTION,
        metric=Metric.REQUIREMENT_VALIDATION,
        assertion="symbolic disagreement is a pipeline inconsistency",
        expected=("fail", "execution", "pass"),
        actual=(
            inconsistency.status.value,
            inconsistency.conflict_class.value,
            flange_requirement.status.value,
        ),
        note="The measured design remains valid; only the cross-check fails.",
    )

    with tempfile.TemporaryDirectory(prefix="spec2cad-store-") as directory:
        store = Store(Path(directory) / "suite.db")
        run_id = store.create_run(
            ROOT / "examples", flange.evidence,
            "deterministic adversarial suite",
        )
        store.save_revision(run_id, flange.intent, {
            "intent_graph": flange.graph.model_dump(mode="json"),
        })
        restored_graph = store.get_intent_graph(run_id, flange.intent.revision)
        restored_program = compile_design(restored_graph)
        restored_execution = execute(restored_program, parameter_table(flange.intent))
        report.check(
            case="persisted_graph_replay", level=Level.FAULT_INJECTION,
            metric=Metric.GRAPH_CONSTRUCTION,
            assertion="persisted Engineering Intent Graph reloads equivalently",
            expected=flange.graph.model_dump(mode="json"),
            actual=restored_graph.model_dump(mode="json"),
        )
        report.check(
            case="persisted_graph_replay", level=Level.FAULT_INJECTION,
            metric=Metric.FEATURE_PLANNING,
            assertion="reloaded graph reproduces equivalent CAD IR",
            expected=flange.revision.program.model_dump(),
            actual=restored_program.model_dump(),
        )
        original_extents = M.plate_extents(flange.revision.execution.shape)
        restored_extents = M.plate_extents(restored_execution.shape)
        report.check(
            case="persisted_graph_replay", level=Level.FAULT_INJECTION,
            metric=Metric.CAD_EXECUTION,
            assertion="reloaded graph reproduces equivalent measured geometry",
            expected=(
                original_extents.width, original_extents.height,
                original_extents.thickness, round(flange.revision.execution.shape.Volume(), 6),
            ),
            actual=(
                restored_extents.width, restored_extents.height,
                restored_extents.thickness, round(restored_execution.shape.Volume(), 6),
            ),
        )

    return report


def write_reports(
    report: GeneralizationReport,
    markdown_path: Path,
    json_path: Path,
) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report.to_json(), indent=2), encoding="utf-8")

    lines = [
        "# Adversarial generalization evaluation",
        "",
        "The feature planner and CAD vocabulary are treated as frozen. Cases vary",
        "evidence or inject faults only through public seams. Expected refusal for",
        "missing, contradictory, or geometrically impossible input counts as correct.",
        "",
        "## Metrics by pipeline stage",
        "",
        "| Stage | Passed | Total | Rate |",
        "|---|---:|---:|---:|",
    ]
    for summary in report.summaries:
        lines.append(
            f"| {summary.metric.replace('_', ' ')} | {summary.passed} | "
            f"{summary.total} | {summary.rate:.0%} |"
        )
    lines += [
        "",
        f"Correct refusals: **{report.correct_refusals}**",
        "",
        "## Outcomes",
        "",
        "| Level | Case | Stage | Assertion | Result | Refusal |",
        "|---|---|---|---|---|---|",
    ]
    for outcome in report.outcomes:
        lines.append(
            f"| {outcome.level} | {outcome.case} | {outcome.metric} | "
            f"{outcome.assertion} | {'PASS' if outcome.passed else '**FAIL**'} | "
            f"{'correct' if outcome.correct_refusal else '—'} |"
        )
    failures = [outcome for outcome in report.outcomes if not outcome.passed]
    lines += ["", "## Failure details", ""]
    if not failures:
        lines.append("No failed assertions.")
    else:
        for failure in failures:
            lines.append(
                f"- **{failure.case} / {failure.assertion}:** expected "
                f"`{failure.expected}`, got `{failure.actual}`. {failure.note}"
            )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
