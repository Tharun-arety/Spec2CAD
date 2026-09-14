"""CADProgram: a typed, kernel-agnostic feature plan.

This is deliberately *not* Python, and deliberately not a direct serialisation of
DesignIntent. It is the narrow, checkable waist of the pipeline:

  - A model may propose operations, but it can only ever produce values that fit
    this schema. It cannot emit code, so there is no arbitrary Python to sandbox.
  - The executor owns every CAD call. If an operation type is unknown, execution
    fails loudly rather than falling back to something plausible.

Numeric fields use an explicit tagged union -- NumberLiteral or ParamRef -- never
a stringly-typed `float | str` overload where "45" and "plate_width" would be
told apart by guessing at runtime. A reference is a distinct type, and an
unresolvable one is an error at resolve time with the offending name reported.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------
# Numeric values: literal or parameter reference, discriminated explicitly
# --------------------------------------------------------------------------


class NumberLiteral(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["literal"] = "literal"
    value: float


class ParamRef(BaseModel):
    """A reference to a DesignIntent parameter, resolved at execution time."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["param_ref"] = "param_ref"
    ref: str


Numeric = Annotated[Union[NumberLiteral, ParamRef], Field(discriminator="kind")]


def lit(value: float) -> NumberLiteral:
    return NumberLiteral(value=float(value))


def ref(name: str) -> ParamRef:
    return ParamRef(ref=name)


class UnresolvedReference(KeyError):
    """Raised when a ParamRef names a parameter that does not exist."""


def resolve(numeric: NumberLiteral | ParamRef, values: dict[str, float]) -> float:
    """Resolve a Numeric against a parameter table.

    Unknown references raise rather than defaulting, so a typo in a reference
    can never silently become geometry.
    """
    if isinstance(numeric, NumberLiteral):
        return float(numeric.value)
    if numeric.ref not in values:
        raise UnresolvedReference(
            f"CADProgram references unknown parameter {numeric.ref!r}; "
            f"known parameters: {sorted(values)}"
        )
    value = values[numeric.ref]
    if value is None:
        raise UnresolvedReference(f"parameter {numeric.ref!r} has no value")
    return float(value)


# --------------------------------------------------------------------------
# Selectors: named intent, never kernel selector strings
# --------------------------------------------------------------------------


class EdgeSelector(str, Enum):
    """Named edge sets. The IR never carries CadQuery selector syntax; the
    mapping from these names to kernel selectors lives in cad/selectors.py."""

    EXTERNAL_VERTICAL_EDGES = "external_vertical_edges"
    EXTERNAL_TOP_PERIMETER = "external_top_perimeter"


class FaceSelector(str, Enum):
    TOP_FACE = "top_face"
    BOTTOM_FACE = "bottom_face"


class Termination(str, Enum):
    THROUGH_ALL = "through_all"
    BLIND = "blind"


# --------------------------------------------------------------------------
# Operations
# --------------------------------------------------------------------------


class BoxOp(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["box"] = "box"
    id: str
    width: Numeric
    height: Numeric
    depth: Numeric
    centered: bool = True


class HoleOp(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["hole"] = "hole"
    id: str
    support: FaceSelector = FaceSelector.TOP_FACE
    diameter: Numeric
    x: Numeric = NumberLiteral(value=0.0)
    y: Numeric = NumberLiteral(value=0.0)
    termination: Termination = Termination.THROUGH_ALL
    depth: Optional[Numeric] = None


class RectangularHolePatternOp(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["rectangular_hole_pattern"] = "rectangular_hole_pattern"
    id: str
    support: FaceSelector = FaceSelector.TOP_FACE
    diameter: Numeric
    spacing_x: Numeric
    spacing_y: Numeric
    count: int = 4
    termination: Termination = Termination.THROUGH_ALL


class ChamferOp(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["chamfer"] = "chamfer"
    id: str
    edge_selector: EdgeSelector
    distance: Numeric


Operation = Annotated[
    Union[BoxOp, HoleOp, RectangularHolePatternOp, ChamferOp],
    Field(discriminator="type"),
]


class CADProgram(BaseModel):
    """An ordered feature plan. Execution order is list order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    part_name: str
    units: Literal["mm"] = "mm"
    operations: list[Operation] = Field(default_factory=list)
    design_revision: int = Field(
        default=1, description="the DesignIntent revision this program was compiled from"
    )

    def operation(self, op_id: str) -> Operation:
        for op in self.operations:
            if op.id == op_id:
                return op
        raise KeyError(f"no operation {op_id!r}")

    @property
    def referenced_parameters(self) -> set[str]:
        """Every parameter name this program depends on. Used by schema
        validation to check the program is satisfiable before execution."""
        names: set[str] = set()

        def walk(value: object) -> None:
            if isinstance(value, ParamRef):
                names.add(value.ref)
            elif isinstance(value, BaseModel):
                for field in type(value).model_fields:
                    walk(getattr(value, field))
            elif isinstance(value, (list, tuple)):
                for item in value:
                    walk(item)

        for op in self.operations:
            walk(op)
        return names

    def feature_sequence(self) -> list[str]:
        return [f"{op.id} ({op.type})" for op in self.operations]

    def describe(self, values: dict[str, float]) -> list[dict]:
        """Each operation with its numeric fields resolved.

        Returned so a caller can show what a feature actually is -- the value
        used, and the parameter it came from -- rather than just its name.
        """
        out: list[dict] = []
        for op in self.operations:
            fields: list[dict] = []
            for name in type(op).model_fields:
                if name in ("id", "type"):
                    continue
                value = getattr(op, name)
                if isinstance(value, (NumberLiteral, ParamRef)):
                    try:
                        resolved = resolve(value, values)
                    except UnresolvedReference:
                        resolved = None
                    fields.append({
                        "name": name,
                        "value": resolved,
                        "parameter": value.ref if isinstance(value, ParamRef) else None,
                    })
                elif value is None:
                    continue
                else:
                    fields.append({
                        "name": name,
                        "value": value.value if hasattr(value, "value") else value,
                        "parameter": None,
                    })
            out.append({"id": op.id, "type": op.type, "fields": fields})
        return out
