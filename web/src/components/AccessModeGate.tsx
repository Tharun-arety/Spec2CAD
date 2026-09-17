import { useEffect, useState, type FormEvent } from 'react'
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
import { KineticCadProof, PROOF_FRAMES } from './KineticCadProof'

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
  const [heroFrame, setHeroFrame] = useState(0)
  const limits = health?.public_limits
  const ownReady = isOwnConnectionReady(settings)

  useEffect(() => {
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
    let interval = 0
    const stop = () => { window.clearInterval(interval); interval = 0 }
    const start = () => {
      stop()
      if (reducedMotion.matches || document.hidden) return
      interval = window.setInterval(
        () => setHeroFrame((current) => (current + 1) % PROOF_FRAMES.length), 4200,
      )
    }
    const handleMotion = () => {
      if (reducedMotion.matches) setHeroFrame(0)
      start()
    }

    document.addEventListener('visibilitychange', start)
    reducedMotion.addEventListener('change', handleMotion)
    start()
    return () => {
      stop()
      document.removeEventListener('visibilitychange', start)
      reducedMotion.removeEventListener('change', handleMotion)
    }
  }, [])

  const configureOwnApi = () => {
    onSettingsChange({ ...settings, mode: 'own' })
    setConfiguring(true)
  }

  const submitOwnApi = (event: FormEvent) => {
    event.preventDefault()
    if (ownReady) onOwnApi()
  }

  return (
    <main className="access-gate relative isolate h-full overflow-y-auto bg-c1 text-c9">
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
            <div className="text-[10.5px] text-c6">Multimodal evidence to measured CAD</div>
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

        <div className="access-gate-content grid flex-1">
          <section aria-labelledby="access-title" className="access-hero-copy">
              <h1 id="access-title"
                  aria-label="Build CAD from text, sketches, datasheets, or mixed sources"
                  className="access-hero-title font-semibold">
                <span>Build <span className="text-accent">CAD</span> from</span>
                <span key={PROOF_FRAMES[heroFrame].term}
                      className="access-hero-term text-observed" aria-hidden>
                  {PROOF_FRAMES[heroFrame].term}
                </span>
              </h1>
              <p className="access-hero-grounding">
                Grounded in <span className="text-observed">evidence</span>. Driven by
                {' '}<span className="text-accent">editable intent</span>. Verified by
                {' '}<span className="text-observed">measurement</span>.
              </p>
          </section>

          <KineticCadProof />

          <section aria-label="Access choices" className="access-choices border border-c4 bg-c1/95">
            <header className="border-b border-c3 px-[17px] py-[13px]">
              <h2 className="text-[14px] font-semibold">Try Spec2CAD</h2>
            </header>

            <div className="access-choice-grid grid">
            <article className="grid content-start gap-[17px] border-c3 p-[17px]
                                sm:grid-cols-[1fr_auto] sm:items-start">
              <div className="flex gap-[11px]">
                <span className="grid h-[31px] w-[31px] shrink-0 place-items-center border
                                 border-c4 bg-c0 text-c7">
                  <Gauge size={15} strokeWidth={1.7} aria-hidden />
                </span>
                <div>
                  <h3 className="text-[14px] font-semibold">Use the hosted demo</h3>
                  <p className="mt-[4px] max-w-[42ch] text-[11.5px] leading-[1.5] text-c7">
                    No key required. Limited shared allowance.
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
                Start with demo
              </Button>
            </article>

            <article className="border-c3 p-[17px]">
              <div className="grid gap-[13px] sm:grid-cols-[1fr_auto] sm:items-center">
                <div className="flex gap-[11px]">
                  <span className="grid h-[31px] w-[31px] shrink-0 place-items-center border
                                   border-accent-line bg-accent-wash text-accent">
                    <KeyRound size={15} strokeWidth={1.7} aria-hidden />
                  </span>
                  <div>
                    <h3 className="text-[14px] font-semibold">Use your own model API</h3>
                    <p className="mt-[4px] max-w-[42ch] text-[11.5px] leading-[1.5] text-c7">
                      Extended testing through your supported provider.
                    </p>
                    <p className="mt-[7px] flex items-center gap-[5px] text-[10.5px] text-c6">
                      <LockKeyhole size={11} strokeWidth={1.8} aria-hidden />
                      Not saved · sent only with your requests · provider charges and safeguards apply
                    </p>
                  </div>
                </div>
                {!configuring ? (
                  <Button intent="solid" size="md" onClick={configureOwnApi}
                          className="min-h-[44px] w-full sm:w-auto">
                    Connect my API
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
            </div>
          </section>
        </div>

        <footer className="access-gate-footer flex flex-wrap items-center
                           justify-between gap-[8px] border-t border-c3/70 pt-[11px]
                           text-[10.5px] text-c6">
          <span>Incomplete requirements stop with an explanation.</span>
          <span>No credential is required for demo access.</span>
        </footer>
      </div>
    </main>
  )
}
