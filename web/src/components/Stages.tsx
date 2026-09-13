/**
 * Inspector contents, one per pipeline stage.
 *
 * Each renders inside the right-hand pane and scrolls on its own. None of them
 * is a page; they are panels in an application, and they assume the viewport is
 * still visible beside them.
 */
import { useState } from 'react'
import type { Check, Evidence, Proposal, Revision, RunState } from '../types'
import { api } from '../api'
import { cn } from '../lib/cn'
import { Button, Empty, Field, Mark, Num, PanelHead, Tip } from './ui'

const show = (v: unknown) => (v === null || v === undefined ? '—' : String(v))

/* --------------------------------------------------------------- sources */

export function SourcesStage({
  onDemo, onUpload, busy, backendLabel, visionAvailable,
}: {
  onDemo: () => void
  onUpload: (s: File, d: File, r: string) => void
  busy: boolean
  backendLabel: string
  visionAvailable: boolean
}) {
  const [sketch, setSketch] = useState<File | null>(null)
  const [datasheet, setDatasheet] = useState<File | null>(null)
  const [requirement, setRequirement] = useState(
    'Manufacture the adapter from 5 mm aluminium. Use normal-clearance holes for M3 ' +
    'screws, maintain at least 4 mm from every hole edge to the plate boundary, and ' +
    'add 1 mm chamfers to the external edges.',
  )

  const fileInput = 'block w-full cursor-pointer border border-c4 bg-c0 px-2 py-1.5 ' +
    'text-[11.5px] file:mr-2 file:cursor-pointer file:border file:border-c4 ' +
    'file:bg-c2 file:px-1.5 file:py-0.5 file:text-[11px] hover:border-c6'

  return (
    <>
      <PanelHead title="Sources" note="three documents, jointly impossible" />

      <div className="p-3.5">
        <Button intent="solid" size="md" className="w-full" onClick={onDemo} disabled={busy}>
          {busy ? 'Compiling…' : 'Compile the example'}
        </Button>
      </div>

      <div className="border-y border-c3">
        {[
          ['Sketch', '40 × 50 mm outline, 4 holes'],
          ['Datasheet', 'NEMA-17, 31 × 31 mm, 4 × M3'],
          ['Requirement', '5 mm Al, ≥4 mm edge, 1 mm chamfer'],
        ].map(([k, v]) => <Field key={k} label={k} dense>{v}</Field>)}
      </div>

      <p className="px-3.5 py-3 text-[11.5px] leading-relaxed text-c7">
        Each document is read correctly. The 40 mm width, the 31 mm pattern and the 4 mm
        clearance cannot all hold at once — that is what this tool is for.
      </p>

      <div className="border-t border-c3 p-3.5">
        <h3 className="mb-2.5 text-[12px] font-semibold">Use your own</h3>
        <div className="space-y-2.5">
          <label className="block">
            <span className="mb-1 block text-[11px] text-c7">Sketch image</span>
            <input type="file" accept="image/*" className={fileInput}
                   onChange={(e) => setSketch(e.target.files?.[0] ?? null)} />
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] text-c7">Datasheet PDF</span>
            <input type="file" accept="application/pdf" className={fileInput}
                   onChange={(e) => setDatasheet(e.target.files?.[0] ?? null)} />
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] text-c7">Requirement</span>
            <textarea value={requirement} onChange={(e) => setRequirement(e.target.value)}
              className="min-h-[76px] w-full resize-y border border-c4 bg-c0 px-2 py-1.5
                         text-[11.5px] leading-relaxed focus:border-c9 focus:outline-none" />
          </label>
          <Tip label={visionAvailable
            ? 'Runs the full pipeline on your documents'
            : 'An uploaded drawing has no recorded fixture, so this needs a vision API key'}>
            <span className="block">
              <Button className="w-full" disabled={busy || !sketch || !datasheet || !visionAvailable}
                onClick={() => sketch && datasheet && onUpload(sketch, datasheet, requirement)}>
                Compile uploaded documents
              </Button>
            </span>
          </Tip>
        </div>
        <p className="mt-2.5 text-[11px] leading-relaxed text-c6">
          Extraction backend: {backendLabel}.
          {!visionAvailable && ' The datasheet is parsed for real regardless.'}
        </p>
      </div>
    </>
  )
}

