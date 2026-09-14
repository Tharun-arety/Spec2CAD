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
  CadStage, EvidenceStage, IntentStage, SourcesStage, ValidateStage,
} from './components/Stages'
import { Download, Lock, PanelRightClose, PanelRightOpen, Plus } from 'lucide-react'
import { Button, Empty, Tip } from './components/ui'
import { VersionGraph } from './components/VersionGraph'
import { ErrorBoundary } from './components/ErrorBoundary'
import { PlanView } from './components/PlanView'
import { GuideBar } from './components/GuideBar'
import { PipelinePreview } from './components/PipelinePreview'
import { EvidenceWorkbench, SourceWorkspace } from './components/Workbenches'
import { hasWebGL } from './lib/webgl'

const VIEWER_FALLBACK_NOTE =
  'This browser has no WebGL context, so the 3D viewer is unavailable. ' +
  'Everything else — evidence, intent, measurement and release — is unaffected.'

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
  const [inspectorOpen, setInspectorOpen] = useState(() =>
    typeof window === 'undefined' || window.matchMedia('(min-width: 861px)').matches,
  )
  // Collapsed by default: the canvas was being squeezed between the inspector
  // and the history panel. History is opened from the revision chip when wanted.
  const [historyOpen, setHistoryOpen] = useState(false)
  const [feature, setFeature] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [replay, setReplay] = useState<ReplayManifest | null>(null)
  const [mode, setMode] = useState<'live' | 'replay'>(FORCED_REPLAY ? 'replay' : 'live')
  const [waking, setWaking] = useState<number | null>(null)
  // Probed once, before three.js is imported. Environments without a GPU
  // context (VMs, remote desktops, locked-down laptops, headless browsers) get
  // the schematic instead of a white screen.
  const [webglOk] = useState(hasWebGL)
  const [viewerFailed, setViewerFailed] = useState<string | null>(null)
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
      const latest = next.revisions.find((r) => r.revision === next.latest_revision)
      // Complete runs land on Evidence. Incomplete text requests stay in the
      // agent workspace so the missing-input follow-up is visible beside the
      // original prompt instead of sending the user into an empty CAD screen.
      setStage(latest?.build_error ? 'sources' : 'evidence')
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
    if (failing) flags.cad = failing
    if (!rev.release.step_export_allowed) flags.validate = rev.proposals.length || 1
  }

  return (
    <div className="app-shell flex h-full flex-col bg-c2">
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
                <span className="flex h-[29px] items-center gap-[6px] rounded-[5px] border border-c4
                                 bg-c1 px-[8px] text-[12px] text-c7">
                  <span aria-hidden className="h-[6px] w-[6px] rounded-full bg-warn" />
                  <span className="hidden lg:inline">Recorded replay</span>
                </span>
              </Tip>
            ) : (
              <Tip side="bottom" label={
                REMOTE_BACKEND
                  ? 'CadQuery is running on the deployed backend. Every solid on screen is built and measured on request.'
                  : 'CadQuery is running locally. Every solid on screen is built and measured on request.'
              }>
                <span className="flex h-[29px] items-center gap-[6px] rounded-[5px] border border-c4
                                 bg-c1 px-[8px] text-[12px] text-c7">
                  <span aria-hidden className="h-[6px] w-[6px] rounded-full bg-success" />
                  <span className="hidden lg:inline">Live kernel</span>
                </span>
              </Tip>
            )}
            {rev && (
              rev.release.step_export_allowed ? (
                <Tip side="bottom" label="The gate authorised this revision. Downloads the measured solid as STEP.">
                  <a href={api.stepUrl(state!.run_id, rev.revision)}
                     className="flex h-[29px] items-center gap-[6px] rounded-[5px] border
                                border-success bg-success px-[11px] text-[12px] font-medium
                                text-c0 shadow-[var(--shadow-raised)]
                                transition-opacity duration-150 hover:opacity-90">
                    <Download size={13} strokeWidth={2} aria-hidden />
                    Export STEP
                  </a>
                </Tip>
              ) : (
                <Tip side="bottom" label={rev.release.reasons.join(' ')}>
                  <button
                    onClick={() => setStage('validate')}
                  className="flex h-[29px] shrink-0 cursor-pointer items-center gap-[6px] rounded-[5px]
                             border border-danger-line bg-danger-wash px-[8px] text-[12px] sm:px-[11px]
                               font-semibold text-danger transition-colors duration-150
                               hover:border-danger">
                    <Lock size={13} strokeWidth={2} aria-hidden />
                    Export blocked
                  </button>
                </Tip>
              )
            )}
            {state && (
              <Tip side="bottom" label="Start a new design from fresh documents">
                <button
                  onClick={() => {
                    setState(null); setViewing(null); setPicked(null)
                    setFeature(null); setScriptOpen(false); setError(null)
                    setStage('sources')
                  }}
                  className="flex h-[29px] w-[29px] shrink-0 cursor-pointer items-center justify-center
                             gap-[6px] rounded-[5px] border border-c4 bg-c0 text-[12px] text-c7
                             shadow-[var(--shadow-raised)] transition-colors duration-150
                             hover:border-c6 hover:text-c9 xl:w-auto xl:px-[10px]"
                >
                  <Plus size={14} strokeWidth={1.9} aria-hidden />
                  <span className="hidden xl:inline">New</span>
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

      <div className="workbench-body relative flex min-h-0 flex-1 overflow-hidden">
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
        <aside className="context-panel chrome-grain pane flex shrink-0 flex-col border-r border-c3 bg-c0">
          {error && (
            <div className="border-b border-danger-line bg-danger-wash px-[13px] py-[10px]">
              <div className="flex items-center gap-[6px] text-[12.5px] font-semibold text-danger">
                <span aria-hidden className="num text-[11px]">✕</span>
                Something went wrong
              </div>
              <p className="mt-[5px] text-[12px] leading-relaxed text-c8">{error}</p>
            </div>
          )}

          {/* The replay notice is gated on the live mode, not merely on the
              bundle being present -- claiming "this is a recording" while talking
              to a real backend would be a lie about what you are looking at. */}
          {stage === 'sources' && (
            <SourcesStage
              backendLabel={health?.sketch_backend_label ?? 'checking…'}
              visionAvailable={health?.vision_available ?? false}
              replay={mode === 'replay' ? replay : null}
              evidence={state?.evidence}
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
          {rev && stage === 'cad' && (
            <CadStage
              rev={rev} selected={feature} onSelect={setFeature}
              scriptOpen={scriptOpen} onToggleScript={() => setScriptOpen((o) => !o)}
            />
          )}
          {rev && stage === 'validate' && (
            <ValidateStage
              rev={rev} busy={busy}
              onRepair={(p: Proposal) =>
                guard(() => api.repair(state!.run_id, p.id, !p.auto_applicable))
              }
            />
          )}

          {/* One contextual next step, so the pipeline is walked in order
              instead of discovered in the sidebar. */}
          {state && rev && stage !== 'sources' && (
            <GuideBar stage={stage} state={state} rev={rev} onGo={setStage} />
          )}
        </aside>
        )}
        {/* viewport column */}
        <main className="workspace-main flex min-w-0 flex-1 flex-col">
          <div className="viewport-ground grid-dots relative min-h-0 flex-1">
            {stage === 'sources' ? (
              <SourceWorkspace
                busy={busy}
                replayMode={mode === 'replay'}
                visionAvailable={health?.vision_available ?? false}
                state={state}
                onDemo={() => guard(api.runDemo)}
                onCompile={(sketch, datasheet, instruction) =>
                  guard(() => api.runUpload(sketch, datasheet, instruction))
                }
              />
            ) : stage === 'evidence' && state ? (
              <EvidenceWorkbench state={state} picked={picked} onPick={setPicked} />
            ) : rev?.build_error ? (
              <Empty>{rev.build_error}</Empty>
            ) : state && rev ? (
              <>
                {/* The 3D viewer is the only part of this app that needs a GPU,
                    so it is the only part allowed to fail for want of one. The
                    probe runs before three.js is even imported; the boundary
                    catches anything that still gets through. */}
                {webglOk && !viewerFailed ? (
                  <ErrorBoundary
                    label="StlViewer"
                    fallback={() => <PlanView rev={rev} note={VIEWER_FALLBACK_NOTE} />}
                  >
                    <Suspense fallback={
                      <div className="grid h-full place-items-center text-[12.5px] text-c6">
                        Loading viewer…
                      </div>
                    }>
                      <StlViewer
                        url={api.stlUrl(state.run_id, rev.revision)}
                        onFailure={setViewerFailed}
                      />
                    </Suspense>
                  </ErrorBoundary>
                ) : (
                  <PlanView
                    rev={rev}
                    note={viewerFailed ?? VIEWER_FALLBACK_NOTE}
                  />
                )}
                <ViewportOverlay
                  rev={rev}
                  interactive={webglOk && !viewerFailed}
                  scriptOpen={scriptOpen}
                  onToggleScript={() => setScriptOpen((s) => !s)}
                  onDownloadStep={rev.release.step_export_allowed
                    ? api.stepUrl(state.run_id, rev.revision) : null}
                />
              </>
            ) : (
              <div className="grid h-full place-items-center overflow-auto py-[21px]">
                <div className="max-w-[460px] px-[21px] text-center">
                  {waking !== null ? (
                    <>
                      <p className="text-[14px] leading-relaxed text-c7">
                        Waking the backend…
                      </p>
                      <p className="mt-[8px] text-[12.5px] leading-relaxed text-c6">
                        It runs on a free instance that sleeps after 15 minutes
                        idle. A cold start takes 30–50 s, plus a couple of seconds
                        for the CAD kernel to load.
                      </p>
                      <p className="num mt-[13px] text-[13px] text-c7">{waking}s</p>
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
                      <p className="mt-[8px] text-[12.5px] leading-relaxed text-c6">
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
                        <p className="mt-[13px] text-[12px] leading-relaxed text-c6">
                          The recording is genuine pipeline output, but it is a
                          recording — no uploads, and only the resolution that was
                          recorded can be applied.
                        </p>
                      )}
                    </>
                  ) : (
                    // No second compile button here: the inspector already has
                    // the primary action, and duplicating it spent the largest
                    // area on screen on a repeat.
                    <PipelinePreview busy={busy} />
                  )}
                </div>
              </div>
            )}

            {scriptOpen && rev && (
              <div className="absolute inset-x-0 bottom-0 max-h-[55%] overflow-auto
                              border-t border-c3 bg-c0/95 backdrop-blur-md">
                <div className="sticky top-0 flex items-center gap-[8px] border-b border-c3
                                bg-c0 px-[13px] py-[8px]">
                  <span className="text-[12.5px] font-semibold">Generated CadQuery</span>
                  <span className="text-[12px] text-c6">
                    emitted for review — nothing executes it
                  </span>
                  <Button intent="ghost" size="sm" className="ml-auto"
                          onClick={() => setScriptOpen(false)}>Close</Button>
                </div>
                <pre className="num p-[13px] text-[12px] leading-relaxed text-c8">{rev.script}</pre>
              </div>
            )}
          </div>

          {stage !== 'sources' && stage !== 'evidence' && (
            <Timeline rev={rev} selected={feature} onSelect={setFeature} />
          )}
        </main>

        {/* Revision history on the right. DesignIntent revisions are already an
            immutable attributed chain, so they are drawn as a commit graph. */}
        {state && rev && historyOpen && (
          <aside className="history-panel chrome-grain pane w-[280px] shrink-0 border-l border-c3 bg-c0">
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
        onGoRelease={() => setStage('validate')}
      />
    </div>
  )
}
