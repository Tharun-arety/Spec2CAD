import { Suspense, lazy, useCallback, useEffect, useState } from 'react'
import {
  FORCED_REPLAY, REMOTE_BACKEND, REPLAY_AVAILABLE, api, setApiMode, wakeBackend,
} from './api'
import { replayApi, type ReplayManifest } from './replay'
import type { Evidence, Health, Proposal, RunState } from './types'
import {
  CommandBar, StageRail, StatusBar, Timeline, ViewportOverlay, type StageId,
} from './components/Shell'
import {
  EvidenceStage, InspectStage, IntentStage, ReleaseStage, SourcesStage,
} from './components/Stages'
import { PanelRightClose, PanelRightOpen, Plus } from 'lucide-react'
import { Button, Empty, Tip } from './components/ui'
import { VersionGraph } from './components/VersionGraph'

// three.js is ~500 kB and is not needed until a run exists.
const StlViewer = lazy(() =>
  import('./components/StlViewer').then((m) => ({ default: m.StlViewer })),
)

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [state, setState] = useState<RunState | null>(null)
  const [viewing, setViewing] = useState<number | null>(null)
  const [stage, setStage] = useState<StageId>('sources')
  const [picked, setPicked] = useState<Evidence | null>(null)
  const [scriptOpen, setScriptOpen] = useState(false)
  const [inspectorOpen, setInspectorOpen] = useState(true)
  const [historyOpen, setHistoryOpen] = useState(true)
  const [feature, setFeature] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [replay, setReplay] = useState<ReplayManifest | null>(null)
  const [mode, setMode] = useState<'live' | 'replay'>(FORCED_REPLAY ? 'replay' : 'live')
  const [waking, setWaking] = useState<number | null>(null)
  const [backendDown, setBackendDown] = useState<string | null>(null)

  useEffect(() => {
    if (REPLAY_AVAILABLE) replayApi.manifest().then(setReplay).catch(() => {})
    if (mode === 'replay') {
      api.health().then(setHealth).catch(() => {})
      return
    }
    // A free instance sleeps after 15 minutes, so the first visitor waits for a
    // container start plus the CadQuery import. Show that, do not hide it.
    if (REMOTE_BACKEND) {
      setWaking(0)
      wakeBackend((p) => setWaking(p.elapsedSeconds))
        .then((h) => { setHealth(h); setWaking(null); setBackendDown(null) })
        .catch((e) => { setWaking(null); setBackendDown(String(e.message ?? e)) })
    } else {
      api.health().then(setHealth).catch((e) => setBackendDown(String(e)))
    }
  }, [mode])

  const useReplayInstead = () => {
    setApiMode('replay')
    setMode('replay')
    setBackendDown(null)
    setError(null)
  }

  const guard = useCallback(async (fn: () => Promise<RunState>) => {
    setBusy(true)
    setError(null)
    try {
      const next = await fn()
      setState(next)
      setViewing(next.latest_revision)
      setPicked(null)
      setFeature(null)
      // Land on the stage that matters: a blocked run needs a decision, a
      // released one wants its report. Neither is the upload form.
      const latest = next.revisions[next.revisions.length - 1]
      setStage(latest.release.step_export_allowed ? 'inspect' : 'release')
      setInspectorOpen(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }, [])

  const rev = state
    ? state.revisions.find((r) => r.revision === viewing) ?? state.revisions[0]
    : null

  const flags: Partial<Record<StageId, number>> = {}
  if (rev) {
    const failing = rev.measured.filter((c) => c.status === 'fail').length
    if (failing) flags.inspect = failing
    if (!rev.release.step_export_allowed) flags.release = rev.proposals.length || 1
  }

  return (
    <div className="flex h-full flex-col bg-c2">
      <CommandBar
        state={state} rev={rev} busy={busy}
        onSelectRevision={(n) => { setViewing(n); setScriptOpen(false) }}
        right={
          <>
            {/* Which of the two backings is actually answering. Live mode used
                to show nothing at all, which made a real CAD kernel and a
                frozen recording look identical from the outside. */}
            {mode === 'replay' ? (
              <Tip side="bottom" label="A frozen recording of a real run. No kernel behind it: uploads and new revisions are refused rather than faked.">
                <span className="rounded-[5px] border border-warn-line bg-warn-wash px-[8px] py-[2px]
                                 text-[10px] font-semibold uppercase tracking-[0.08em] text-warn">
                  recorded replay
                </span>
              </Tip>
            ) : (
              <Tip side="bottom" label={
                REMOTE_BACKEND
                  ? 'CadQuery is running on the deployed backend. Every solid on screen is built and measured on request.'
                  : 'CadQuery is running locally. Every solid on screen is built and measured on request.'
              }>
                <span className="flex items-center gap-[6px] rounded-[5px] border border-success-line
                                 bg-success-wash px-[8px] py-[2px] text-[10px] font-semibold
                                 uppercase tracking-[0.08em] text-success">
                  <span aria-hidden className="h-[5px] w-[5px] rounded-full bg-current" />
                  live kernel
                </span>
              </Tip>
            )}
            {state && (
              <Tip side="bottom" label="Start a new design from fresh documents">
                <button
                  onClick={() => {
                    setState(null); setViewing(null); setPicked(null)
                    setFeature(null); setScriptOpen(false); setError(null)
                    setStage('sources')
                  }}
                  className="flex h-[29px] cursor-pointer items-center gap-[6px] rounded-[5px]
                             border border-c4 bg-c0 px-[10px] text-[11px] text-c7
                             shadow-[var(--shadow-raised)] transition-colors duration-150
                             hover:border-c6 hover:text-c9"
                >
                  <Plus size={14} strokeWidth={1.9} aria-hidden />
                  New
                </button>
              </Tip>
            )}
            {state && (
              <Tip side="bottom" label={historyOpen ? 'Hide revision history' : 'Show revision history'}>
                <button
                  onClick={() => setHistoryOpen((o) => !o)}
                  aria-label={historyOpen ? 'Hide revision history' : 'Show revision history'}
                  aria-expanded={historyOpen}
                  className="grid h-[29px] w-[29px] cursor-pointer place-items-center rounded-[5px]
                             border border-c4 bg-c0 text-c7 shadow-[var(--shadow-raised)]
                             transition-colors duration-150 hover:border-c6 hover:text-c9"
                >
                  {historyOpen
                    ? <PanelRightClose size={15} strokeWidth={1.7} aria-hidden />
                    : <PanelRightOpen size={15} strokeWidth={1.7} aria-hidden />}
                </button>
              </Tip>
            )}
          </>
        }
      />

      <div className="flex min-h-0 flex-1 overflow-x-auto">
        {/* Rail and inspector travel together on the left, the way an activity
            bar and its sidebar do. The rail sits against the panel it drives, so
            choosing a stage and reading it are one glance. */}
        <StageRail
          active={stage} flags={flags} enabled={!!state} open={inspectorOpen}
          onSelect={(s) => {
            if (s === stage) setInspectorOpen((o) => !o)
            else { setStage(s); setInspectorOpen(true) }
          }}
        />

        {inspectorOpen && (
        <aside className="pane flex w-[233px] shrink-0 flex-col border-r border-c3
                          bg-c0 xl:w-[var(--spacing-inspector)]">
          {error && (
            <div className="border-b border-danger-line bg-danger-wash px-[13px] py-[10px]">
              <div className="flex items-center gap-[6px] text-[11.5px] font-semibold text-danger">
                <span aria-hidden className="num text-[10px]">✕</span>
                Something went wrong
              </div>
              <p className="mt-[5px] text-[11px] leading-relaxed text-c8">{error}</p>
            </div>
          )}

          {/* The replay notice is gated on the live mode, not merely on the
              bundle being present -- claiming "this is a recording" while talking
              to a real backend would be a lie about what you are looking at. */}
          {stage === 'sources' && (
            <SourcesStage
              busy={busy}
              backendLabel={health?.sketch_backend_label ?? 'checking…'}
              visionAvailable={health?.vision_available ?? false}
              replay={mode === 'replay' ? replay : null}
              onDemo={() => guard(api.runDemo)}
              onUpload={(s, d, r) => guard(() => api.runUpload(s, d, r))}
            />
          )}
          {stage !== 'sources' && !(state && rev) && (
            <Empty>Compile a run to inspect it.</Empty>
          )}
          {state && rev && stage === 'evidence' && (
            <EvidenceStage state={state} picked={picked} onPick={setPicked} />
          )}
          {rev && stage === 'intent' && (
            <IntentStage
              rev={rev} busy={busy}
              onRevise={(updates, reason, ack) =>
                guard(() => api.revise(state!.run_id, updates, reason, ack))
              }
            />
          )}
          {rev && stage === 'inspect' && <InspectStage rev={rev} />}
          {rev && stage === 'release' && (
            <ReleaseStage
              rev={rev} busy={busy}
              onRepair={(p: Proposal) =>
                guard(() => api.repair(state!.run_id, p.id, !p.auto_applicable))
              }
            />
          )}
        </aside>
        )}
        {/* viewport column */}
        <main className="flex min-w-[380px] flex-1 flex-col">
          <div className="viewport-ground grid-dots relative min-h-0 flex-1">
            {rev?.build_error ? (
              <Empty>{rev.build_error}</Empty>
            ) : state && rev ? (
              <>
                <Suspense fallback={
                  <div className="grid h-full place-items-center text-[11.5px] text-c6">
                    Loading viewer…
                  </div>
                }>
                  <StlViewer url={api.stlUrl(state.run_id, rev.revision)} />
                </Suspense>
                <ViewportOverlay
                  rev={rev}
                  scriptOpen={scriptOpen}
                  onToggleScript={() => setScriptOpen((s) => !s)}
                  onDownloadStep={rev.release.step_export_allowed
                    ? api.stepUrl(state.run_id, rev.revision) : null}
                />
              </>
            ) : (
              <div className="grid h-full place-items-center">
                <div className="max-w-[380px] px-[21px] text-center">
                  {waking !== null ? (
                    <>
                      <p className="text-[14px] leading-relaxed text-c7">
                        Waking the backend…
                      </p>
                      <p className="mt-[8px] text-[11.5px] leading-relaxed text-c6">
                        It runs on a free instance that sleeps after 15 minutes
                        idle. A cold start takes 30–50 s, plus a couple of seconds
                        for the CAD kernel to load.
                      </p>
                      <p className="num mt-[13px] text-[12px] text-c7">{waking}s</p>
                      <div aria-hidden
                           className="mx-auto mt-[8px] h-[2px] w-[144px] overflow-hidden rounded-full bg-c3">
                        <div className="h-full animate-pulse rounded-full bg-accent"
                             style={{ width: `${Math.min(100, (waking / 60) * 100)}%` }} />
                      </div>
                    </>
                  ) : backendDown ? (
                    <>
                      <p className="text-[14px] leading-relaxed text-c8">
                        The backend is not responding.
                      </p>
                      <p className="mt-[8px] text-[11.5px] leading-relaxed text-c6">
                        {backendDown}
                      </p>
                      <div className="mt-[21px] flex flex-wrap justify-center gap-[8px]">
                        <Button intent="outline" size="md"
                                onClick={() => { setBackendDown(null); setMode('live') }}>
                          Try again
                        </Button>
                        {REPLAY_AVAILABLE && (
                          <Button intent="solid" size="md" onClick={useReplayInstead}>
                            View the recorded run
                          </Button>
                        )}
                      </div>
                      {REPLAY_AVAILABLE && (
                        <p className="mt-[13px] text-[11px] leading-relaxed text-c6">
                          The recording is genuine pipeline output, but it is a
                          recording — no uploads, and only the resolution that was
                          recorded can be applied.
                        </p>
                      )}
                    </>
                  ) : (
                    <>
                      <p className="text-[14px] leading-relaxed text-c7">
                        {busy
                          ? 'Extracting, fusing, compiling, building and measuring…'
                          : 'Compile the example to watch a design get refused, repaired and released.'}
                      </p>
                      {!busy && (
                        <Button intent="solid" size="md" className="mt-[21px]"
                                onClick={() => guard(api.runDemo)}>
                          Compile the example
                        </Button>
                      )}
                    </>
                  )}
                </div>
              </div>
            )}

            {scriptOpen && rev && (
              <div className="absolute inset-x-0 bottom-0 max-h-[55%] overflow-auto
                              border-t border-c3 bg-c0/95 backdrop-blur-md">
                <div className="sticky top-0 flex items-center gap-[8px] border-b border-c3
                                bg-c0 px-[13px] py-[8px]">
                  <span className="text-[11.5px] font-semibold">Generated CadQuery</span>
                  <span className="text-[11px] text-c6">
                    emitted for review — nothing executes it
                  </span>
                  <Button intent="ghost" size="sm" className="ml-auto"
                          onClick={() => setScriptOpen(false)}>Close</Button>
                </div>
                <pre className="num p-[13px] text-[11px] leading-relaxed text-c8">{rev.script}</pre>
              </div>
            )}
          </div>

          <Timeline rev={rev} selected={feature} onSelect={setFeature} />
        </main>

        {/* Revision history on the right. DesignIntent revisions are already an
            immutable attributed chain, so they are drawn as a commit graph. */}
        {state && rev && historyOpen && (
          <aside className="pane w-[233px] shrink-0 border-l border-c3 bg-c0">
            <VersionGraph
              revisions={state.revisions}
              current={rev.revision}
              onSelect={(n) => { setViewing(n); setScriptOpen(false) }}
            />
          </aside>
        )}

      </div>

      <StatusBar
        rev={rev}
        backendLabel={health?.sketch_backend_label ?? ''}
        onGoRelease={() => setStage('release')}
      />
    </div>
  )
}
