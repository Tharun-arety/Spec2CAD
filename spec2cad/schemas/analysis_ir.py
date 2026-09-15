"""Typed inputs for engineering calculations; no hidden loads or materials."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class MaterialProperties(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    density_kg_m3: float = Field(gt=0)
    yield_strength_mpa: float | None = Field(default=None, gt=0)
    elastic_modulus_gpa: float | None = Field(default=None, gt=0)
    thermal_expansion_per_c: float | None = Field(default=None, gt=0)


class MassPropertiesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["mass_properties"] = "mass_properties"
    id: str = "mass_properties"


class AxialStressRequest(BaseModel):
    """Uniform axial-member calculation using B-Rep average section area."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["axial_stress"] = "axial_stress"
    id: str
    force_n: float
    load_path_length_mm: float = Field(gt=0)
    required_safety_factor: float = Field(default=1.0, gt=0)


class BendingStressRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["bending_stress"] = "bending_stress"
    id: str
    moment_n_mm: float
    section_modulus_mm3: float = Field(gt=0)
    required_safety_factor: float = Field(default=1.0, gt=0)


class ThermalExpansionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["thermal_expansion"] = "thermal_expansion"
    id: str
    original_length_mm: float = Field(gt=0)
    temperature_change_c: float


class FitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["fit"] = "fit"
    id: str
    hole_nominal_mm: float = Field(gt=0)
    hole_tolerance_mm: float = Field(ge=0)
    shaft_nominal_mm: float = Field(gt=0)
    shaft_tolerance_mm: float = Field(ge=0)
    require_clearance: bool = True


AnalysisRequest = Annotated[
    Union[
        MassPropertiesRequest, AxialStressRequest, BendingStressRequest,
        ThermalExpansionRequest, FitRequest,
    ],
    Field(discriminator="type"),
]


class AnalysisProgram(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    material: MaterialProperties
    requests: list[AnalysisRequest] = Field(default_factory=list, max_length=50)
