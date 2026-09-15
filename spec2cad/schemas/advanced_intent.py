"""Semantic feature requests emitted by extraction and stored in the EIG."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IntentPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    x: float
    y: float


class IntentSegment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["line", "three_point_arc"]
    end: IntentPoint
    midpoint: IntentPoint | None = None

    @model_validator(mode="after")
    def arc_has_midpoint(self):
        if self.type == "three_point_arc" and self.midpoint is None:
            raise ValueError("an arc segment requires a midpoint")
        return self


class ProfileFeatureIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["profile_extrude", "profile_revolve"]
    id: str
    plane: Literal["XY", "XZ", "YZ"] = "XY"
    start: IntentPoint
    segments: list[IntentSegment] = Field(min_length=2)
    mode: Literal["add", "cut"] = "add"
    distance: float | None = Field(default=None, gt=0)
    centered: bool = True
    axis_start: IntentPoint | None = None
    axis_end: IntentPoint | None = None
    angle_degrees: float = Field(default=360, gt=0, le=360)

    @model_validator(mode="after")
    def required_operation_fields(self):
        if self.type == "profile_extrude" and self.distance is None:
            raise ValueError("profile_extrude requires distance")
        if self.type == "profile_revolve" and (
            self.axis_start is None or self.axis_end is None
        ):
            raise ValueError("profile_revolve requires axis_start and axis_end")
        return self


class SheetMetalFeatureIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["sheet_metal_bend"] = "sheet_metal_bend"
    id: str
    leg_a: float = Field(gt=0)
    leg_b: float = Field(gt=0)
    width: float = Field(gt=0)
    thickness: float = Field(gt=0)
    inside_radius: float = Field(ge=0)
    angle_degrees: float = Field(default=90, gt=0, le=180)
    k_factor: float = Field(default=0.44, ge=0, le=1)


class CurvedRodFeatureIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["curved_rod"] = "curved_rod"
    id: str
    diameter: float = Field(gt=0)
    total_length: float = Field(gt=0)
    bend_start: float = Field(ge=0)
    bend_radius: float = Field(gt=0)
    bend_angle_degrees: float = Field(gt=0, lt=360)
    plane: Literal["XY", "XZ", "YZ"] = "XY"


class RectangularLoftFeatureIntent(BaseModel):
    """A rectangular section changing linearly along its normal axis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["rectangular_loft"] = "rectangular_loft"
    id: str
    start_width: float = Field(gt=0)
    start_height: float = Field(gt=0)
    end_width: float = Field(gt=0)
    end_height: float = Field(gt=0)
    length: float = Field(gt=0)
    plane: Literal["XY", "XZ", "YZ"] = "XY"


class CurvedStripFeatureIntent(BaseModel):
    """Sweep a rectangular section along a straight–arc–straight path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["curved_strip"] = "curved_strip"
    id: str
    strip_width: float = Field(gt=0)
    extrusion_thickness: float = Field(gt=0)
    shank_length: float = Field(ge=0)
    bend_radius: float = Field(gt=0)
    bend_angle_degrees: float = Field(gt=0, lt=360)
    tail_length: float = Field(ge=0)
    plane: Literal["XY"] = "XY"


class ThreadedFastenerFeatureIntent(BaseModel):
    """A metric external-thread fastener with an integrated hex flange head."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["threaded_fastener"] = "threaded_fastener"
    id: str
    major_diameter: float = Field(gt=0)
    pitch: float = Field(gt=0)
    thread_length: float = Field(gt=0)
    shank_length: float = Field(ge=0)
    head_across_flats: float = Field(gt=0)
    head_height: float = Field(gt=0)
    flange_diameter: float = Field(gt=0)
    flange_thickness: float = Field(gt=0)


FeatureIntent = Annotated[
    Union[
        ProfileFeatureIntent, SheetMetalFeatureIntent, CurvedRodFeatureIntent,
        RectangularLoftFeatureIntent,
        CurvedStripFeatureIntent, ThreadedFastenerFeatureIntent,
    ],
    Field(discriminator="type")
]
