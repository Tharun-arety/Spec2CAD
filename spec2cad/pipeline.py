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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import uuid

from spec2cad.cad.compiler import REQUIRED_FOR_COMPILATION, compile_design, parameter_table
from spec2cad.cad.executor import ExecutionError, ExecutionResult, execute, import_step
from spec2cad.cad.script_writer import write_script
from spec2cad.extractors.base import (
    VisionBackend,
    reasoning_available,
    reasoning_model,
    select_backend,
)
from spec2cad.extractors.datasheet import extract_datasheet, read_document_text
from spec2cad.extractors.drawing import SketchExtraction, extract_sketch
from spec2cad.extractors.reasoning import extract_requirement_with_reasoning
from spec2cad.fusion.conflict_detector import run_preflight
from spec2cad.fusion.graph_builder import (
    build_intent_graph,
    graph_for_revision,
    project_to_design_intent,
)
from spec2cad.fusion.source_policy import is_interface_critical
from spec2cad.repair.repair_planner import RepairProposal, apply_repair, plan_repairs
from spec2cad.schemas.cad_ir import CADProgram
from spec2cad.schemas.design_intent import DesignIntent
from spec2cad.schemas.evidence import EvidenceSet, SemanticTarget, SourceModality
from spec2cad.schemas.intent_graph import AdvancedFeatureNode, EngineeringIntentGraph
from spec2cad.schemas.report import (
    CheckResult,
    CheckStage,
    CheckStatus,
    ConflictClass,
    Report,
)
from spec2cad.validation.dimensions import run_dimensions
from spec2cad.validation.advanced import run_advanced_geometry
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
    intent_graph: Optional[EngineeringIntentGraph] = None
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
    reasoning_backend: str = "not used (no requirement supplied)"
    reasoning_fell_back: bool = False
    reasoning_fallback_reason: Optional[str] = None
    unsupported_features: list[str] = field(default_factory=list)
    clarification_questions: list[str] = field(default_factory=list)
    messages: list["ChatMessage"] = field(default_factory=list)

    @property
    def latest(self) -> RevisionResult:
        return self.revisions[-1]

    def revision(self, number: int) -> RevisionResult:
        for r in self.revisions:
            if r.revision == number:
                return r
        raise KeyError(f"no revision v{number} in this run")


@dataclass(frozen=True)
class ChatMessage:
    id: str
    role: str
    content: str
    kind: str = "message"
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @classmethod
    def create(cls, role: str, content: str, kind: str = "message") -> "ChatMessage":
        return cls(id=uuid.uuid4().hex[:12], role=role, content=content, kind=kind)


def _assistant_message(result: RunResult) -> ChatMessage:
    if result.clarification_questions:
        return ChatMessage.create(
            "assistant", "\n".join(result.clarification_questions), "clarification"
        )
    if result.latest.build_error:
        return ChatMessage.create("assistant", result.latest.build_error, "error")
    count = len(result.latest.program.operations) if result.latest.program else 0
    return ChatMessage.create(
        "assistant",
        f"Generated and validated {result.latest.intent.part.name} with {count} CAD feature"
        f"{'s' if count != 1 else ''}.",
        "result",
    )


def _requirement_text(requirement: str | Path) -> str:
    if isinstance(requirement, Path) and requirement.exists():
        return requirement.read_text(encoding="utf-8")
    return str(requirement)


