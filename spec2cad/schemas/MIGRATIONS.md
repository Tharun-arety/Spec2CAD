# Persisted schema migration policy

Current root-document version: `1.0.0`  
Current SQLite schema version: `PRAGMA user_version = 1`

Persisted root documents—`EvidenceSet`, `DesignIntent`,
`EngineeringIntentGraph`, `CADProgram`, `Report`, and the revision-state
envelope—carry `schema_version`. SQLite migrations are sequential, recorded in
`schema_migrations`, and update `PRAGMA user_version` only after their migration
step succeeds.

## Compatibility rules

- Missing `schema_version` is the single supported legacy form (`0.0.0`). It is
  normalized in memory to `1.0.0`; the next write persists the current version.
- Patch versions may clarify validation without changing serialized meaning.
- Minor versions may add optional fields with deterministic defaults. Readers
  must preserve or explicitly migrate their meaning before rewriting them.
- Major versions indicate an incompatible semantic change and require an
  explicit, tested migrator. They are never guessed from payload shape.
- Unknown future document versions and SQLite versions fail closed. This build
  never silently downgrades or rewrites data it does not understand.
- Migrations are additive or copy-on-write. Destructive column/table removal
  requires an owner-approved decision, backup/restore evidence, and a new major
  schema version.
- A migration test must cover the oldest supported input, the current output,
  idempotent reopening, and refusal of unknown future versions.

## Version 1.0.0 / database migration 1

- Establishes explicit versions for the existing evidence, intent, EIG,
  CADProgram, report and revision-state roots.
- Adds the SQLite `schema_migrations` ledger and initializes
  `PRAGMA user_version` to `1` without rewriting existing run or revision rows.
- Treats pre-versioning JSON documents as legacy version `0.0.0`; model defaults
  and state-envelope normalization provide the compatible read path.

