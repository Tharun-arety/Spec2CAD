"""Transitional Feature IR → CADProgram lowering for the motor R1 slice.

`CADProgram` remains the CadQuery adapter's internal execution IR.  This module
does not import CadQuery and does not execute geometry.
"""

from __future__ import annotations

from spec2cad.feature_validation import require_valid_feature_ir
from spec2cad.schemas.cad_ir import (
    BoxOp,
    CADProgram,
    ChamferOp,
    CylinderOp,
    EdgeSelector,
    FaceSelector,
    HoleOp,
    FilletOp,
    LinearSlotPatternOp,
    NumberLiteral,
    ParamRef,
    RectangularHolePatternOp,
    Termination,
    TubeOp,
    lit,
    ref,
)
from spec2cad.schemas.feature_ir import (
    BinaryExpression,
    BinaryOperator,
    ChamferFeature,
    EdgeSetSelector,
    FeatureIR,
    IntentRelation,
    FilletFeature,
    LinearSlotPatternFeature,
    LiteralExpression,
    PadFeature,
    ParameterExpression,
    PocketFeature,
    RectangularPatternFeature,
    SketchCircle,
    SketchFeature,
    SketchLine,
)


class FeatureIRLoweringError(ValueError):
    """The validated Feature IR exceeds the transitional CadQuery lowering."""


def _realizes_id(feature) -> str:
    links = [
        link.eig_node_id for link in feature.intent_links
        if link.relation is IntentRelation.REALIZES
    ]
    if len(links) != 1:
        raise FeatureIRLoweringError(
            f"feature {feature.id!r} must have exactly one realizes link"
        )
    return links[0]


def _evaluate(expression, values: dict[str, float]) -> float:
    if isinstance(expression, LiteralExpression):
        return expression.value
    if isinstance(expression, ParameterExpression):
        return values[expression.parameter_id]
    left, right = _evaluate(expression.left, values), _evaluate(expression.right, values)
    if expression.operator is BinaryOperator.ADD:
        return left + right
    if expression.operator is BinaryOperator.SUBTRACT:
        return left - right
    if expression.operator is BinaryOperator.MULTIPLY:
        return left * right
    return left / right


def _numeric(expression, parameters) -> NumberLiteral | ParamRef:
    if isinstance(expression, LiteralExpression):
        return lit(expression.value)
    if isinstance(expression, ParameterExpression):
        return ref(parameters[expression.parameter_id].name)
    values = {item.id: item.value for item in parameters.values()}
    return lit(_evaluate(expression, values))


def _parameter_ids(expression) -> set[str]:
    if isinstance(expression, ParameterExpression):
        return {expression.parameter_id}
    if isinstance(expression, BinaryExpression):
        return _parameter_ids(expression.left) | _parameter_ids(expression.right)
    return set()


def _centered_rectangle_parameters(sketch: SketchFeature) -> tuple[str, str]:
    lines = sketch.sketch.geometry
    if len(lines) != 4 or not all(isinstance(item, SketchLine) for item in lines):
        raise FeatureIRLoweringError(
            f"pad sketch {sketch.id!r} is not the bounded four-line rectangle"
        )
    x_ids: set[str] = set()
    y_ids: set[str] = set()
    for line in lines:
        x_ids |= _parameter_ids(line.start.x) | _parameter_ids(line.end.x)
        y_ids |= _parameter_ids(line.start.y) | _parameter_ids(line.end.y)
    if len(x_ids) != 1 or len(y_ids) != 1:
        raise FeatureIRLoweringError(
            f"pad sketch {sketch.id!r} does not expose one width and height parameter"
        )
    return next(iter(x_ids)), next(iter(y_ids))


