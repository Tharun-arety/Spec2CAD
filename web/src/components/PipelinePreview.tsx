/**
 * What the canvas shows before anything has been compiled.
 *
 * It previously held a restatement of the "Compile the example" button that is
 * already in the inspector, which wasted the largest area on screen on a
 * duplicate. This says what is about to happen instead: three documents, the
 * facts each one carries, and the single design intent they have to reconcile.
 *
 * The counts are the example's known contents, so they are labelled as the
 * example rather than presented as a live reading.
 */

const SOURCES = [
  { name: 'Sketch', detail: '40 × 50 mm outline', facts: 4 },
  { name: 'Datasheet', detail: 'NEMA-17, 31 × 31 mm', facts: 5 },
  { name: 'Requirement', detail: '5 mm Al, ≥4 mm edge', facts: 6 },
]

export function PipelinePreview({ busy }: { busy: boolean }) {
  return (
    <div className="px-[21px] text-center">
      <div className="flex items-start justify-center gap-[10px]">
        {SOURCES.map((s, i) => (
          <div key={s.name} className="flex items-start gap-[10px]">
            {i > 0 && (
              <span aria-hidden className="mt-[26px] text-[14px] text-c5">+</span>
            )}
            <div className="w-[116px] rounded-[7px] border border-c4 bg-c0 px-[10px] py-[9px]
                            shadow-[var(--shadow-raised)]">
              <div className="text-[12.5px] font-semibold text-c9">{s.name}</div>
              <div className="mt-[2px] text-[11.5px] leading-snug text-c6">{s.detail}</div>
              <div className="num mt-[6px] text-[11.5px] text-c7">{s.facts} facts</div>
            </div>
          </div>
        ))}
      </div>

      <div aria-hidden className="mx-auto my-[10px] h-[26px] w-px bg-c4" />

      <div className="mx-auto w-[233px] rounded-[7px] border border-dashed border-c4
                      bg-c1 px-[13px] py-[10px]">
        <div className="text-[12.5px] font-medium text-c8">
          {busy ? 'Reconciling…' : 'Design intent pending'}
        </div>
        <div className="mt-[2px] text-[11.5px] leading-snug text-c6">
          15 read, 1 derived from ISO 273
        </div>
      </div>

      <p className="mx-auto mt-[18px] max-w-[340px] text-[12.5px] leading-relaxed text-c7">
        {busy
          ? 'Extracting, fusing, compiling, building and measuring…'
          : 'Three documents that each read correctly and cannot all be satisfied. Compile to watch the design get refused, repaired and released.'}
      </p>
    </div>
  )
}
