"""Feature IR fails closed before backend execution."""

import pytest

from spec2cad.feature_validation import (
    DiagnosticCode,
    FeatureIRValidationError,
    require_valid_feature_ir,
    validate_feature_ir,
)
from spec2cad.schemas.feature_ir import (
    BinaryExpression,
    BinaryOperator,
    PadFeature,
    parameter,
    literal,
)
from tests.test_feature_ir_schema import motor_shaped_feature_ir


def codes(document, **kwargs):
    return {item.code for item in validate_feature_ir(document, **kwargs).diagnostics}


def test_valid_motor_shaped_document_has_no_diagnostics():
    report = require_valid_feature_ir(motor_shaped_feature_ir())
    assert report.valid is True
    assert report.diagnostics == ()
    assert report.schema_version == "1.0.0"


def test_reordered_dependency_fails_before_backend():
    document = motor_shaped_feature_ir()
    features = list(document.features)
    features[0], features[1] = features[1], features[0]
    invalid = document.model_copy(update={"features": tuple(features)})
    assert DiagnosticCode.DEPENDENCY_ORDER in codes(invalid)
    with pytest.raises(FeatureIRValidationError) as exc:
        require_valid_feature_ir(invalid)
    assert exc.value.report.valid is False


def test_missing_parameter_and_zero_division_are_typed_diagnostics():
    document = motor_shaped_feature_ir()
    pad = document.features[1]
    missing = pad.model_copy(update={"length": parameter("missing_parameter")})
    missing_doc = document.model_copy(update={
        "features": (document.features[0], missing, *document.features[2:])
    })
    assert DiagnosticCode.MISSING_PARAMETER in codes(missing_doc)

    zero = BinaryExpression(
        operator=BinaryOperator.DIVIDE, left=literal(5), right=literal(0)
    )
    zero_pad = pad.model_copy(update={"length": zero})
    zero_doc = document.model_copy(update={
        "features": (document.features[0], zero_pad, *document.features[2:])
    })
    assert DiagnosticCode.INVALID_EXPRESSION in codes(zero_doc)


def test_adapter_support_set_refuses_unsupported_feature_explicitly():
    document = motor_shaped_feature_ir()
    supported = {item.type for item in document.features} - {"chamfer"}
    report = validate_feature_ir(document, supported_feature_types=supported)
    unsupported = [
        item for item in report.diagnostics
        if item.code is DiagnosticCode.UNSUPPORTED_FEATURE
    ]
    assert [item.record_id for item in unsupported] == ["edge_chamfer"]


def test_duplicate_parameter_names_and_dangling_membership_are_rejected():
    document = motor_shaped_feature_ir()
    duplicate = document.parameters[1].model_copy(update={"name": "plate_width"})
    duplicate_doc = document.model_copy(update={
        "parameters": (document.parameters[0], duplicate, *document.parameters[2:])
    })
    assert DiagnosticCode.DUPLICATE_PARAMETER_NAME in codes(duplicate_doc)

    body = document.bodies[0].model_copy(update={
        "feature_ids": (*document.bodies[0].feature_ids, "missing_feature")
    })
    body_doc = document.model_copy(update={"bodies": (body,)})
    assert DiagnosticCode.BODY_MEMBERSHIP in codes(body_doc)


def test_dangling_profile_and_interface_references_are_rejected():
    document = motor_shaped_feature_ir()
    pad = document.features[1].model_copy(update={"profile_id": "missing_profile"})
    interface = document.interfaces[0].model_copy(update={
        "parameter_ids": (*document.interfaces[0].parameter_ids, "missing_parameter")
    })
    invalid = document.model_copy(update={
        "features": (document.features[0], pad, *document.features[2:]),
        "interfaces": (interface,),
    })
    found = codes(invalid)
    assert DiagnosticCode.DANGLING_REFERENCE in found
    assert DiagnosticCode.INTERFACE_REFERENCE in found

