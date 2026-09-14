import { ArrowRight } from 'lucide-react'
import type { Revision, RunState } from '../types'
import type { StageId } from './Shell'

/**
 * The one contextual "Continue" that walks the pipeline in order.
 *
 * Compiling used to land straight on the verdict, which showed the conclusion
 * and skipped the transformation the project is actually about: heterogeneous
 * documents becoming parameters, parameters becoming geometry, geometry
 * becoming a measurement. Each step states what it found, so advancing is a
 * narrative rather than a dare to go hunting in the sidebar.
 */

const NEXT: Partial<Record<StageId, StageId>> = {
  evidence: 'intent',
  intent: 'cad',
  cad: 'validate',
}

const LABEL: Record<StageId, string> = {
  sources: 'Sources',
  evidence: 'Evidence',
  intent: 'Intent',
  cad: 'CAD',
  validate: 'Validate',
}

function summary(stage: StageId, state: RunState, rev: Revision): string | null {
  switch (stage) {
    case 'evidence': {
      // A knowledge table (ISO 273) is a source of evidence but not a document
      // the user supplied, and counting it as one overstates what was read.
      const docs = new Set(
        state.evidence
          .filter((e) => e.source.modality !== 'engineering_rule')
          .map((e) => e.source.file),
      ).size
      const derived = state.evidence.filter(
        (e) => e.source.modality === 'engineering_rule').length
      const tail = derived ? `, ${derived} derived from standards` : ''
      return `${docs} documents → ${state.evidence.length} observations${tail}`
    }
    case 'intent': {
      const count = Object.keys(rev.parameters).length
      const hard = rev.constraints.filter((c) => c.severity === 'hard').length
      return `${count} parameters · ${hard} hard constraint${hard === 1 ? '' : 's'}`
    }
    case 'cad': {
      const built = rev.operations.filter((o) => o.measured).length
      return `${built} feature${built === 1 ? '' : 's'} built and measured`
    }
    default:
      return null
  }
}

export function GuideBar({
  stage, state, rev, onGo,
}: {
  stage: StageId
  state: RunState
  rev: Revision
  onGo: (s: StageId) => void
}) {
  const next = NEXT[stage]
  if (!next) return null
  const note = summary(stage, state, rev)

  return (
    <div className="sticky bottom-0 z-10 flex items-center gap-[10px] border-t border-c3
                    bg-c0/95 px-[14px] py-[9px] backdrop-blur-md">
      {note && (
        <span className="num min-w-0 flex-1 truncate text-[12px] text-c7">{note}</span>
      )}
      <button
        onClick={() => onGo(next)}
        className="flex shrink-0 cursor-pointer items-center gap-[6px] rounded-[5px]
                   border border-accent bg-accent px-[11px] py-[5px] text-[12.5px]
                   font-medium text-accent-fg shadow-[var(--shadow-raised)]
                   transition-opacity duration-150 hover:opacity-90"
      >
        Continue to {LABEL[next]}
        <ArrowRight size={13} strokeWidth={2} aria-hidden />
      </button>
    </div>
  )
}