def gather_evidence(
    sketch: Optional[Path] = None,
    datasheet: Optional[Path] = None,
    requirement: Optional[str | Path] = None,
    backend_override: Optional[str] = None,
    use_reasoning: bool = False,
    reasoning_context: str | None = None,
) -> tuple[EvidenceSet, object | None]:
    """Run every extractor whose source was supplied.

    Partial source sets are intentional. They still produce attributed evidence
    and a DesignIntent with explicit missing parameters; downstream compilation
    may then stop with a useful completeness error instead of the transport
    layer refusing the run before the pipeline can say what it learned.
    """
    if sketch is None and datasheet is None and requirement is None:
        raise ValueError("at least one source is required")

    items = []
    sketch_result = None
    reasoning_result = None

    # When OpenAI reasoning is available, give the sketch to the same typed
    # semantic planner that interprets the written requirement. The legacy
    # sketch reader is deliberately plate-specific; running it first would
    # constrain an otherwise generic part back to the motor-adapter vocabulary.
    selected_backend = select_backend(backend_override) if sketch is not None else None
    multimodal_sketch = bool(
        sketch is not None
        and use_reasoning
        and reasoning_available()
        and selected_backend is VisionBackend.OPENAI
    )
    if sketch is not None and not multimodal_sketch:
        sketch_result = extract_sketch(sketch, backend_override)
        items.extend(sketch_result.evidence)
    if datasheet is not None:
        items.extend(extract_datasheet(datasheet))

    should_reason = requirement is not None or (
        use_reasoning and (sketch is not None or datasheet is not None)
    )
    if should_reason:
        seed = _requirement_text(requirement) if requirement is not None else ""
        context_parts: list[str] = []
        if reasoning_context:
            context_parts.append(reasoning_context)
        elif seed:
            context_parts.append(f"[WRITTEN REQUIREMENT]\n{seed}")
        if datasheet is not None:
            document_text = read_document_text(datasheet)
            if document_text:
                context_parts.append(
                    f"[TECHNICAL PDF: {datasheet.name}]\n{document_text}"
                )
        if sketch is not None:
            context_parts.append(
                f"[ENGINEERING SKETCH: {sketch.name}]\n"
                "The attached image is engineering evidence. Use only written "
                "dimensions and explicit geometric relationships."
            )
        if not context_parts:
            context_parts.append("Interpret the supplied engineering evidence.")

        source_modality = (
            SourceModality.REQUIREMENT_TEXT if requirement is not None
            else SourceModality.SKETCH if sketch is not None
            else SourceModality.DATASHEET
        )
        source_name = (
            Path(requirement).name if isinstance(requirement, Path)
            else "requirement.txt" if requirement is not None
            else sketch.name if sketch is not None
            else datasheet.name
        )
        source_files = {
            **({"requirement": source_name} if requirement is not None else {}),
            **({"sketch": sketch.name} if sketch is not None else {}),
            **({"technical_document": datasheet.name} if datasheet is not None else {}),
            "combined": source_name,
        }
        reasoning_result = extract_requirement_with_reasoning(
            seed,
            source_name=source_name,
            enabled=use_reasoning,
            reasoning_context="\n\n".join(context_parts),
            image_path=sketch if multimodal_sketch else None,
            source_modality=source_modality,
            source_files=source_files,
        )
        items.extend(reasoning_result.evidence)
        if multimodal_sketch:
            sketch_result = SketchExtraction(
                evidence=[],
                backend=VisionBackend.OPENAI,
                label=f"openai multimodal intent ({reasoning_model()})",
                fell_back=reasoning_result.fell_back,
                fallback_reason=reasoning_result.fallback_reason,
            )

    label = sketch_result.label if sketch_result else "not used (no sketch supplied)"
    return EvidenceSet(
        items=items,
        backend_used=label,
        reasoning_backend=(
            reasoning_result.label
            if reasoning_result else "not used (no semantic input supplied)"
        ),
        reasoning_fell_back=reasoning_result.fell_back if reasoning_result else False,
        reasoning_fallback_reason=(
            reasoning_result.fallback_reason if reasoning_result else None
        ),
        unsupported_features=(
            reasoning_result.unsupported_features if reasoning_result else []
        ),
        clarification_questions=(
            reasoning_result.clarification_questions if reasoning_result else []
        ),
        feature_requests=(
            reasoning_result.feature_requests if reasoning_result else []
        ),
    ), sketch_result


