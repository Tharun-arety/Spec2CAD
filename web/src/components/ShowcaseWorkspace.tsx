import { AlertTriangle, Bot, Play, RotateCw } from 'lucide-react'
import type { ReplayCatalog } from '../replay'
import type { RunState } from '../types'
import type { CapabilityRegistry } from '../types'
import { cn } from '../lib/cn'
import { Button, Mark } from './ui'
import { CapabilityTags } from './CapabilityTags'

export function ShowcaseWorkspace({
  busy, catalog, catalogError, state, activeScenarioId, capabilityRegistry,
  onDemo, onRetryCatalog,
}: {
  busy: boolean
  catalog: ReplayCatalog | null
  catalogError: string | null
  state: RunState | null
  activeScenarioId: string | null
  capabilityRegistry: CapabilityRegistry | null
  onDemo: (scenarioId: string) => void
  onRetryCatalog: () => void
}) {
  return (
    <section className="flex h-full min-h-0 flex-col bg-c0" aria-label="Recorded examples">
      <div className="flex h-[37px] shrink-0 items-center gap-[7px] border-b border-c3 bg-c1 px-[13px]">
        <Bot size={13} strokeWidth={1.7} className="text-c6" aria-hidden />
        <span className="text-[12.5px] text-c9">Example library</span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto bg-c1 px-[21px] py-[34px]">
        <div className="mx-auto max-w-[860px]">
          <div className="max-w-[650px]">
            <h1 className="text-[25px] font-semibold leading-[1.12] tracking-[-0.03em] text-c9">
              Five engineering workflows
            </h1>
            <p className="mt-[8px] text-[14px] leading-[1.7] text-c7">
              Each recording starts from a different evidence condition. Open one here,
              then follow its decisions and approvals in the agent panel.
            </p>
          </div>

          {catalog ? (
            <div className="mt-[21px] grid gap-[9px] md:grid-cols-2">
              {catalog.scenarios.map((scenario, index) => {
                const active = activeScenarioId === scenario.id
                  && state?.run_id === `recorded-${scenario.id}`
                const featured = index === 0
                return (
                  <article key={scenario.id} className={cn(
                    'flex min-h-[154px] flex-col rounded-[8px] border bg-c0 px-[14px] py-[13px]',
                    'shadow-[var(--shadow-raised)] transition-colors duration-150',
                    featured && 'md:col-span-2 md:min-h-[138px]',
                    active ? 'border-accent bg-accent-wash' : 'border-c3 hover:border-c5',
                  )}>
                    <div className="flex items-start justify-between gap-[13px]">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-[5px]">
                          <span className={cn('num mr-[3px] text-[11px] font-semibold',
                            active ? 'text-accent' : 'text-c6')}>{scenario.step}</span>
                          {scenario.inputs.map((input) => (
                            <span key={input} className="rounded-[3px] border border-c4 bg-c1
                                                         px-[5px] py-[1px] text-[10px] text-c7">
                              {input === 'document' ? 'technical document' : input}
                            </span>
                          ))}
                        </div>
                        <h2 className="mt-[3px] text-[15px] font-semibold text-c9">{scenario.title}</h2>
                        <p className="mt-[2px] text-[11px] font-medium text-accent">{scenario.proof}</p>
                      </div>
                      {active && <Mark state="pass" glyph>Loaded</Mark>}
                    </div>

                    <p className={cn('mt-[7px] text-[12px] leading-[1.55] text-c7',
                                     featured && 'md:max-w-[660px]')}>
                      {scenario.description}
                    </p>
                    <p className="mt-[7px] border-l-2 border-warn-line pl-[8px]
                                  text-[10.5px] leading-relaxed text-c6">
                      {scenario.uncertainty}
                    </p>

                    <div className="mt-auto flex flex-wrap items-end gap-x-[9px] gap-y-[8px] pt-[11px]">
                      <div className="min-w-[220px] flex-1">
                        <CapabilityTags ids={scenario.capability_ids} registry={capabilityRegistry} />
                        <p className="num mt-[6px] text-[10px] text-c6">{scenario.operation}</p>
                      </div>
                      <Button intent={active ? 'outline' : featured ? 'solid' : 'outline'}
                              size="sm" onClick={() => onDemo(scenario.id)} disabled={busy}>
                        <Play size={12} fill="currentColor" aria-hidden />
                        {busy && active ? 'Loading…' : active ? 'Replay again' : 'Open run'}
                      </Button>
                    </div>
                  </article>
                )
              })}
            </div>
          ) : catalogError ? (
            <div role="alert" className="mt-[21px] max-w-[540px] rounded-[8px] border
                                         border-warn-line bg-warn-wash px-[14px] py-[13px]">
              <div className="flex items-start gap-[9px]">
                <AlertTriangle size={15} strokeWidth={1.8} className="mt-[2px] shrink-0 text-warn"
                               aria-hidden />
                <div>
                  <p className="text-[12.5px] font-semibold text-c9">
                    Recorded workflows could not be loaded
                  </p>
                  <p className="mt-[4px] text-[11.5px] leading-relaxed text-c7">
                    The static example catalog is unavailable. Your live model connection
                    is unaffected.
                  </p>
                  <p className="num mt-[5px] break-words text-[10px] text-c6">{catalogError}</p>
                  <Button intent="outline" size="sm" className="mt-[9px]" onClick={onRetryCatalog}>
                    <RotateCw size={12} strokeWidth={1.8} aria-hidden />
                    Retry examples
                  </Button>
                </div>
              </div>
            </div>
          ) : (
            <div role="status" aria-live="polite" className="mt-[21px] text-[12.5px] text-c6">
              Loading recorded workflows…
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
