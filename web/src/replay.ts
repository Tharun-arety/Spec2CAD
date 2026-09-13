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
import type { Health, RunState } from './types'

const BASE = '/replay'

export interface ReplayManifest {
  mode: string
  disclaimer: string
  frozen_at: string
  sketch_backend: string
  applied_proposal: string
  limits: string[]
  state: RunState
}

let cached: ReplayManifest | null = null

async function manifest(): Promise<ReplayManifest> {
  if (!cached) {
    const res = await fetch(`${BASE}/run.json`)
    if (!res.ok) throw new Error(`replay bundle missing (${res.status})`)
    cached = (await res.json()) as ReplayManifest
  }
  return cached
}

/** Deep-ish clone so slicing revisions cannot mutate the cached manifest. */
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T

export class ReplayUnavailable extends Error {}

export const replayApi = {
  isReplay: true,

  async manifest() {
    return manifest()
  },

  async health(): Promise<Health> {
    const m = await manifest()
    return {
      status: 'replay',
      sketch_backend: 'fixture',
      sketch_backend_label: `${m.sketch_backend} · recorded replay`,
      vision_available: false,
    }
  },

  /** The recorded run, rewound to before the repair was approved. */
  async runDemo(): Promise<RunState> {
    const m = await manifest()
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

  /** Only the resolution that was recorded has a rebuilt revision. */
  async repair(_runId: string, proposalId: string): Promise<RunState> {
    const m = await manifest()
    if (proposalId !== m.applied_proposal) {
      throw new ReplayUnavailable(
        `Only the "${m.applied_proposal}" resolution was recorded with rebuilt ` +
        'geometry. Applying a different one needs a CAD kernel, which this ' +
        'deployment does not have.',
      )
    }
    return clone(m.state)
  },

  stlUrl: (_runId: string, rev: number) => `${BASE}/artifacts/v${rev}.stl`,
  stepUrl: (_runId: string, rev: number) => `${BASE}/artifacts/v${rev}.step`,
  previewUrl: (_runId: string, evidenceId: string) =>
    `${BASE}/previews/${evidenceId}.png`,
}
