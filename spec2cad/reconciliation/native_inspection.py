"""Typed diagnostic inspection of native CAD State Graph health."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from spec2cad.cad_state_serialization import csg_content_hash
from spec2cad.schemas.cad_state_graph import (
    CADStateGraph,
    ConstraintNode,
    ConstraintObservation,
    DiagnosticNode,
    DocumentNode,
    RecomputeObservation,
    SketchNode,
)
from spec2cad.schemas.feature_ir import StableId


NATIVE_INSPECTION_SCHEMA_VERSION = "1.0.0"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NativeInspectionKind(str, Enum):
    SKETCH_DOF = "sketch_dof"
    REDUNDANT_CONSTRAINT = "redundant_constraint"
    CONFLICTING_CONSTRAINT = "conflicting_constraint"
    BROKEN_REFERENCE = "broken_reference"
    RECOMPUTE = "recompute"


class NativeInspectionStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_ASSESSED = "not_assessed"


class NativeInspectionFinding(_FrozenModel):
    id: StableId
    label: str = Field(min_length=1)
    kind: NativeInspectionKind
    status: NativeInspectionStatus
    csg_record_ids: tuple[StableId, ...] = Field(min_length=1)
    message: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_records(self) -> "NativeInspectionFinding":
        if len(self.csg_record_ids) != len(set(self.csg_record_ids)):
            raise ValueError("inspection CSG record ids must be unique")
        return self


class NativeInspectionReport(_FrozenModel):
    schema_version: Literal["1.0.0"] = NATIVE_INSPECTION_SCHEMA_VERSION
    id: StableId
    design_revision: int = Field(ge=1)
    backend_id: StableId
    backend_version: str = Field(min_length=1)
    csg_id: StableId
    csg_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    findings: tuple[NativeInspectionFinding, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_findings(self) -> "NativeInspectionReport":
        ids = [item.id for item in self.findings]
        if len(ids) != len(set(ids)):
            raise ValueError("native inspection finding ids must be unique")
        missing = set(NativeInspectionKind) - {item.kind for item in self.findings}
        if missing:
            raise ValueError(
                "native inspection report is missing checks: "
                + ", ".join(sorted(item.value for item in missing))
            )
        return self

    def findings_of(
        self, kind: NativeInspectionKind
    ) -> tuple[NativeInspectionFinding, ...]:
        return tuple(item for item in self.findings if item.kind is kind)

    @property
    def passed(self) -> bool:
        return all(item.status is NativeInspectionStatus.PASS for item in self.findings)


def _finding(
    *,
    finding_id: str,
    label: str,
    kind: NativeInspectionKind,
    status: NativeInspectionStatus,
    record_ids: tuple[str, ...],
    message: str,
) -> NativeInspectionFinding:
    return NativeInspectionFinding(
        id=finding_id,
        label=label,
        kind=kind,
        status=status,
        csg_record_ids=record_ids,
        message=message,
    )


def inspect_native_health(
    graph: CADStateGraph,
    *,
    design_revision: int,
) -> NativeInspectionReport:
    """Inspect existing typed native state without inferring defect origin."""
    findings: list[NativeInspectionFinding] = []
    documents = [item for item in graph.nodes if isinstance(item, DocumentNode)]
    sketches = [item for item in graph.nodes if isinstance(item, SketchNode)]
    constraints = [item for item in graph.nodes if isinstance(item, ConstraintNode)]

    for document in documents:
        if document.recompute is RecomputeObservation.SUCCEEDED:
            status = NativeInspectionStatus.PASS
            message = "Native document recompute succeeded."
        elif document.recompute is RecomputeObservation.FAILED:
            status = NativeInspectionStatus.FAIL
            message = "Native document recompute failed."
        else:
            status = NativeInspectionStatus.NOT_ASSESSED
            message = f"Native recompute state is {document.recompute.value}."
        findings.append(_finding(
            finding_id=f"inspection.recompute.{document.id}",
            label=f"{document.label} recompute",
            kind=NativeInspectionKind.RECOMPUTE,
            status=status,
            record_ids=(document.id,),
            message=message,
        ))

    if not sketches:
        findings.append(_finding(
            finding_id="inspection.sketch_dof.not_assessed",
            label="Sketch degrees of freedom",
            kind=NativeInspectionKind.SKETCH_DOF,
            status=NativeInspectionStatus.NOT_ASSESSED,
            record_ids=(graph.root_document_id,),
            message="The backend reported no native sketch solver state.",
        ))
    for sketch in sketches:
        if sketch.degrees_of_freedom is None:
            status = NativeInspectionStatus.NOT_ASSESSED
            message = "Sketch degrees of freedom were not reported."
        elif sketch.degrees_of_freedom == 0 and sketch.fully_constrained is not False:
            status = NativeInspectionStatus.PASS
            message = "Sketch has zero degrees of freedom."
        else:
            status = NativeInspectionStatus.FAIL
            message = (
                f"Sketch has {sketch.degrees_of_freedom} remaining degrees of freedom."
            )
        findings.append(_finding(
            finding_id=f"inspection.sketch_dof.{sketch.id}",
            label=f"{sketch.label} degrees of freedom",
            kind=NativeInspectionKind.SKETCH_DOF,
            status=status,
            record_ids=(sketch.id,),
            message=message,
        ))

    if not constraints:
        for kind in (
            NativeInspectionKind.REDUNDANT_CONSTRAINT,
            NativeInspectionKind.CONFLICTING_CONSTRAINT,
        ):
            findings.append(_finding(
                finding_id=f"inspection.{kind.value}.not_assessed",
                label=kind.value.replace("_", " ").title(),
                kind=kind,
                status=NativeInspectionStatus.NOT_ASSESSED,
                record_ids=(graph.root_document_id,),
                message="The backend reported no native constraint state.",
            ))
    for constraint in constraints:
        if constraint.state is ConstraintObservation.UNKNOWN:
            redundant_status = conflict_status = NativeInspectionStatus.NOT_ASSESSED
        else:
            redundant_status = (
                NativeInspectionStatus.FAIL
                if constraint.state is ConstraintObservation.REDUNDANT
                else NativeInspectionStatus.PASS
            )
            conflict_status = (
                NativeInspectionStatus.FAIL
                if constraint.state is ConstraintObservation.VIOLATED
                else NativeInspectionStatus.PASS
            )
        findings.extend((
            _finding(
                finding_id=f"inspection.redundant_constraint.{constraint.id}",
                label=f"{constraint.label} redundancy",
                kind=NativeInspectionKind.REDUNDANT_CONSTRAINT,
                status=redundant_status,
                record_ids=(constraint.id,),
                message=(
                    "Constraint is redundant."
                    if redundant_status is NativeInspectionStatus.FAIL
                    else "Constraint redundancy is unknown."
                    if redundant_status is NativeInspectionStatus.NOT_ASSESSED
                    else "Constraint is not redundant."
                ),
            ),
            _finding(
                finding_id=f"inspection.conflicting_constraint.{constraint.id}",
                label=f"{constraint.label} conflict",
                kind=NativeInspectionKind.CONFLICTING_CONSTRAINT,
                status=conflict_status,
                record_ids=(constraint.id,),
                message=(
                    "Constraint is violated/conflicting."
                    if conflict_status is NativeInspectionStatus.FAIL
                    else "Constraint conflict state is unknown."
                    if conflict_status is NativeInspectionStatus.NOT_ASSESSED
                    else "Constraint is not violated/conflicting."
                ),
            ),
        ))

    broken = [
        item for item in graph.nodes
        if isinstance(item, DiagnosticNode)
        and item.code in {"broken_reference", "broken_native_reference"}
    ]
    if broken:
        for diagnostic in broken:
            findings.append(_finding(
                finding_id=f"inspection.broken_reference.{diagnostic.id}",
                label=diagnostic.label,
                kind=NativeInspectionKind.BROKEN_REFERENCE,
                status=NativeInspectionStatus.FAIL,
                record_ids=(diagnostic.id, *diagnostic.related_node_ids),
                message=diagnostic.message,
            ))
    elif any(document.editable for document in documents):
        findings.append(_finding(
            finding_id="inspection.broken_reference.none",
            label="Native reference health",
            kind=NativeInspectionKind.BROKEN_REFERENCE,
            status=NativeInspectionStatus.PASS,
            record_ids=(graph.root_document_id,),
            message="No broken native reference diagnostic was reported.",
        ))
    else:
        findings.append(_finding(
            finding_id="inspection.broken_reference.not_assessed",
            label="Native reference health",
            kind=NativeInspectionKind.BROKEN_REFERENCE,
            status=NativeInspectionStatus.NOT_ASSESSED,
            record_ids=(graph.root_document_id,),
            message="The backend has no editable native reference state.",
        ))

    return NativeInspectionReport(
        id=f"inspection.{graph.backend_id}.native.r{design_revision}",
        design_revision=design_revision,
        backend_id=graph.backend_id,
        backend_version=graph.backend_version,
        csg_id=graph.id,
        csg_sha256=csg_content_hash(graph),
        findings=tuple(findings),
    )
