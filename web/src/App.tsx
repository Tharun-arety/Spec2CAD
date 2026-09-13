import { Suspense, lazy, useCallback, useEffect, useState } from 'react'
import { api } from './api'
import type { Evidence, Health, Proposal, RunState } from './types'
import {
  CommandBar, StageRail, StatusBar, Timeline, ViewportOverlay, type StageId,
} from './components/Shell'
import {
  EvidenceStage, InspectStage, IntentStage, ReleaseStage, SourcesStage,
} from './components/Stages'
import { Button, Empty } from './components/ui'

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
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.health().then(setHealth).catch((e) => setError(String(e)))
  }, [])

  const guard = useCallback(async (fn: () => Promise<RunState>) => {
    setBusy(true)
    setError(null)
    try {
      const next = await fn()
      setState(next)
      setViewing(next.latest_revision)
      setPicked(null)
      // Land on the stage that matters: a blocked run needs a decision, a
      // released one wants its report. Neither is the upload form.
      const latest = next.revisions[next.revisions.length - 1]
      setStage(latest.release.step_export_allowed ? 'inspect' : 'release')
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
      />

      <div className="flex min-h-0 flex-1">
        <StageRail active={stage} onSelect={setStage} flags={flags} enabled={!!state} />

        {/* viewport column */}
        <main className="flex min-w-0 flex-1 flex-col">
          <div className="relative min-h-0 flex-1 grid-dots bg-c0">
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
                <div className="max-w-[340px] text-center">
                  <p className="text-[12.5px] leading-relaxed text-c7">
                    {busy
                      ? 'Extracting, fusing, compiling, building and measuring…'
                      : 'Compile the example to watch a design get refused, repaired and released.'}
                  </p>
                  {!busy && (
                    <Button intent="solid" size="md" className="mt-4"
                            onClick={() => guard(api.runDemo)}>
                      Compile the example
                    </Button>
                  )}
                </div>
              </div>
            )}

            {scriptOpen && rev && (
              <div className="absolute inset-x-0 bottom-0 max-h-[55%] overflow-auto
                              border-t border-c4 bg-c0/97 backdrop-blur-sm">
                <div className="sticky top-0 flex items-center gap-2 border-b border-c3
                                bg-c0 px-3 py-1.5">
                  <span className="text-[11.5px] font-semibold">Generated CadQuery</span>
                  <span className="text-[11px] text-c6">
                    emitted for review — nothing executes it
                  </span>
                  <Button intent="ghost" size="sm" className="ml-auto"
                          onClick={() => setScriptOpen(false)}>Close</Button>
                </div>
                <pre className="num p-3 text-[11px] leading-relaxed">{rev.script}</pre>
              </div>
            )}
          </div>

          <Timeline rev={rev} />
        </main>

        {/* inspector */}
        <aside className="pane flex w-[360px] shrink-0 flex-col border-l border-c4 bg-c0">
          {error && (
            <div className="border-b-2 border-c9 px-3.5 py-2.5">
              <div className="text-[11.5px] font-semibold">✕ Something went wrong</div>
              <p className="mt-1 text-[11px] leading-relaxed text-c7">{error}</p>
            </div>
          )}

          {stage === 'sources' && (
            <SourcesStage
              busy={busy}
              backendLabel={health?.sketch_backend_label ?? 'checking…'}
              visionAvailable={health?.vision_available ?? false}
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
          {rev && stage === 'intent' && <IntentStage rev={rev} />}
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
      </div>

      <StatusBar
        rev={rev}
        backendLabel={health?.sketch_backend_label ?? ''}
        onGoRelease={() => setStage('release')}
      />
    </div>
  )
}
