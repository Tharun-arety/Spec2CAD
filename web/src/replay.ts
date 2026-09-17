/**
 * Static replay client.
 *
 * Used where there is no backend — Vercel cannot host this pipeline, because
 * CadQuery/OpenCascade is a ~163 MB native dependency and a serverless function
 * would have to load a 118 MB binary on every cold start.
 *
 * So the deployed build replays a real recorded run instead of faking one. The
 * evidence, both DesignIntent revisions, every report, both meshes, the
 * authorised STEP and all the source highlights are genuine outputs of the
 * pipeline, frozen by scripts/freeze_demo.py.
 *
 * What it will NOT do is pretend. Uploading documents and applying a resolution
 * that was not recorded both fail with an explanation, rather than quietly
 * returning the one result that happens to be on disk.
 */
import type { CapabilityRegistry, Health, RunState } from './types'

const BASE = '/replay'

export interface ReplayScenario {
  id: string
  step: string
  title: string
  focus: string
  proof: string
  uncertainty: string
  description: string
  capabilities: string[]
  capability_ids?: string[]
  operation: string
  inputs: Array<'text' | 'sketch' | 'document'>
}

export interface ReplayCatalog {
  mode: string
  disclaimer: string
  frozen_at: string
  default_scenario: string
  scenarios: ReplayScenario[]
}

export interface ReplayManifest {
  mode: string
  scenario: ReplayScenario
  disclaimer: string
  frozen_at: string
  sketch_backend: string
  applied_proposal: string | null
  limits: string[]
  state: RunState
}

let cachedCatalog: ReplayCatalog | null = null
let catalogPromise: Promise<ReplayCatalog> | null = null
let cachedCapabilities: CapabilityRegistry | null = null
let capabilitiesPromise: Promise<CapabilityRegistry> | null = null
const cachedManifests = new Map<string, ReplayManifest>()
const manifestPromises = new Map<string, Promise<ReplayManifest>>()

function catalog(): Promise<ReplayCatalog> {
  if (cachedCatalog) return Promise.resolve(cachedCatalog)
  if (!catalogPromise) {
    catalogPromise = fetch(`${BASE}/catalog.json`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`replay catalog missing (${res.status})`)
        cachedCatalog = (await res.json()) as ReplayCatalog
        return cachedCatalog
      })
      .catch((error: unknown) => {
        // A rejected promise is not a cache entry. Let the visible Retry action
        // issue a fresh request after a transient/static-host failure.
        catalogPromise = null
        throw error
      })
  }
  return catalogPromise
}

function capabilities(): Promise<CapabilityRegistry> {
  if (cachedCapabilities) return Promise.resolve(cachedCapabilities)
  if (!capabilitiesPromise) {
    capabilitiesPromise = fetch(`${BASE}/capabilities.json`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`capability registry missing (${res.status})`)
        cachedCapabilities = (await res.json()) as CapabilityRegistry
        return cachedCapabilities
      })
  }
  return capabilitiesPromise
}

async function manifest(scenarioId?: string): Promise<ReplayManifest> {
  const showcase = await catalog()
  const id = scenarioId ?? showcase.default_scenario
  const known = showcase.scenarios.some((scenario) => scenario.id === id)
  if (!known) throw new Error(`recorded scenario not found: ${id}`)
  const cached = cachedManifests.get(id)
  if (cached) return cached
  let pending = manifestPromises.get(id)
  if (!pending) {
    pending = fetch(`${BASE}/scenarios/${encodeURIComponent(id)}/run.json`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`replay bundle missing for ${id} (${res.status})`)
        const next = (await res.json()) as ReplayManifest
        cachedManifests.set(id, next)
        return next
      })
    manifestPromises.set(id, pending)
  }
  return pending
}

/** Deep-ish clone so slicing revisions cannot mutate the cached manifest. */
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T

export class ReplayUnavailable extends Error {}

const scenarioFromRun = (runId: string) =>
  runId.startsWith('recorded-') ? runId.slice('recorded-'.length) : undefined

const bundleBase = (runId: string) => {
  const scenarioId = scenarioFromRun(runId)
  return scenarioId
    ? `${BASE}/scenarios/${encodeURIComponent(scenarioId)}`
    : `${BASE}/scenarios/flanged-shaft-coupling`
}

export const replayApi = {
  isReplay: true,

  catalog,
  manifest,

  async health(): Promise<Health> {
    const [m, registry] = await Promise.all([manifest(), capabilities()])
    return {
      status: 'replay',
      sketch_backend: 'fixture',
      sketch_backend_label: `${m.sketch_backend} · recorded replay`,
      vision_available: false,
      capabilities: registry.capabilities
        .filter((item) => item.implementation_maturity !== 'unavailable')
        .map((item) => item.id),
      capability_registry: registry,
    }
  },

  /** The recorded run, rewound to before the repair was approved. */
  async runDemo(scenarioId?: string): Promise<RunState> {
    const m = await manifest(scenarioId)
    const state = clone(m.state)
    state.revisions = state.revisions.filter((r) => r.revision === 1)
    state.latest_revision = 1
    return state
  },

  async runUpload(): Promise<RunState> {
    throw new ReplayUnavailable(
      'This deployment replays a recorded run and has no CAD kernel behind it, ' +
      'so it cannot process uploaded documents. Run the project locally, or ' +
      'deploy the FastAPI backend as a container, to compile your own.',
    )
  },

  async revise(): Promise<RunState> {
    throw new ReplayUnavailable(
      'Creating a revision means rebuilding the part, and this deployment has no ' +
      'CAD kernel behind it. Run the project locally, or deploy the FastAPI ' +
      'backend as a container, to edit parameters and generate new revisions.',
    )
  },

  /** Only the resolution that was recorded has a rebuilt revision. */
  async repair(_runId: string, proposalId: string): Promise<RunState> {
    const m = await manifest(scenarioFromRun(_runId))
    if (!m.applied_proposal || proposalId !== m.applied_proposal) {
      throw new ReplayUnavailable(
        m.applied_proposal
          ? `Only the "${m.applied_proposal}" resolution was recorded with rebuilt ` +
            'geometry. Applying a different one needs a CAD kernel, which this ' +
            'deployment does not have.'
          : 'This recorded scenario has no repair revision. Applying a resolution ' +
            'needs a CAD kernel, which this deployment does not have.',
      )
    }
    return clone(m.state)
  },

  stlUrl: (runId: string, rev: number) => `${bundleBase(runId)}/artifacts/v${rev}.stl`,
  stepUrl: (runId: string, rev: number) => `${bundleBase(runId)}/artifacts/v${rev}.step`,
  previewUrl: (runId: string, evidenceId: string) =>
    `${bundleBase(runId)}/previews/${evidenceId}.png`,
  sourceUrl: (runId: string, filename: string) =>
    `${bundleBase(runId)}/sources/${encodeURIComponent(filename)}`,
}
