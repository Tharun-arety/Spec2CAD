"""Which source is entitled to define which fact.

This is the ownership table, and it is the only place that decides authority.
Extractors call into it rather than each asserting their own authority, so the
policy cannot drift between modalities.

The important subtlety (and the thing an earlier draft got wrong) is that this
table does NOT settle disagreements on its own. A blanket "datasheet beats
sketch" rule would silently discard an explicit dimension a human wrote on a
drawing, which is exactly the kind of quiet overrule that makes a system
untrustworthy. Authority ranks *candidates*; it never overrules an explicit
annotation. See conflict_detector.resolve_target for how that plays out:

  - one explicit claim            -> use it
  - explicit vs inferred          -> explicit wins, regardless of modality
  - two explicit claims agreeing  -> use it, note corroboration
  - two explicit claims differing -> ADJUDICATION_REQUIRED, never auto-resolved
"""

from __future__ import annotations

from spec2cad.schemas.evidence import Authority, SemanticTarget, SourceModality

T = SemanticTarget
M = SourceModality

# Facts dictated by the mating component. The datasheet physically owns these:
# getting them "right" per the sketch would still produce a part that does not bolt on.
INTERFACE_TARGETS: frozenset[SemanticTarget] = frozenset({
    T.HOLE_SPACING_X,
    T.HOLE_SPACING_Y,
    T.MOUNTING_HOLE_COUNT,
    T.MOUNTING_THREAD_SPEC,
    T.MOTOR_BOSS_DIAMETER,
})

# Facts the written requirement owns: what it is made of and what it must satisfy.
REQUIREMENT_TARGETS: frozenset[SemanticTarget] = frozenset({
    T.MATERIAL,
    T.PLATE_THICKNESS,
    T.MIN_HOLE_EDGE_CLEARANCE,
    T.EXTERNAL_CHAMFER,
    T.MANUFACTURING_PROCESS,
})

# Facts only the drawing describes: the envelope of the part being designed.
ENVELOPE_TARGETS: frozenset[SemanticTarget] = frozenset({
    T.PLATE_WIDTH,
    T.PLATE_HEIGHT,
})


def authority_for(
    modality: SourceModality, target: SemanticTarget, is_explicit: bool
) -> Authority:
    """Rank this source's entitlement to define this target."""
    # A value derived from a cited standard is definitive for what it computes.
    if modality is M.ENGINEERING_RULE:
        return Authority.DEFINITIVE

    if modality is M.DATASHEET:
        return Authority.DEFINITIVE if target in INTERFACE_TARGETS else Authority.SUPPORTING

    if modality is M.REQUIREMENT_TEXT:
        if target in REQUIREMENT_TARGETS:
            # An inferred process spec is advisory even though text owns the field.
            return Authority.DEFINITIVE if is_explicit else Authority.ADVISORY
        # Text may mention interface facts, but the datasheet owns them.
        return Authority.SUPPORTING

    if modality is M.SKETCH:
        if target in ENVELOPE_TARGETS:
            # An annotated dimension is exact evidence; a scaled-off one is not.
            return Authority.DEFINITIVE if is_explicit else Authority.ADVISORY
        if target in INTERFACE_TARGETS:
            return Authority.SUPPORTING
        return Authority.SUPPORTING if is_explicit else Authority.ADVISORY

    return Authority.SUPPORTING


def owning_modality(target: SemanticTarget) -> SourceModality | None:
    """The modality expected to own a target, for explaining decisions."""
    if target in INTERFACE_TARGETS:
        return M.DATASHEET
    if target in REQUIREMENT_TARGETS:
        return M.REQUIREMENT_TEXT
    if target in ENVELOPE_TARGETS:
        return M.SKETCH
    return None


def is_interface_critical(target: SemanticTarget) -> bool:
    """True when changing this value changes what the part can bolt to.

    The repair planner uses this to mark "just move the holes" proposals unsafe.
    """
    return target in INTERFACE_TARGETS
