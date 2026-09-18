"""Bounded disagreement-origin diagnosis over consistency matrices.

The classifier reports which recorded representation transition contains a
disagreement.  It does not claim root-cause certainty beyond that transition,
and unsupported layer pairings remain explicitly unlocalized.
"""

from __future__ import annotations

from enum import Enum
import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from spec2cad.schemas.feature_ir import StableId

from .consistency import ConsistencyStatus, QuantityConsistencyMatrix
from .sensors import SensorEvidence, SensorLayer


DEFECT_DIAGNOSIS_SCHEMA_VERSION = "1.0.0"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DefectOrigin(str, Enum):
    INTENT_COMPILATION = "intent_compilation"
    FEATURE_IR_LOWERING = "feature_ir_lowering"
    BACKEND_REALIZATION = "backend_realization"
    TOPOLOGY = "topology"
    MEASUREMENT = "measurement"
    VISUAL_INSPECTION = "visual_inspection"
    UNLOCALIZED = "unlocalized"


class DefectDiagnosis(_FrozenModel):
    schema_version: Literal["1.0.0"] = DEFECT_DIAGNOSIS_SCHEMA_VERSION
    id: StableId
    design_revision: int = Field(ge=1)
    quantity: StableId
    matrix_id: StableId
    sensor_ids: tuple[StableId, StableId]
    sensor_layers: tuple[SensorLayer, SensorLayer]
    origin: DefectOrigin
    advisory: bool = False
    explanation: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_diagnosis(self) -> "DefectDiagnosis":
        if self.sensor_ids[0] >= self.sensor_ids[1]:
            raise ValueError("diagnosis sensor ids must be sorted and unique")
        if self.advisory != (self.origin is DefectOrigin.VISUAL_INSPECTION):
            raise ValueError("only visual-inspection diagnoses are advisory")
        return self


def _origin_for_layers(
    left: SensorLayer,
    right: SensorLayer,
) -> tuple[DefectOrigin, str]:
    layers = {left, right}

    if SensorLayer.VISUAL_DIAGNOSTIC in layers:
        return (
            DefectOrigin.VISUAL_INSPECTION,
            "Disagreement includes advisory visual diagnostic evidence.",
        )
    if SensorLayer.TOPOLOGY_RESULT in layers:
        return (
            DefectOrigin.TOPOLOGY,
            "Disagreement includes a recorded semantic topology result.",
        )
    if SensorLayer.SOLVER_STATE in layers:
        return (
            DefectOrigin.BACKEND_REALIZATION,
            "Recorded backend solver/recompute state disagrees with its peer.",
        )
    if layers == {
        SensorLayer.ENGINEERING_INTENT_EXPECTATION,
        SensorLayer.FEATURE_IR_VALUE,
    }:
        return (
            DefectOrigin.INTENT_COMPILATION,
            "Engineering intent and its compiled Feature IR value disagree.",
        )
    if layers == {
        SensorLayer.FEATURE_IR_VALUE,
        SensorLayer.NATIVE_CONSTRAINT,
    }:
        return (
            DefectOrigin.FEATURE_IR_LOWERING,
            "Feature IR and the lowered native constraint disagree.",
        )
    if layers == {
        SensorLayer.NATIVE_CONSTRAINT,
        SensorLayer.BREP_MEASUREMENT,
    }:
        return (
            DefectOrigin.BACKEND_REALIZATION,
            "Native constraint and realized BRep measurement disagree.",
        )
    if left is right is SensorLayer.BREP_MEASUREMENT:
        return (
            DefectOrigin.MEASUREMENT,
            "Independent BRep measurements of the same quantity disagree.",
        )
    return (
        DefectOrigin.UNLOCALIZED,
        "The recorded sensor layers do not bound one supported transition.",
    )


def _diagnosis_id(
    matrix: QuantityConsistencyMatrix,
    sensor_ids: tuple[str, str],
    origin: DefectOrigin,
) -> str:
    identity = "\n".join((
        str(matrix.design_revision),
        matrix.quantity,
        matrix.id,
        *sensor_ids,
        origin.value,
    ))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"diagnosis.{digest[:32]}"


def diagnose_inconsistencies(
    evidence: tuple[SensorEvidence, ...],
    matrices: tuple[QuantityConsistencyMatrix, ...],
) -> tuple[DefectDiagnosis, ...]:
    """Diagnose each unique inconsistent matrix pair using recorded layers."""
    by_id = {item.id: item for item in evidence}
    if len(by_id) != len(evidence):
        raise ValueError("SensorEvidence ids must be unique")

    diagnoses: list[DefectDiagnosis] = []
    for matrix in sorted(matrices, key=lambda item: (item.quantity, item.id)):
        missing_ids = sorted(set(matrix.sensor_ids) - set(by_id))
        if missing_ids:
            raise ValueError(
                "matrix references missing SensorEvidence: " + ", ".join(missing_ids)
            )
        for sensor_id in matrix.sensor_ids:
            item = by_id[sensor_id]
            if item.design_revision != matrix.design_revision:
                raise ValueError("matrix and SensorEvidence design revisions differ")
            if item.quantity != matrix.quantity:
                raise ValueError("matrix and SensorEvidence quantities differ")

        for cell in matrix.cells:
            if (
                cell.status is not ConsistencyStatus.INCONSISTENT
                or cell.row_sensor_id >= cell.column_sensor_id
            ):
                continue
            sensor_ids = (cell.row_sensor_id, cell.column_sensor_id)
            left, right = (by_id[item] for item in sensor_ids)
            origin, explanation = _origin_for_layers(
                left.source.layer, right.source.layer
            )
            diagnoses.append(DefectDiagnosis(
                id=_diagnosis_id(matrix, sensor_ids, origin),
                design_revision=matrix.design_revision,
                quantity=matrix.quantity,
                matrix_id=matrix.id,
                sensor_ids=sensor_ids,
                sensor_layers=(left.source.layer, right.source.layer),
                origin=origin,
                advisory=origin is DefectOrigin.VISUAL_INSPECTION,
                explanation=explanation,
            ))
    return tuple(diagnoses)