def evaluate_revision(
    intent: DesignIntent,
    intent_graph: Optional[EngineeringIntentGraph] = None,
    clarification_questions: Optional[list[str]] = None,
) -> RevisionResult:
    """Run the four stages against one revision."""
    result = RevisionResult(intent=intent, intent_graph=intent_graph)
    advanced_geometry = bool(
        intent_graph and any(
            isinstance(node, AdvancedFeatureNode) for node in intent_graph.nodes
        )
    )

    # 1. preflight -- advisory, never blocks
    result.preflight = (
        Report(
            stage=CheckStage.PREFLIGHT,
            design_revision=intent.revision,
            checks=[CheckResult(
                id="pre_advanced_feature_contract",
                stage=CheckStage.PREFLIGHT,
                name="Advanced feature intent is schema-complete",
                status=CheckStatus.PASS,
                message="typed profile/sheet feature request passed schema validation",
            )],
        )
        if advanced_geometry else run_preflight(intent)
    )

    # A material ambiguity is not a CAD execution failure and must not be
    # guessed by the planner. Preserve extracted evidence and stop at the
    # semantic boundary until the user answers in a new prompt.
    if clarification_questions:
        question_text = " ".join(clarification_questions)
        result.build_error = f"Clarification required before CAD planning: {question_text}"
        clarification_report = Report(
            stage=CheckStage.SCHEMA,
            design_revision=intent.revision,
            checks=[CheckResult(
                id="semantic_clarification_required",
                stage=CheckStage.SCHEMA,
                name="Engineering intent is unambiguous",
                status=CheckStatus.FAIL,
                conflict_class=ConflictClass.COMPLETENESS,
                message=question_text,
            )],
        )
        result.measured = [clarification_report]
        result.decision = evaluate_release(intent, [clarification_report])
        return result

    # 2. diagnostic generation -- runs even when preflight predicts a failure
    try:
        program = compile_design(intent_graph or intent)
        values = parameter_table(intent)
        result.program = program
        result.script = write_script(program, values)
        result.execution = execute(program, values)
    except (ExecutionError, ValueError) as exc:
        result.build_error = f"{type(exc).__name__}: {exc}"
        # An absent solid is never a releasable result. Passing an empty report
        # list to the gate used to authorise failed builds because it saw no
        # measured failures. Represent the build failure as a blocking check so
        # the UI and API cannot call an incomplete run "released".
        build_report = Report(
            stage=CheckStage.SCHEMA,
            design_revision=intent.revision,
            checks=[CheckResult(
                id="build_execution",
                stage=CheckStage.SCHEMA,
                name="Geometry generated",
                status=CheckStatus.FAIL,
                conflict_class=ConflictClass.EXECUTION,
                responsible_parameters=[
                    name for name in REQUIRED_FOR_COMPILATION if not intent.has(name)
                ],
                message=result.build_error,
            )],
        )
        result.measured = [build_report]
        result.decision = evaluate_release(intent, [build_report])
        return result

    shape = result.execution.shape

    # 3. measured validation -- observes the solid
    result.measured = [
        run_topology(shape, intent, skip_analytic_volume=advanced_geometry),
        (
            run_advanced_geometry(result.execution, intent.revision)
            if advanced_geometry else run_dimensions(shape, intent)
        ),
        run_requirements(shape, intent, intent_graph),
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
    sketch: Optional[Path] = None,
    datasheet: Optional[Path] = None,
    requirement: Optional[str | Path] = None,
    backend_override: Optional[str] = None,
    use_reasoning: bool = False,
    reasoning_context: str | None = None,
    create_messages: bool = True,
) -> RunResult:
    """Extract supplied sources, fuse them and evaluate DesignIntent v1."""
    evidence, sketch_result = gather_evidence(
        sketch, datasheet, requirement, backend_override, use_reasoning,
        reasoning_context,
    )
    # The recorded fixture and narrow deterministic document parser describe a
    # motor adapter. A multimodal request that produced an advanced feature is
    # named from its extracted part identity instead of being forced back into
    # the historical plate template merely because it included an attachment.
    attached = sketch is not None or datasheet is not None
    part_name = (
        "motor_adapter_plate"
        if attached and not evidence.feature_requests
        else None
    )
    intent_graph, _ = build_intent_graph(evidence, part_name=part_name)
    intent = project_to_design_intent(intent_graph)
    result = RunResult(
        evidence=evidence,
        revisions=[evaluate_revision(
            intent, intent_graph, evidence.clarification_questions
        )],
        sketch_backend=(
            sketch_result.label if sketch_result else "not used (no sketch supplied)"
        ),
        sketch_fell_back=sketch_result.fell_back if sketch_result else False,
        sketch_fallback_reason=sketch_result.fallback_reason if sketch_result else None,
        reasoning_backend=(
            evidence.reasoning_backend
        ),
        reasoning_fell_back=evidence.reasoning_fell_back,
        reasoning_fallback_reason=evidence.reasoning_fallback_reason,
        unsupported_features=evidence.unsupported_features,
        clarification_questions=evidence.clarification_questions,
    )
    if create_messages and (requirement is not None or sketch is not None or datasheet is not None):
        request_text = (
            _requirement_text(requirement) if requirement is not None
            else "Interpret the attached " + " and ".join(
                name for name, present in (
                    ("engineering sketch", sketch is not None),
                    ("technical document", datasheet is not None),
                ) if present
            ) + "."
        )
        result.messages = [
            ChatMessage.create("user", request_text, "request"),
            _assistant_message(result),
        ]
    return result


