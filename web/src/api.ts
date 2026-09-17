import type { Health, RunState } from './types'
import { replayApi } from './replay'

/**
 * Two ways this app can be backed, and it is always explicit about which.
 *
 *   live    a real FastAPI + CadQuery backend. VITE_API_BASE points at it
 *           (the deployed one), or it falls through to the dev proxy at /api.
 *   replay  the frozen recording in /replay. Genuine pipeline output, but a
 *           recording: no uploads, no new revisions.
 *
 * The deployed backend runs on a free instance that sleeps after 15 minutes,
 * so a cold visitor waits 30-50 s for the container plus ~2.4 s for CadQuery to
 * import. That is surfaced as a waking state rather than a hung spinner, and if
 * it never comes back the user is OFFERED the replay -- never silently given it.
 */

const API_BASE: string = import.meta.env.VITE_API_BASE || '/api'

export interface ModelConnectionInput {
  provider: 'openai' | 'openai_compatible'
  apiKey: string
  model: string
  baseUrl?: string
}

function modelHeaders(connection?: ModelConnectionInput | null): Record<string, string> {
  return connection
    ? { 'X-Spec2CAD-Model-API-Key': connection.apiKey }
    : {}
}

function appendModelConnection(body: FormData, connection?: ModelConnectionInput | null) {
  if (!connection) return
  body.append('model_provider', connection.provider)
  body.append('model_name', connection.model)
  if (connection.baseUrl) body.append('model_base_url', connection.baseUrl)
}

/** Replay only; there is no backend at all. */
export const FORCED_REPLAY = import.meta.env.VITE_REPLAY === '1'

/** The frozen bundle is present and may be offered if the backend is down. */
export const REPLAY_AVAILABLE =
  FORCED_REPLAY || import.meta.env.VITE_REPLAY_FALLBACK === '1'

/** True when the backend is remote, so waking it is a real wait worth showing. */
export const REMOTE_BACKEND = !!import.meta.env.VITE_API_BASE

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail: unknown = await res.text()
    try {
      detail = JSON.parse(detail as string).detail ?? detail
    } catch {
      /* plain text body */
    }
    const requestId = res.headers.get('X-Request-ID')
    const message = typeof detail === 'string' ? detail : JSON.stringify(detail)
    throw new Error(requestId ? `${message} (request ${requestId})` : message)
  }
  return res.json() as Promise<T>
}

const LIVE_REQUEST_TIMEOUT_MS = 75_000

/**
 * Bound non-idempotent live calls without retrying them. A retry could create a
 * second paid model call or CAD revision after the first request reached the
 * server, so recovery stays an explicit user action with the draft preserved.
 */
async function liveRequest<T>(url: string, init: RequestInit): Promise<T> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), LIVE_REQUEST_TIMEOUT_MS)
  try {
    const response = await fetch(url, { ...init, signal: controller.signal })
    return await json<T>(response)
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('The request exceeded 75 seconds. Your inputs are still here; check the service and retry once.')
    }
    throw error
  } finally {
    window.clearTimeout(timer)
  }
}

const liveApi = {
  isReplay: false,

  health: () => fetch(`${API_BASE}/health`).then(json<Health>),

  runDemo: () => liveRequest<RunState>(`${API_BASE}/runs/demo`, { method: 'POST' }),

  runUpload: (
    sketch: File | null,
    datasheet: File | null,
    requirement: string,
    connection?: ModelConnectionInput | null,
  ) => {
    const body = new FormData()
    if (sketch) body.append('sketch', sketch)
    if (datasheet) body.append('datasheet', datasheet)
    if (requirement.trim()) body.append('requirement', requirement.trim())
    appendModelConnection(body, connection)
    return liveRequest<RunState>(`${API_BASE}/runs`, {
      method: 'POST', body, headers: modelHeaders(connection),
    })
  },

  continueRun: (
    runId: string, message: string, connection?: ModelConnectionInput | null,
  ) =>
    liveRequest<RunState>(`${API_BASE}/runs/${runId}/messages`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...modelHeaders(connection),
      },
      body: JSON.stringify({
        message,
        model_provider: connection?.provider,
        model_name: connection?.model,
        model_base_url: connection?.baseUrl,
      }),
    }),

  repair: (runId: string, proposalId: string, acknowledgeUnsafe = false) =>
    liveRequest<RunState>(`${API_BASE}/runs/${runId}/repair`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        proposal_id: proposalId,
        approved_by: 'ui-user',
        acknowledge_unsafe: acknowledgeUnsafe,
      }),
    }),

  revise: (runId: string, updates: Record<string, number>,
           reason: string, acknowledgeInterface = false) =>
    liveRequest<RunState>(`${API_BASE}/runs/${runId}/revise`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        updates, approved_by: 'ui-user', reason,
        acknowledge_interface: acknowledgeInterface,
      }),
    }),

  stlUrl: (runId: string, rev: number) =>
    `${API_BASE}/runs/${runId}/revisions/${rev}/model.stl`,
  stepUrl: (runId: string, rev: number) =>
    `${API_BASE}/runs/${runId}/revisions/${rev}/model.step`,
  previewUrl: (runId: string, evidenceId: string) =>
    `${API_BASE}/runs/${runId}/evidence/${evidenceId}/preview`,
  sourceUrl: (runId: string, filename: string) =>
    `${API_BASE}/runs/${runId}/sources/${encodeURIComponent(filename)}`,
}

