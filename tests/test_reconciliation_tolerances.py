"""Contract tests for the declared R1 cross-backend tolerance policy."""

import json

import pytest
from pydantic import ValidationError

from spec2cad.reconciliation import (
    R1_TOLERANCE_POLICY,
    QuantityKind,
    ToleranceRule,
)


def test_dimension_and_position_accept_the_exact_boundary():
    dimension = R1_TOLERANCE_POLICY.compare(
        QuantityKind.DIMENSION, 50.0, 50.01, unit="mm"
    )
    position = R1_TOLERANCE_POLICY.compare(
        QuantityKind.POSITION, -15.5, -15.49, unit="mm"
    )
    assert dimension.consistent is True
    assert position.consistent is True
    assert dimension.allowed_error == pytest.approx(0.01)


def test_difference_outside_linear_boundary_is_inconsistent():
    result = R1_TOLERANCE_POLICY.compare(
        QuantityKind.DIMENSION, 22.5, 22.5101, unit="mm"
    )
    assert result.consistent is False
    assert result.absolute_error > result.allowed_error


def test_volume_uses_the_larger_of_absolute_and_relative_tolerance():
    motor = R1_TOLERANCE_POLICY.compare(
        QuantityKind.VOLUME, 9070.376844, 9070.386844, unit="mm3"
    )
    large = R1_TOLERANCE_POLICY.compare(
        QuantityKind.VOLUME, 1_000_000_000.0, 1_000_000_900.0, unit="mm3"
    )
    assert motor.allowed_error == pytest.approx(0.01)
    assert large.allowed_error == pytest.approx(1000.0)
    assert motor.consistent and large.consistent


def test_unit_mismatch_and_nonfinite_values_are_refused():
    with pytest.raises(ValueError, match="requires mm"):
        R1_TOLERANCE_POLICY.compare(
            QuantityKind.POSITION, 0.0, 0.0, unit="inch"
        )
    with pytest.raises(ValueError, match="must be finite"):
        R1_TOLERANCE_POLICY.compare(
            QuantityKind.DIMENSION, 1.0, float("nan"), unit="mm"
        )
    with pytest.raises(ValidationError):
        ToleranceRule(unit="mm", absolute=float("inf"))


def test_policy_is_versioned_and_json_serializable():
    payload = R1_TOLERANCE_POLICY.model_dump(mode="json")
    assert payload["schema_version"] == "1.0.0"
    assert payload["policy_version"] == "1.0.0"
    assert json.loads(R1_TOLERANCE_POLICY.model_dump_json()) == payload

