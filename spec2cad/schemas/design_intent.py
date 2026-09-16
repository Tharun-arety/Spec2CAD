"""DesignIntent: the consolidated, model-independent engineering representation.

This is the layer a CAD kernel never sees and an extractor never writes. It sits
between them so that "what the engineer means" can be reasoned about, argued
with, and *revised* without touching either geometry or sources.

Revisions are immutable. A repair does not mutate a parameter; it derives
DesignIntent v2 from v1, recording what changed, which proposal caused it, and
who approved it. v1 remains intact and retrievable forever. This is what makes
the audit trail real rather than decorative -- you can always answer "what did
we believe before the human intervened, and why did that change?"
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from spec2cad.schemas.evidence import Authority, SemanticTarget


class ParameterStatus(str, Enum):
    CONFIRMED = "confirmed"
    INFERRED = "inferred"                    # derived via a cited rule
    CONFLICTING = "conflicting"              # participates in a constraint conflict
    ADJUDICATION_REQUIRED = "adjudication_required"  # sources disagree explicitly
    MISSING = "missing"


class ConstraintSeverity(str, Enum):
    HARD = "hard"   # violation blocks release
    SOFT = "soft"   # violation warns only


class Parameter(BaseModel):
    """One scalar design parameter with full provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    value: float | int | str | None
    unit: Optional[str] = None
    status: ParameterStatus = ParameterStatus.CONFIRMED

    provenance: list[str] = Field(
        default_factory=list, description="Evidence ids that support this value"
    )
    authority: Authority = Authority.SUPPORTING
    is_explicit: bool = Field(
        default=False,
        description="backed by an explicit annotation rather than an inference",
    )
    derivation: Optional[str] = Field(
        default=None, description="cited rule when status is INFERRED, e.g. 'ISO 273 (medium)'"
    )
    competing_values: list[dict[str, Any]] = Field(
        default_factory=list,
        description="populated when sources disagree explicitly; never auto-collapsed",
    )

    @property
    def numeric(self) -> float:
        if not isinstance(self.value, (int, float)):
            raise TypeError(f"parameter {self.name!r} is not numeric: {self.value!r}")
        return float(self.value)


class Interface(BaseModel):
    """A mating interface -- the part of the design another component dictates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    hole_count: int
    hole_diameter: float
    spacing_x: float
    spacing_y: float
    placement: str = "symmetric_about_origin"
    unit: str = "mm"
    provenance: list[str] = Field(default_factory=list)

    @property
    def is_interface_critical(self) -> bool:
        """Changing these values changes what the part can physically bolt to.
        The repair planner uses this to refuse 'just move the holes' fixes."""
        return True


class Constraint(BaseModel):
    """A requirement the finished geometry must satisfy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    type: str
    value: float
    unit: str = "mm"
    severity: ConstraintSeverity = ConstraintSeverity.HARD
    description: str = ""
    provenance: list[str] = Field(default_factory=list)


class PartInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    material: Optional[str] = None
    manufacturing_process: Optional[str] = None
    provenance: list[str] = Field(default_factory=list)


class ParameterChange(BaseModel):
    """A single before/after delta between two revisions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    parameter: str
    before: float | int | str | None
    after: float | int | str | None
    reason: str


class DesignIntent(BaseModel):
    """An immutable revision of the consolidated design intent.

    frozen=True blocks attribute assignment, so a repair cannot quietly edit a
    parameter in place -- it must go through derive() and leave a record.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    revision: int = 1
    parent_revision: Optional[int] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    applied_proposal: Optional[str] = Field(
        default=None, description="id of the repair proposal that produced this revision"
    )
    approved_by: Optional[str] = Field(
        default=None, description="who authorised the change; None for the original"
    )
    changes: list[ParameterChange] = Field(default_factory=list)

    part: PartInfo
    parameters: dict[str, Parameter] = Field(default_factory=dict)
    interfaces: list[Interface] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)

    # ---------- access ----------

    def param(self, name: str | SemanticTarget) -> Parameter:
        key = name.value if isinstance(name, SemanticTarget) else name
        if key not in self.parameters:
            raise KeyError(f"no parameter {key!r} in DesignIntent v{self.revision}")
        return self.parameters[key]

    def value_of(self, name: str | SemanticTarget) -> float:
        return self.param(name).numeric

    def has(self, name: str | SemanticTarget) -> bool:
        key = name.value if isinstance(name, SemanticTarget) else name
        return key in self.parameters and self.parameters[key].value is not None

    def constraint(self, constraint_type: str) -> Optional[Constraint]:
        return next((c for c in self.constraints if c.type == constraint_type), None)

    @property
    def missing_parameters(self) -> list[str]:
        return [n for n, p in self.parameters.items() if p.value is None]

    # ---------- revision ----------

    def derive(
        self,
        *,
        updates: dict[str, float | int | str],
        proposal_id: str,
        approved_by: str,
        reason: str,
        status: ParameterStatus = ParameterStatus.CONFIRMED,
    ) -> "DesignIntent":
        """Produce the next revision. Never mutates self.

        Every changed parameter is recorded with its before/after value and the
        proposal that justified it, so the lineage explains itself.
        """
        if not updates:
            raise ValueError("derive() requires at least one parameter update")

        new_params = {k: v.model_copy(deep=True) for k, v in self.parameters.items()}
        recorded: list[ParameterChange] = []

        for name, new_value in updates.items():
            if name not in new_params:
                raise KeyError(f"cannot update unknown parameter {name!r}")
            before = new_params[name].value
            new_params[name] = new_params[name].model_copy(
                update={"value": new_value, "status": status}
            )
            recorded.append(
                ParameterChange(parameter=name, before=before, after=new_value, reason=reason)
            )

        return DesignIntent(
            revision=self.revision + 1,
            parent_revision=self.revision,
            applied_proposal=proposal_id,
            approved_by=approved_by,
            changes=recorded,
            part=self.part.model_copy(deep=True),
            parameters=new_params,
            interfaces=[i.model_copy(deep=True) for i in self.interfaces],
            constraints=[c.model_copy(deep=True) for c in self.constraints],
        )

    def lineage_summary(self) -> str:
        if self.parent_revision is None:
            return f"v{self.revision} (original)"
        deltas = ", ".join(f"{c.parameter}: {c.before} -> {c.after}" for c in self.changes)
        return (
            f"v{self.revision} from v{self.parent_revision} "
            f"via {self.applied_proposal} approved by {self.approved_by} [{deltas}]"
        )
