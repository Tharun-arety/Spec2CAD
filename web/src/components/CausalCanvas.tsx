import { useState } from 'react'
import {
  Boxes, FileText, GitPullRequestArrow, Ruler, ShieldCheck, SlidersHorizontal,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { Revision, RunState } from '../types'
import { cn } from '../lib/cn'
import { Mark, Num, PanelHead } from './ui'

type CanvasNodeId = 'evidence' | 'intent' | 'feature-ir' | 'cad-state' | 'measurement' | 'release'

interface CanvasNode {
  id: CanvasNodeId
  label: string
  kind: string
  value: string
  detail: string
  icon: LucideIcon
  area: string
  state: 'neutral' | 'observed' | 'failed' | 'passed'
}

function unresolvedParameters(rev: Revision) {
  return Object.entries(rev.parameters).filter(([, parameter]) => parameter.status === 'missing')
}

function buildNodes(state: RunState, rev: Revision): CanvasNode[] {
  const documents = new Set(
    state.evidence
      .filter((evidence) => evidence.source.modality !== 'engineering_rule')
      .map((evidence) => evidence.source.file),
  )
  const missing = unresolvedParameters(rev)
  const built = rev.operations.filter((operation) => operation.measured)
  const failing = rev.measured.filter((check) => check.status === 'fail')
  const released = rev.release.step_export_allowed
  const backend = rev.backend_evidence?.classification
    ? rev.backend_evidence.classification.replace(/_/g, ' ').toLowerCase()
    : `${built.length} observed features`

  return [
    {
      id: 'evidence', label: 'Source evidence', kind: 'recorded input',
      value: `${documents.size} document${documents.size === 1 ? '' : 's'} / ${state.evidence.length} facts`,
      detail: 'Every extracted value retains its source file, region and authority.',
      icon: FileText, area: 'evidence', state: 'observed',
    },
    {
      id: 'intent', label: 'Engineering intent', kind: `DesignIntent v${rev.revision}`,
      value: missing.length ? `${missing.length} unresolved parameter${missing.length === 1 ? '' : 's'}` : `${Object.keys(rev.parameters).length} parameters resolved`,
      detail: missing.length
        ? `Missing: ${missing.map(([name]) => name.replace(/_/g, ' ')).join(', ')}. No value is invented.`
        : 'The authoritative parameter set is complete for this bounded build.',
      icon: SlidersHorizontal, area: 'intent', state: missing.length ? 'failed' : 'observed',
    },
    {
      id: 'feature-ir', label: 'Feature IR', kind: 'deterministic plan',
      value: `${rev.operations.length} ordered operation${rev.operations.length === 1 ? '' : 's'}`,
      detail: 'Backend-neutral features compile from approved intent; model prose never executes as CAD code.',
      icon: GitPullRequestArrow, area: 'feature', state: 'neutral',
    },
    {
      id: 'cad-state', label: 'CAD state', kind: 'immutable observation',
      value: backend,
      detail: 'The build record describes what the configured backend actually produced.',
      icon: Boxes, area: 'cad', state: rev.build_error ? 'failed' : 'observed',
    },
    {
      id: 'measurement', label: 'Measured evidence', kind: 'finished solid',
      value: `${rev.measured.length - failing.length} pass / ${failing.length} fail`,
      detail: failing[0]?.message ?? 'The governing measurements agree with the approved intent.',
      icon: Ruler, area: 'measure', state: failing.length ? 'failed' : 'passed',
    },
    {
      id: 'release', label: 'Release decision', kind: 'measured gate',
      value: released ? 'STEP authorised' : 'STEP withheld',
      detail: rev.release.reasons[0] ?? rev.release.explanation,
      icon: ShieldCheck, area: 'release', state: released ? 'passed' : 'failed',
    },
  ]
}

export function CanvasStage({ state, rev }: { state: RunState; rev: Revision }) {
  const missing = unresolvedParameters(rev)
  const failing = rev.measured.filter((check) => check.status === 'fail')
  const recommendation = rev.proposals.find((proposal) => proposal.recommended)

  return (
    <>
      <PanelHead title="Causal trace" note={`revision ${rev.revision}`} />
      <p className="border-b border-c3 px-[13px] py-[10px] text-[12.5px] leading-relaxed text-c7">
        Read the design as a chain of accountable transformations. Select a node on the
        canvas to inspect what it knows and which authority produced it.
      </p>
      <div className="border-b border-c3 px-[13px] py-[11px]">
        <div className="text-[11.5px] font-medium text-c6">Active causal path</div>
        <div className="mt-[7px] space-y-[6px] text-[12.5px]">
          <div className="flex items-center justify-between gap-[8px]"><span>Source observations</span><Num value={state.evidence.length} /></div>
          <div className="flex items-center justify-between gap-[8px]"><span>Unresolved intent</span><Num value={missing.length} strong={missing.length > 0} /></div>
          <div className="flex items-center justify-between gap-[8px]"><span>Failing measurements</span><Num value={failing.length} strong={failing.length > 0} /></div>
        </div>
      </div>
      {(missing.length > 0 || failing.length > 0) && (
        <section className="border-b border-danger-line bg-danger-wash px-[13px] py-[11px]" aria-label="Localized issue">
          <div className="flex items-center justify-between gap-[8px]">
            <h3 className="text-[12.5px] font-semibold">Localized issue</h3>
            <Mark state="fail" glyph>release blocked</Mark>
          </div>
          <p className="mt-[6px] text-[12px] leading-relaxed text-c8">
            {missing.length
              ? `Intent is missing ${missing.map(([name]) => name.replace(/_/g, ' ')).join(', ')}.`
              : failing[0]?.message}
          </p>
        </section>
      )}
      {recommendation && (
        <section className="px-[13px] py-[11px]" aria-label="Suggested resolution">
          <div className="text-[11.5px] font-medium text-accent">Suggested resolution</div>
          <h3 className="mt-[4px] text-[13px] font-semibold text-c9">{recommendation.title}</h3>
          <p className="mt-[5px] text-[12px] leading-relaxed text-c7">{recommendation.rationale}</p>
          <p className="mt-[7px] border-t border-c3 pt-[7px] text-[11.5px] leading-relaxed text-c6">
            Recommendation only. It becomes intent only after approval and creates a new revision.
          </p>
        </section>
      )}
    </>
  )
}

export function CanvasWorkspace({ state, rev }: { state: RunState; rev: Revision }) {
  const nodes = buildNodes(state, rev)
  const [selected, setSelected] = useState<CanvasNodeId>('intent')
  const active = nodes.find((node) => node.id === selected) ?? nodes[0]

  return (
    <section className="causal-canvas flex h-full min-h-0 flex-col bg-c1" aria-label="Engineering causal canvas">
      <header className="flex h-[37px] shrink-0 items-center gap-[8px] border-b border-c3 bg-c0 px-[13px]">
        <GitPullRequestArrow size={14} strokeWidth={1.7} className="text-c6" aria-hidden />
        <span className="text-[12.5px] font-medium text-c9">Engineering causal canvas</span>
        <span className="num ml-auto text-[11.5px] text-c6">EIG → Feature IR → observed CAD → release</span>
      </header>

      <div className="relative min-h-0 flex-1 overflow-auto p-[21px]">
        <svg className="causal-links" viewBox="0 0 900 500" preserveAspectRatio="none" aria-hidden>
          <path d="M145 116 H360" />
          <path d="M540 116 H755" />
          <path d="M755 142 V356" />
          <path d="M755 384 H540" />
          <path d="M360 384 H145" />
        </svg>
        <div className="causal-node-grid">
          {nodes.map((node) => {
            const Icon = node.icon
            const on = node.id === selected
            return (
              <button
                key={node.id}
                type="button"
                aria-pressed={on}
                onClick={() => setSelected(node.id)}
                className={cn('causal-node', `causal-node-${node.state}`)}
                style={{ gridArea: node.area }}
              >
                <span className="causal-node-icon"><Icon size={15} strokeWidth={1.7} aria-hidden /></span>
                <span className="min-w-0">
                  <span className="block text-[11px] text-c6">{node.kind}</span>
                  <strong className="mt-[2px] block text-[13px] font-semibold text-c9">{node.label}</strong>
                  <span className="num mt-[6px] block text-[11.5px] text-c7">{node.value}</span>
                </span>
              </button>
            )
          })}
        </div>
      </div>

      <div className="canvas-detail shrink-0 border-t border-c3 bg-c0 px-[13px] py-[10px]" aria-live="polite">
        <div className="flex items-baseline gap-[8px]">
          <strong className="text-[12.5px] font-semibold text-c9">{active.label}</strong>
          <span className="num text-[11px] text-c6">{active.kind}</span>
        </div>
        <p className="mt-[3px] max-w-[76ch] text-[12px] leading-relaxed text-c7">{active.detail}</p>
      </div>
    </section>
  )
}
