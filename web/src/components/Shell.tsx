/**
 * The application frame: command bar, stage rail, feature timeline, status bar.
 *
 * The shape is taken from parametric CAD tools rather than from a web page. The
 * viewport is permanent and central, history runs along the bottom as a
 * timeline, and the right-hand inspector changes with the selected stage. The
 * frame itself never scrolls.
 */
import {
  Box, CheckSquare, CircleSlash, FileStack, Ruler, ShieldCheck,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '../lib/cn'
import type { Revision, RunState } from '../types'
import { Button, Mark, Num, Tip } from './ui'

export type StageId = 'sources' | 'evidence' | 'intent' | 'inspect' | 'release'

export const STAGES: {
  id: StageId; label: string; icon: typeof Box; hint: string
}[] = [
  { id: 'sources', label: 'Sources', icon: FileStack, hint: 'The three input documents' },
  { id: 'evidence', label: 'Evidence', icon: Ruler, hint: 'Every fact, and where it was read' },
  { id: 'intent', label: 'Intent', icon: Box, hint: 'Consolidated parameters and constraints' },
  { id: 'inspect', label: 'Inspect', icon: CheckSquare, hint: 'Measured on the finished solid' },
  { id: 'release', label: 'Release', icon: ShieldCheck, hint: 'The gate, and how to clear it' },
]

/* ------------------------------------------------------------ command bar */

export function CommandBar({
  state, rev, onSelectRevision, busy, right,
}: {
  state: RunState | null
  rev: Revision | null
  onSelectRevision: (n: number) => void
  busy: boolean
  right?: ReactNode
}) {
  return (
    <header className="flex h-[var(--spacing-bar)] shrink-0 items-center gap-3
                       border-b border-c4 bg-c0 pl-3 pr-3">
      <div className="flex items-center gap-2">
        <div className="grid h-[22px] w-[22px] place-items-center border border-c9 bg-c9">
          <span className="num text-[11px] font-bold leading-none text-c0">S2</span>
        </div>
        <span className="text-[13px] font-semibold tracking-tight">Spec2CAD</span>
      </div>

      {rev && (
        <>
          <span className="h-4 w-px bg-c4" />
          <div className="flex min-w-0 items-baseline gap-2">
            <span className="truncate text-[12.5px]">
              {rev.part.name.replace(/_/g, ' ')}
            </span>
            <span className="text-[11.5px] text-c6">
              {rev.part.material}
              {rev.part.manufacturing_process && ` · ${rev.part.manufacturing_process}`}
            </span>
          </div>

          {/* Revision selector, the way a CAD tool lets you step back through
              document history. Earlier revisions stay openable. */}
          <div className="ml-1 flex items-center border border-c4">
            {state?.revisions.map((r) => (
              <Tip key={r.revision} side="bottom"
                   label={r.changes[0]
                     ? `${r.changes[0].parameter} ${r.changes[0].before} → ${r.changes[0].after}, approved by ${r.approved_by}`
                     : 'As extracted from the sources'}>
                <button
                  onClick={() => onSelectRevision(r.revision)}
                  className={cn(
                    'num h-[24px] cursor-pointer border-r border-c4 px-2 text-[11.5px] last:border-r-0',
                    r.revision === rev.revision
                      ? 'bg-c9 font-semibold text-c0'
                      : 'bg-c0 text-c7 hover:bg-c2',
                  )}
                >
                  v{r.revision}
                </button>
              </Tip>
            ))}
          </div>
        </>
      )}

      <div className="ml-auto flex items-center gap-2">
        {busy && (
          <span className="num text-[11px] text-c6">working…</span>
        )}
        {right}
      </div>
    </header>
  )
}

/* ------------------------------------------------------------- stage rail */

export function StageRail({
  active, onSelect, flags, enabled,
}: {
  active: StageId
  onSelect: (s: StageId) => void
  flags: Partial<Record<StageId, number>>
  enabled: boolean
}) {
  return (
    <nav className="flex w-[var(--spacing-rail)] shrink-0 flex-col items-center gap-0.5
                    border-r border-c4 bg-c1 py-2"
         aria-label="Pipeline stages">
      {STAGES.map(({ id, label, icon: Icon, hint }, i) => {
        const on = id === active
        const flag = flags[id]
        return (
          <Tip key={id} side="right" label={<><strong>{label}</strong> — {hint}</>}>
            <button
              onClick={() => onSelect(id)}
              disabled={!enabled && id !== 'sources'}
              aria-current={on ? 'step' : undefined}
              className={cn(
                'relative grid h-[46px] w-[42px] cursor-pointer place-items-center gap-0.5 border',
                'transition-colors duration-100 disabled:cursor-not-allowed disabled:opacity-30',
                on ? 'border-c9 bg-c9 text-c0' : 'border-transparent text-c7 hover:bg-c3',
              )}
            >
              <Icon size={15} strokeWidth={1.75} aria-hidden />
              <span className="text-[9.5px] leading-none">{label}</span>
              {!!flag && (
                <span className={cn(
                  'num absolute right-0.5 top-0.5 grid h-[13px] min-w-[13px] place-items-center',
                  'border px-0.5 text-[9px] font-semibold leading-none',
                  on ? 'border-c0 bg-c0 text-c9' : 'border-c9 bg-c9 text-c0',
                )}>
                  {flag}
                </span>
              )}
              {/* flow connector between steps */}
              {i < STAGES.length - 1 && (
                <span aria-hidden className="absolute -bottom-[3px] h-[3px] w-px bg-c4" />
              )}
            </button>
          </Tip>
        )
      })}
    </nav>
  )
}

/* --------------------------------------------------------------- timeline */

export function Timeline({ rev }: { rev: Revision | null }) {
  return (
    <div className="flex h-[46px] shrink-0 items-center gap-2 border-t border-c4 bg-c1 px-3">
      <span className="shrink-0 text-[11px] text-c7">History</span>
      <div className="flex min-w-0 flex-1 items-center gap-0 overflow-x-auto">
        {rev?.feature_sequence.length ? (
          rev.feature_sequence.map((f, i) => {
            const [id, kind] = f.replace(')', '').split(' (')
            return (
              <div key={f} className="flex shrink-0 items-center">
                {i > 0 && <span aria-hidden className="h-px w-3 bg-c4" />}
                <Tip label={`${kind} operation`}>
                  <div className="feature cursor-default">
                    <span className="num text-[10px] text-c6">{i + 1}</span>
                    <span>{id.replace(/_/g, ' ')}</span>
                  </div>
                </Tip>
              </div>
            )
          })
        ) : (
          <span className="text-[11.5px] text-c6">No features built yet</span>
        )}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------- status bar */

export function StatusBar({
  rev, backendLabel, onGoRelease,
}: {
  rev: Revision | null
  backendLabel: string
  onGoRelease: () => void
}) {
  const blocked = rev ? !rev.release.step_export_allowed : false
  const clearance = rev?.measured.find((c) => c.id === 'req_edge_clearance')

  return (
    <footer className={cn(
      'flex h-[28px] shrink-0 items-center gap-3 border-t px-3 text-[11.5px]',
      blocked ? 'border-c9 bg-c9 text-c0' : 'border-c4 bg-c1 text-c7',
    )}>
      {rev ? (
        <>
          <button onClick={onGoRelease}
            className={cn('cursor-pointer font-semibold uppercase tracking-[0.06em]',
                          blocked ? 'underline underline-offset-2' : '')}>
            {blocked ? '✕ Blocked' : '✓ Released'}
          </button>
          {clearance?.measured_value != null && (
            <span className={blocked ? 'text-c0' : 'text-c7'}>
              edge clearance{' '}
              <span className="num font-semibold">
                {clearance.measured_value.toFixed(1)}
              </span>
              {' / '}
              <span className="num">{clearance.required_value?.toFixed(1)}</span> mm required
            </span>
          )}
          <span className={cn('ml-auto', blocked ? 'text-c5' : 'text-c6')}>
            measured on the solid
          </span>
        </>
      ) : (
        <>
          <CircleSlash size={12} aria-hidden />
          <span>Nothing compiled</span>
          <span className="ml-auto text-c6">{backendLabel}</span>
        </>
      )}
    </footer>
  )
}

/* ------------------------------------------------------------- viewport UI */

export function ViewportOverlay({
  rev, onDownloadStep, onToggleScript, scriptOpen,
}: {
  rev: Revision
  onDownloadStep: string | null
  onToggleScript: () => void
  scriptOpen: boolean
}) {
  return (
    <>
      {/* corner readout, as a CAD viewport shows units and orientation */}
      <div className="pointer-events-none absolute left-3 top-3 flex flex-col gap-1">
        <span className="num bg-c0/85 px-1.5 py-0.5 text-[10.5px] text-c7">
          mm · v{rev.revision}
        </span>
      </div>

      <div className="absolute right-3 top-3">
        <ReleaseStampSlot rev={rev} />
      </div>

      <div className="absolute bottom-3 left-3 flex items-center gap-1.5">
        {onDownloadStep ? (
          <a href={onDownloadStep}>
            <Button intent="solid" size="sm">Download STEP</Button>
          </a>
        ) : (
          <Tip label={rev.release.reasons.join(' ')}>
            <span className="inline-block">
              <Button size="sm" disabled>STEP withheld</Button>
            </span>
          </Tip>
        )}
        <Button intent={scriptOpen ? 'solid' : 'outline'} size="sm" onClick={onToggleScript}>
          {scriptOpen ? 'Hide code' : 'View code'}
        </Button>
      </div>

      {/* hidden on narrow viewports, where it would sit on top of the buttons */}
      <span className="pointer-events-none absolute bottom-3 right-3 hidden num
                       bg-c0/85 px-1.5 py-0.5 text-[10.5px] text-c6 lg:block">
        drag to orbit · scroll to zoom
      </span>
    </>
  )
}

function ReleaseStampSlot({ rev }: { rev: Revision }) {
  const blocked = !rev.release.step_export_allowed
  return (
    <div className={cn('stamp', blocked ? 'stamp-blocked' : 'stamp-released')}
         role="img" aria-label={blocked ? 'Not for manufacture' : 'Released'}>
      {blocked ? <>Not for<br />manufacture</> : <>Released</>}
    </div>
  )
}

export { Mark, Num }
