"""End-to-end orchestration.

The four stages the architecture insists on staying separate:

    preflight  ->  diagnostic generation  ->  measured validation  ->  release gate
    (advisory)     (always runs)              (observes the solid)     (the only block)

A run always produces geometry, even when preflight predicts a violation, so the
conflict report can quote a measurement rather than a prediction. Only the gate
decides whether that geometry may leave the building.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from spec2cad.cad.compiler import compile_design, parameter_table
from spec2cad.cad.executor import ExecutionError, ExecutionResult, execute, import_step
from spec2cad.cad.script_writer import write_script
from spec2cad.extractors.datasheet import extract_datasheet
from spec2cad.extractors.drawing import extract_sketch
from spec2cad.extractors.text import extract_requirement
from spec2cad.fusion.conflict_detector import run_preflight
from spec2cad.fusion.entity_resolver import build_design_intent
from spec2cad.repair.repair_planner import RepairProposal, apply_repair, plan_repairs
from spec2cad.schemas.cad_ir import CADProgram
from spec2cad.schemas.design_intent import DesignIntent
from spec2cad.schemas.evidence import EvidenceSet
from spec2cad.schemas.report import CheckStage, Report
from spec2cad.validation.dimensions import run_dimensions
from spec2cad.validation.gate import ReleaseDecision, evaluate_release
from spec2cad.validation.requirements import (
    compare_prediction_to_measurement,
    run_requirements,
)
from spec2cad.validation.topology import run_topology


@dataclass
class RevisionResult:
    """Everything produced for one DesignIntent revision."""

    intent: DesignIntent
    program: Optional[CADProgram] = None
    execution: Optional[ExecutionResult] = None
    preflight: Optional[Report] = None
    measured: list[Report] = field(default_factory=list)
    cross_checks: list = field(default_factory=list)
    decision: Optional[ReleaseDecision] = None
    proposals: list[RepairProposal] = field(default_factory=list)
    build_error: Optional[str] = None
    script: str = ""

    @property
    def revision(self) -> int:
        return self.intent.revision

    @property
    def released(self) -> bool:
        return self.decision is not None and self.decision.step_export_allowed

    def all_checks(self) -> list:
        out = list(self.preflight.checks) if self.preflight else []
        for report in self.measured:
            out.extend(report.checks)
        out.extend(self.cross_checks)
        return out


@dataclass
class RunResult:
    """A whole session: evidence, and every revision derived from it."""

    evidence: EvidenceSet
    revisions: list[RevisionResult] = field(default_factory=list)
    sketch_backend: str = ""
    sketch_fell_back: bool = False
    sketch_fallback_reason: Optional[str] = None

    @property
    def latest(self) -> RevisionResult:
        return self.revisions[-1]

    def revision(self, number: int) -> RevisionResult:
        for r in self.revisions:
            if r.revision == number:
                return r
        raise KeyError(f"no revision v{number} in this run")


def gather_evidence(
    sketch: Path, datasheet: Path, requirement: Path,
    backend_override: Optional[str] = None,
) -> tuple[EvidenceSet, object]:
    """Run all three extractors."""
    sketch_result = extract_sketch(sketch, backend_override)
    items = list(sketch_result.evidence)
    items += extract_datasheet(datasheet)
    items += extract_requirement(requirement)
    return EvidenceSet(items=items, backend_used=sketch_result.label), sketch_result


def evaluate_revision(intent: DesignIntent) -> RevisionResult:
    """Run the four stages against one revision."""
    result = RevisionResult(intent=intent)

    # 1. preflight -- advisory, never blocks
    result.preflight = run_preflight(intent)

    # 2. diagnostic generation -- runs even when preflight predicts a failure
    try:
        program = compile_design(intent)
        values = parameter_table(intent)
        result.program = program
        result.script = write_script(program, values)
        result.execution = execute(program, values)
    except (ExecutionError, ValueError) as exc:
        result.build_error = f"{type(exc).__name__}: {exc}"
        result.decision = evaluate_release(intent, [])
        return result

    shape = result.execution.shape

    # 3. measured validation -- observes the solid
    result.measured = [
        run_topology(shape, intent),
        run_dimensions(shape, intent),
        run_requirements(shape, intent),
    ]
    requirement_report = result.measured[-1]
    result.cross_checks = compare_prediction_to_measurement(
        result.preflight, requirement_report
    )

    # 4. release gate -- the only stage that can block, and only on measurements
    cross_report = Report(
        stage=CheckStage.REQUIREMENT,
        design_revision=intent.revision,
        checks=result.cross_checks,
    )
    result.decision = evaluate_release(intent, result.measured + [cross_report])
    result.proposals = plan_repairs(intent, result.decision)
    return result


def run(
    sketch: Path, datasheet: Path, requirement: Path,
    backend_override: Optional[str] = None,
) -> RunResult:
    """Extract, fuse and evaluate DesignIntent v1."""
    evidence, sketch_result = gather_evidence(
        sketch, datasheet, requirement, backend_override
    )
    intent, _ = build_design_intent(evidence)
    return RunResult(
        evidence=evidence,
        revisions=[evaluate_revision(intent)],
        sketch_backend=sketch_result.label,
        sketch_fell_back=sketch_result.fell_back,
        sketch_fallback_reason=sketch_result.fallback_reason,
    )


def repair(
    run_result: RunResult,
    proposal_id: str,
    *,
    approved_by: str,
    acknowledge_unsafe: bool = False,
) -> RunResult:
    """Apply a proposal, deriving and evaluating the next revision."""
    current = run_result.latest
    proposal = next((p for p in current.proposals if p.id == proposal_id), None)
    if proposal is None:
        available = [p.id for p in current.proposals]
        raise KeyError(f"no proposal {proposal_id!r}; available: {available}")

    next_intent = apply_repair(
        current.intent, proposal,
        approved_by=approved_by, acknowledge_unsafe=acknowledge_unsafe,
    )
    # A new RunResult rather than an in-place append. DesignIntent revisions are
    # immutable, and a run that silently re-pointed its own `latest` would make
    # "what did v1 conclude?" unanswerable once a repair had been applied.
    return RunResult(
        evidence=run_result.evidence,
        revisions=[*run_result.revisions, evaluate_revision(next_intent)],
        sketch_backend=run_result.sketch_backend,
        sketch_fell_back=run_result.sketch_fell_back,
        sketch_fallback_reason=run_result.sketch_fallback_reason,
    )


def verify_exported_step(step_path: Path, intent: DesignIntent) -> list[Report]:
    """Re-import an exported STEP and validate the artifact itself.

    Validating the in-memory result proves the pipeline worked. Validating the
    re-imported file proves the thing a manufacturer would actually receive is
    the same part.
    """
    shape = import_step(step_path)
    return [
        run_topology(shape, intent),
        run_dimensions(shape, intent),
        run_requirements(shape, intent),
    ]
