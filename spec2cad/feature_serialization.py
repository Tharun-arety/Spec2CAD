"""Canonical serialization and content identity for Feature IR."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from spec2cad.feature_validation import require_valid_feature_ir
from spec2cad.schemas.feature_ir import FEATURE_IR_SCHEMA_VERSION, FeatureIR


class FeatureIRSerializationError(ValueError):
    """Serialized Feature IR is ambiguous or does not satisfy its schema."""


class FeatureIRManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    document_id: str
    document_schema_version: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_length: int = Field(gt=0)


def canonical_feature_ir_bytes(document: FeatureIR) -> bytes:
    """Validate and encode all semantic fields with one canonical JSON form."""
    require_valid_feature_ir(document)
    return json.dumps(
        document.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def feature_ir_content_hash(document: FeatureIR) -> str:
    return hashlib.sha256(canonical_feature_ir_bytes(document)).hexdigest()


def feature_ir_manifest(document: FeatureIR) -> FeatureIRManifest:
    payload = canonical_feature_ir_bytes(document)
    return FeatureIRManifest(
        document_id=document.id,
        document_schema_version=document.schema_version,
        content_sha256=hashlib.sha256(payload).hexdigest(),
        byte_length=len(payload),
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise FeatureIRSerializationError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def deserialize_feature_ir(payload: bytes | str) -> FeatureIR:
    try:
        raw = json.loads(payload, object_pairs_hook=_unique_object)
    except FeatureIRSerializationError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
        raise FeatureIRSerializationError(f"invalid Feature IR JSON: {exc}") from exc
    try:
        document = FeatureIR.model_validate(raw)
    except ValidationError as exc:
        raise FeatureIRSerializationError(f"invalid Feature IR document: {exc}") from exc
    if document.schema_version != FEATURE_IR_SCHEMA_VERSION:
        raise FeatureIRSerializationError(
            f"unsupported Feature IR schema {document.schema_version!r}"
        )
    try:
        require_valid_feature_ir(document)
    except ValueError as exc:
        raise FeatureIRSerializationError(f"invalid Feature IR document: {exc}") from exc
    return document

