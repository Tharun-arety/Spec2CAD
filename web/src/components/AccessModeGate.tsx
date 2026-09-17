import { useState, type FormEvent } from 'react'
import { Check, Gauge, KeyRound, LockKeyhole } from 'lucide-react'
import type { Health } from '../types'
import {
  isOwnConnectionReady,
  type ModelConnectionSettings,
} from '../lib/modelConnection'
import { Button } from './ui'
import { ModelConnectionFields } from './ModelConnectionFields'
import { Spec2CADMark } from './Spec2CADMark'
import { EvidenceMesh } from './EvidenceMesh'

interface AccessModeGateProps {
  health: Health | null
  waking: number | null
  backendDown: boolean
  settings: ModelConnectionSettings
  onSettingsChange: (settings: ModelConnectionSettings) => void
  onDemo: () => void
  onOwnApi: () => void
}

export function AccessModeGate({
  health, waking, backendDown, settings, onSettingsChange, onDemo, onOwnApi,
}: AccessModeGateProps) {
  const [configuring, setConfiguring] = useState(settings.mode === 'own')
  const limits = health?.public_limits
  const ownReady = isOwnConnectionReady(settings)

  const configureOwnApi = () => {
    onSettingsChange({ ...settings, mode: 'own' })
    setConfiguring(true)
  }

  const submitOwnApi = (event: FormEvent) => {
    event.preventDefault()
    if (ownReady) onOwnApi()
  }

  return (
    <main className="access-gate relative isolate min-h-full overflow-y-auto bg-c1 text-c9">
      <div className="pointer-events-none fixed inset-0 -z-10 overflow-hidden bg-c1">
        <EvidenceMesh />
      </div>

      <div className="access-gate-shell mx-auto flex w-full max-w-[1440px] flex-col px-[21px]
                      sm:px-[34px] lg:px-[55px]">
        <header className="flex h-[72px] shrink-0 items-center gap-[10px] border-b border-c3/70">
          <span className="grid h-[31px] w-[31px] place-items-center border border-accent-line
                           bg-accent-wash">
            <Spec2CADMark size={22} />
          </span>
          <div>
            <div className="display-type text-[16px] font-semibold text-c9">Spec2CAD</div>
            <div className="text-[10.5px] text-c6">Evidence-led CAD generation</div>
          </div>
          <div className="ml-auto flex items-center gap-[6px] text-[11px] text-c6" role="status">
            <span
              aria-hidden
              className={`h-[6px] w-[6px] rounded-full ${
                health ? 'bg-success' : backendDown ? 'bg-danger' : 'bg-warn'
              }`}
            />
            {health
              ? 'Pipeline ready'
              : backendDown
                ? 'Pipeline unavailable'
                : waking !== null
                  ? `Waking pipeline · ${waking}s`
                  : 'Checking pipeline'}
          </div>
        </header>

        <div className="access-gate-content grid flex-1 content-start">
          <section aria-labelledby="access-title" className="max-w-[670px]">
            <h1 id="access-title" className="max-w-[14ch] text-balance text-[42px] font-semibold
                                             leading-[1.02] tracking-[-0.038em]
                                             sm:text-[56px] lg:text-[64px]">
              Build CAD from evidence, not guesses.
            </h1>
            <p className="mt-[21px] max-w-[58ch] text-[14px] leading-[1.7] text-c7 sm:text-[15px]">
              Model interpretation becomes editable engineering intent. Deterministic
              operations build the part. Measured evidence decides whether it can be released.
            </p>
            <div className="num mt-[26px] flex flex-wrap items-center gap-x-[9px] gap-y-[5px]
                            text-[11px] text-c6" aria-label="Spec2CAD pipeline">
              <span className="text-observed">source evidence</span>
              <span aria-hidden className="text-c5">/</span>
              <span className="text-accent">editable intent</span>
              <span aria-hidden className="text-c5">/</span>
              <span>Feature IR</span>
              <span aria-hidden className="text-c5">/</span>
              <span className="text-observed">measured CAD</span>
            </div>
          </section>

          <section aria-label="Access choices" className="self-start border border-c4 bg-c1/95">
            <header className="border-b border-c3 px-[17px] py-[13px]">
              <h2 className="text-[14px] font-semibold">Choose your access</h2>
              <p className="mt-[3px] text-[11.5px] text-c6">
                Both paths use the same governed CAD pipeline.
              </p>
            </header>

            <article className="grid gap-[13px] border-b border-c3 p-[17px] sm:grid-cols-[1fr_auto]
                                sm:items-center">
              <div className="flex gap-[11px]">
                <span className="grid h-[31px] w-[31px] shrink-0 place-items-center border
                                 border-c4 bg-c0 text-c7">
                  <Gauge size={15} strokeWidth={1.7} aria-hidden />
                </span>
                <div>
                  <h3 className="text-[14px] font-semibold">Explore with demo access</h3>
                  <p className="mt-[4px] max-w-[42ch] text-[11.5px] leading-[1.5] text-c7">
                    No setup. Use our shared model allowance for a bounded evaluation.
                  </p>
                  <p className="mt-[7px] flex items-center gap-[5px] text-[10.5px] text-c6">
                    <Check size={11} strokeWidth={2} aria-hidden />
                    {limits
                      ? `${limits.ai_units_per_client_day} AI units daily · ${limits.requests_per_minute} requests per minute`
                      : 'Limited daily AI usage · shared capacity'}
                  </p>
                </div>
              </div>
              <Button intent="outline" size="md" onClick={onDemo}
                      className="min-h-[44px] w-full sm:w-auto">
                Start demo
              </Button>
            </article>

            <article className="p-[17px]">
              <div className="grid gap-[13px] sm:grid-cols-[1fr_auto] sm:items-center">
                <div className="flex gap-[11px]">
                  <span className="grid h-[31px] w-[31px] shrink-0 place-items-center border
                                   border-accent-line bg-accent-wash text-accent">
                    <KeyRound size={15} strokeWidth={1.7} aria-hidden />
                  </span>
                  <div>
                    <h3 className="text-[14px] font-semibold">Bring your own API</h3>
                    <p className="mt-[4px] max-w-[42ch] text-[11.5px] leading-[1.5] text-c7">
                      Use your provider account for extensive testing without the shared allowance.
                    </p>
                    <p className="mt-[7px] flex items-center gap-[5px] text-[10.5px] text-c6">
                      <LockKeyhole size={11} strokeWidth={1.8} aria-hidden />
                      Key stays in this tab · provider charges and safeguards apply
                    </p>
                  </div>
                </div>
                {!configuring ? (
                  <Button intent="solid" size="md" onClick={configureOwnApi}
                          className="min-h-[44px] w-full sm:w-auto">
                    Connect API
                  </Button>
                ) : null}
              </div>

              {configuring ? (
                <form onSubmit={submitOwnApi} className="mt-[17px] border-t border-c3 pt-[15px]">
                  <div className="grid gap-[13px] sm:grid-cols-2">
                    <ModelConnectionFields
                      settings={settings}
                      onChange={onSettingsChange}
                      idPrefix="access"
                      showMode={false}
                      showStatus={false}
                      autoFocus
                      spacious
                    />
                  </div>
                  <p className="mt-[10px] max-w-[72ch] text-[10.5px] leading-[1.5] text-c6">
                    Custom endpoints must be allowlisted public HTTPS hosts and support
                    chat completions, strict JSON schema output, and image input when used.
                    Your API key is never written to browser storage or run records.
                  </p>
                  {!ownReady ? (
                    <p role="status" className="mt-[7px] text-[10.5px] font-medium text-warn">
                      Enter the key, model, and required endpoint to continue.
                    </p>
                  ) : null}
                  <div className="mt-[12px] flex flex-wrap items-center gap-[7px]">
                    <Button type="submit" intent="solid" size="md" disabled={!ownReady}
                            className="min-h-[44px]">
                      Enter with my API
                    </Button>
                    <Button type="button" intent="ghost" size="md"
                            onClick={() => setConfiguring(false)} className="min-h-[44px]">
                      Back
                    </Button>
                  </div>
                </form>
              ) : null}
            </article>
          </section>
        </div>

        <footer className="access-gate-footer absolute flex flex-wrap items-center
                           justify-between gap-[8px] border-t border-c3/70 pt-[11px]
                           text-[10.5px] text-c6">
          <span>Intent stays editable. CAD stays deterministic.</span>
          <span>No credential is required for demo access.</span>
        </footer>
      </div>
    </main>
  )
}
