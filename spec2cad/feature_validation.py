"""Fail-closed validation for Feature IR before any backend is invoked."""

from __future__ import annotations

from enum import Enum
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict

from spec2cad.schemas.feature_ir import (
    BinaryExpression,
    BinaryOperator,
    ChamferFeature,
    Feature,
    FeatureEdgeSetReference,
    FeatureIR,
    FeatureSurfaceReference,
    FilletFeature,
    LiteralExpression,
    LinearSlotPatternFeature,
    PadFeature,
    ParameterExpression,
    PocketFeature,
    RectangularPatternFeature,
    SketchFeature,
)


class DiagnosticCode(str, Enum):
    DUPLICATE_PARAMETER_NAME = "duplicate_parameter_name"
    MISSING_PARAMETER = "missing_parameter"
    INVALID_EXPRESSION = "invalid_expression"
    DEPENDENCY_ORDER = "dependency_order"
    DANGLING_REFERENCE = "dangling_reference"
    BODY_MEMBERSHIP = "body_membership"
    INTERFACE_REFERENCE = "interface_reference"
    UNSUPPORTED_FEATURE = "unsupported_feature"
    INVALID_FEATURE_VALUE = "invalid_feature_value"


class FeatureIRDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    code: DiagnosticCode
    record_id: str
    severity: Literal["error"] = "error"
    message: str


class FeatureIRValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    document_id: str
    valid: bool
    diagnostics: tuple[FeatureIRDiagnostic, ...] = ()


class FeatureIRValidationError(ValueError):
    def __init__(self, report: FeatureIRValidationReport):
        self.report = report
        super().__init__("; ".join(item.message for item in report.diagnostics))


ALL_FEATURE_TYPES = frozenset({
    "sketch", "pad", "pocket", "rectangular_pattern", "linear_slot_pattern",
    "chamfer", "fillet",
})


def _iter_expressions(value) -> Iterable:
    if isinstance(value, (LiteralExpression, ParameterExpression, BinaryExpression)):
        yield value
        if isinstance(value, BinaryExpression):
            yield from _iter_expressions(value.left)
            yield from _iter_expressions(value.right)
        return
    if isinstance(value, BaseModel):
        for field in type(value).model_fields:
            yield from _iter_expressions(getattr(value, field))
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_expressions(item)


def _evaluate(expression, values: dict[str, float]) -> float:
    if isinstance(expression, LiteralExpression):
        return expression.value
    if isinstance(expression, ParameterExpression):
        if expression.parameter_id not in values:
            raise KeyError(expression.parameter_id)
        return values[expression.parameter_id]
    left = _evaluate(expression.left, values)
    right = _evaluate(expression.right, values)
    if expression.operator is BinaryOperator.ADD:
        return left + right
    if expression.operator is BinaryOperator.SUBTRACT:
        return left - right
    if expression.operator is BinaryOperator.MULTIPLY:
        return left * right
    if right == 0:
        raise ZeroDivisionError("Feature IR expression divides by zero")
    return left / right


