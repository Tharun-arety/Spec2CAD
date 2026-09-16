"""Typed evidence records consumed by cross-backend reconciliation."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from spec2cad.schemas.feature_ir import StableId


OBSERVATION_SCHEMA_VERSION = "1.0.0"
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ObservationLayer(str, Enum):
    ENGINEERING_INTENT = "engineering_intent"
    FEATURE_IR = "feature_ir"
    NATIVE_STATE = "native_state"
    BREP_MEASUREMENT = "brep_measurement"


class Applicability(str, Enum):
    APPLICABLE = "applicable"
    UNSUPPORTED = "unsupported"
    NOT_ASSESSED = "not_assessed"


class GovernedQuantity(str, Enum):
    PLATE_WIDTH = "plate_width"
    PLATE_HEIGHT = "plate_height"
    PLATE_THICKNESS = "plate_thickness"
    OPENING_DIAMETER = "opening_diameter"
    MOUNTING_DIAMETER = "mounting_diameter"
    MOUNTING_HOLE_CENTERS = "mounting_hole_centers"
    HOLE_SPACING_X = "hole_spacing_x"
    HOLE_SPACING_Y = "hole_spacing_y"
    VOLUME = "volume"
    INTERFACE_GEOMETRY = "interface_geometry"
    REQUIREMENT_PREDICATE = "requirement_predicate"


class ObservationUnit(str, Enum):
    MILLIMETRE = "mm"
    CUBIC_MILLIMETRE = "mm3"
    NONE = "none"


class PredicateOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_ASSESSED = "not_assessed"


class ObservationSource(_FrozenModel):
    layer: ObservationLayer
    document_id: StableId
    document_sha256: Sha256
    backend_id: StableId | None = None
    backend_version: str | None = None

    @model_validator(mode="after")
    def validate_backend_identity(self) -> "ObservationSource":
        backend_layer = self.layer in {
            ObservationLayer.NATIVE_STATE,
            ObservationLayer.BREP_MEASUREMENT,
        }
        if backend_layer != (self.backend_id is not None and self.backend_version is not None):
            raise ValueError("backend layers require backend id and version only")
        return self


class Point2D(_FrozenModel):
    x_mm: float = Field(allow_inf_nan=False)
    y_mm: float = Field(allow_inf_nan=False)


class _Observation(_FrozenModel):
    schema_version: Literal["1.0.0"] = OBSERVATION_SCHEMA_VERSION
    id: StableId
    quantity: GovernedQuantity
    source: ObservationSource
    applicability: Applicability = Applicability.APPLICABLE
    method: str = Field(min_length=1)
    governing: bool = False
    related_record_ids: tuple[StableId, ...] = ()
    reason: str | None = None

    @model_validator(mode="after")
    def validate_evidence_role(self):
        if self.applicability is Applicability.APPLICABLE:
            if self.reason is not None:
                raise ValueError("applicable observation cannot have an unavailable reason")
        elif not self.reason:
            raise ValueError("unavailable observation requires a reason")
        if self.governing and self.source.layer not in {
            ObservationLayer.NATIVE_STATE,
            ObservationLayer.BREP_MEASUREMENT,
        }:
            raise ValueError("intent and Feature IR observations cannot govern release")
        if self.governing and self.applicability is not Applicability.APPLICABLE:
            raise ValueError("unavailable observation cannot govern release")
        return self


class NumericObservation(_Observation):
    kind: Literal["numeric"] = "numeric"
    value: float | None = Field(default=None, allow_inf_nan=False)
    unit: ObservationUnit

    @model_validator(mode="after")
    def validate_value(self) -> "NumericObservation":
        if (self.value is not None) != (self.applicability is Applicability.APPLICABLE):
            raise ValueError("numeric value must exist exactly when applicable")
        expected = {
            GovernedQuantity.VOLUME: ObservationUnit.CUBIC_MILLIMETRE,
        }.get(self.quantity, ObservationUnit.MILLIMETRE)
        if self.quantity is GovernedQuantity.REQUIREMENT_PREDICATE:
            expected = ObservationUnit.NONE
        if self.unit is not expected:
            raise ValueError(f"{self.quantity.value} requires unit {expected.value}")
        return self


class PointSetObservation(_Observation):
    kind: Literal["point_set"] = "point_set"
    quantity: Literal[GovernedQuantity.MOUNTING_HOLE_CENTERS] = (
        GovernedQuantity.MOUNTING_HOLE_CENTERS
    )
    points: tuple[Point2D, ...] = ()

    @model_validator(mode="after")
    def validate_points(self) -> "PointSetObservation":
        if bool(self.points) != (self.applicability is Applicability.APPLICABLE):
            raise ValueError("point set must exist exactly when applicable")
        if len(set(self.points)) != len(self.points):
            raise ValueError("observed points must be unique")
        return self


class InterfaceGeometryObservation(_Observation):
    kind: Literal["interface_geometry"] = "interface_geometry"
    quantity: Literal[GovernedQuantity.INTERFACE_GEOMETRY] = (
        GovernedQuantity.INTERFACE_GEOMETRY
    )
    opening_diameter_mm: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    mounting_diameter_mm: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    mounting_centers: tuple[Point2D, ...] = ()

    @model_validator(mode="after")
    def validate_geometry(self) -> "InterfaceGeometryObservation":
        complete = (
            self.opening_diameter_mm is not None
            and self.mounting_diameter_mm is not None
            and bool(self.mounting_centers)
        )
        if complete != (self.applicability is Applicability.APPLICABLE):
            raise ValueError("interface geometry must be complete exactly when applicable")
        return self


class PredicateObservation(_Observation):
    kind: Literal["predicate"] = "predicate"
    quantity: Literal[GovernedQuantity.REQUIREMENT_PREDICATE] = (
        GovernedQuantity.REQUIREMENT_PREDICATE
    )
    requirement_id: StableId
    outcome: PredicateOutcome
    measured_value: float | None = Field(default=None, allow_inf_nan=False)
    threshold: float | None = Field(default=None, allow_inf_nan=False)
    unit: Literal["mm"] = "mm"

    @model_validator(mode="after")
    def validate_outcome(self) -> "PredicateObservation":
        assessed = self.outcome is not PredicateOutcome.NOT_ASSESSED
        if assessed != (self.applicability is Applicability.APPLICABLE):
            raise ValueError("predicate outcome and applicability disagree")
        if assessed != (self.measured_value is not None and self.threshold is not None):
            raise ValueError("assessed predicate requires measured value and threshold")
        return self


Observation = Annotated[
    Union[
        NumericObservation,
        PointSetObservation,
        InterfaceGeometryObservation,
        PredicateObservation,
    ],
    Field(discriminator="kind"),
]


class ObservationSet(_FrozenModel):
    schema_version: Literal["1.0.0"] = OBSERVATION_SCHEMA_VERSION
    id: StableId
    design_revision: int = Field(ge=1)
    feature_ir_sha256: Sha256
    observations: tuple[Observation, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "ObservationSet":
        ids = [item.id for item in self.observations]
        if len(ids) != len(set(ids)):
            raise ValueError("observation ids must be unique")
        return self
