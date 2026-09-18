"""Truth-contract tests for the machine-readable capability registry."""

import json

import pytest

from spec2cad.capabilities import (
    CAPABILITIES,
    CAPABILITY_SCHEMA_VERSION,
    HEALTH_CAPABILITY_IDS,
    ImplementationMaturity,
    IntegrationLevel,
    ReleaseRole,
    capability,
    capability_payload,
)


def test_registry_ids_are_unique_and_cover_every_legacy_health_claim():
    ids = [item.id for item in CAPABILITIES]
    assert len(ids) == len(set(ids))
    assert set(HEALTH_CAPABILITY_IDS) <= set(ids)


def test_each_axis_is_independent_for_known_lower_maturity_features():
    assembly = capability("assembly_mates")
    assert assembly.implementation_maturity is ImplementationMaturity.BOUNDED
    assert assembly.integration is IntegrationLevel.STANDALONE_API
    assert assembly.release_role is ReleaseRole.STANDALONE_RESULT

    advanced = capability("sheet_metal_90_bend")
    assert advanced.integration is IntegrationLevel.OPTIONAL_PIPELINE
    assert advanced.release_role is ReleaseRole.GOVERNING
    assert "not full dimensional/interface fidelity" in advanced.limitations[0]

    feature_ir = capability("feature_ir")
    protocol = capability("backend_protocol")
    assert feature_ir.integration is IntegrationLevel.PRODUCTION_PIPELINE
    assert protocol.integration is IntegrationLevel.PRODUCTION_PIPELINE
    assert protocol.supported_backends == ("cadquery", "freecad")


def test_r1h_capabilities_separate_governing_motor_and_advisory_breadth():
    freecad = capability("freecad_backend")
    csg = capability("cad_state_graph")
    reconciliation = capability("cross_backend_reconciliation")
    assert freecad.integration is IntegrationLevel.OPTIONAL_PIPELINE
    assert csg.release_role is ReleaseRole.DIAGNOSTIC
    assert reconciliation.release_role is ReleaseRole.GOVERNING
    assert reconciliation.supported_backends == ("cadquery", "freecad")
    assert "tests/test_r1_native_foundation_benchmark.py" in (
        reconciliation.benchmark_evidence
    )
    assert "tests/test_r2_sensor_fault_localization_benchmark.py" in (
        reconciliation.benchmark_evidence
    )
    assert "eval/r2_sensor_fault_localization_report.json" in (
        reconciliation.benchmark_evidence
    )
    assert reconciliation.version == "1.1.0"
    assert "motor-adapter bounded" in reconciliation.limitations[0]
    assert "four broader compositions" in reconciliation.limitations[0]
    assert "tests/test_r1h_broad_cad.py" in capability("linear_slot_pattern").benchmark_evidence


def test_governing_claims_have_pipeline_integration_and_benchmark_evidence():
    for item in CAPABILITIES:
        if item.release_role is ReleaseRole.GOVERNING:
            assert item.integration in {
                IntegrationLevel.PRODUCTION_PIPELINE,
                IntegrationLevel.OPTIONAL_PIPELINE,
            }
            assert item.benchmark_evidence


def test_registry_serialization_is_deterministic_and_json_compatible():
    first = capability_payload()
    second = capability_payload()
    assert first == second
    assert first["schema_version"] == CAPABILITY_SCHEMA_VERSION
    assert json.loads(json.dumps(first, sort_keys=True)) == first


def test_unknown_capability_fails_loudly():
    with pytest.raises(KeyError, match="unknown capability"):
        capability("invented_backend")
