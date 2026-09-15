"""Typed geometric predicates compiled from engineering requirements.

Requirements are no longer validator function names in disguise. This IR says
which semantic feature is governed, what geometry it is compared with, and the
threshold. Kernel-specific measurement remains downstream.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class FeatureSelector(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["feature"] = "feature"
    feature_id: str


class PartBoundarySelector(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["part_boundary"] = "part_boundary"
    part_id: str


GeometrySelector = Annotated[
    Union[FeatureSelector, PartBoundarySelector], Field(discriminator="kind")
]


class MinimumDistancePredicate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["minimum_distance"] = "minimum_distance"
    id: str
    subject: FeatureSelector
    target: PartBoundarySelector
    threshold: float
    unit: Literal["mm"] = "mm"
    hard: bool = True
    source_requirement_id: str


RequirementPredicate = Annotated[
    Union[MinimumDistancePredicate], Field(discriminator="type")
]


class RequirementProgram(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    design_revision: int
    predicates: list[RequirementPredicate] = Field(default_factory=list)
