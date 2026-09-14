import type { Health, RunState } from './types'
import { replayApi } from './replay'

const BASE = '/api'

/**
 * Replay mode is a build-time decision (VITE_REPLAY=1), set for deployments
 * that have no backend. It is never inferred from a failed request, so a
 * backend that is merely down reports an error rather than silently degrading
 * into a recording.
 */
export const IS_REPLAY = import.meta.env.VITE_REPLAY === '1'

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail: unknown = await res.text()
    try {
      detail = JSON.parse(detail as string).detail ?? detail
    } catch {
      /* plain text body */
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return res.json() as Promise<T>
}

const liveApi = {
  isReplay: false,

  health: () => fetch(`${BASE}/health`).then(json<Health>),

  runDemo: () => fetch(`${BASE}/runs/demo`, { method: 'POST' }).then(json<RunState>),

  runUpload: (sketch: File, datasheet: File, requirement: string) => {
    const body = new FormData()
    body.append('sketch', sketch)
    body.append('datasheet', datasheet)
    body.append('requirement', requirement)
    return fetch(`${BASE}/runs`, { method: 'POST', body }).then(json<RunState>)
  },

  repair: (runId: string, proposalId: string, acknowledgeUnsafe = false) =>
    fetch(`${BASE}/runs/${runId}/repair`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        proposal_id: proposalId,
        approved_by: 'ui-user',
        acknowledge_unsafe: acknowledgeUnsafe,
      }),
    }).then(json<RunState>),

  revise: (runId: string, updates: Record<string, number>,
           reason: string, acknowledgeInterface = false) =>
    fetch(`${BASE}/runs/${runId}/revise`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        updates, approved_by: 'ui-user', reason,
        acknowledge_interface: acknowledgeInterface,
      }),
    }).then(json<RunState>),

  stlUrl: (runId: string, rev: number) =>
    `${BASE}/runs/${runId}/revisions/${rev}/model.stl`,
  stepUrl: (runId: string, rev: number) =>
    `${BASE}/runs/${runId}/revisions/${rev}/model.step`,
  previewUrl: (runId: string, evidenceId: string) =>
    `${BASE}/runs/${runId}/evidence/${evidenceId}/preview`,
}

export const api = IS_REPLAY
  ? {
      ...replayApi,
      runUpload: (_s: File, _d: File, _r: string) => replayApi.runUpload(),
      revise: (_id: string, _u: Record<string, number>, _r: string, _a?: boolean) =>
        replayApi.revise(),
      repair: (runId: string, proposalId: string, _ack?: boolean) =>
        replayApi.repair(runId, proposalId),
    }
  : liveApi
