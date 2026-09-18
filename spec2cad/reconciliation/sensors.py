"""Versioned evidence emitted by reconciliation sensors.

Sensor evidence records what one inspection method reported about one governed
quantity.  It remains separate from design authority and from release decisions:
the release role only states whether a validated consumer may use the evidence.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from spec2cad.schemas.feature_ir import StableId

from .observations import Applicability


SENSOR_EVIDENCE_SCHEMA_VERSION = "1.0.0"
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
SemanticVersion = Annotated[
    str,
    StringConstraints(pattern=r"^\d+\.\d+\.\d+$"),
]
SensorUnit = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=32,
        pattern=r"^[A-Za-z0-9%*/^_.-]+$",
    ),
]
SensorValue = float | bool | str | tuple[float, ...]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SensorLayer(str, Enum):
    ENGINEERING_INTENT_EXPECTATION = "engineering_intent_expectation"
    FEATURE_IR_VALUE = "feature_ir_value"
    NATIVE_CONSTRAINT = "native_constraint"
    BREP_MEASUREMENT = "brep_measurement"
    TOPOLOGY_RESULT = "topology_result"
    SOLVER_STATE = "solver_state"
    VISUAL_DIAGNOSTIC = "visual_diagnostic"


class SensorReleaseRole(str, Enum):
    GOVERNING = "governing"
    REFERENCE = "reference"
    DIAGNOSTIC = "diagnostic"


class SensorDiagnosticSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class SensorDiagnostic(_FrozenModel):
    severity: SensorDiagnosticSeverity
    code: StableId
    message: str = Field(min_length=1)
    related_record_ids: tuple[StableId, ...] = ()

    @model_validator(mode="after")
    def validate_related_records(self) -> "SensorDiagnostic":
        if len(self.related_record_ids) != len(set(self.related_record_ids)):
            raise ValueError("diagnostic related record ids must be unique")
        return self


class SensorReference(_FrozenModel):
    layer: SensorLayer
    document_id: StableId
    document_sha256: Sha256
    record_ids: tuple[StableId, ...] = Field(min_length=1)
    backend_id: StableId | None = None
    backend_version: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_reference(self) -> "SensorReference":
        if len(self.record_ids) != len(set(self.record_ids)):
            raise ValueError("sensor source record ids must be unique")
        if (self.backend_id is None) != (self.backend_version is None):
            raise ValueError("backend id and version must be provided together")
        backend_layers = {
            SensorLayer.NATIVE_CONSTRAINT,
            SensorLayer.BREP_MEASUREMENT,
            SensorLayer.TOPOLOGY_RESULT,
            SensorLayer.SOLVER_STATE,
        }
        if self.layer in backend_layers and self.backend_id is None:
            raise ValueError(f"{self.layer.value} requires backend id and version")
        return self


class SensorMethod(_FrozenModel):
    id: StableId
    version: SemanticVersion
    description: str = Field(min_length=1)


class SensorTolerance(_FrozenModel):
    policy_id: StableId
    policy_version: SemanticVersion
    unit: SensorUnit
    absolute: float = Field(ge=0, allow_inf_nan=False)
    relative: float = Field(default=0.0, ge=0, allow_inf_nan=False)


class SensorEvidence(_FrozenModel):
    schema_version: Literal["1.0.0"] = SENSOR_EVIDENCE_SCHEMA_VERSION
    id: StableId
    label: str = Field(min_length=1)
    revision: int = Field(ge=1)
    design_revision: int = Field(ge=1)
    quantity: StableId
    source: SensorReference
    value: SensorValue | None
    unit: SensorUnit
    tolerance: SensorTolerance | None = None
    method: SensorMethod
    applicability: Applicability = Applicability.APPLICABLE
    release_role: SensorReleaseRole
    related_record_ids: tuple[StableId, ...] = ()
    diagnostics: tuple[SensorDiagnostic, ...] = ()

    @model_validator(mode="after")
    def validate_evidence(self) -> "SensorEvidence":
        if len(self.related_record_ids) != len(set(self.related_record_ids)):
            raise ValueError("sensor related record ids must be unique")

        if (
            self.source.layer is SensorLayer.VISUAL_DIAGNOSTIC
            and self.release_role is not SensorReleaseRole.DIAGNOSTIC
        ):
            raise ValueError("visual evidence must remain diagnostic")

        if self.applicability is not Applicability.APPLICABLE:
            if self.value is not None:
                raise ValueError("unavailable evidence must not contain a value")
            if self.release_role is SensorReleaseRole.GOVERNING:
                raise ValueError("unavailable evidence cannot govern release")
            if not self.diagnostics:
                raise ValueError("unavailable evidence requires a diagnostic")
            return self

        if self.value is None:
            raise ValueError("applicable evidence requires a value")

        if (
            self.release_role is SensorReleaseRole.GOVERNING
            and self.source.layer in {
                SensorLayer.ENGINEERING_INTENT_EXPECTATION,
                SensorLayer.FEATURE_IR_VALUE,
            }
        ):
            raise ValueError(f"{self.source.layer.value} evidence cannot govern release")

        quantitative = not isinstance(self.value, (bool, str))
        if quantitative:
            values = self.value if isinstance(self.value, tuple) else (self.value,)
            if not values:
                raise ValueError("quantitative sensor value must not be empty")
            if any(not math.isfinite(item) for item in values):
                raise ValueError("quantitative sensor values must be finite")
            if self.unit == "none":
                raise ValueError("quantitative evidence requires a physical unit")
            if (
                self.release_role is SensorReleaseRole.GOVERNING
                and self.tolerance is None
            ):
                raise ValueError("governing numeric evidence requires a tolerance")
        else:
            if self.unit != "none":
                raise ValueError("categorical evidence must use unit none")
            if self.tolerance is not None:
                raise ValueError("categorical evidence cannot carry a numeric tolerance")

        if self.tolerance is not None and self.tolerance.unit != self.unit:
            raise ValueError("tolerance unit must match sensor evidence unit")
        return self
