"""Persisted roots and SQLite migrations are explicit and fail closed."""

import json
import sqlite3

import pytest
from pydantic import ValidationError

from spec2cad.schemas.cad_ir import CADProgram
from spec2cad.schemas.design_intent import DesignIntent, PartInfo
from spec2cad.schemas.evidence import EvidenceSet
from spec2cad.schemas.intent_graph import EngineeringIntentGraph
from spec2cad.schemas.report import CheckStage, Report
from spec2cad.schemas.versioning import PERSISTED_SCHEMA_VERSION
from spec2cad.store import DATABASE_SCHEMA_VERSION, Store


def _intent() -> DesignIntent:
    return DesignIntent(part=PartInfo(name="migration_test"))


def test_every_existing_persisted_root_has_an_explicit_version():
    roots = [
        EvidenceSet(), _intent(), EngineeringIntentGraph(), CADProgram(part_name="p"),
        Report(stage=CheckStage.SCHEMA, design_revision=1),
    ]
    assert {root.model_dump(mode="json")["schema_version"] for root in roots} == {
        PERSISTED_SCHEMA_VERSION
    }


def test_new_store_records_sequential_database_migration(tmp_path):
    path = tmp_path / "new.db"
    Store(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == DATABASE_SCHEMA_VERSION
        rows = conn.execute(
            "SELECT version, description FROM schema_migrations ORDER BY version"
        ).fetchall()
    assert rows == [(1, "establish versioned evidence, intent, EIG, report and state roots")]


def test_legacy_unversioned_json_is_normalized_without_rewriting_rows(tmp_path):
    path = tmp_path / "legacy.db"
    store = Store(path)
    run_id = store.create_run(tmp_path, EvidenceSet(), "fixture")
    store.save_revision(run_id, _intent(), {"intent_graph": {"revision": 1, "nodes": [], "edges": []}})

    with sqlite3.connect(path) as conn:
        evidence = json.loads(conn.execute(
            "SELECT evidence_json FROM runs WHERE id = ?", (run_id,)
        ).fetchone()[0])
        evidence.pop("schema_version")
        intent_json, state_json = conn.execute(
            "SELECT intent_json, state_json FROM revisions WHERE run_id = ?", (run_id,)
        ).fetchone()
        intent = json.loads(intent_json)
        state = json.loads(state_json)
        intent.pop("schema_version")
        state.pop("schema_version")
        conn.execute("UPDATE runs SET evidence_json = ? WHERE id = ?", (json.dumps(evidence), run_id))
        conn.execute(
            "UPDATE revisions SET intent_json = ?, state_json = ? WHERE run_id = ?",
            (json.dumps(intent), json.dumps(state), run_id),
        )
        conn.execute("DELETE FROM schema_migrations")
        conn.execute("PRAGMA user_version = 0")
        conn.commit()

    reopened = Store(path)
    assert reopened.get_run(run_id).evidence.schema_version == PERSISTED_SCHEMA_VERSION
    assert reopened.get_intent(run_id, 1).schema_version == PERSISTED_SCHEMA_VERSION
    assert reopened.get_state(run_id, 1)["schema_version"] == PERSISTED_SCHEMA_VERSION
    assert reopened.get_intent_graph(run_id, 1).schema_version == PERSISTED_SCHEMA_VERSION


def test_unknown_future_database_and_document_versions_fail_closed(tmp_path):
    path = tmp_path / "future.db"
    Store(path)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version = 999")
    with pytest.raises(RuntimeError, match="newer than supported"):
        Store(path)

    with pytest.raises(ValidationError):
        EvidenceSet.model_validate({"schema_version": "99.0.0", "items": []})
