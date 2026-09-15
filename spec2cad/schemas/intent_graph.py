"""EngineeringIntentGraph: design intent as a graph rather than a parameter table.

DesignIntent answers "what is plate_width?". It cannot answer "which hole
pattern does this clearance requirement govern?", "what is this opening derived
from?", or "if the motor changes, what else moves?" -- because the relationships
that would carry those answers are currently either flattened into a string
(`derivation="pilot boss 22 mm + 0.5 mm fit allowance"`), duplicated as copied
floats (`Interface.spacing_x` holds its own copy of `hole_spacing_x`), or
implied by a type tag a validator switches on (`Constraint.type`).

The graph keeps those relationships as edges, so they can be traversed instead
of parsed. Four things that were previously unreachable become reachable:

  1. `shaft_opening_diameter` --derived_from--> `motor_boss_diameter`, a real
     edge rather than a sentence a human has to read.
  2. An interface no longer copies the pattern's numbers. It points at the same
     DimensionNodes the pattern points at, so there is one source of truth.
  3. A requirement points at the feature it governs, which is the seed of a
     requirement predicate IR: "min edge clearance" stops being a magic string
     and becomes (requirement, constrains, hole_pattern).
  4. Explicitly disagreeing sources become `conflicts_with` edges between the
     candidate dimensions instead of an opaque `competing_values` blob.

`project_to_design_intent` still reproduces the established DesignIntent exactly,
and parity tests protect the compatibility layer. The live pipeline now gives
the graph to the feature compiler and requirement-predicate compiler directly;
the flat view remains for validators, repair policy, API compatibility, and
incremental migration.

ReferenceGeometry is introduced only for references a consumer actually uses:
the top face and external vertical edge set. AssemblyEntity, general datums, and
`depends_on` remain absent until a real assembly or feature requires them.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from spec2cad.schemas.design_intent import ConstraintSeverity, ParameterStatus
from spec2cad.schemas.evidence import Authority
from spec2cad.schemas.advanced_intent import FeatureIntent


class NodeKind(str, Enum):
    PART = "part"
    FEATURE = "feature"
    INTERFACE = "interface"
    DIMENSION = "dimension"
    REQUIREMENT = "requirement"
    MATERIAL = "material"
    PROCESS = "process"
    EVIDENCE = "evidence"
    REFERENCE_GEOMETRY = "reference_geometry"
    ADVANCED_FEATURE = "advanced_feature"


class FeatureType(str, Enum):
    """What a feature *is*, independent of how any one kernel builds it.

    Kept separate from the CAD IR's operation types on purpose. `BASE_SOLID` is
    a box today, but an L-bracket's base solid is an extruded profile, and the
    intent layer should not have to care which.
    """

    BASE_SOLID = "base_solid"
    OPENING = "opening"
    HOLE_PATTERN = "hole_pattern"
    EDGE_TREATMENT = "edge_treatment"
    SLOT_PATTERN = "slot_pattern"
    FILLET = "fillet"
    CYLINDER_BASE = "cylinder_base"
    TUBE_BASE = "tube_base"


class ReferenceType(str, Enum):
    FACE = "face"
    EDGE_SET = "edge_set"


class ReferenceSelector(str, Enum):
    TOP_FACE = "top_face"
    EXTERNAL_VERTICAL_EDGES = "external_vertical_edges"


class EdgeKind(str, Enum):
    HAS_FEATURE = "has_feature"          # part      -> feature
    HAS_INTERFACE = "has_interface"      # part      -> interface
    DEFINES = "defines"                  # dimension -> feature | interface
    CONSTRAINS = "constrains"            # requirement -> feature
    DERIVED_FROM = "derived_from"        # dimension -> dimension
    SUPPORTED_BY = "supported_by"        # any       -> evidence
    CONFLICTS_WITH = "conflicts_with"    # dimension -> dimension
    MADE_OF = "made_of"                  # part      -> material
    PRODUCED_BY = "produced_by"          # part      -> process
    LOCATED_RELATIVE_TO = "located_relative_to"  # feature -> reference geometry


class _Node(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    label: str = ""


class PartNode(_Node):
    kind: Literal[NodeKind.PART] = NodeKind.PART
    name: str
    part_type: str = "part"


class MaterialNode(_Node):
    kind: Literal[NodeKind.MATERIAL] = NodeKind.MATERIAL
    name: str


class ProcessNode(_Node):
    kind: Literal[NodeKind.PROCESS] = NodeKind.PROCESS
    name: str


class DimensionNode(_Node):
    """One scalar of design intent.

    Carries everything Parameter does except provenance, which is held as
    SUPPORTED_BY edges. Storing it in both places would let the two disagree,
    and the edge is the version the rest of the graph can traverse.
    """

    kind: Literal[NodeKind.DIMENSION] = NodeKind.DIMENSION
    name: str
    value: float | int | str | None = None
    unit: Optional[str] = None
    status: ParameterStatus = ParameterStatus.CONFIRMED
    authority: Authority = Authority.SUPPORTING
    is_explicit: bool = False
    derivation: Optional[str] = None
    competing_values: list[dict[str, Any]] = Field(default_factory=list)


class FeatureNode(_Node):
    kind: Literal[NodeKind.FEATURE] = NodeKind.FEATURE
    feature_type: FeatureType


class AdvancedFeatureNode(_Node):
    """A schema-validated profile or sheet feature, independent of part name."""

    kind: Literal[NodeKind.ADVANCED_FEATURE] = NodeKind.ADVANCED_FEATURE
    request: FeatureIntent


class InterfaceNode(_Node):
    kind: Literal[NodeKind.INTERFACE] = NodeKind.INTERFACE
    name: str
    placement: str = "symmetric_about_origin"
    unit: str = "mm"


class RequirementNode(_Node):
    kind: Literal[NodeKind.REQUIREMENT] = NodeKind.REQUIREMENT
    requirement_type: str
    value: float
    unit: str = "mm"
    severity: ConstraintSeverity = ConstraintSeverity.HARD
    description: str = ""


class EvidenceNode(_Node):
    """A pointer to one Evidence item, not a copy of it.

    The EvidenceSet stays the store. Duplicating the value here would create a
    second place for it to be wrong.
    """

    kind: Literal[NodeKind.EVIDENCE] = NodeKind.EVIDENCE
    target: str
    modality: str


class ReferenceGeometryNode(_Node):
    """A semantic datum selected later by each kernel adapter."""

    kind: Literal[NodeKind.REFERENCE_GEOMETRY] = NodeKind.REFERENCE_GEOMETRY
    reference_type: ReferenceType
    selector: ReferenceSelector


AnyNode = Annotated[
    Union[
        PartNode, MaterialNode, ProcessNode, DimensionNode,
        FeatureNode, AdvancedFeatureNode, InterfaceNode, RequirementNode, EvidenceNode,
        ReferenceGeometryNode,
    ],
    Field(discriminator="kind"),
]


class Edge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    target: str
    kind: EdgeKind
    role: Optional[str] = Field(
        default=None,
        description="which part this plays, e.g. a DEFINES edge with role "
        "'spacing_x'. Keeps the edge vocabulary small without losing meaning.",
    )


class EngineeringIntentGraph(BaseModel):
    """An immutable graph of one design revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    revision: int = 1
    nodes: list[AnyNode] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)

    # ---------- access ----------

    def node(self, node_id: str) -> AnyNode:
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(f"no node {node_id!r} in the intent graph")

    def has_node(self, node_id: str) -> bool:
        return any(n.id == node_id for n in self.nodes)

    def nodes_of(self, kind: NodeKind) -> list[AnyNode]:
        return [n for n in self.nodes if n.kind is kind]

    def dimension(self, name: str) -> Optional[DimensionNode]:
        for n in self.nodes:
            if isinstance(n, DimensionNode) and n.name == name:
                return n
        return None

    def out_edges(
        self, node_id: str, kind: Optional[EdgeKind] = None,
        role: Optional[str] = None,
    ) -> list[Edge]:
        return [
            e for e in self.edges
            if e.source == node_id
            and (kind is None or e.kind is kind)
            and (role is None or e.role == role)
        ]

    def in_edges(
        self, node_id: str, kind: Optional[EdgeKind] = None,
        role: Optional[str] = None,
    ) -> list[Edge]:
        return [
            e for e in self.edges
            if e.target == node_id
            and (kind is None or e.kind is kind)
            and (role is None or e.role == role)
        ]

    def supporting_evidence(self, node_id: str) -> list[str]:
        """Evidence ids backing this node, in the order they were attached."""
        return [e.target for e in self.out_edges(node_id, EdgeKind.SUPPORTED_BY)]

    def defining_dimension(
        self, node_id: str, role: str
    ) -> Optional[DimensionNode]:
        """The dimension playing `role` for this feature or interface."""
        for e in self.in_edges(node_id, EdgeKind.DEFINES, role=role):
            found = self.node(e.source)
            if isinstance(found, DimensionNode):
                return found
        return None

    def feature_ids(self) -> list[str]:
        return [n.id for n in self.nodes if isinstance(n, FeatureNode)]

    def validate_edges(self) -> list[str]:
        """Dangling edges, if any. A graph that references a node it does not
        contain is a builder bug, and silently traversing past it would hide it."""
        ids = {n.id for n in self.nodes}
        problems = []
        for e in self.edges:
            if e.source not in ids:
                problems.append(f"{e.kind.value} edge from unknown node {e.source!r}")
            if e.target not in ids:
                problems.append(f"{e.kind.value} edge to unknown node {e.target!r}")
        return problems
