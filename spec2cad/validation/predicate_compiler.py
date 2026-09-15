"""Compile intent-graph requirement relations into geometric predicates."""

from __future__ import annotations

from spec2cad.schemas.design_intent import ConstraintSeverity
from spec2cad.schemas.intent_graph import (
    EdgeKind,
    EngineeringIntentGraph,
    FeatureNode,
    PartNode,
    RequirementNode,
)
from spec2cad.schemas.requirement_ir import (
    FeatureSelector,
    MinimumDistancePredicate,
    PartBoundarySelector,
    RequirementProgram,
)


class PredicateCompilationError(ValueError):
    pass


def compile_requirement_predicates(
    graph: EngineeringIntentGraph,
) -> RequirementProgram:
    part = next((node for node in graph.nodes if isinstance(node, PartNode)), None)
    if part is None:
        raise PredicateCompilationError("intent graph has no part boundary")

    predicates = []
    for requirement in graph.nodes:
        if not isinstance(requirement, RequirementNode):
            continue
        governed = graph.out_edges(requirement.id, EdgeKind.CONSTRAINS)
        if not governed:
            continue
        for relation in governed:
            feature = graph.node(relation.target)
            if not isinstance(feature, FeatureNode):
                raise PredicateCompilationError(
                    f"requirement {requirement.id!r} constrains a non-feature node"
                )
            if requirement.requirement_type != "min_hole_edge_clearance":
                raise PredicateCompilationError(
                    f"no predicate compiler for {requirement.requirement_type!r}"
                )
            predicates.append(MinimumDistancePredicate(
                id=f"predicate_{requirement.id}_{feature.id}",
                subject=FeatureSelector(feature_id=feature.id),
                target=PartBoundarySelector(part_id=part.id),
                threshold=requirement.value,
                unit="mm",
                hard=requirement.severity is ConstraintSeverity.HARD,
                source_requirement_id=requirement.id,
            ))
    return RequirementProgram(design_revision=graph.revision, predicates=predicates)
