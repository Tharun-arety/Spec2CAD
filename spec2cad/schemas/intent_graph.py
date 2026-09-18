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
import math
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class InterfaceType(str, Enum):
    MOUNTING_PATTERN = "mounting_pattern"
    PLANAR = "planar"
    CYLINDRICAL = "cylindrical"
    CUSTOM = "custom"


class InterfaceGeometryKind(str, Enum):
    FEATURE = "feature"
    HOLE_PATTERN = "hole_pattern"
    BORE = "bore"
    DATUM = "datum"


class InterfaceFitKind(str, Enum):
    CLEARANCE = "clearance"
    TRANSITION = "transition"
    INTERFERENCE = "interference"
    UNDEFINED = "undefined"


class InterfaceCoordinateSystem(_Node):
    origin_mm: tuple[float, float, float]
    x_axis: tuple[float, float, float]
    y_axis: tuple[float, float, float]
    z_axis: tuple[float, float, float]

    @model_validator(mode="after")
    def validate_frame(self) -> "InterfaceCoordinateSystem":
        vectors = (self.x_axis, self.y_axis, self.z_axis)
        if not all(math.isfinite(value) for vector in vectors for value in vector):
            raise ValueError("coordinate axes must be finite")
        if not all(math.isfinite(value) for value in self.origin_mm):
            raise ValueError("coordinate origin must be finite")

        def dot(left, right):
            return sum(a * b for a, b in zip(left, right))

        if any(abs(dot(vector, vector) - 1.0) > 1e-9 for vector in vectors) or any(
            abs(dot(left, right)) > 1e-9
            for left, right in (
                (self.x_axis, self.y_axis),
                (self.x_axis, self.z_axis),
                (self.y_axis, self.z_axis),
            )
        ):
            raise ValueError("coordinate axes must be orthonormal")
        cross = (
            self.x_axis[1] * self.y_axis[2] - self.x_axis[2] * self.y_axis[1],
            self.x_axis[2] * self.y_axis[0] - self.x_axis[0] * self.y_axis[2],
            self.x_axis[0] * self.y_axis[1] - self.x_axis[1] * self.y_axis[0],
        )
        if any(abs(actual - expected) > 1e-9 for actual, expected in zip(cross, self.z_axis)):
            raise ValueError("coordinate axes must be right-handed")
        return self


class InterfaceGeometryBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    geometry_kind: InterfaceGeometryKind = InterfaceGeometryKind.FEATURE


class InterfaceDimensionBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str = Field(min_length=1)
    dimension_id: str = Field(min_length=1)
    protected: bool = True


