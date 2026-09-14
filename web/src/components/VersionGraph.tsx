/**
 * Revision history drawn as a commit graph.
 *
 * DesignIntent revisions are already a linear, immutable, attributed history --
 * each one records its parent, the proposal that caused it, what changed and who
 * approved it. That is a commit log in everything but name, so it is drawn as
 * one: newest at the top, nodes on a spine, the change as the message.
 *
 * The node marker carries the release decision, which is the thing you most
 * want to see when scanning history: a filled node was released, a hollow one
 * was refused.
 */
import { GitCommitVertical } from 'lucide-react'
import { cn } from '../lib/cn'
import type { Revision } from '../types'
import { Num, PanelHead, Tip } from './ui'

export function VersionGraph({
  revisions, current, onSelect,
}: {
  revisions: Revision[]
  current: number
  onSelect: (n: number) => void
}) {
  // newest first, the way a commit log reads
  const ordered = [...revisions].sort((a, b) => b.revision - a.revision)

  return (
    <>
      <PanelHead
        title="Revisions"
        note={`${revisions.length}`}
        aside={<GitCommitVertical size={14} strokeWidth={1.7} className="text-c6" aria-hidden />}
      />

      <ol className="px-[13px] py-[13px]">
        {ordered.map((r, i) => {
          const on = r.revision === current
          const released = r.release.step_export_allowed
          const change = r.changes[0]

          return (
            <li key={r.revision} className="relative">
              {/* Connector to the next commit. Drawn per item and anchored to
                  this item's own box, so it stays aligned whatever height the
                  message below it takes. */}
              {i < ordered.length - 1 && (
                <span aria-hidden
                      className="absolute bottom-0 left-[10px] top-[16px] w-px bg-c4" />
              )}
              <button
                onClick={() => onSelect(r.revision)}
                aria-current={on ? 'true' : undefined}
                className={cn(
                  'group flex w-full cursor-pointer items-start gap-[10px] rounded-[5px]',
                  'px-[5px] py-[8px] text-left transition-colors duration-150',
                  on ? 'bg-accent-wash' : 'hover:bg-c2',
                )}
              >
                {/* node: filled = released, hollow = refused */}
                <Tip label={released ? 'Released for manufacture' : 'Refused by the release gate'}>
                  <span
                    aria-hidden
                    className={cn(
                      'mt-[2px] grid h-[11px] w-[11px] shrink-0 place-items-center rounded-full',
                      'border-[1.5px] bg-c0 transition-colors duration-150',
                      released ? 'border-success' : 'border-danger',
                      on && 'ring-2 ring-accent/35',
                    )}
                  >
                    {released && (
                      <span className="h-[5px] w-[5px] rounded-full bg-success" />
                    )}
                  </span>
                </Tip>

                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline gap-[8px]">
                    <span className={cn('num text-[12px]',
                                        on ? 'font-semibold text-accent' : 'text-c8')}>
                      v{r.revision}
                    </span>
                    <span className={cn('text-[10px]', released ? 'text-success' : 'text-danger')}>
                      {released ? 'released' : 'refused'}
                    </span>
                  </span>

                  {change ? (
                    <span className="mt-[3px] block text-[11px] leading-snug text-c7">
                      <span className="text-c8">{change.parameter.replace(/_/g, ' ')}</span>{' '}
                      <Num value={String(change.before)} />
                      <span className="px-[3px] text-c6">→</span>
                      <Num value={String(change.after)} strong />
                    </span>
                  ) : (
                    <span className="mt-[3px] block text-[11px] leading-snug text-c7">
                      as extracted from the sources
                    </span>
                  )}

                  <span className="mt-[2px] block text-[10px] leading-snug text-c6">
                    {r.approved_by
                      ? <>{r.applied_proposal} · approved by {r.approved_by}</>
                      : 'no approval required'}
                  </span>
                </span>
              </button>
            </li>
          )
        })}
      </ol>

      <p className="border-t border-c3 px-[13px] py-[10px] text-[10.5px] leading-relaxed text-c6">
        Revisions are immutable. A repair derives the next one and records what changed,
        which proposal caused it and who approved it — earlier revisions stay openable.
      </p>
    </>
  )
}
