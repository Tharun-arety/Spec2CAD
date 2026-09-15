/**
 * The application frame: command bar, stage rail, feature timeline, status bar.
 *
 * The shape is taken from parametric CAD tools rather than from a web page. The
 * viewport is permanent and central, history runs along the bottom as a
 * timeline, and the right-hand inspector changes with the selected stage. The
 * frame itself never scrolls.
 */
import {
  Box, CheckSquare, CircleSlash, FileStack, GitCommitVertical, Ruler, ShieldCheck,
} from 'lucide-react'
import type { ReactNode } from 'react'

export const REPO_URL = 'https://github.com/Tharun-arety/Spec2CAD'

/** lucide removed its brand icons, so the GitHub mark is inlined. */
function GithubMark({ size = 15 }: { size?: number }) {
  return (
    <svg viewBox="0 0 16 16" width={size} height={size} fill="currentColor" aria-hidden>
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38
        0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01
        1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95
        0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.42 7.42 0 0 1 2-.27c.68 0
        1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87
        3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16
        8c0-4.42-3.58-8-8-8Z" />
    </svg>
  )
}
import { cn } from '../lib/cn'
import { formatValue } from '../lib/formatValue'
import type { Revision, RunState } from '../types'
import { Button, Mark, Num, Tip } from './ui'

export type StageId = 'sources' | 'evidence' | 'intent' | 'cad' | 'validate' | 'revisions'

