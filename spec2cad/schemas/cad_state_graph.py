"""Immutable observations of one backend build.

The CAD State Graph records what a backend actually created. It is never design
authority, and its persistent topology identity is semantic and geometric—not a
raw face or edge index from a transient kernel result.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from spec2cad.schemas.feature_ir import FeatureIR, StableId
from spec2cad.schemas.intent_graph import EngineeringIntentGraph


CAD_STATE_GRAPH_SCHEMA_VERSION = "1.0.0"
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class QuantityUnit(str, Enum):
    MILLIMETRE = "mm"
    SQUARE_MILLIMETRE = "mm2"
    CUBIC_MILLIMETRE = "mm3"
    DEGREE = "degree"
    COUNT = "count"
    NONE = "none"


class ObservedQuantity(_FrozenModel):
    name: StableId
    value: float = Field(allow_inf_nan=False)
    unit: QuantityUnit


class RecomputeObservation(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PENDING = "pending"


class ConstraintObservation(str, Enum):
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    REDUNDANT = "redundant"
    UNKNOWN = "unknown"


class TopologyKind(str, Enum):
    SOLID = "solid"
    FACE = "face"
    EDGE = "edge"
    VERTEX = "vertex"


class GeometryKind(str, Enum):
    LINE = "line"
    CIRCLE = "circle"
    ARC = "arc"


class DatumKind(str, Enum):
    ORIGIN = "origin"
    PLANE = "plane"
    AXIS = "axis"
    POINT = "point"
    SURFACE = "surface"


class DiagnosticSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class NativeConcept(str, Enum):
    EDITABLE_DOCUMENT = "editable_document"
    PARAMETRIC_SKETCH = "parametric_sketch"
    SKETCH_CONSTRAINT = "sketch_constraint"
    PARAMETER_EXPRESSION = "parameter_expression"
    NATIVE_FEATURE = "native_feature"
    SEMANTIC_TOPOLOGY = "semantic_topology"
    NATIVE_EXPORT = "native_export"
    NEUTRAL_EXPORT = "neutral_export"
    PREVIEW_EXPORT = "preview_export"


class UnavailabilityKind(str, Enum):
    ABSENT = "absent"
    UNSUPPORTED = "unsupported"


class RelationshipKind(str, Enum):
    REALIZES_INTENT = "realizes_intent"
    REALIZES_FEATURE_IR = "realizes_feature_ir"
    DEPENDS_ON = "depends_on"
    REFERENCES = "references"
    CONSTRAINED_BY = "constrained_by"
    CONSUMES_PROFILE = "consumes_profile"
    PRODUCES_TOPOLOGY = "produces_topology"
    CORRESPONDS_TO_INTERFACE = "corresponds_to_interface"


class ReferenceNamespace(str, Enum):
    CAD_STATE_GRAPH = "cad_state_graph"
    ENGINEERING_INTENT_GRAPH = "engineering_intent_graph"
    FEATURE_IR = "feature_ir"


class GraphReference(_FrozenModel):
    namespace: ReferenceNamespace
    id: StableId


class CSGRelationship(_FrozenModel):
    id: StableId
    kind: RelationshipKind
    source: GraphReference
    target: GraphReference

    @model_validator(mode="after")
    def validate_namespaces(self) -> "CSGRelationship":
        if self.source.namespace is not ReferenceNamespace.CAD_STATE_GRAPH:
            raise ValueError("relationship source must be a CAD State Graph node")
        expected = {
            RelationshipKind.REALIZES_INTENT: {
                ReferenceNamespace.ENGINEERING_INTENT_GRAPH
            },
            RelationshipKind.REALIZES_FEATURE_IR: {ReferenceNamespace.FEATURE_IR},
            RelationshipKind.CORRESPONDS_TO_INTERFACE: {
                ReferenceNamespace.ENGINEERING_INTENT_GRAPH,
                ReferenceNamespace.FEATURE_IR,
            },
        }.get(self.kind, {ReferenceNamespace.CAD_STATE_GRAPH})
        if self.target.namespace not in expected:
            raise ValueError(
                f"{self.kind.value} target must use "
                + " or ".join(sorted(item.value for item in expected))
            )
        return self


class _Node(_FrozenModel):
    id: StableId
    label: str = Field(min_length=1)
    backend_native_id: str | None = None


class DocumentNode(_Node):
    kind: Literal["document"] = "document"
    native_format: str | None = None
    editable: bool
    recompute: RecomputeObservation
    body_ids: tuple[StableId, ...] = ()


class BodyNode(_Node):
    kind: Literal["body"] = "body"
    feature_ids: tuple[StableId, ...] = ()
    solid_count: int = Field(ge=0)
    measurements: tuple[ObservedQuantity, ...] = ()


class SketchNode(_Node):
    kind: Literal["sketch"] = "sketch"
    support_reference_id: StableId | None = None
    geometry_ids: tuple[StableId, ...] = ()
    constraint_ids: tuple[StableId, ...] = ()
    fully_constrained: bool | None = None
    degrees_of_freedom: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_constraint_state(self) -> "SketchNode":
        if self.fully_constrained is True and self.degrees_of_freedom not in (None, 0):
            raise ValueError("fully constrained sketch cannot have degrees of freedom")
        return self


class SketchGeometryNode(_Node):
    kind: Literal["sketch_geometry"] = "sketch_geometry"
    geometry_kind: GeometryKind
    construction: bool = False
    coordinates: tuple[float, ...] = ()
    radius_mm: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_geometry_shape(self) -> "SketchGeometryNode":
        expected = {
            GeometryKind.LINE: 4,
            GeometryKind.CIRCLE: 2,
            GeometryKind.ARC: 4,
        }[self.geometry_kind]
        if len(self.coordinates) != expected:
            raise ValueError(
                f"{self.geometry_kind.value} geometry requires {expected} coordinates"
            )
        if self.geometry_kind in {GeometryKind.CIRCLE, GeometryKind.ARC}:
            if self.radius_mm is None:
                raise ValueError("circle and arc geometry require radius")
        elif self.radius_mm is not None:
            raise ValueError("line geometry cannot have radius")
        return self


class ConstraintNode(_Node):
    kind: Literal["constraint"] = "constraint"
    constraint_type: StableId
    geometry_ids: tuple[StableId, ...] = Field(min_length=1)
    state: ConstraintObservation
    value: float | None = Field(default=None, allow_inf_nan=False)
    unit: QuantityUnit | None = None
    expression_id: StableId | None = None

    @model_validator(mode="after")
    def validate_value_unit(self) -> "ConstraintNode":
        if (self.value is None) != (self.unit is None):
            raise ValueError("constraint value and unit must be present together")
        return self


class ParameterExpressionNode(_Node):
    kind: Literal["parameter_expression"] = "parameter_expression"
    parameter_name: StableId
    value: float = Field(allow_inf_nan=False)
    unit: QuantityUnit
    editable: bool
    native_expression: str | None = None


class NativeFeatureNode(_Node):
    kind: Literal["native_feature"] = "native_feature"
    native_feature_type: str = Field(min_length=1)
    portable_feature_type: StableId | None = None
    sequence_index: int = Field(ge=0)
    suppressed: bool = False
    input_ids: tuple[StableId, ...] = ()
    output_topology_ids: tuple[StableId, ...] = ()
    measurements: tuple[ObservedQuantity, ...] = ()


class DatumReferenceNode(_Node):
    kind: Literal["datum_reference"] = "datum_reference"
    datum_kind: DatumKind
    origin: tuple[float, float, float] | None = None
    direction: tuple[float, float, float] | None = None


class SemanticTopologyNode(_Node):
    kind: Literal["semantic_topology"] = "semantic_topology"
    topology_kind: TopologyKind
    semantic_role: StableId
    geometry_type: StableId
    signature_sha256: Sha256
    centroid_mm: tuple[float, float, float] | None = None
    direction: tuple[float, float, float] | None = None
    adjacent_topology_ids: tuple[StableId, ...] = ()
    measurements: tuple[ObservedQuantity, ...] = ()

    @model_validator(mode="after")
    def reject_raw_index_identity(self) -> "SemanticTopologyNode":
        candidates = (self.id, self.semantic_role, self.backend_native_id or "")
        for value in candidates:
            compact = value.lower().replace("_", "")
            if compact.startswith(("face", "edge", "vertex")) and compact.lstrip(
                "abcdefghijklmnopqrstuvwxyz"
            ).isdigit():
                raise ValueError("persistent topology identity cannot be a raw index")
        return self


class ArtifactNode(_Node):
    kind: Literal["artifact"] = "artifact"
    artifact_kind: Literal["native_model", "neutral_model", "preview_model"]
    filename: str = Field(min_length=1, pattern=r"^[^/\\]+$")
    media_type: str = Field(min_length=3, pattern=r"^[^/\s]+/[^/\s]+$")
    content_sha256: Sha256
    byte_length: int = Field(gt=0)


class DiagnosticNode(_Node):
    kind: Literal["diagnostic"] = "diagnostic"
    severity: DiagnosticSeverity
    code: StableId
    message: str = Field(min_length=1)
    related_node_ids: tuple[StableId, ...] = ()


class UnavailableConceptNode(_Node):
    """Truthful negative observation, distinct from an extraction failure."""

    kind: Literal["unavailable_concept"] = "unavailable_concept"
    concept: NativeConcept
    status: UnavailabilityKind
    reason: str = Field(min_length=1)
    requested_feature_ir_ids: tuple[StableId, ...] = ()


CSGNode = Annotated[
    Union[
        DocumentNode,
        BodyNode,
        SketchNode,
        SketchGeometryNode,
        ConstraintNode,
        ParameterExpressionNode,
        NativeFeatureNode,
        DatumReferenceNode,
        SemanticTopologyNode,
        ArtifactNode,
        DiagnosticNode,
        UnavailableConceptNode,
    ],
    Field(discriminator="kind"),
]


class CADStateGraph(_FrozenModel):
    schema_version: Literal["1.0.0"] = CAD_STATE_GRAPH_SCHEMA_VERSION
    id: StableId
    build_request_id: str = Field(min_length=1)
    backend_id: StableId
    backend_version: str = Field(min_length=1)
    source_feature_ir_sha256: Sha256
    root_document_id: StableId
    nodes: tuple[CSGNode, ...] = Field(min_length=1)
    relationships: tuple[CSGRelationship, ...] = ()

    @model_validator(mode="after")
    def validate_graph(self) -> "CADStateGraph":
        by_id = {item.id: item for item in self.nodes}
        if len(by_id) != len(self.nodes):
            raise ValueError("CAD State Graph node ids must be globally unique")
        relationship_ids = {item.id for item in self.relationships}
        if len(relationship_ids) != len(self.relationships):
            raise ValueError("CAD State Graph relationship ids must be globally unique")
        if set(by_id) & relationship_ids:
            raise ValueError("node and relationship ids must not overlap")
        root = by_id.get(self.root_document_id)
        if not isinstance(root, DocumentNode):
            raise ValueError("root_document_id must reference a document node")

        def require(ids: tuple[str, ...], expected, owner: str) -> None:
            for node_id in ids:
                if not isinstance(by_id.get(node_id), expected):
                    raise ValueError(f"{owner} references invalid node {node_id!r}")

        for node in self.nodes:
            if isinstance(node, DocumentNode):
                require(node.body_ids, BodyNode, node.id)
            elif isinstance(node, BodyNode):
                require(node.feature_ids, (SketchNode, NativeFeatureNode), node.id)
            elif isinstance(node, SketchNode):
                require(node.geometry_ids, SketchGeometryNode, node.id)
                require(node.constraint_ids, ConstraintNode, node.id)
                if node.support_reference_id is not None:
                    require((node.support_reference_id,), DatumReferenceNode, node.id)
            elif isinstance(node, ConstraintNode):
                require(node.geometry_ids, SketchGeometryNode, node.id)
                if node.expression_id is not None:
                    require((node.expression_id,), ParameterExpressionNode, node.id)
            elif isinstance(node, NativeFeatureNode):
                for input_id in node.input_ids:
                    if input_id not in by_id:
                        raise ValueError(f"{node.id} references invalid node {input_id!r}")
                require(node.output_topology_ids, SemanticTopologyNode, node.id)
            elif isinstance(node, SemanticTopologyNode):
                require(node.adjacent_topology_ids, SemanticTopologyNode, node.id)
            elif isinstance(node, DiagnosticNode):
                for related_id in node.related_node_ids:
                    if related_id not in by_id:
                        raise ValueError(f"{node.id} references invalid node {related_id!r}")

        for relationship in self.relationships:
            source = by_id.get(relationship.source.id)
            if source is None:
                raise ValueError(
                    f"relationship {relationship.id} has dangling source"
                )
            target = (
                by_id.get(relationship.target.id)
                if relationship.target.namespace is ReferenceNamespace.CAD_STATE_GRAPH
                else None
            )
            if (
                relationship.target.namespace is ReferenceNamespace.CAD_STATE_GRAPH
                and target is None
            ):
                raise ValueError(
                    f"relationship {relationship.id} has dangling internal target"
                )
            if relationship.kind is RelationshipKind.CONSTRAINED_BY and not (
                isinstance(source, SketchNode) and isinstance(target, ConstraintNode)
            ):
                raise ValueError("constrained_by requires sketch to constraint")
            if relationship.kind is RelationshipKind.CONSUMES_PROFILE and not (
                isinstance(source, NativeFeatureNode) and isinstance(target, SketchNode)
            ):
                raise ValueError("consumes_profile requires feature to sketch")
            if relationship.kind is RelationshipKind.PRODUCES_TOPOLOGY and not (
                isinstance(source, NativeFeatureNode)
                and isinstance(target, SemanticTopologyNode)
            ):
                raise ValueError("produces_topology requires feature to topology")
        return self


def validate_csg_provenance(
    graph: CADStateGraph,
    *,
    intent_graph: EngineeringIntentGraph | None = None,
    feature_ir: FeatureIR | None = None,
) -> None:
    """Resolve every external relationship against its authoritative document."""
    eig_ids = {item.id for item in intent_graph.nodes} if intent_graph else set()
    feature_ids: set[str] = set()
    if feature_ir is not None:
        feature_ids = {
            feature_ir.id,
            feature_ir.part.id,
            *(item.id for item in feature_ir.bodies),
            *(item.id for item in feature_ir.parameters),
            *(item.id for item in feature_ir.features),
            *(item.id for item in feature_ir.interfaces),
        }
    for relationship in graph.relationships:
        namespace = relationship.target.namespace
        if namespace is ReferenceNamespace.ENGINEERING_INTENT_GRAPH:
            if intent_graph is None:
                raise ValueError("EIG is required to validate CSG provenance")
            if relationship.target.id not in eig_ids:
                raise ValueError(
                    f"relationship {relationship.id} references missing EIG node"
                )
        elif namespace is ReferenceNamespace.FEATURE_IR:
            if feature_ir is None:
                raise ValueError("Feature IR is required to validate CSG provenance")
            if relationship.target.id not in feature_ids:
                raise ValueError(
                    f"relationship {relationship.id} references missing Feature IR record"
                )
