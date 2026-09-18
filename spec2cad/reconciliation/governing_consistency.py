"""Derive the release-facing result of governing sensor comparisons."""

from __future__ import annotations

from enum import Enum
import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from spec2cad.schemas.feature_ir import StableId

from .consistency import ConsistencyStatus, QuantityConsistencyMatrix
from .sensors import SensorEvidence, SensorReleaseRole


GOVERNING_CONSISTENCY_SCHEMA_VERSION = "1.0.0"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GoverningConsistencyStatus(str, Enum):
    CONSISTENT = "consistent"
    INCONSISTENT = "inconsistent"
    NOT_ASSESSED = "not_assessed"


class GoverningConsistencyAssessment(_FrozenModel):
    schema_version: Literal["1.0.0"] = GOVERNING_CONSISTENCY_SCHEMA_VERSION
    id: StableId
    design_revision: int = Field(ge=1)
    status: GoverningConsistencyStatus
    governing: bool
    governing_sensor_ids: tuple[StableId, ...] = ()
    matrix_ids: tuple[StableId, ...] = ()
    inconsistent_pairs: tuple[tuple[StableId, StableId], ...] = ()
    not_assessed_pairs: tuple[tuple[StableId, StableId], ...] = ()
    reasons: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_assessment(self) -> "GoverningConsistencyAssessment":
        if self.governing != bool(self.governing_sensor_ids):
            raise ValueError("governing flag must reflect governing sensor ids")
        if tuple(sorted(set(self.governing_sensor_ids))) != self.governing_sensor_ids:
            raise ValueError("governing sensor ids must be sorted and unique")
        if tuple(sorted(set(self.matrix_ids))) != self.matrix_ids:
            raise ValueError("matrix ids must be sorted and unique")
        for pairs in (self.inconsistent_pairs, self.not_assessed_pairs):
            if tuple(sorted(set(pairs))) != pairs or any(
                left >= right for left, right in pairs
            ):
                raise ValueError("assessment pairs must be sorted and unique")
        if not self.governing and self.status is not GoverningConsistencyStatus.NOT_ASSESSED:
            raise ValueError("non-governing assessment cannot claim a result")
        if (
            self.status is GoverningConsistencyStatus.INCONSISTENT
            and not self.inconsistent_pairs
        ):
            raise ValueError("inconsistent assessment requires an inconsistent pair")
        if self.status is GoverningConsistencyStatus.CONSISTENT and (
            self.inconsistent_pairs or self.not_assessed_pairs
        ):
            raise ValueError("consistent assessment cannot contain unresolved pairs")
        return self

    @property
    def release_consistent(self) -> bool:
        return self.governing and self.status is GoverningConsistencyStatus.CONSISTENT


def _assessment_id(
    design_revision: int,
    governing_ids: tuple[str, ...],
    matrix_ids: tuple[str, ...],
    status: GoverningConsistencyStatus,
) -> str:
    identity = "\n".join((
        str(design_revision), *governing_ids, *matrix_ids, status.value,
    ))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"governing_consistency.{digest[:32]}"


