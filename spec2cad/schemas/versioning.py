"""Version identifiers shared by persisted root documents."""

PERSISTED_SCHEMA_VERSION = "1.0.0"
LEGACY_UNVERSIONED_SCHEMA = "0.0.0"


def normalize_legacy_root(payload: dict) -> dict:
    """Return a current-version copy of an unversioned legacy root payload."""
    version = payload.get("schema_version", LEGACY_UNVERSIONED_SCHEMA)
    if version == LEGACY_UNVERSIONED_SCHEMA:
        return {"schema_version": PERSISTED_SCHEMA_VERSION, **payload}
    if version != PERSISTED_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported persisted schema version {version!r}; "
            f"this build supports {PERSISTED_SCHEMA_VERSION!r}"
        )
    return payload

