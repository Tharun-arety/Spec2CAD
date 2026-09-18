"""Backend-neutral parametric realization plan.

Feature IR says how engineering intent can be realized without naming a CAD
kernel.  It is declarative data: expressions are a closed AST, sketch geometry
and constraints are explicit, and topology references are semantic.  CadQuery
selectors, FreeCAD object names, GUI commands and executable code do not belong
in this representation.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


FEATURE_IR_SCHEMA_VERSION = "1.0.0"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


StableId = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z][a-z0-9_]*(?:[.:/-][a-z0-9_]+)*$",
    ),
]


class IntentRelation(str, Enum):
    REALIZES = "realizes"
    PARAMETERIZES = "parameterizes"
    GROUPS = "groups"
    CORRESPONDS_TO = "corresponds_to"


class IntentLink(_FrozenModel):
    eig_node_id: StableId
    relation: IntentRelation


class _IntentLinkedModel(_FrozenModel):
    id: StableId
    label: str
    intent_links: tuple[IntentLink, ...] = Field(min_length=1)


class ParameterKind(str, Enum):
    LENGTH = "length"
    ANGLE = "angle"
    COUNT = "count"
    RATIO = "ratio"


class FeatureIRParameter(_IntentLinkedModel):
    name: StableId
    kind: ParameterKind
    value: float = Field(allow_inf_nan=False)
    unit: Literal["mm", "degree", "none"]
    protected: bool = False

    @model_validator(mode="after")
    def kind_matches_unit(self):
        expected = {
            ParameterKind.LENGTH: "mm",
            ParameterKind.ANGLE: "degree",
            ParameterKind.COUNT: "none",
            ParameterKind.RATIO: "none",
        }[self.kind]
        if self.unit != expected:
            raise ValueError(f"{self.kind.value} parameter requires unit {expected}")
        if self.kind is ParameterKind.COUNT and (
            self.value < 1 or not self.value.is_integer()
        ):
            raise ValueError("count parameter must be a positive integer")
        return self


class LiteralExpression(_FrozenModel):
    type: Literal["literal"] = "literal"
    value: float = Field(allow_inf_nan=False)


class ParameterExpression(_FrozenModel):
    type: Literal["parameter"] = "parameter"
    parameter_id: StableId


class BinaryOperator(str, Enum):
    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"


class BinaryExpression(_FrozenModel):
    type: Literal["binary"] = "binary"
    operator: BinaryOperator
    left: Expression
    right: Expression


Expression = Annotated[
    Union[LiteralExpression, ParameterExpression, BinaryExpression],
    Field(discriminator="type"),
]


def literal(value: float) -> LiteralExpression:
    return LiteralExpression(value=float(value))


def parameter(parameter_id: StableId) -> ParameterExpression:
    return ParameterExpression(parameter_id=parameter_id)


class Point2D(_FrozenModel):
    x: Expression
    y: Expression


class Vector3D(_FrozenModel):
    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)
    z: float = Field(allow_inf_nan=False)


class DatumPlane(str, Enum):
    XY = "XY"
    XZ = "XZ"
    YZ = "YZ"


class DatumPlaneReference(_FrozenModel):
    type: Literal["datum_plane"] = "datum_plane"
    plane: DatumPlane


class SurfaceSelector(str, Enum):
    POSITIVE_NORMAL = "positive_normal"
    NEGATIVE_NORMAL = "negative_normal"
    OUTER_CYLINDER = "outer_cylinder"
    INNER_CYLINDER = "inner_cylinder"


class FeatureSurfaceReference(_FrozenModel):
    type: Literal["feature_surface"] = "feature_surface"
    feature_id: StableId
    selector: SurfaceSelector
    direction: Vector3D | None = None


class EdgeSetSelector(str, Enum):
    EXTERNAL_PERIMETER = "external_perimeter"
    INTERNAL_PERIMETER = "internal_perimeter"
    PARALLEL_TO_AXIS = "parallel_to_axis"


class FeatureEdgeSetReference(_FrozenModel):
    type: Literal["feature_edge_set"] = "feature_edge_set"
    feature_id: StableId
    selector: EdgeSetSelector
    direction: Vector3D | None = None


SemanticReference = Annotated[
    Union[DatumPlaneReference, FeatureSurfaceReference, FeatureEdgeSetReference],
    Field(discriminator="type"),
]


class SketchPoint(_FrozenModel):
    type: Literal["point"] = "point"
    id: StableId
    position: Point2D
    construction: bool = False


class SketchLine(_FrozenModel):
    type: Literal["line"] = "line"
    id: StableId
    start: Point2D
    end: Point2D
    construction: bool = False


class SketchCircle(_FrozenModel):
    type: Literal["circle"] = "circle"
    id: StableId
    center: Point2D
    diameter: Expression
    construction: bool = False


class SketchArc(_FrozenModel):
    type: Literal["three_point_arc"] = "three_point_arc"
    id: StableId
    start: Point2D
    midpoint: Point2D
    end: Point2D
    construction: bool = False


SketchGeometry = Annotated[
    Union[SketchPoint, SketchLine, SketchCircle, SketchArc],
    Field(discriminator="type"),
]


class GeometryPoint(str, Enum):
    START = "start"
    END = "end"
    CENTER = "center"
    WHOLE = "whole"


class GeometryPointReference(_FrozenModel):
    geometry_id: StableId
    point: GeometryPoint


class CoincidentConstraint(_FrozenModel):
    type: Literal["coincident"] = "coincident"
    id: StableId
    first: GeometryPointReference
    second: GeometryPointReference


class HorizontalConstraint(_FrozenModel):
    type: Literal["horizontal"] = "horizontal"
    id: StableId
    geometry_id: StableId


class VerticalConstraint(_FrozenModel):
    type: Literal["vertical"] = "vertical"
    id: StableId
    geometry_id: StableId


class DistanceConstraint(_FrozenModel):
    type: Literal["distance"] = "distance"
    id: StableId
    first: GeometryPointReference
    second: GeometryPointReference
    value: Expression


class DiameterConstraint(_FrozenModel):
    type: Literal["diameter"] = "diameter"
    id: StableId
    geometry_id: StableId
    value: Expression


class EqualConstraint(_FrozenModel):
    type: Literal["equal"] = "equal"
    id: StableId
    first_geometry_id: StableId
    second_geometry_id: StableId


class FixedConstraint(_FrozenModel):
    type: Literal["fixed"] = "fixed"
    id: StableId
    geometry_ids: tuple[StableId, ...] = Field(min_length=1)


SketchConstraint = Annotated[
    Union[
        CoincidentConstraint,
        HorizontalConstraint,
        VerticalConstraint,
        DistanceConstraint,
        DiameterConstraint,
        EqualConstraint,
        FixedConstraint,
    ],
    Field(discriminator="type"),
]


class SketchProfile(_FrozenModel):
    id: StableId
    label: str
    geometry_ids: tuple[StableId, ...] = Field(min_length=1)
    closed: bool = True


class SketchDefinition(_FrozenModel):
    support: SemanticReference
    geometry: tuple[SketchGeometry, ...] = Field(min_length=1)
    profiles: tuple[SketchProfile, ...] = Field(min_length=1)
    constraints: tuple[SketchConstraint, ...] = ()


class SketchFeature(_IntentLinkedModel):
    type: Literal["sketch"] = "sketch"
    sketch: SketchDefinition


class PadFeature(_IntentLinkedModel):
    type: Literal["pad"] = "pad"
    sketch_id: StableId
    profile_id: StableId
    length: Expression
    symmetric: bool = False


class PocketFeature(_IntentLinkedModel):
    type: Literal["pocket"] = "pocket"
    sketch_id: StableId
    profile_id: StableId
    termination: Literal["through_all", "blind"] = "through_all"
    depth: Expression | None = None

    @model_validator(mode="after")
    def blind_has_depth(self):
        if (self.termination == "blind") != (self.depth is not None):
            raise ValueError("blind pocket requires depth; through_all forbids it")
        return self


class RectangularPatternFeature(_IntentLinkedModel):
    type: Literal["rectangular_pattern"] = "rectangular_pattern"
    source_feature_id: StableId
    count_x: Expression
    count_y: Expression
    spacing_x: Expression
    spacing_y: Expression


class LinearSlotPatternFeature(_IntentLinkedModel):
    type: Literal["linear_slot_pattern"] = "linear_slot_pattern"
    support: FeatureSurfaceReference
    width: Expression
    length: Expression
    spacing: Expression
    count: Expression
    angle_degrees: Expression


class ChamferFeature(_IntentLinkedModel):
    type: Literal["chamfer"] = "chamfer"
    edges: FeatureEdgeSetReference
    distance: Expression


class FilletFeature(_IntentLinkedModel):
    type: Literal["fillet"] = "fillet"
    edges: FeatureEdgeSetReference
    radius: Expression


Feature = Annotated[
    Union[
        SketchFeature,
        PadFeature,
        PocketFeature,
        RectangularPatternFeature,
        LinearSlotPatternFeature,
        ChamferFeature,
        FilletFeature,
    ],
    Field(discriminator="type"),
]


class FeatureIRBody(_IntentLinkedModel):
    feature_ids: tuple[StableId, ...] = Field(min_length=1)


class FeatureIRPart(_IntentLinkedModel):
    name: StableId
    body_ids: tuple[StableId, ...] = Field(min_length=1)
    interface_ids: tuple[StableId, ...] = ()


class FeatureIRInterfaceGeometryBinding(_FrozenModel):
    role: StableId
    eig_geometry_node_id: StableId
    geometry_kind: Literal["feature", "hole_pattern", "bore", "datum"]
    reference: SemanticReference
    feature_ids: tuple[StableId, ...] = Field(min_length=1)
    parameter_ids: tuple[StableId, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_binding(self):
        if len(self.feature_ids) != len(set(self.feature_ids)):
            raise ValueError("interface geometry feature ids must be unique")
        if len(self.parameter_ids) != len(set(self.parameter_ids)):
            raise ValueError("interface geometry parameter ids must be unique")
        if isinstance(
            self.reference, (FeatureSurfaceReference, FeatureEdgeSetReference)
        ) and self.reference.feature_id not in self.feature_ids:
            raise ValueError(
                "interface geometry reference must belong to its feature ids"
            )
        return self


class FeatureIRInterface(_IntentLinkedModel):
    reference: SemanticReference
    feature_ids: tuple[StableId, ...] = Field(min_length=1)
    parameter_ids: tuple[StableId, ...] = Field(min_length=1)
    correspondence_version: Literal["1.0.0"] | None = None
    geometry_bindings: tuple[FeatureIRInterfaceGeometryBinding, ...] = ()

    @model_validator(mode="after")
    def validate_correspondence(self):
        if (self.correspondence_version is None) != (not self.geometry_bindings):
            raise ValueError(
                "interface correspondence version must reflect completeness"
            )
        if self.correspondence_version is None:
            return self
        roles = tuple(item.role for item in self.geometry_bindings)
        if len(roles) != len(set(roles)):
            raise ValueError("interface correspondence roles must be unique")
        eig_ids = tuple(item.eig_geometry_node_id for item in self.geometry_bindings)
        if len(eig_ids) != len(set(eig_ids)):
            raise ValueError("interface correspondence EIG geometry ids must be unique")
        expected_features = {
            feature_id
            for binding in self.geometry_bindings
            for feature_id in binding.feature_ids
        }
        expected_parameters = {
            parameter_id
            for binding in self.geometry_bindings
            for parameter_id in binding.parameter_ids
        }
        if set(self.feature_ids) != expected_features:
            raise ValueError(
                "interface feature ids must exactly cover geometry bindings"
            )
        if set(self.parameter_ids) != expected_parameters:
            raise ValueError(
                "interface parameter ids must exactly cover geometry bindings"
            )
        return self


class FeatureIR(_FrozenModel):
    """One ordered, backend-neutral realization plan."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    id: StableId
    label: str
    design_revision: int = Field(ge=1)
    part: FeatureIRPart
    bodies: tuple[FeatureIRBody, ...] = Field(min_length=1)
    parameters: tuple[FeatureIRParameter, ...] = ()
    features: tuple[Feature, ...] = Field(min_length=1)
    interfaces: tuple[FeatureIRInterface, ...] = ()

    @model_validator(mode="after")
    def stable_ids_are_globally_unique(self):
        ids: list[str] = [self.id, self.part.id]
        ids.extend(item.id for item in self.bodies)
        ids.extend(item.id for item in self.parameters)
        ids.extend(item.id for item in self.features)
        ids.extend(item.id for item in self.interfaces)
        for feature in self.features:
            if isinstance(feature, SketchFeature):
                ids.extend(item.id for item in feature.sketch.geometry)
                ids.extend(item.id for item in feature.sketch.profiles)
                ids.extend(item.id for item in feature.sketch.constraints)
        duplicates = sorted({item for item in ids if ids.count(item) > 1})
        if duplicates:
            raise ValueError(f"Feature IR ids must be globally unique: {duplicates}")
        return self

    def intent_linked_records(self) -> tuple[_IntentLinkedModel, ...]:
        return (
            self.part,
            *self.bodies,
            *self.parameters,
            *self.features,
            *self.interfaces,
        )


