import { ChevronDown } from 'lucide-react'
import type { Evidence } from '../types'

/**
 * Which sources were parsed live and which replayed a recorded reading.
 *
 * This is derived from the evidence records themselves rather than written as
 * prose, so it cannot drift away from what actually happened: every Evidence
 * carries `is_fixture` and the `extraction_method` that produced it.
 *
 * It is deliberately prominent. A claim that the pipeline read three documents
 * is the single most load-bearing claim this project makes, and burying the
 * caveat in footer text next to a confident headline is the fastest way to lose
 * a reviewer's trust.
 */

export interface SourceMode {
  file: string
  modality: string
  live: number
  fixture: number
  methods: string[]
  /** A standards table rather than a document the user supplied. */
  derived: boolean
}

export function summariseExtraction(evidence: Evidence[]): SourceMode[] {
  const by = new Map<string, SourceMode>()
  for (const e of evidence) {
    const key = e.source.file
    let row = by.get(key)
    if (!row) {
      row = {
        file: key, modality: e.source.modality, live: 0, fixture: 0, methods: [],
        derived: e.source.modality === 'engineering_rule',
      }
      by.set(key, row)
    }
    if (e.is_fixture) row.fixture += 1
    else row.live += 1
    const m = e.extraction_method.replace(/_/g, ' ').toLowerCase()
    if (!row.methods.includes(m)) row.methods.push(m)
  }
  return [...by.values()]
}

const short = (path: string) => path.split(/[\\/]/).pop() ?? path

export function ExtractionMode({ evidence }: { evidence: Evidence[] }) {
  if (evidence.length === 0) return null
  const rows = summariseExtraction(evidence)
  // Standards applied by rule are not "read", so they are excluded from the
  // live-vs-recorded verdict and labelled separately below.
  const docs = rows.filter((r) => !r.derived)
  const anyFixture = docs.some((r) => r.fixture > 0)
  const allFixture = docs.length > 0 && docs.every((r) => r.live === 0)

  const headline = allFixture
    ? 'All documents replayed from recorded evidence'
    : anyFixture
      ? 'Mixed: some documents parsed live, some replayed'
      : 'All documents parsed live'

  const liveCount = docs.filter((r) => r.live > 0).length
  const recordedCount = docs.filter((r) => r.fixture > 0 && r.live === 0).length
  const standardCount = rows.filter((r) => r.derived).length
  const summary = [
    liveCount ? `${liveCount} live` : '',
    recordedCount ? `${recordedCount} recorded` : '',
    standardCount ? `${standardCount} standard` : '',
  ].filter(Boolean).join(' / ')

  return (
    <section className="border-b border-c3 bg-c1">
      <details className="group">
        <summary className="grid cursor-pointer list-none grid-cols-[auto_minmax(0,1fr)_auto]
                            items-center gap-x-[8px] gap-y-[2px] px-[13px] py-[8px]
                            text-[12.5px] text-c7 transition-colors hover:bg-c2 hover:text-c9">
          <span aria-hidden className={[
            'h-[7px] w-[7px] shrink-0 rounded-full',
            anyFixture ? 'bg-warn' : 'bg-success',
          ].join(' ')} />
          <span className="font-medium text-c8">Source provenance</span>
          <ChevronDown size={14} strokeWidth={1.8} aria-hidden
                       className="shrink-0 transition-transform duration-150 group-open:rotate-180" />
          <span className="num col-span-2 col-start-2 text-[11.5px] text-c6">{summary}</span>
        </summary>

        <div className="border-t border-c3 px-[13px] pb-[11px] pt-[9px]">
          <p className={[
            'text-[12.5px] font-medium',
            anyFixture ? 'text-warn' : 'text-success',
          ].join(' ')}>
            {headline}
          </p>
          <ul className="mt-[7px]">
            {rows.map((r) => {
              const isFixture = !r.derived && r.fixture > 0 && r.live === 0
              return (
                <li key={r.file} className="flex items-baseline gap-[8px] py-[3px] text-[12.5px]">
                  <span aria-hidden className={[
                    'mt-[1px] h-[6px] w-[6px] shrink-0 rounded-full',
                    r.derived ? 'bg-c5' : isFixture ? 'bg-warn' : 'bg-success',
                  ].join(' ')} />
                  <span className="min-w-0 flex-1 truncate font-medium text-c9" title={short(r.file)}>
                    {short(r.file)}
                  </span>
                  <span className="num shrink-0 text-[11.5px] text-c7">
                    {r.derived ? 'standard' : isFixture ? 'recorded' : 'live'} / {r.methods.join(', ')}
                  </span>
                </li>
              )
            })}
          </ul>

          {anyFixture && (
            <p className="mt-[7px] text-[12px] leading-relaxed text-c7">
              Recorded values replay a verified prior reading; they are not being
              extracted again in this run. Add a vision API key to read the sketch live.
            </p>
          )}
        </div>
      </details>
    </section>
  )
}
