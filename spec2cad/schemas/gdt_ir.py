"""A small, typed GD&T inspection IR with explicit datums and tolerance zones."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


FaceName = Literal["top", "bottom", "positive_x", "negative_x", "positive_y", "negative_y"]


class DatumPlane(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    face: FaceName


class CircularFeatureSelector(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    nominal_diameter: float = Field(gt=0)
    nominal_x: float = 0.0
    nominal_y: float = 0.0


class SizeTolerance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["size"] = "size"
    id: str
    feature: CircularFeatureSelector
    lower_limit: float
    upper_limit: float

    @model_validator(mode="after")
    def valid_limits(self):
        if self.lower_limit > self.upper_limit:
            raise ValueError("size lower_limit must not exceed upper_limit")
        return self


class PositionTolerance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["position"] = "position"
    id: str
    feature: CircularFeatureSelector
    tolerance_diameter: float = Field(gt=0)
    datum_references: list[str] = Field(default_factory=list, max_length=8)


class FlatnessTolerance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["flatness"] = "flatness"
    id: str
    face: FaceName
    tolerance: float = Field(gt=0)


class PerpendicularityTolerance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["perpendicularity"] = "perpendicularity"
    id: str
    face: FaceName
    datum: str
    tolerance: float = Field(gt=0, description="parallel-plane zone width in mm")


FeatureControlFrame = Annotated[
    Union[SizeTolerance, PositionTolerance, FlatnessTolerance, PerpendicularityTolerance],
    Field(discriminator="type"),
]


class InspectionProgram(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    datums: list[DatumPlane] = Field(default_factory=list, max_length=32)
    controls: list[FeatureControlFrame] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def datum_references_exist(self):
        known = {datum.id for datum in self.datums}
        for control in self.controls:
            refs = (
                control.datum_references if isinstance(control, PositionTolerance)
                else [control.datum] if isinstance(control, PerpendicularityTolerance)
                else []
            )
            missing = set(refs) - known
            if missing:
                raise ValueError(f"control {control.id!r} references unknown datums {sorted(missing)}")
        return self
