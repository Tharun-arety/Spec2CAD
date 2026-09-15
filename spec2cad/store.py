"""SQLite persistence for runs and their revisions.

Geometry is deliberately NOT stored. Because the pipeline is deterministic, a
persisted EngineeringIntentGraph plus the compiler is enough to reproduce the
exact solid on demand -- storing the B-Rep as well would create a second source
of truth that could drift from the intent that supposedly produced it.

What is persisted is the evidence, every intent graph and DesignIntent revision
with its lineage, and the reports. That is the audit trail: it answers "what did
we believe, on what grounds, and who changed it" after a restart.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from spec2cad.schemas.design_intent import DesignIntent
from spec2cad.schemas.evidence import EvidenceSet
from spec2cad.schemas.intent_graph import EngineeringIntentGraph

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id                TEXT PRIMARY KEY,
    created_at        TEXT NOT NULL,
    input_dir         TEXT NOT NULL,
    sketch_backend    TEXT NOT NULL,
    sketch_fell_back  INTEGER NOT NULL DEFAULT 0,
    fallback_reason   TEXT,
    evidence_json     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS revisions (
    run_id       TEXT NOT NULL,
    revision     INTEGER NOT NULL,
    created_at   TEXT NOT NULL,
    intent_json  TEXT NOT NULL,
    state_json   TEXT NOT NULL,
    PRIMARY KEY (run_id, revision),
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS api_usage (
    day          TEXT NOT NULL,
    client_hash  TEXT NOT NULL,
    units        INTEGER NOT NULL,
    PRIMARY KEY (day, client_hash)
);
"""


@dataclass
class StoredRun:
    id: str
    created_at: str
    input_dir: Path
    sketch_backend: str
    sketch_fell_back: bool
    fallback_reason: Optional[str]
    evidence: EvidenceSet


class Store:
    def __init__(self, db_path: str | Path = "build/spec2cad.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ---------------- runs ----------------

    def create_run(
        self,
        input_dir: Path,
        evidence: EvidenceSet,
        sketch_backend: str,
        fell_back: bool = False,
        fallback_reason: Optional[str] = None,
    ) -> str:
        # Full 128-bit identifiers act as possession tokens for otherwise
        # unauthenticated public runs and their uploaded source documents.
        run_id = uuid.uuid4().hex
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO runs (id, created_at, input_dir, sketch_backend, "
                "sketch_fell_back, fallback_reason, evidence_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    datetime.now(timezone.utc).isoformat(),
                    str(input_dir),
                    sketch_backend,
                    int(fell_back),
                    fallback_reason,
                    evidence.model_dump_json(),
                ),
            )
            conn.commit()
        return run_id

    def get_run(self, run_id: str) -> Optional[StoredRun]:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return StoredRun(
            id=row["id"],
            created_at=row["created_at"],
            input_dir=Path(row["input_dir"]),
            sketch_backend=row["sketch_backend"],
            sketch_fell_back=bool(row["sketch_fell_back"]),
            fallback_reason=row["fallback_reason"],
            evidence=EvidenceSet.model_validate_json(row["evidence_json"]),
        )

    def list_runs(self, limit: int = 50) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id, created_at, sketch_backend FROM runs "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def reserve_api_units(
        self,
        day: str,
        client_hash: str,
        units: int,
        *,
        client_limit: int,
        global_limit: int,
    ) -> tuple[int, int]:
        """Atomically reserve daily model-call units across worker processes."""
        if units <= 0:
            raise ValueError("usage units must be positive")
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            client_used = conn.execute(
                "SELECT COALESCE(SUM(units), 0) AS n FROM api_usage "
                "WHERE day = ? AND client_hash = ?",
                (day, client_hash),
            ).fetchone()["n"]
            global_used = conn.execute(
                "SELECT COALESCE(SUM(units), 0) AS n FROM api_usage WHERE day = ?",
                (day,),
            ).fetchone()["n"]
            if client_used + units > client_limit:
                conn.rollback()
                raise ValueError("client_daily_limit")
            if global_used + units > global_limit:
                conn.rollback()
                raise ValueError("global_daily_limit")
            conn.execute(
                "INSERT INTO api_usage (day, client_hash, units) VALUES (?, ?, ?) "
                "ON CONFLICT(day, client_hash) DO UPDATE SET units = units + excluded.units",
                (day, client_hash, units),
            )
            conn.commit()
            return client_used + units, global_used + units

    # ---------------- revisions ----------------

    def save_revision(self, run_id: str, intent: DesignIntent, state: dict) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO revisions "
                "(run_id, revision, created_at, intent_json, state_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    run_id,
                    intent.revision,
                    datetime.now(timezone.utc).isoformat(),
                    intent.model_dump_json(),
                    json.dumps(state, default=str),
                ),
            )
            conn.commit()

    def get_intent(self, run_id: str, revision: int) -> Optional[DesignIntent]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT intent_json FROM revisions WHERE run_id = ? AND revision = ?",
                (run_id, revision),
            ).fetchone()
        return DesignIntent.model_validate_json(row["intent_json"]) if row else None

    def get_state(self, run_id: str, revision: int) -> Optional[dict]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT state_json FROM revisions WHERE run_id = ? AND revision = ?",
                (run_id, revision),
            ).fetchone()
        return json.loads(row["state_json"]) if row else None

    def get_intent_graph(
        self, run_id: str, revision: int
    ) -> Optional[EngineeringIntentGraph]:
        """Restore the graph embedded in the persisted revision state."""
        state = self.get_state(run_id, revision)
        payload = state.get("intent_graph") if state else None
        return EngineeringIntentGraph.model_validate(payload) if payload else None

    def list_revisions(self, run_id: str) -> list[int]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT revision FROM revisions WHERE run_id = ? ORDER BY revision",
                (run_id,),
            ).fetchall()
        return [r["revision"] for r in rows]

    def latest_revision(self, run_id: str) -> Optional[int]:
        revisions = self.list_revisions(run_id)
        return revisions[-1] if revisions else None
