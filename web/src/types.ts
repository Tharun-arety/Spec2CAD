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
  value: unknown
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

export interface BackendEvidenceCheck {
  name: string
  left: number
  right: number
  tolerance: number
  consistent: boolean
}

export interface BackendEvidence {
  mode: 'dual_backend'
  feature_ir_sha256: string
  backends: Record<string, {
    status: string
    version?: string | null
    csg_sha256?: string | null
  }>
  classification: string
  governing: boolean
  checks: BackendEvidenceCheck[]
  reasons: string[]
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
  derived_geometry?: Record<string, number>
  editable_parameters: EditableParam[]
  preflight: Check[]
  measured: Check[]
  cross_checks: Check[]
  backend_evidence?: BackendEvidence | null
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
  reasoning_backend?: string
  reasoning_fell_back?: boolean
  reasoning_fallback_reason?: string | null
  unsupported_features?: string[]
  clarification_questions?: string[]
  messages?: ChatMessage[]
  feature_requests?: Record<string, unknown>[]
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
  vision_model?: string | null
  reasoning_available?: boolean
  reasoning_model?: string | null
  model_connections?: {
    bring_your_own_key: boolean
    providers: string[]
    compatible_hosts: string[]
    credentials_persisted: boolean
  }
  public_limits?: {
    requests_per_minute: number
    ai_units_per_client_day: number
    max_requirement_chars: number
    max_conversation_messages: number
    max_concurrent_jobs?: number
    job_queue_timeout_ms?: number
    max_cached_runs?: number
  }
  capabilities?: string[]
  capability_registry?: CapabilityRegistry
}

export interface CapabilityRecord {
  id: string
  label: string
  category: 'extraction' | 'representation' | 'geometry' | 'inspection' | 'engineering' | 'platform'
  summary: string
  implementation_maturity: 'unavailable' | 'fixture' | 'bounded' | 'proven'
  integration: 'absent' | 'library' | 'showcase' | 'standalone_api' | 'optional_pipeline' | 'production_pipeline'
  release_role: 'none' | 'diagnostic' | 'standalone_result' | 'governing'
  supported_backends: string[]
  benchmark_evidence: string[]
  limitations: string[]
  version: string
}

export interface CapabilityRegistry {
  schema_version: string
  capabilities: CapabilityRecord[]
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  kind: 'request' | 'answer' | 'clarification' | 'result' | 'error' | 'message'
  created_at: string
}
