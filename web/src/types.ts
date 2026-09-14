export type Status = 'pass' | 'fail' | 'warn' | 'skipped'

export interface SourceRef {
  file: string
  modality: string
  page: number | null
  region: number[] | null
  detail: string | null
}

export interface Evidence {
  id: string
  target: string
  kind: string
  value: number | string
  unit: string | null
  source: SourceRef
  extraction_method: string
  confidence: number
  authority: string
  is_explicit_annotation: boolean
  is_fixture: boolean
  raw_text: string | null
  original_value: string | null
  has_preview: boolean
}

export interface Check {
  id: string
  stage: string
  name: string
  status: Status
  expected: string | null
  actual: string | null
  required_value: number | null
  measured_value: number | null
  conflict_class: string | null
  responsible_parameters: string[]
  message: string
}

export interface Parameter {
  value: number | string | null
  unit: string | null
  status: string
  provenance: string[]
  authority: string
  is_explicit: boolean
  derivation: string | null
  competing_values: Record<string, unknown>[]
}

export interface Proposal {
  id: string
  title: string
  safety: 'safe' | 'unsafe'
  updates: Record<string, number>
  rationale: string
  consequence: string | null
  recommended: boolean
  auto_applicable: boolean
}

export interface Release {
  status: string
  step_export_allowed: boolean
  watermark: string | null
  reasons: string[]
  explanation: string
  responsible_parameters: string[]
}

export interface OpField {
  name: string
  value: number | boolean | string | null
  parameter: string | null
}

/**
 * What the kernel reported after building one operation.
 *
 * Null when the operation never got as far as being built. The UI must show
 * that as "not built" rather than implying a zero measurement.
 */
export interface OpMeasurement {
  volume: number
  volume_delta: number
  is_valid: boolean
  solid_count: number
  seconds: number
  no_op: boolean
}

export interface Operation {
  id: string
  type: string
  /** What we asked the kernel to do. */
  fields: OpField[]
  /** What the solid looked like afterwards. */
  measured: OpMeasurement | null
}

export interface EditableParam {
  name: string
  value: number
  unit: string | null
  interface_critical: boolean
}

export interface Revision {
  revision: number
  parent_revision: number | null
  lineage: string
  applied_proposal: string | null
  approved_by: string | null
  changes: { parameter: string; before: unknown; after: unknown; reason: string }[]
  part: { name: string; material: string | null; manufacturing_process: string | null }
  parameters: Record<string, Parameter>
  constraints: { id: string; type: string; value: number; unit: string; severity: string }[]
  feature_sequence: string[]
  operations: Operation[]
  editable_parameters: EditableParam[]
  preflight: Check[]
  measured: Check[]
  cross_checks: Check[]
  build_error: string | null
  release: Release
  proposals: Proposal[]
  script: string
}

export interface RunState {
  run_id: string
  sketch_backend: string
  sketch_fell_back: boolean
  sketch_fallback_reason: string | null
  contains_fixture_evidence: boolean
  evidence: Evidence[]
  revisions: Revision[]
  latest_revision: number
}

export interface Health {
  status: string
  sketch_backend: string
  sketch_backend_label: string
  vision_available: boolean
}
