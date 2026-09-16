"""Canonical Feature IR identity is stable and strict."""

import json
from pathlib import Path

import pytest

from spec2cad.feature_compiler import compile_feature_ir
from spec2cad.feature_serialization import (
    FeatureIRSerializationError,
    canonical_feature_ir_bytes,
    deserialize_feature_ir,
    feature_ir_content_hash,
    feature_ir_manifest,
)
from spec2cad.pipeline import run
from tests.test_feature_ir_schema import motor_shaped_feature_ir


ROOT = Path(__file__).resolve().parents[1]
MOTOR = ROOT / "examples" / "motor_adapter"


def compiled_motor():
    result = run(
        MOTOR / "sketch.png", MOTOR / "motor_datasheet.pdf",
        MOTOR / "requirement.txt", backend_override="fixture",
    )
    return compile_feature_ir(result.latest.intent_graph)


def test_actual_motor_feature_ir_has_repeatable_bytes_hash_and_manifest():
    document = compiled_motor()
    first = canonical_feature_ir_bytes(document)
    second = canonical_feature_ir_bytes(document)
    manifest = feature_ir_manifest(document)
    assert first == second
    assert feature_ir_content_hash(document) == manifest.content_sha256
    assert manifest.byte_length == len(first)
    assert manifest.document_schema_version == "1.0.0"
    assert deserialize_feature_ir(first) == document


def test_input_json_key_order_does_not_change_canonical_identity():
    document = motor_shaped_feature_ir()
    payload = document.model_dump(mode="json")
    reversed_payload = dict(reversed(list(payload.items())))
    restored = deserialize_feature_ir(json.dumps(reversed_payload))
    assert canonical_feature_ir_bytes(restored) == canonical_feature_ir_bytes(document)
    assert feature_ir_content_hash(restored) == feature_ir_content_hash(document)


def test_semantic_value_change_changes_content_hash():
    document = motor_shaped_feature_ir()
    changed_parameter = document.parameters[0].model_copy(update={"value": 46.0})
    changed = document.model_copy(update={
        "parameters": (changed_parameter, *document.parameters[1:])
    })
    assert feature_ir_content_hash(changed) != feature_ir_content_hash(document)


def test_duplicate_json_keys_are_refused_before_model_validation():
    with pytest.raises(FeatureIRSerializationError, match="duplicate JSON key"):
        deserialize_feature_ir(
            '{"schema_version":"1.0.0","schema_version":"1.0.0"}'
        )


def test_unknown_schema_and_invalid_dependencies_are_refused():
    payload = motor_shaped_feature_ir().model_dump(mode="json")
    payload["schema_version"] = "99.0.0"
    with pytest.raises(FeatureIRSerializationError, match="invalid Feature IR document"):
        deserialize_feature_ir(json.dumps(payload))

    document = motor_shaped_feature_ir()
    pad = document.features[1].model_copy(update={"sketch_id": "missing_sketch"})
    invalid = document.model_copy(update={
        "features": (document.features[0], pad, *document.features[2:])
    })
    with pytest.raises(ValueError, match="missing_sketch"):
        canonical_feature_ir_bytes(invalid)