const replayAdapter = {
  ...replayApi,
  runUpload: (
    _s: File | null, _d: File | null, _r: string, _c?: ModelConnectionInput | null,
  ) => replayApi.runUpload(),
  continueRun: (
    _id: string, _message: string, _c?: ModelConnectionInput | null,
  ) => replayApi.revise(),
  repair: (runId: string, proposalId: string, _ack?: boolean) =>
    replayApi.repair(runId, proposalId),
  revise: (_id: string, _u: Record<string, number>, _r: string, _a?: boolean) =>
    replayApi.revise(),
}

type Impl = typeof liveApi | typeof replayAdapter

let impl: Impl = FORCED_REPLAY ? (replayAdapter as Impl) : (liveApi as Impl)

/** Switch backing mode. Called only from an explicit user choice. */
export function setApiMode(mode: 'live' | 'replay') {
  impl = mode === 'replay' ? (replayAdapter as Impl) : (liveApi as Impl)
}

/** Stable facade so components keep a single import regardless of mode. */
export const api = {
  get isReplay() { return impl.isReplay },
  health: () => impl.health(),
  runDemo: () => impl.runDemo(),
  runUpload: (
    s: File | null, d: File | null, r: string, connection?: ModelConnectionInput | null,
  ) => impl.runUpload(s, d, r, connection),
  continueRun: (
    runId: string, message: string, connection?: ModelConnectionInput | null,
  ) => impl.continueRun(runId, message, connection),
  repair: (runId: string, proposalId: string, ack?: boolean) =>
    impl.repair(runId, proposalId, ack),
  revise: (runId: string, updates: Record<string, number>, reason: string, ack?: boolean) =>
    impl.revise(runId, updates, reason, ack),
  stlUrl: (runId: string, rev: number) => impl.stlUrl(runId, rev),
  stepUrl: (runId: string, rev: number) => impl.stepUrl(runId, rev),
  previewUrl: (runId: string, evidenceId: string) => impl.previewUrl(runId, evidenceId),
  sourceUrl: (runId: string, filename: string) => impl.sourceUrl(runId, filename),
}

export interface WakeProgress {
  attempt: number
  elapsedSeconds: number
}

/**
 * Poll the backend until it answers.
 *
 * A sleeping free instance returns errors or hangs until the container is up,
 * so this retries with a ceiling rather than failing on the first refusal.
 * Resolves with the health payload, or rejects once the budget is spent.
 */
export async function wakeBackend(
  onProgress?: (p: WakeProgress) => void,
  budgetMs = 100_000,
): Promise<Health> {
  const started = Date.now()
  let attempt = 0

  for (;;) {
    attempt += 1
    onProgress?.({
      attempt,
      elapsedSeconds: Math.round((Date.now() - started) / 1000),
    })
    try {
      const controller = new AbortController()
      const timer = setTimeout(() => controller.abort(), 12_000)
      const res = await fetch(`${API_BASE}/health`, { signal: controller.signal })
      clearTimeout(timer)
      if (res.ok) return (await res.json()) as Health
    } catch {
      /* asleep, starting, or unreachable -- keep trying within budget */
    }
    if (Date.now() - started > budgetMs) {
      throw new Error(
        'The backend did not respond in time. Free instances sleep after 15 ' +
        'minutes and can take a while to wake, or it may be out of its monthly ' +
        'hours.',
      )
    }
    await new Promise((r) => setTimeout(r, 3000))
  }
}
