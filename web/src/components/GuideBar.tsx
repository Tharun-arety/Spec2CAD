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
  intent: 'canvas',
  canvas: 'cad',
  cad: 'validate',
}

const LABEL: Record<StageId, string> = {
  sources: 'Sources',
  evidence: 'Evidence',
  intent: 'Intent',
  canvas: 'Canvas',
  cad: 'CAD',
  validate: 'Validate',
  revisions: 'Revisions',
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
    case 'canvas': {
      const failing = rev.measured.filter((check) => check.status === 'fail').length
      return failing
        ? `${failing} governing failure${failing === 1 ? '' : 's'} localized`
        : 'evidence, intent, build and release are traceable'
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
  if (stage === 'intent' && rev.build_error) {
    const missing = ['plate_width', 'plate_height', 'plate_thickness']
      .filter((name) => rev.parameters[name]?.status === 'missing')
      .map((name) => name.replace(/_/g, ' '))
    return (
      <div className="sticky bottom-0 z-10 border-t border-warn-line bg-warn-wash
                      px-[14px] py-[9px]">
        <p className="text-[12px] leading-relaxed text-c8">
          {missing.length ? `Missing: ${missing.join(', ')}` : 'More source information is needed.'}
        </p>
        <button
          type="button"
          onClick={() => onGo('sources')}
          className="mt-[7px] flex cursor-pointer items-center gap-[6px] rounded-[5px]
                     border border-accent bg-accent px-[11px] py-[5px] text-[12.5px]
                     font-medium text-accent-fg shadow-[var(--shadow-raised)]"
        >
          Add missing inputs
          <ArrowRight size={13} strokeWidth={2} aria-hidden />
        </button>
      </div>
    )
  }

  const next = NEXT[stage]
  if (!next) return null
  const note = summary(stage, state, rev)

  return (
    <div className="sticky bottom-0 z-10 grid gap-[7px] border-t border-c3
                    bg-c0 px-[13px] py-[9px]">
      {note && (
        <span className="num text-[11px] leading-[1.4] text-c6">{note}</span>
      )}
      <button
        onClick={() => onGo(next)}
        className="flex cursor-pointer items-center justify-between gap-[6px] rounded-[2px]
                   border border-c4 bg-c1 px-[9px] py-[6px] text-[12px]
                   font-medium text-c9 transition-colors duration-150
                   hover:border-accent hover:bg-accent-wash"
      >
        Continue to {LABEL[next]}
        <ArrowRight size={13} strokeWidth={2} className="text-accent" aria-hidden />
      </button>
    </div>
  )
}