def assess_governing_consistency(
    evidence: tuple[SensorEvidence, ...],
    matrices: tuple[QuantityConsistencyMatrix, ...],
) -> GoverningConsistencyAssessment:
    """Reduce eligible governing/reference cells into one fail-closed result."""
    if not evidence:
        raise ValueError("at least one SensorEvidence record is required")
    evidence_by_id = {item.id: item for item in evidence}
    if len(evidence_by_id) != len(evidence):
        raise ValueError("SensorEvidence ids must be unique")
    revisions = {item.design_revision for item in evidence}
    if len(revisions) != 1:
        raise ValueError("all SensorEvidence must use the same design revision")
    design_revision = revisions.pop()
    matrix_by_id = {item.id: item for item in matrices}
    if len(matrix_by_id) != len(matrices):
        raise ValueError("consistency matrix ids must be unique")

    governing_ids = tuple(sorted(
        item.id for item in evidence
        if item.release_role is SensorReleaseRole.GOVERNING
    ))
    relevant_matrices = tuple(sorted(
        (
            matrix for matrix in matrices
            if set(matrix.sensor_ids) & set(governing_ids)
        ),
        key=lambda item: item.id,
    ))
    if not governing_ids:
        status = GoverningConsistencyStatus.NOT_ASSESSED
        return GoverningConsistencyAssessment(
            id=_assessment_id(design_revision, (), (), status),
            design_revision=design_revision,
            status=status,
            governing=False,
            reasons=("no governing SensorEvidence is present",),
        )

    represented_governing = {
        sensor_id for matrix in relevant_matrices for sensor_id in matrix.sensor_ids
        if sensor_id in governing_ids
    }
    if represented_governing != set(governing_ids):
        missing = sorted(set(governing_ids) - represented_governing)
        raise ValueError(
            "governing SensorEvidence is missing from matrices: " + ", ".join(missing)
        )

    inconsistent: set[tuple[str, str]] = set()
    not_assessed: set[tuple[str, str]] = set()
    governing_without_peer: list[str] = []
    eligible_roles = {
        SensorReleaseRole.GOVERNING,
        SensorReleaseRole.REFERENCE,
    }
    for matrix in relevant_matrices:
        if matrix.design_revision != design_revision:
            raise ValueError("matrix and SensorEvidence design revisions differ")
        for sensor_id in matrix.sensor_ids:
            item = evidence_by_id.get(sensor_id)
            if item is None:
                raise ValueError(f"matrix references missing SensorEvidence {sensor_id}")
            if item.quantity != matrix.quantity:
                raise ValueError("matrix and SensorEvidence quantities differ")

        for governing_id in set(matrix.sensor_ids) & set(governing_ids):
            peers = [
                sensor_id for sensor_id in matrix.sensor_ids
                if sensor_id != governing_id
                and evidence_by_id[sensor_id].release_role in eligible_roles
            ]
            if not peers:
                governing_without_peer.append(governing_id)

        for cell in matrix.cells:
            if cell.row_sensor_id >= cell.column_sensor_id:
                continue
            pair = (cell.row_sensor_id, cell.column_sensor_id)
            left, right = (evidence_by_id[item] for item in pair)
            if not ({left.id, right.id} & set(governing_ids)):
                continue
            if left.release_role not in eligible_roles or right.release_role not in eligible_roles:
                continue
            if cell.status is ConsistencyStatus.INCONSISTENT:
                inconsistent.add(pair)
            elif cell.status is ConsistencyStatus.NOT_ASSESSED:
                not_assessed.add(pair)

    reasons: list[str] = []
    if inconsistent:
        status = GoverningConsistencyStatus.INCONSISTENT
        reasons.extend(
            f"governing comparison {left} vs {right} is inconsistent"
            for left, right in sorted(inconsistent)
        )
    elif not_assessed or governing_without_peer:
        status = GoverningConsistencyStatus.NOT_ASSESSED
        reasons.extend(
            f"governing comparison {left} vs {right} is not assessed"
            for left, right in sorted(not_assessed)
        )
        reasons.extend(
            f"governing sensor {sensor_id} has no eligible independent peer"
            for sensor_id in sorted(set(governing_without_peer))
        )
    else:
        status = GoverningConsistencyStatus.CONSISTENT
        reasons.append("all eligible governing sensor comparisons are consistent")

    matrix_ids = tuple(item.id for item in relevant_matrices)
    return GoverningConsistencyAssessment(
        id=_assessment_id(design_revision, governing_ids, matrix_ids, status),
        design_revision=design_revision,
        status=status,
        governing=True,
        governing_sensor_ids=governing_ids,
        matrix_ids=matrix_ids,
        inconsistent_pairs=tuple(sorted(inconsistent)),
        not_assessed_pairs=tuple(sorted(not_assessed)),
        reasons=tuple(reasons),
    )