def validate_feature_ir(
    document: FeatureIR,
    *,
    supported_feature_types: Iterable[str] | None = None,
) -> FeatureIRValidationReport:
    diagnostics: list[FeatureIRDiagnostic] = []

    def error(code: DiagnosticCode, record_id: str, message: str) -> None:
        diagnostics.append(FeatureIRDiagnostic(
            id=f"fir_diag_{len(diagnostics) + 1:04d}",
            code=code,
            record_id=record_id,
            message=message,
        ))

    parameter_values = {item.id: item.value for item in document.parameters}
    parameter_names = [item.name for item in document.parameters]
    for name in sorted({item for item in parameter_names if parameter_names.count(item) > 1}):
        error(
            DiagnosticCode.DUPLICATE_PARAMETER_NAME,
            document.id,
            f"parameter name {name!r} is not unique",
        )

    supported = set(supported_feature_types or ALL_FEATURE_TYPES)
    features_by_id = {item.id: item for item in document.features}
    seen: dict[str, Feature] = {}

    def require_earlier(record_id: str, dependency_id: str, relationship: str) -> None:
        if dependency_id in seen:
            return
        code = (
            DiagnosticCode.DEPENDENCY_ORDER
            if dependency_id in features_by_id else DiagnosticCode.DANGLING_REFERENCE
        )
        error(
            code,
            record_id,
            f"{record_id} {relationship} {dependency_id!r}, which is not available earlier",
        )

    for feature in document.features:
        if feature.type not in supported:
            error(
                DiagnosticCode.UNSUPPORTED_FEATURE,
                feature.id,
                f"feature type {feature.type!r} is not supported by the selected adapter",
            )

        for expression in _iter_expressions(feature):
            try:
                _evaluate(expression, parameter_values)
            except KeyError as exc:
                error(
                    DiagnosticCode.MISSING_PARAMETER,
                    feature.id,
                    f"{feature.id} references missing parameter {exc.args[0]!r}",
                )
            except (ArithmeticError, ValueError) as exc:
                error(
                    DiagnosticCode.INVALID_EXPRESSION,
                    feature.id,
                    f"{feature.id} has invalid expression: {exc}",
                )

        if isinstance(feature, SketchFeature):
            support = feature.sketch.support
            if isinstance(support, (FeatureSurfaceReference, FeatureEdgeSetReference)):
                require_earlier(feature.id, support.feature_id, "is supported by")
            geometry_ids = {item.id for item in feature.sketch.geometry}
            for profile in feature.sketch.profiles:
                for geometry_id in profile.geometry_ids:
                    if geometry_id not in geometry_ids:
                        error(
                            DiagnosticCode.DANGLING_REFERENCE,
                            profile.id,
                            f"profile {profile.id} references missing geometry {geometry_id!r}",
                        )
            for constraint in feature.sketch.constraints:
                referenced = []
                for field in type(constraint).model_fields:
                    value = getattr(constraint, field)
                    if field.endswith("geometry_id"):
                        referenced.append(value)
                    elif field == "geometry_ids":
                        referenced.extend(value)
                    elif hasattr(value, "geometry_id"):
                        referenced.append(value.geometry_id)
                for geometry_id in referenced:
                    if geometry_id not in geometry_ids:
                        error(
                            DiagnosticCode.DANGLING_REFERENCE,
                            constraint.id,
                            f"constraint {constraint.id} references missing geometry {geometry_id!r}",
                        )
        elif isinstance(feature, (PadFeature, PocketFeature)):
            require_earlier(feature.id, feature.sketch_id, "consumes sketch")
            sketch = seen.get(feature.sketch_id)
            if isinstance(sketch, SketchFeature) and feature.profile_id not in {
                item.id for item in sketch.sketch.profiles
            }:
                error(
                    DiagnosticCode.DANGLING_REFERENCE,
                    feature.id,
                    f"{feature.id} references missing profile {feature.profile_id!r}",
                )
            length = feature.length if isinstance(feature, PadFeature) else feature.depth
            if length is not None:
                try:
                    if _evaluate(length, parameter_values) <= 0:
                        raise ValueError("length/depth must be positive")
                except (KeyError, ArithmeticError):
                    pass  # already diagnosed by the generic expression pass
                except ValueError as exc:
                    error(DiagnosticCode.INVALID_FEATURE_VALUE, feature.id, str(exc))
        elif isinstance(feature, RectangularPatternFeature):
            require_earlier(feature.id, feature.source_feature_id, "patterns feature")
            for name in ("count_x", "count_y"):
                try:
                    value = _evaluate(getattr(feature, name), parameter_values)
                    if value < 1 or not float(value).is_integer():
                        error(
                            DiagnosticCode.INVALID_FEATURE_VALUE,
                            feature.id,
                            f"{feature.id} {name} must be a positive integer",
                        )
                except (KeyError, ArithmeticError, ValueError):
                    pass
        elif isinstance(feature, LinearSlotPatternFeature):
            require_earlier(feature.id, feature.support.feature_id, "cuts support")
            try:
                count = _evaluate(feature.count, parameter_values)
                width = _evaluate(feature.width, parameter_values)
                length = _evaluate(feature.length, parameter_values)
                spacing = _evaluate(feature.spacing, parameter_values)
                if count < 1 or not float(count).is_integer():
                    error(
                        DiagnosticCode.INVALID_FEATURE_VALUE, feature.id,
                        f"{feature.id} count must be a positive integer",
                    )
                if width <= 0 or length <= 0 or length < width or spacing < 0:
                    error(
                        DiagnosticCode.INVALID_FEATURE_VALUE, feature.id,
                        "slot width/length must be positive, length >= width, and spacing >= 0",
                    )
            except (KeyError, ArithmeticError, ValueError):
                pass
        elif isinstance(feature, (ChamferFeature, FilletFeature)):
            require_earlier(feature.id, feature.edges.feature_id, "references edges from")

        seen[feature.id] = feature

    body_ids = {item.id for item in document.bodies}
    for body_id in document.part.body_ids:
        if body_id not in body_ids:
            error(
                DiagnosticCode.BODY_MEMBERSHIP,
                document.part.id,
                f"part references missing body {body_id!r}",
            )
    memberships: dict[str, int] = {item.id: 0 for item in document.features}
    order = {item.id: index for index, item in enumerate(document.features)}
    for body in document.bodies:
        prior = -1
        for feature_id in body.feature_ids:
            if feature_id not in memberships:
                error(
                    DiagnosticCode.BODY_MEMBERSHIP,
                    body.id,
                    f"body {body.id} references missing feature {feature_id!r}",
                )
                continue
            memberships[feature_id] += 1
            if order[feature_id] < prior:
                error(
                    DiagnosticCode.BODY_MEMBERSHIP,
                    body.id,
                    f"body {body.id} feature order differs from the document order",
                )
            prior = order[feature_id]
    for feature_id, count in memberships.items():
        if count != 1:
            error(
                DiagnosticCode.BODY_MEMBERSHIP,
                feature_id,
                f"feature {feature_id} must belong to exactly one body; found {count}",
            )

    interface_ids = {item.id for item in document.interfaces}
    for interface_id in document.part.interface_ids:
        if interface_id not in interface_ids:
            error(
                DiagnosticCode.INTERFACE_REFERENCE,
                document.part.id,
                f"part references missing interface {interface_id!r}",
            )
    for interface in document.interfaces:
        for feature_id in interface.feature_ids:
            if feature_id not in features_by_id:
                error(
                    DiagnosticCode.INTERFACE_REFERENCE,
                    interface.id,
                    f"interface {interface.id} references missing feature {feature_id!r}",
                )
        for parameter_id in interface.parameter_ids:
            if parameter_id not in parameter_values:
                error(
                    DiagnosticCode.INTERFACE_REFERENCE,
                    interface.id,
                    f"interface {interface.id} references missing parameter {parameter_id!r}",
                )
        for binding in interface.geometry_bindings:
            for feature_id in binding.feature_ids:
                if feature_id not in features_by_id:
                    error(
                        DiagnosticCode.INTERFACE_REFERENCE,
                        interface.id,
                        f"interface role {binding.role} references missing feature "
                        f"{feature_id!r}",
                    )
            for parameter_id in binding.parameter_ids:
                if parameter_id not in parameter_values:
                    error(
                        DiagnosticCode.INTERFACE_REFERENCE,
                        interface.id,
                        f"interface role {binding.role} references missing parameter "
                        f"{parameter_id!r}",
                    )
            reference = binding.reference
            if isinstance(
                reference, (FeatureSurfaceReference, FeatureEdgeSetReference)
            ) and reference.feature_id not in features_by_id:
                error(
                    DiagnosticCode.INTERFACE_REFERENCE,
                    interface.id,
                    f"interface role {binding.role} has dangling geometry reference",
                )

    return FeatureIRValidationReport(
        document_id=document.id,
        valid=not diagnostics,
        diagnostics=tuple(diagnostics),
    )


def require_valid_feature_ir(
    document: FeatureIR,
    *,
    supported_feature_types: Iterable[str] | None = None,
) -> FeatureIRValidationReport:
    report = validate_feature_ir(
        document, supported_feature_types=supported_feature_types
    )
    if not report.valid:
        raise FeatureIRValidationError(report)
    return report