class InterfaceFitSpecification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fit_kind: InterfaceFitKind
    tolerance_policy_id: str = Field(min_length=1)
    tolerance_policy_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    designation: str = Field(min_length=1)
    minimum_clearance_mm: float | None = Field(default=None, allow_inf_nan=False)
    maximum_clearance_mm: float | None = Field(default=None, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_clearance_bounds(self) -> "InterfaceFitSpecification":
        if (self.minimum_clearance_mm is None) != (self.maximum_clearance_mm is None):
            raise ValueError("fit clearance bounds must be provided together")
        if (
            self.minimum_clearance_mm is not None
            and self.minimum_clearance_mm > self.maximum_clearance_mm
        ):
            raise ValueError("minimum clearance cannot exceed maximum clearance")
        if (
            self.fit_kind is InterfaceFitKind.CLEARANCE
            and self.minimum_clearance_mm is not None
            and self.minimum_clearance_mm < 0
        ):
            raise ValueError("clearance fit cannot have negative minimum clearance")
        return self


class CompatibleInterfaceCounterpart(_Node):
    interface_type: InterfaceType
    source_evidence_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_evidence_ids(self) -> "CompatibleInterfaceCounterpart":
        if len(self.source_evidence_ids) != len(set(self.source_evidence_ids)):
            raise ValueError("counterpart source evidence ids must be unique")
        return self


class InterfaceNode(_Node):
    kind: Literal[NodeKind.INTERFACE] = NodeKind.INTERFACE
    name: str
    placement: str = "symmetric_about_origin"
    unit: str = "mm"
    contract_version: Literal["1.0.0"] | None = None
    interface_type: InterfaceType = InterfaceType.CUSTOM
    coordinate_system: InterfaceCoordinateSystem | None = None
    governed_geometry: tuple[InterfaceGeometryBinding, ...] = ()
    governed_dimensions: tuple[InterfaceDimensionBinding, ...] = ()
    fit: InterfaceFitSpecification | None = None
    compatible_counterpart: CompatibleInterfaceCounterpart | None = None
    protected_parameter_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_interface_contract(self) -> "InterfaceNode":
        geometry_roles = tuple(item.role for item in self.governed_geometry)
        if len(geometry_roles) != len(set(geometry_roles)):
            raise ValueError("interface geometry roles must be unique")
        dimension_roles = tuple(item.role for item in self.governed_dimensions)
        if len(dimension_roles) != len(set(dimension_roles)):
            raise ValueError("interface dimension roles must be unique")
        dimension_ids = tuple(item.dimension_id for item in self.governed_dimensions)
        if len(dimension_ids) != len(set(dimension_ids)):
            raise ValueError("interface dimension ids must be unique")
        expected_protected = tuple(sorted(
            item.dimension_id for item in self.governed_dimensions if item.protected
        ))
        if tuple(sorted(self.protected_parameter_ids)) != expected_protected:
            raise ValueError("protected parameter ids must match dimension bindings")
        if len(self.protected_parameter_ids) != len(set(self.protected_parameter_ids)):
            raise ValueError("protected parameter ids must be unique")

        pieces = (
            self.coordinate_system is not None,
            bool(self.governed_geometry),
            bool(self.governed_dimensions),
            self.fit is not None,
            self.compatible_counterpart is not None,
        )
        if any(pieces) and not all(pieces):
            raise ValueError("first-class interface contract must be complete")
        if all(pieces) != (self.contract_version is not None):
            raise ValueError("interface contract version must reflect completeness")
        if (
            self.compatible_counterpart is not None
            and self.compatible_counterpart.interface_type is not self.interface_type
        ):
            raise ValueError("counterpart interface type must be compatible")
        return self

    @property
    def contract_complete(self) -> bool:
        return self.contract_version is not None


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

    schema_version: Literal["1.0.0"] = "1.0.0"
    revision: int = 1
    nodes: list[AnyNode] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_interface_contracts(self) -> "EngineeringIntentGraph":
        by_id = {item.id: item for item in self.nodes}
        if len(by_id) != len(self.nodes):
            raise ValueError("Engineering Intent Graph node ids must be unique")
        for interface in (
            item for item in self.nodes
            if isinstance(item, InterfaceNode) and item.contract_complete
        ):
            declared = {
                (item.role, item.dimension_id)
                for item in interface.governed_dimensions
            }
            connected = {
                (edge.role, edge.source)
                for edge in self.edges
                if edge.target == interface.id and edge.kind is EdgeKind.DEFINES
            }
            if declared != connected:
                raise ValueError(
                    f"interface {interface.id} dimension bindings must match DEFINES edges"
                )
            for binding in interface.governed_dimensions:
                if not isinstance(by_id.get(binding.dimension_id), DimensionNode):
                    raise ValueError(
                        f"interface {interface.id} references missing dimension node"
                    )
            for binding in interface.governed_geometry:
                if not isinstance(
                    by_id.get(binding.node_id),
                    (FeatureNode, AdvancedFeatureNode, ReferenceGeometryNode),
                ):
                    raise ValueError(
                        f"interface {interface.id} references missing geometry node"
                    )
            counterpart = interface.compatible_counterpart
            supported = {
                edge.target for edge in self.edges
                if edge.source == interface.id and edge.kind is EdgeKind.SUPPORTED_BY
            }
            if any(
                not isinstance(by_id.get(evidence_id), EvidenceNode)
                or evidence_id not in supported
                for evidence_id in counterpart.source_evidence_ids
            ):
                raise ValueError(
                    f"interface {interface.id} counterpart provenance is not cited"
                )
        return self

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