/* -------------------------------------------------------------- evidence */

export function EvidenceStage({
  state, picked, onPick,
}: {
  state: RunState
  picked: Evidence | null
  onPick: (e: Evidence | null) => void
}) {
  return (
    <>
      <PanelHead title="Evidence" note={`${state.evidence.length} facts`} />

      <table className="w-full border-collapse">
        <tbody>
          {state.evidence.map((e) => {
            const on = picked?.id === e.id
            return (
              <tr key={e.id} onClick={() => onPick(on ? null : e)}
                  className={cn('cursor-pointer border-b border-c3',
                                on ? 'bg-c9 text-c0' : 'hover:bg-c2')}>
                <td className="py-1.5 pl-3.5 pr-2">
                  <div className="text-[11.5px]">{e.target.replace(/_/g, ' ')}</div>
                  <div className={cn('text-[10.5px]', on ? 'text-c5' : 'text-c6')}>
                    {e.source.modality.replace('_', ' ')}
                    {e.source.page && ` p.${e.source.page}`}
                  </div>
                </td>
                <td className="py-1.5 pr-2 text-right">
                  <Num value={show(e.value)} unit={e.unit} strong
                       className={on ? 'text-c0' : undefined} />
                </td>
                <td className="w-[18px] py-1.5 pr-3.5 text-right">
                  {/* an inferred value is marked, a stated one is not: the
                      absence of a mark is the common case */}
                  {!e.is_explicit_annotation && (
                    <Tip label="Derived from a rule or a standard, not stated on any document">
                      <span className={cn('num text-[10px]', on ? 'text-c5' : 'text-c6')}>ƒ</span>
                    </Tip>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>

      {picked && (
        <div className="border-t-2 border-c9">
          <PanelHead title="Where it came from" aside={
            <Button intent="ghost" size="sm" onClick={() => onPick(null)}>Close</Button>
          } />
          <div className="p-3.5">
            {picked.has_preview ? (
              <img src={api.previewUrl(state.run_id, picked.id)}
                   alt={`Source of ${picked.target}`}
                   className="w-full border border-c4" />
            ) : (
              <p className="text-[11.5px] leading-relaxed text-c7">
                Derived from {picked.source.detail ?? 'a rule'}, so there is no region on a
                document to point at.
              </p>
            )}
            {picked.raw_text && (
              <p className="mt-2.5 border-l-2 border-c4 pl-2.5 text-[11.5px]
                            leading-relaxed text-c7">
                {picked.raw_text}
              </p>
            )}
          </div>
          <div className="border-t border-c3">
            <Field label="Confidence" dense>
              <Num value={picked.confidence.toFixed(2)} />
              <span className="ml-2 text-[11px] text-c6">that it was read correctly</span>
            </Field>
            <Field label="Authority" dense>
              {picked.authority}
              <span className="ml-2 text-[11px] text-c6">entitlement to define this</span>
            </Field>
            <Field label="Method" dense>
              <span className="num text-[11px]">{picked.extraction_method.replace(/_/g, ' ')}</span>
            </Field>
            {picked.original_value && (
              <Field label="Before units" dense>{picked.original_value}</Field>
            )}
          </div>
        </div>
      )}
    </>
  )
}

/* ---------------------------------------------------------------- intent */

export function IntentStage({ rev }: { rev: Revision }) {
  return (
    <>
      <PanelHead title="Design intent" note={`revision ${rev.revision}`} />

      {rev.changes.length > 0 && (
        <div className="hatch border-b border-c3 px-3.5 py-2.5">
          <div className="text-[11px] text-c7">Changed in this revision</div>
          {rev.changes.map((c) => (
            <div key={c.parameter} className="mt-1 text-[12px]">
              <span>{c.parameter.replace(/_/g, ' ')} </span>
              <Num value={String(c.before)} />
              <span className="px-1 text-c6">→</span>
              <Num value={String(c.after)} strong />
              <div className="text-[11px] text-c6">approved by {rev.approved_by}</div>
            </div>
          ))}
        </div>
      )}

      <div>
        {Object.entries(rev.parameters).map(([name, p]) => (
          <Field key={name} label={name.replace(/_/g, ' ')} dense>
            <span className="flex items-baseline gap-2">
              <Num value={show(p.value)} unit={p.unit} strong />
              {p.status !== 'confirmed' && (
                <Tip label={p.derivation ?? p.provenance.join(', ')}>
                  <span className="num text-[10px] text-c6">
                    {p.status === 'inferred' ? 'ƒ derived' : p.status}
                  </span>
                </Tip>
              )}
            </span>
          </Field>
        ))}
      </div>

      <PanelHead title="Constraints" />
      {rev.constraints.map((c) => (
        <Field key={c.id} label={c.type.replace(/_/g, ' ')} dense>
          <Num value={c.value} unit={c.unit} strong />
          <span className="ml-2 text-[11px] text-c6">{c.severity}</span>
        </Field>
      ))}
    </>
  )
}

/* --------------------------------------------------------------- inspect */

function CheckRow({ c }: { c: Check }) {
  const failed = c.status === 'fail'
  return (
    <div className={cn('border-b border-c3 px-3.5 py-2',
                       failed && 'hatch border-l-2 border-l-c9')}>
      <div className="flex items-baseline gap-2">
        <Mark state={c.status} glyph />
        <span className={cn('flex-1 text-[11.5px]', failed && 'font-semibold')}>{c.name}</span>
        <Num value={c.actual ?? '—'} strong={failed} />
      </div>
      {c.expected && (
        <div className="mt-0.5 pl-4 text-[10.5px] text-c6">
          required <span className="num">{c.expected}</span>
        </div>
      )}
      {failed && (
        <p className="mt-1 pl-4 text-[11px] leading-snug text-c8">{c.message}</p>
      )}
    </div>
  )
}

export function InspectStage({ rev }: { rev: Revision }) {
  const [tab, setTab] = useState<'measured' | 'preflight'>('measured')
  const checks = tab === 'measured' ? rev.measured : rev.preflight
  const failing = checks.filter((c) => c.status === 'fail').length

  return (
    <>
      <PanelHead
        title="Inspection"
        aside={
          <div className="flex border border-c4">
            {(['measured', 'preflight'] as const).map((t) => (
              <button key={t} onClick={() => setTab(t)}
                className={cn('cursor-pointer px-2 py-0.5 text-[11px] capitalize',
                  tab === t ? 'bg-c9 text-c0' : 'bg-c0 text-c7 hover:bg-c2')}>
                {t}
              </button>
            ))}
          </div>
        }
      />

      <p className="border-b border-c3 px-3.5 py-2 text-[11px] leading-relaxed text-c7">
        {tab === 'measured'
          ? 'Read off the finished solid — hole sizes and positions from the B-Rep, extents from face geometry, material integrity against the analytic volume.'
          : 'Predicted symbolically before any geometry existed. Advisory only; it never blocks a release.'}
      </p>

      <div className="flex items-center gap-2 border-b border-c3 px-3.5 py-1.5">
        <Mark state={failing ? 'fail' : 'pass'} box glyph>
          {failing ? `${failing} failing` : 'all passing'}
        </Mark>
        <span className="num text-[11px] text-c6">{checks.length} checks</span>
      </div>

      {checks.map((c) => <CheckRow key={c.id} c={c} />)}

      {tab === 'measured' && rev.cross_checks.length > 0 && (
        <>
          <PanelHead title="Prediction vs measurement" />
          <p className="border-b border-c3 px-3.5 py-2 text-[11px] leading-relaxed text-c7">
            If these disagreed it would mean a bug in the pipeline, not a problem with
            the design.
          </p>
          {rev.cross_checks.map((c) => <CheckRow key={c.id} c={c} />)}
        </>
      )}
    </>
  )
}

/* --------------------------------------------------------------- release */

export function ReleaseStage({
  rev, onRepair, busy,
}: { rev: Revision; onRepair: (p: Proposal) => void; busy: boolean }) {
  const blocked = !rev.release.step_export_allowed
  const clearance = rev.measured.find((c) => c.id === 'req_edge_clearance')

  return (
    <>
      <PanelHead title="Release" aside={
        <Mark state={blocked ? 'fail' : 'pass'} box glyph>
          {blocked ? 'blocked' : 'authorised'}
        </Mark>
      } />

      <div className={cn('border-b border-c3 px-3.5 py-3', blocked && 'hatch')}>
        {blocked && clearance?.measured_value != null ? (
          <>
            <p className="text-[12.5px] leading-relaxed">
              The solid measures{' '}
              <Num value={clearance.measured_value.toFixed(1)} unit="mm" strong
                   className="text-[15px]" />
              {' '}between the nearest hole edge and the boundary, where{' '}
              <Num value={clearance.required_value?.toFixed(1)} unit="mm" /> is required.
            </p>
            <p className="mt-2 text-[11.5px] leading-relaxed text-c7">
              Every source was read correctly. This is a constraint conflict, not a
              misreading, so it is attributed to parameters rather than blamed on a
              document.
            </p>
          </>
        ) : (
          <p className="text-[12.5px] leading-relaxed">{rev.release.explanation}</p>
        )}
      </div>

      {blocked && rev.release.responsible_parameters.length > 0 && (
        <div className="border-b border-c3">
          <div className="px-3.5 pt-2 text-[11px] text-c7">Responsible parameters</div>
          {rev.release.responsible_parameters.map((p) => (
            <Field key={p} label={p.replace(/_/g, ' ')} dense>
              <span className="text-[11px] text-c6">read correctly, not jointly satisfiable</span>
            </Field>
          ))}
        </div>
      )}

      {rev.proposals.length > 0 && (
        <>
          <PanelHead title="Resolutions" note={`${rev.proposals.length} options`} />
          <div className="space-y-2 p-3.5">
            {rev.proposals.map((p) => {
              const safe = p.safety === 'safe'
              return (
                <article key={p.id}
                  className={cn('border p-2.5', safe ? 'border-c4 bg-c0' : 'border-c9 bg-c0')}>
                  <div className="mb-1.5 flex items-start gap-2">
                    <Mark state={safe ? 'pass' : 'fail'} box>
                      {safe ? 'keeps interface' : 'changes the part'}
                    </Mark>
                    {p.recommended && (
                      <span className="num text-[10px] text-c7">recommended</span>
                    )}
                  </div>
                  <h4 className="text-[12px] font-semibold leading-snug">{p.title}</h4>
                  <p className="mt-1 text-[11px] leading-relaxed text-c7">{p.rationale}</p>
                  {p.consequence && (
                    <p className="mt-1.5 border-l-2 border-c9 pl-2 text-[11px]
                                  leading-relaxed text-c8">
                      {p.consequence}
                    </p>
                  )}
                  <div className="mt-2.5">
                    {p.auto_applicable ? (
                      <Button intent={p.recommended ? 'solid' : 'outline'} size="sm"
                              disabled={busy} onClick={() => onRepair(p)}>
                        Approve &amp; rebuild
                      </Button>
                    ) : (
                      <Tip label="This discards a stated requirement or breaks the motor interface. It will not apply on a click.">
                        <span className="inline-block">
                          <Button size="sm" disabled>Needs a decision</Button>
                        </span>
                      </Tip>
                    )}
                  </div>
                </article>
              )
            })}
          </div>
        </>
      )}

      {!blocked && (
        <Empty>
          Every hard requirement is satisfied by the measured geometry. The STEP is
          available from the viewport.
        </Empty>
      )}
    </>
  )
}
