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

  return (
    <section className={[
      'border-b',
      anyFixture ? 'border-warn-line bg-warn-wash' : 'border-success-line bg-success-wash',
    ].join(' ')}>
      <div className="flex items-baseline gap-[8px] px-[14px] pt-[11px]">
        <span className={[
          'rounded-[4px] px-[6px] py-px text-[11px] font-semibold uppercase tracking-[0.08em]',
          anyFixture ? 'bg-warn text-c0' : 'bg-success text-c0',
        ].join(' ')}>
          Extraction mode
        </span>
        <span className={[
          'text-[13px] font-medium',
          anyFixture ? 'text-warn' : 'text-success',
        ].join(' ')}>
          {headline}
        </span>
      </div>

      <ul className="px-[14px] py-[9px]">
        {rows.map((r) => {
          const isFixture = !r.derived && r.fixture > 0 && r.live === 0
          return (
            <li key={r.file} className="flex items-baseline gap-[8px] py-[2px] text-[12.5px]">
              <span aria-hidden className={[
                'mt-[1px] h-[6px] w-[6px] shrink-0 rounded-full',
                r.derived ? 'bg-c5' : isFixture ? 'bg-warn' : 'bg-success',
              ].join(' ')} />
              <span className="min-w-0 flex-1 truncate font-medium text-c9">
                {short(r.file)}
              </span>
              <span className="num shrink-0 text-[11.5px] text-c7">
                {r.derived ? 'standard' : isFixture ? 'recorded' : 'live'} · {r.methods.join(', ')}
              </span>
            </li>
          )
        })}
      </ul>

      {anyFixture && (
        <p className="px-[14px] pb-[11px] text-[12px] leading-relaxed text-c8">
          Recorded evidence is a real prior reading replayed verbatim, not a
          guess — but it is not being read now. Set an API key on the backend to
          extract the sketch live.
        </p>
      )}
    </section>
  )
}
