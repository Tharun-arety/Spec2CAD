"""Compile DesignIntent into a typed CADProgram.

This is a separate stage from execution on purpose. The compiler decides *what
features exist and in what order*; the executor decides *how to build them*.
Keeping them apart means the feature plan can be inspected, diffed between
revisions, and validated for satisfiability before a CAD kernel is ever started.

Parameters are referenced, not inlined, so the program for v1 and the program
for v2 are structurally identical and differ only in the parameter table they
resolve against. That is what makes "the same design, one value changed"
literally true rather than a figure of speech.
"""

from __future__ import annotations

from spec2cad.schemas.cad_ir import (
    BoxOp,
    CADProgram,
    ChamferOp,
    EdgeSelector,
    FaceSelector,
    HoleOp,
    RectangularHolePatternOp,
    Termination,
    ref,
)
from spec2cad.schemas.design_intent import DesignIntent


class CompilationError(ValueError):
    """Raised when DesignIntent cannot be expressed as a feature plan."""


REQUIRED_FOR_COMPILATION = [
    "plate_width",
    "plate_height",
    "plate_thickness",
]


def compile_design(intent: DesignIntent) -> CADProgram:
    """Produce the feature plan for a motor adapter plate."""
    missing = [n for n in REQUIRED_FOR_COMPILATION if not intent.has(n)]
    if missing:
        raise CompilationError(
            f"cannot compile without {', '.join(missing)}; "
            f"these have no value in DesignIntent v{intent.revision}"
        )

    operations: list = [
        BoxOp(
            id="base_plate",
            width=ref("plate_width"),
            height=ref("plate_height"),
            depth=ref("plate_thickness"),
            centered=True,
        )
    ]

    # The plate must clear the motor's pilot boss.
    if intent.has("shaft_opening_diameter"):
        operations.append(
            HoleOp(
                id="shaft_opening",
                support=FaceSelector.TOP_FACE,
                diameter=ref("shaft_opening_diameter"),
                termination=Termination.THROUGH_ALL,
            )
        )

    # The mounting pattern comes from the interface, which the datasheet owns.
    if intent.has("hole_spacing_x") and intent.has("mounting_hole_diameter"):
        count = int(intent.value_of("mounting_hole_count")) if intent.has(
            "mounting_hole_count"
        ) else 4
        operations.append(
            RectangularHolePatternOp(
                id="mounting_holes",
                support=FaceSelector.TOP_FACE,
                diameter=ref("mounting_hole_diameter"),
                spacing_x=ref("hole_spacing_x"),
                spacing_y=ref("hole_spacing_y"),
                count=count,
                termination=Termination.THROUGH_ALL,
            )
        )

    if intent.has("external_chamfer"):
        operations.append(
            ChamferOp(
                id="external_chamfers",
                edge_selector=EdgeSelector.EXTERNAL_VERTICAL_EDGES,
                distance=ref("external_chamfer"),
            )
        )

    program = CADProgram(
        part_name=intent.part.name,
        operations=operations,
        design_revision=intent.revision,
    )

    # Fail now, not mid-build, if the plan references something unresolvable.
    unresolvable = [
        name for name in program.referenced_parameters if not intent.has(name)
    ]
    if unresolvable:
        raise CompilationError(
            f"feature plan references parameters with no value: {', '.join(unresolvable)}"
        )
    return program


def parameter_table(intent: DesignIntent) -> dict[str, float]:
    """The numeric table a CADProgram resolves its references against."""
    return {
        name: float(p.value)
        for name, p in intent.parameters.items()
        if isinstance(p.value, (int, float))
    }
