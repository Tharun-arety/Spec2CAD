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
    <header className="flex h-[var(--spacing-bar)] shrink-0 items-center gap-[13px]
                       border-b border-c3 bg-c0 px-[13px]">
      <div className="flex items-center gap-[8px]">
        <div className="grid h-[26px] w-[26px] place-items-center rounded-[5px]
                        bg-c9 shadow-[var(--shadow-raised)]">
          <span className="num text-[11px] font-semibold leading-none text-c0">S2</span>
        </div>
        <span className="text-[14px] font-semibold tracking-[-0.014em]">Spec2CAD</span>
      </div>

      {rev && (
        <>
          <span className="h-[21px] w-px bg-c3" />
          <div className="flex min-w-0 items-baseline gap-[8px]">
            <span className="truncate text-[14px] font-medium tracking-[-0.008em]">
              {rev.part.name.replace(/_/g, ' ')}
            </span>
            <span className="text-[11px] text-c6">
              {rev.part.material}
              {rev.part.manufacturing_process && ` · ${rev.part.manufacturing_process}`}
            </span>
          </div>

          {/* Revision selector, the way a CAD tool lets you step back through
              document history. Earlier revisions stay openable. */}
          <div className="ml-[3px] flex items-center overflow-hidden rounded-[5px]
                          border border-c4 shadow-[var(--shadow-raised)]">
            {state?.revisions.map((r) => (
              <Tip key={r.revision} side="bottom"
                   label={r.changes[0]
                     ? `${r.changes[0].parameter} ${r.changes[0].before} → ${r.changes[0].after}, approved by ${r.approved_by}`
                     : 'As extracted from the sources'}>
                <button
                  onClick={() => onSelectRevision(r.revision)}
                  className={cn(
                    'num h-[26px] cursor-pointer border-r border-c4 px-[10px] text-[11px]',
                    'transition-colors duration-150 last:border-r-0',
                    r.revision === rev.revision
                      ? 'bg-accent font-semibold text-accent-fg'
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

      <div className="ml-auto flex items-center gap-[8px]">
        {busy && (
          <span className="num flex items-center gap-[6px] text-[11px] text-c6">
            <span aria-hidden className="h-[6px] w-[6px] animate-pulse rounded-full bg-accent" />
            working…
          </span>
        )}
        {right}
      </div>
    </header>
  )
}

/* ------------------------------------------------------------- stage rail */

export function StageRail({
  active, onSelect, flags, enabled, open,
}: {
  active: StageId
  onSelect: (s: StageId) => void
  flags: Partial<Record<StageId, number>>
  enabled: boolean
  open: boolean
}) {
  return (
    <nav className={cn(
           'flex w-[var(--spacing-rail)] shrink-0 flex-col items-stretch gap-[2px]',
           'bg-c1 py-[8px] pl-[5px]',
           // only needed when the panel is closed and the rail meets the viewport
           !open && 'border-r border-c3',
         )}
         aria-label="Pipeline stages">
      {STAGES.map(({ id, label, icon: Icon, hint }, i) => {
        const on = id === active
        const flag = flags[id]
        return (
          <Tip key={id} side="right" label={
            <><strong>{label}</strong> — {hint}
              {on && open && <><br />Click again to collapse the panel.</>}</>
          }>
            <button
              onClick={() => onSelect(id)}
              disabled={!enabled && id !== 'sources'}
              aria-current={on && open ? 'step' : undefined}
              aria-expanded={on ? open : undefined}
              className={cn(
                'relative grid h-[47px] cursor-pointer place-items-center gap-[3px]',
                'rounded-l-[8px] pl-[3px] transition-colors duration-150',
                'disabled:cursor-not-allowed disabled:opacity-30',
                on && open
                  // the active tab takes the panel's own surface so the two
                  // read as one object rather than a control and a distant pane
                  ? 'bg-c0 font-medium text-accent shadow-[inset_3px_0_0_0_var(--color-accent)]'
                  : 'text-c7 hover:bg-c2 hover:text-c9',
              )}
            >
              <Icon size={16} strokeWidth={1.7} aria-hidden />
              <span className="text-[9.5px] font-medium leading-none tracking-[-0.01em]">
                {label}
              </span>
              {!!flag && (
                <span className={cn(
                  'num absolute right-[4px] top-[4px] grid h-[14px] min-w-[14px] place-items-center',
                  'rounded-full px-[3px] text-[9px] font-semibold leading-none',
                  'bg-danger text-c0',
                )}>
                  {flag}
                </span>
              )}
              {/* flow connector between steps */}
              {i < STAGES.length - 1 && !(on && open) && (
                <span aria-hidden
                      className="absolute -bottom-[1px] left-1/2 h-px w-[21px] -translate-x-1/2 bg-c3" />
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
    <div className="flex h-[var(--spacing-timeline)] shrink-0 items-center gap-[13px]
                    border-t border-c3 bg-c1 px-[13px]">
      <span className="shrink-0 text-[11px] font-medium text-c7">History</span>
      <div className="flex min-w-0 flex-1 items-center gap-0 overflow-x-auto py-[8px]">
        {rev?.feature_sequence.length ? (
          rev.feature_sequence.map((f, i) => {
            const [id, kind] = f.replace(')', '').split(' (')
            return (
              <div key={f} className="flex shrink-0 items-center">
                {i > 0 && <span aria-hidden className="h-px w-[13px] bg-c4" />}
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
      'flex h-[var(--spacing-status)] shrink-0 items-center gap-[13px]',
      'border-t px-[13px] text-[11px]',
      blocked
        ? 'border-danger-line bg-danger-wash text-danger'
        : rev ? 'border-success-line bg-success-wash text-success'
              : 'border-c3 bg-c1 text-c7',
    )}>
      {rev ? (
        <>
          <button onClick={onGoRelease}
            className={cn('cursor-pointer font-semibold uppercase tracking-[0.07em]',
                          blocked ? 'underline underline-offset-[3px]' : '')}>
            {blocked ? '✕ Blocked' : '✓ Released'}
          </button>
          {clearance?.measured_value != null && (
            <span className="text-c7">
              edge clearance{' '}
              <span className="num font-semibold">
                {clearance.measured_value.toFixed(1)}
              </span>
              {' / '}
              <span className="num">{clearance.required_value?.toFixed(1)}</span> mm required
            </span>
          )}
          <span className="ml-auto text-c6">measured on the solid</span>
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
      <div className="pointer-events-none absolute left-[13px] top-[13px] flex flex-col gap-[5px]">
        <span className="num rounded-[5px] border border-c3 bg-c0/80 px-[8px]
                         py-[3px] text-[10.5px] text-c7 backdrop-blur-md">
          mm · v{rev.revision}
        </span>
      </div>

      <div className="absolute right-[13px] top-[13px]">
        <ReleaseStampSlot rev={rev} />
      </div>

      <div className="absolute bottom-[13px] left-[13px] flex items-center gap-[5px]">
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
      <span className="pointer-events-none absolute bottom-[13px] right-[13px] hidden num
                       rounded-[5px] border border-c3 bg-c0/80 px-[8px] py-[3px]
                       text-[10.5px] text-c6 backdrop-blur-md lg:block">
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