def continue_conversation(run_result: RunResult, message: str) -> RunResult:
    """Resolve a clarification or refine a design without losing its audit trail."""
    content = message.strip()
    if not content:
        raise ValueError("a conversation turn cannot be empty")
    user_message = ChatMessage.create("user", content, "answer")
    history = [*run_result.messages, user_message]
    transcript = "\n\n".join(
        f"{item.role.upper()}: {item.content}" for item in history
    )
    fresh = run(
        requirement=content,
        use_reasoning=True,
        reasoning_context=transcript,
        create_messages=False,
    )
    next_revision = run_result.latest.revision + 1
    graph = fresh.latest.intent_graph.model_copy(update={"revision": next_revision})
    intent = project_to_design_intent(graph).model_copy(update={
        "parent_revision": run_result.latest.revision,
    })
    combined = RunResult(
        evidence=fresh.evidence,
        revisions=[
            *run_result.revisions,
            evaluate_revision(intent, graph, fresh.clarification_questions),
        ],
        sketch_backend=run_result.sketch_backend,
        sketch_fell_back=run_result.sketch_fell_back,
        sketch_fallback_reason=run_result.sketch_fallback_reason,
        reasoning_backend=fresh.reasoning_backend,
        reasoning_fell_back=fresh.reasoning_fell_back,
        reasoning_fallback_reason=fresh.reasoning_fallback_reason,
        unsupported_features=fresh.unsupported_features,
        clarification_questions=fresh.clarification_questions,
        messages=history,
    )
    combined.messages.append(_assistant_message(combined))
    return combined


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
    next_graph = (
        graph_for_revision(current.intent_graph, next_intent)
        if current.intent_graph is not None else None
    )
    return RunResult(
        evidence=run_result.evidence,
        revisions=[*run_result.revisions, evaluate_revision(next_intent, next_graph)],
        sketch_backend=run_result.sketch_backend,
        sketch_fell_back=run_result.sketch_fell_back,
        sketch_fallback_reason=run_result.sketch_fallback_reason,
        reasoning_backend=run_result.reasoning_backend,
        reasoning_fell_back=run_result.reasoning_fell_back,
        reasoning_fallback_reason=run_result.reasoning_fallback_reason,
        unsupported_features=run_result.unsupported_features,
        clarification_questions=run_result.clarification_questions,
        messages=run_result.messages,
    )


class InterfaceChangeRequiresAcknowledgement(PermissionError):
    """Raised when a manual edit would move a mating interface unacknowledged."""


def interface_critical(names: list[str]) -> list[str]:
    """Which of these parameter names dictate how the part mates."""
    out = []
    for name in names:
        try:
            target = SemanticTarget(name)
        except ValueError:
            continue
        if is_interface_critical(target):
            out.append(name)
    return out


def revise(
    run_result: RunResult,
    updates: dict[str, float],
    *,
    approved_by: str,
    reason: str = "manual parameter edit",
    acknowledge_interface: bool = False,
) -> RunResult:
    """Derive the next revision from a hand-edited parameter.

    Repair proposals only exist while something is blocked, so once a design is
    released there would otherwise be no way to take it further. This is that
    way -- and it goes through derive() like any other revision, so a manual
    edit is recorded with its author and its before/after exactly as an accepted
    proposal is.

    Moving a mating interface by hand is possible but never silent: it needs an
    explicit acknowledgement, for the same reason the repair planner refuses to
    auto-apply one.
    """
    if not updates:
        raise ValueError("a revision needs at least one parameter change")

    current = run_result.latest
    unknown = [n for n in updates if n not in current.intent.parameters]
    if unknown:
        raise KeyError(f"unknown parameter(s): {', '.join(sorted(unknown))}")

    risky = interface_critical(list(updates))
    if risky and not acknowledge_interface:
        raise InterfaceChangeRequiresAcknowledgement(
            f"{', '.join(risky)} dictate how the part mates with the motor. "
            f"Changing them produces a part that builds cleanly, passes every check "
            f"against the altered intent, and does not bolt on. Acknowledge explicitly "
            f"to proceed."
        )

    next_intent = current.intent.derive(
        updates=updates,
        proposal_id="manual_edit",
        approved_by=approved_by,
        reason=reason,
    )
    next_graph = (
        graph_for_revision(current.intent_graph, next_intent)
        if current.intent_graph is not None else None
    )
    return RunResult(
        evidence=run_result.evidence,
        revisions=[*run_result.revisions, evaluate_revision(next_intent, next_graph)],
        sketch_backend=run_result.sketch_backend,
        sketch_fell_back=run_result.sketch_fell_back,
        sketch_fallback_reason=run_result.sketch_fallback_reason,
        reasoning_backend=run_result.reasoning_backend,
        reasoning_fell_back=run_result.reasoning_fell_back,
        reasoning_fallback_reason=run_result.reasoning_fallback_reason,
        unsupported_features=run_result.unsupported_features,
        clarification_questions=run_result.clarification_questions,
        messages=run_result.messages,
    )


def verify_exported_step(
    step_path: Path,
    intent: DesignIntent,
    intent_graph: Optional[EngineeringIntentGraph] = None,
) -> list[Report]:
    """Re-import an exported STEP and validate the artifact itself.

    Validating the in-memory result proves the pipeline worked. Validating the
    re-imported file proves the thing a manufacturer would actually receive is
    the same part.
    """
    shape = import_step(step_path)
    return [
        run_topology(shape, intent),
        run_dimensions(shape, intent),
        run_requirements(shape, intent, intent_graph),
    ]
