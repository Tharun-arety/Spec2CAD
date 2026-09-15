"""Typed assembly intent: components, placement and verifiable mates."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from spec2cad.schemas.cad_ir import CADProgram


class Transform(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    translation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation_axis: tuple[float, float, float] = (0.0, 0.0, 1.0)
    rotation_degrees: float = 0.0

    @model_validator(mode="after")
    def axis_is_nonzero(self):
        if sum(v * v for v in self.rotation_axis) <= 1e-18:
            raise ValueError("rotation_axis must be non-zero")
        return self


class ComponentInstance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    program: CADProgram
    parameters: dict[str, float] = Field(default_factory=dict, max_length=128)
    transform: Transform = Transform()


class CoincidentOriginMate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["coincident_origins"] = "coincident_origins"
    id: str
    component_a: str
    component_b: str
    tolerance_mm: float = Field(default=1e-4, gt=0)


class OffsetMate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["offset"] = "offset"
    id: str
    component_a: str
    component_b: str
    axis: Literal["x", "y", "z"]
    distance_mm: float
    tolerance_mm: float = Field(default=1e-4, gt=0)


class ConcentricAxisMate(BaseModel):
    """Validate two explicitly identified global assembly axes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["concentric_axes"] = "concentric_axes"
    id: str
    component_a: str
    component_b: str
    axis_a: tuple[float, float, float]
    axis_b: tuple[float, float, float]
    tolerance_mm: float = Field(default=1e-4, gt=0)
    angular_tolerance_degrees: float = Field(default=1e-3, gt=0)


MateConstraint = Annotated[
    Union[CoincidentOriginMate, OffsetMate, ConcentricAxisMate],
    Field(discriminator="type"),
]


class AssemblyProgram(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    components: list[ComponentInstance] = Field(min_length=2, max_length=20)
    mates: list[MateConstraint] = Field(default_factory=list, max_length=100)
    check_collisions: bool = True
    allowed_contacts: set[frozenset[str]] = Field(default_factory=set, max_length=100)

    @model_validator(mode="after")
    def references_exist(self):
        ids = [component.id for component in self.components]
        if len(ids) != len(set(ids)):
            raise ValueError("assembly component ids must be unique")
        known = set(ids)
        for mate in self.mates:
            missing = {mate.component_a, mate.component_b} - known
            if missing:
                raise ValueError(f"mate {mate.id!r} references unknown components {sorted(missing)}")
        return self