def lower_feature_ir_to_cad_program(document: FeatureIR) -> CADProgram:
    """Lower the validated motor slice without changing the established IR."""
    require_valid_feature_ir(document)
    parameters = {item.id: item for item in document.parameters}
    features = {item.id: item for item in document.features}
    patterned_sources = {
        item.source_feature_id
        for item in document.features
        if isinstance(item, RectangularPatternFeature)
    }
    operations = []

    for feature in document.features:
        if isinstance(feature, SketchFeature):
            continue
        if isinstance(feature, PadFeature):
            sketch = features[feature.sketch_id]
            if not isinstance(sketch, SketchFeature):
                raise FeatureIRLoweringError(f"{feature.id!r} does not reference a sketch")
            geometry = sketch.sketch.geometry
            if len(geometry) in {1, 2} and all(
                isinstance(item, SketchCircle) for item in geometry
            ):
                diameters = [
                    _numeric(item.diameter, parameters) for item in geometry
                ]
                if len(diameters) == 1:
                    operations.append(CylinderOp(
                        id=_realizes_id(feature), diameter=diameters[0],
                        length=_numeric(feature.length, parameters), centered=True,
                    ))
                else:
                    operations.append(TubeOp(
                        id=_realizes_id(feature), outer_diameter=diameters[0],
                        inner_diameter=diameters[1],
                        length=_numeric(feature.length, parameters), centered=True,
                    ))
            else:
                width_id, height_id = _centered_rectangle_parameters(sketch)
                operations.append(BoxOp(
                    id=_realizes_id(feature),
                    width=ref(parameters[width_id].name),
                    height=ref(parameters[height_id].name),
                    depth=_numeric(feature.length, parameters),
                    centered=True,
                ))
            continue
        if isinstance(feature, PocketFeature):
            if feature.id in patterned_sources:
                continue
            sketch = features[feature.sketch_id]
            if not isinstance(sketch, SketchFeature):
                raise FeatureIRLoweringError(f"{feature.id!r} does not reference a sketch")
            geometry = sketch.sketch.geometry
            if len(geometry) != 1 or not isinstance(geometry[0], SketchCircle):
                raise FeatureIRLoweringError(
                    f"pocket {feature.id!r} is not the bounded circular opening"
                )
            circle = geometry[0]
            operations.append(HoleOp(
                id=_realizes_id(feature),
                support=FaceSelector.TOP_FACE,
                diameter=_numeric(circle.diameter, parameters),
                x=_numeric(circle.center.x, parameters),
                y=_numeric(circle.center.y, parameters),
                termination=Termination.THROUGH_ALL,
            ))
            continue
        if isinstance(feature, RectangularPatternFeature):
            seed = features[feature.source_feature_id]
            if not isinstance(seed, PocketFeature):
                raise FeatureIRLoweringError(
                    f"pattern {feature.id!r} source is not a pocket"
                )
            sketch = features[seed.sketch_id]
            circle = sketch.sketch.geometry[0] if isinstance(sketch, SketchFeature) else None
            if not isinstance(circle, SketchCircle):
                raise FeatureIRLoweringError(
                    f"pattern {feature.id!r} source has no circular seed"
                )
            values = {item.id: item.value for item in parameters.values()}
            count = int(
                _evaluate(feature.count_x, values) * _evaluate(feature.count_y, values)
            )
            operations.append(RectangularHolePatternOp(
                id=_realizes_id(feature),
                support=FaceSelector.TOP_FACE,
                diameter=_numeric(circle.diameter, parameters),
                spacing_x=_numeric(feature.spacing_x, parameters),
                spacing_y=_numeric(feature.spacing_y, parameters),
                count=count,
                termination=Termination.THROUGH_ALL,
            ))
            continue
        if isinstance(feature, LinearSlotPatternFeature):
            values = {item.id: item.value for item in parameters.values()}
            operations.append(LinearSlotPatternOp(
                id=_realizes_id(feature),
                support=FaceSelector.TOP_FACE,
                width=_numeric(feature.width, parameters),
                length=_numeric(feature.length, parameters),
                spacing=_numeric(feature.spacing, parameters),
                count=int(_evaluate(feature.count, values)),
                angle_degrees=_numeric(feature.angle_degrees, parameters),
                termination=Termination.THROUGH_ALL,
            ))
            continue
        if isinstance(feature, ChamferFeature):
            if feature.edges.selector is not EdgeSetSelector.PARALLEL_TO_AXIS:
                raise FeatureIRLoweringError(
                    f"chamfer {feature.id!r} uses an unsupported semantic edge selector"
                )
            operations.append(ChamferOp(
                id=_realizes_id(feature),
                edge_selector=EdgeSelector.EXTERNAL_VERTICAL_EDGES,
                distance=_numeric(feature.distance, parameters),
            ))
            continue
        if isinstance(feature, FilletFeature):
            if feature.edges.selector is not EdgeSetSelector.PARALLEL_TO_AXIS:
                raise FeatureIRLoweringError(
                    f"fillet {feature.id!r} uses an unsupported semantic edge selector"
                )
            operations.append(FilletOp(
                id=_realizes_id(feature),
                edge_selector=EdgeSelector.EXTERNAL_VERTICAL_EDGES,
                radius=_numeric(feature.radius, parameters),
            ))
            continue
        raise FeatureIRLoweringError(
            f"Feature IR type {feature.type!r} is not supported by motor lowering"
        )

    return CADProgram(
        part_name=document.part.name,
        operations=operations,
        design_revision=document.design_revision,
    )