class FeatureIRProvenanceError(ValueError):
    """Raised when a Feature IR link cannot traverse to its source EIG."""


def validate_eig_provenance(document: FeatureIR, eig) -> None:
    """Validate exact revision, node existence, kind and relationship role."""
    from spec2cad.schemas.intent_graph import (
        AdvancedFeatureNode,
        DimensionNode,
        EdgeKind,
        FeatureNode,
        InterfaceNode,
        PartNode,
    )

    if document.design_revision != eig.revision:
        raise FeatureIRProvenanceError(
            f"Feature IR revision {document.design_revision} does not match "
            f"EIG revision {eig.revision}"
        )

    expected = {
        FeatureIRPart: (IntentRelation.REALIZES, (PartNode,)),
        FeatureIRBody: (IntentRelation.GROUPS, (PartNode,)),
        FeatureIRParameter: (IntentRelation.PARAMETERIZES, (DimensionNode,)),
        SketchFeature: (IntentRelation.REALIZES, (FeatureNode, AdvancedFeatureNode)),
        PadFeature: (IntentRelation.REALIZES, (FeatureNode, AdvancedFeatureNode)),
        PocketFeature: (IntentRelation.REALIZES, (FeatureNode, AdvancedFeatureNode)),
        RectangularPatternFeature: (
            IntentRelation.REALIZES, (FeatureNode, AdvancedFeatureNode)
        ),
        LinearSlotPatternFeature: (
            IntentRelation.REALIZES, (FeatureNode, AdvancedFeatureNode)
        ),
        ChamferFeature: (IntentRelation.REALIZES, (FeatureNode, AdvancedFeatureNode)),
        FilletFeature: (IntentRelation.REALIZES, (FeatureNode, AdvancedFeatureNode)),
        FeatureIRInterface: (IntentRelation.CORRESPONDS_TO, (InterfaceNode,)),
    }
    problems: list[str] = []
    for record in document.intent_linked_records():
        relation, node_types = expected[type(record)]
        for link in record.intent_links:
            if not eig.has_node(link.eig_node_id):
                problems.append(
                    f"{record.id} links to missing EIG node {link.eig_node_id}"
                )
                continue
            node = eig.node(link.eig_node_id)
            if link.relation is not relation:
                problems.append(
                    f"{record.id} requires {relation.value} link, got {link.relation.value}"
                )
            if not isinstance(node, node_types):
                problems.append(
                    f"{record.id} links to incompatible EIG node kind {node.kind.value}"
                )
    features_by_id = {item.id: item for item in document.features}
    parameters_by_id = {item.id: item for item in document.parameters}
    for interface in document.interfaces:
        if interface.correspondence_version is None:
            continue
        interface_links = [
            link for link in interface.intent_links
            if link.relation is IntentRelation.CORRESPONDS_TO
        ]
        if len(interface_links) != 1:
            problems.append(
                f"{interface.id} requires exactly one EIG interface correspondence"
            )
            continue
        eig_interface = (
            eig.node(interface_links[0].eig_node_id)
            if eig.has_node(interface_links[0].eig_node_id) else None
        )
        if not isinstance(eig_interface, InterfaceNode):
            continue
        if not eig_interface.contract_complete:
            problems.append(
                f"{interface.id} cannot claim complete correspondence to a legacy interface"
            )
            continue
        expected_geometry = {
            (item.role, item.node_id, item.geometry_kind.value)
            for item in eig_interface.governed_geometry
        }
        actual_geometry = {
            (item.role, item.eig_geometry_node_id, item.geometry_kind)
            for item in interface.geometry_bindings
        }
        if actual_geometry != expected_geometry:
            problems.append(
                f"{interface.id} geometry bindings do not exactly match its EIG interface"
            )
        for binding in interface.geometry_bindings:
            expected_features = {
                feature.id
                for feature in document.features
                if any(
                    link.eig_node_id == binding.eig_geometry_node_id
                    and link.relation is IntentRelation.REALIZES
                    for link in feature.intent_links
                )
            }
            if set(binding.feature_ids) != expected_features:
                problems.append(
                    f"{interface.id} role {binding.role} does not exactly cover "
                    "its Feature IR realizations"
                )
            expected_parameters = {
                edge.source for edge in eig.in_edges(
                    binding.eig_geometry_node_id, EdgeKind.DEFINES
                )
            }
            if set(binding.parameter_ids) != expected_parameters:
                problems.append(
                    f"{interface.id} role {binding.role} does not exactly cover "
                    "its EIG dimensions"
                )
            for feature_id in binding.feature_ids:
                if feature_id not in features_by_id:
                    problems.append(
                        f"{interface.id} role {binding.role} references missing feature"
                    )
            for parameter_id in binding.parameter_ids:
                parameter_record = parameters_by_id.get(parameter_id)
                if parameter_record is None or not parameter_record.protected:
                    problems.append(
                        f"{interface.id} role {binding.role} requires protected parameters"
                    )
    if problems:
        raise FeatureIRProvenanceError("; ".join(problems))


BinaryExpression.model_rebuild()
FeatureIR.model_rebuild()