export const STAGES: {
  id: StageId; label: string; icon: typeof Box; hint: string
}[] = [
  { id: 'sources', label: 'Sources', icon: FileStack, hint: 'The three input documents' },
  { id: 'evidence', label: 'Evidence', icon: Ruler, hint: 'Every fact, and where it was read' },
  { id: 'intent', label: 'Intent', icon: Box, hint: 'Consolidated parameters and constraints' },
  { id: 'cad', label: 'CAD', icon: CheckSquare, hint: 'The features built, and what each one did' },
  { id: 'validate', label: 'Validate', icon: ShieldCheck, hint: 'Measured on the solid, and the gate' },
  { id: 'revisions', label: 'Revisions', icon: GitCommitVertical, hint: 'Immutable versions and approvals' },
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
    <header className="chrome-grain flex h-[var(--spacing-bar)] shrink-0 items-center gap-[8px]
                       overflow-hidden border-b border-c3 bg-c0 px-[8px] sm:px-[13px]">
      <div className="flex shrink-0 items-center gap-[8px]">
        <div className="brand-mark grid h-[27px] w-[27px] place-items-center rounded-[6px]
                        border border-c4 bg-c2 shadow-[var(--shadow-raised)]">
          <span className="display-type text-[11px] font-semibold leading-none text-accent">S2</span>
        </div>
        <span className="display-type text-[14px] font-semibold tracking-[-0.025em]">Spec2CAD</span>
      </div>

      {rev && (
        <>
          <span className="hidden h-[21px] w-px bg-c3 md:block" />
          <div className="hidden min-w-0 items-baseline gap-[8px] md:flex">
            <span className="max-w-[210px] truncate text-[14px] font-medium tracking-[-0.008em]">
              {rev.part.name.replace(/_/g, ' ')}
            </span>
            <span className="hidden whitespace-nowrap text-[12px] text-c6 2xl:inline">
              {rev.part.material}
              {rev.part.manufacturing_process && ` · ${rev.part.manufacturing_process}`}
            </span>
          </div>

          {/* Which revision you are looking at. Switching between them is the
              revision graph's job, so this stays a read-only indicator rather
              than a second control doing the same work. */}
          <Tip side="bottom" label={
            rev.changes[0]
              ? `${rev.changes[0].parameter} ${rev.changes[0].before} → ${rev.changes[0].after}, approved by ${rev.approved_by}`
              : 'As extracted from the sources'
          }>
            <span className="num shrink-0 rounded-[5px] border border-accent-line
                             bg-accent-wash px-[8px] py-[2px] text-[12px] font-semibold
                             text-accent">
              v{rev.revision}
            </span>
          </Tip>
        </>
      )}

      <div className="ml-auto flex min-w-0 items-center gap-[5px]">
        <Tip side="bottom" label="Source on GitHub">
          <a href={REPO_URL} target="_blank" rel="noreferrer noopener"
             aria-label="Source on GitHub"
             className="flex h-[29px] w-[29px] shrink-0 items-center justify-center gap-[6px]
                        rounded-[5px] border border-c4 bg-c0 text-[12px] text-c7
                        shadow-[var(--shadow-raised)] xl:w-auto xl:px-[10px]
                        transition-colors duration-150 hover:border-c6 hover:text-c9">
            <GithubMark />
            <span className="hidden xl:inline">GitHub</span>
          </a>
        </Tip>
        {busy && (
          <span className="num flex items-center gap-[6px] text-[12px] text-c6">
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
  active, onSelect, flags, counts, enabled, open,
}: {
  active: StageId
  onSelect: (s: StageId) => void
  flags: Partial<Record<StageId, number>>
  counts?: Partial<Record<StageId, number>>
  enabled: boolean
  open: boolean
}) {
  return (
    <nav className={cn(
           'flex w-[var(--spacing-rail)] shrink-0 flex-col items-stretch gap-[2px]',
           'chrome-grain bg-c1 py-[8px] pl-[5px]',
           // only needed when the panel is closed and the rail meets the viewport
           !open && 'border-r border-c3',
         )}
         aria-label="Pipeline stages">
      {STAGES.map(({ id, label, icon: Icon, hint }, i) => {
        const on = id === active
        const flag = flags[id]
        const count = counts?.[id]
        const docked = id === 'revisions'
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
                docked && 'mt-auto border-t border-c3 pt-[3px]',
                'disabled:cursor-not-allowed disabled:opacity-30',
                on && open
                  // the active tab takes the panel's own surface so the two
                  // read as one object rather than a control and a distant pane
                  ? 'bg-c0 font-medium text-accent shadow-[inset_3px_0_0_0_var(--color-accent)]'
                  : 'text-c7 hover:bg-c2 hover:text-c9',
              )}
            >
              <Icon size={16} strokeWidth={1.7} aria-hidden />
              <span className="text-[10.5px] font-medium leading-none tracking-[-0.01em]">
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
              {!flag && count != null && count > 0 && (
                <span className="num absolute right-[4px] top-[4px] grid h-[14px] min-w-[14px]
                                 place-items-center rounded-full bg-accent px-[3px]
                                 text-[9px] font-semibold leading-none text-accent-fg">
                  {count}
                </span>
              )}
              {/* flow connector between steps */}
              {i < STAGES.length - 2 && !(on && open) && (
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

export function Timeline({
  rev, selected, onSelect,
}: {
  rev: Revision | null
  selected: string | null
  onSelect: (id: string | null) => void
}) {
  const op = rev?.operations.find((o) => o.id === selected) ?? null

  return (
    <div className="shrink-0 border-t border-c3 bg-c1">
      {/* Detail for the selected feature. These nodes looked clickable and did
          nothing before; each now opens what the operation actually is -- its
          resolved values, and the parameter each one came from. */}
      {op && (
        <div className="flex items-start gap-[13px] border-b border-c3 bg-c0 px-[13px] py-[10px]">
          <span className="text-[12.5px] font-semibold">
            {op.id.replace(/_/g, ' ')}
          </span>
          <span className="num rounded-[5px] border border-c3 bg-c1 px-[6px] py-px text-[11px] text-c7">
            {op.type.replace(/_/g, ' ')}
          </span>
          <div className="flex flex-wrap items-center gap-x-[13px] gap-y-[5px]">
            {op.fields.map((f) => (
              <span key={f.name} className="flex items-baseline gap-[5px] text-[12px]">
                <span className="text-c7">{f.name.replace(/_/g, ' ')}</span>
                <Num value={formatValue(f.value)} strong />
                {f.parameter && (
                  <Tip label={`from the ${f.parameter.replace(/_/g, ' ')} parameter`}>
                    <span className="num text-[9.5px] text-c6">
                      ← {f.parameter.replace(/_/g, ' ')}
                    </span>
                  </Tip>
                )}
              </span>
            ))}
          </div>
          <button onClick={() => onSelect(null)}
                  className="ml-auto shrink-0 cursor-pointer text-[12px] text-c6 hover:text-c9">
            Close
          </button>
        </div>
      )}

      <div className="flex h-[var(--spacing-timeline)] items-center gap-[13px] px-[13px]">
        <span className="shrink-0 text-[12px] font-medium text-c7">History</span>
        <div className="flex min-w-0 flex-1 items-center gap-0 overflow-x-auto py-[8px]">
          {rev?.operations.length ? (
            rev.operations.map((o, i) => {
              const on = o.id === selected
              return (
                <div key={o.id} className="flex shrink-0 items-center">
                  {i > 0 && <span aria-hidden className="h-px w-[13px] bg-c4" />}
                  <button
                    onClick={() => onSelect(on ? null : o.id)}
                    aria-pressed={on}
                    className={cn('feature cursor-pointer transition-colors duration-150',
                                  on
                                    ? 'border-accent bg-accent-wash text-accent'
                                    : 'hover:border-c5')}
                  >
                    <span className={cn('num text-[11px]', on ? 'text-accent' : 'text-c6')}>
                      {i + 1}
                    </span>
                    <span>{o.id.replace(/_/g, ' ')}</span>
                  </button>
                </div>
              )
            })
          ) : (
            <span className="text-[12px] text-c6">No features built yet</span>
          )}
        </div>
      </div>
    </div>
  )
}


/* ------------------------------------------------------------- status bar */

export function StatusBar({
  rev, backendLabel, onGoRelease, awaitingDetails = false,
}: {
  rev: Revision | null
  backendLabel: string
  onGoRelease: () => void
  awaitingDetails?: boolean
}) {
  const blocked = rev ? !rev.release.step_export_allowed : false
  const clearance = rev?.measured.find((c) => c.id === 'req_edge_clearance')

  return (
    <footer className={cn(
      'flex h-[var(--spacing-status)] shrink-0 items-center gap-[13px]',
      'chrome-grain border-t px-[13px] text-[12px]',
      awaitingDetails
        ? 'border-warn-line bg-warn-wash text-warn'
        : blocked
        ? 'border-danger-line bg-danger-wash text-danger'
        : rev ? 'border-success-line bg-success-wash text-success'
              : 'border-c3 bg-c1 text-c7',
    )}>
      {rev ? (
        <>
          <button onClick={onGoRelease}
            className={cn('cursor-pointer font-semibold uppercase tracking-[0.07em]',
                          blocked ? 'underline underline-offset-[3px]' : '')}>
            {awaitingDetails ? '… Waiting for details' : blocked ? '✕ Blocked' : '✓ Released'}
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
          <span className="ml-auto hidden text-c6 md:inline">measured on the solid</span>
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
  rev, onDownloadStep, onToggleScript, scriptOpen, interactive = true,
}: {
  rev: Revision
  onDownloadStep: string | null
  onToggleScript: () => void
  scriptOpen: boolean
  /** False when the schematic fallback is showing: it does not orbit. */
  interactive?: boolean
}) {
  return (
    <>
      {/* corner readout, as a CAD viewport shows units and orientation */}
      <div className="pointer-events-none absolute left-[13px] top-[13px] flex flex-col gap-[5px]">
        <span className="num flex items-center gap-[6px] rounded-[5px] border border-c3
                         bg-c0/80 px-[8px] py-[3px] text-[11.5px] text-c7 backdrop-blur-md">
          mm · v{rev.revision}
          <span aria-hidden className="h-[9px] w-px bg-c4" />
          <Mark state={rev.release.step_export_allowed ? 'pass' : 'fail'} glyph>
            {rev.release.step_export_allowed ? 'released' : 'refused'}
          </Mark>
        </span>
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
      {interactive && (
        <span className="pointer-events-none absolute bottom-[13px] right-[13px] hidden num
                         rounded-[5px] border border-c3 bg-c0/80 px-[8px] py-[3px]
                         text-[11.5px] text-c6 backdrop-blur-md lg:block">
          drag to orbit · scroll to zoom
        </span>
      )}
    </>
  )
}

export { Mark, Num }
