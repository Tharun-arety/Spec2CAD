import type { Health, RunState } from './types'

const BASE = '/api'

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

export const api = {
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

  stlUrl: (runId: string, rev: number) =>
    `${BASE}/runs/${runId}/revisions/${rev}/model.stl`,
  stepUrl: (runId: string, rev: number) =>
    `${BASE}/runs/${runId}/revisions/${rev}/model.step`,
  previewUrl: (runId: string, evidenceId: string) =>
    `${BASE}/runs/${runId}/evidence/${evidenceId}/preview`,
}
