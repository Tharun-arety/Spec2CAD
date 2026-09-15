"""Typed contract between the conversational planner and deterministic CAD tools."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


AgentAction = Literal["execute", "clarify", "explain", "unsupported"]
CADToolName = Literal[
    "box",
    "cylinder",
    "tube",
    "hole",
    "rectangular_hole_pattern",
    "linear_slot_pattern",
    "chamfer",
    "fillet",
    "profile_extrude",
    "profile_revolve",
    "curved_rod_sweep",
    "rectangular_loft",
    "curved_strip_sweep",
    "threaded_fastener",
    "sheet_metal_90_bend",
]


class AgentToolArgument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    value: float | int | str | bool | None = None
    unit: str | None = None
    source: str = Field(description="Short provenance phrase from the user's evidence")


class AgentToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: CADToolName
    purpose: str
    arguments: list[AgentToolArgument] = Field(default_factory=list)


class ClarificationOption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    value: str
    description: str


class ClarificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    question: str
    why: str
    options: list[ClarificationOption] = Field(default_factory=list, max_length=4)
    allow_free_text: bool = True


class AgentPlan(BaseModel):
    """User-visible interpretation and the tool path selected for one turn."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: AgentAction
    summary: str
    steps: list[str] = Field(default_factory=list, max_length=8)
    tool_calls: list[AgentToolCall] = Field(default_factory=list, max_length=12)
    clarifications: list[ClarificationRequest] = Field(default_factory=list, max_length=4)
