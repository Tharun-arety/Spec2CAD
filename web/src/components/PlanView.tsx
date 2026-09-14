import type { Revision } from '../types'

/**
 * A dimensioned top view, drawn in SVG straight from the revision parameters.
 *
 * This is the fallback when WebGL is unavailable, and it is deliberately not an
 * apology box. Every line here comes from the same parameters the kernel built
 * from, so the panel still answers the question the 3D view answers -- how wide
 * is the plate, where are the holes, how much material is left at the edge --
 * without needing a GPU.
 *
 * It is labelled as a schematic because that is what it is: a parametric plan
 * view, not a projection of the measured B-Rep.
 */

const num = (rev: Revision, name: string): number | null => {
  const v = rev.parameters[name]?.value
  return typeof v === 'number' ? v : null
}

export function PlanView({ rev, note }: { rev: Revision; note?: string }) {
  const w = num(rev, 'plate_width')
  const h = num(rev, 'plate_height')
  const bore = num(rev, 'shaft_opening_diameter') ?? 0
  const holeD = num(rev, 'mounting_hole_diameter') ?? 0
  const sx = num(rev, 'hole_spacing_x') ?? 0
  const sy = num(rev, 'hole_spacing_y') ?? 0
  const chamfer = num(rev, 'external_chamfer') ?? 0

  if (w === null || h === null) {
    return (
      <div className="grid h-full place-items-center p-[21px] text-center">
        <p className="text-[13px] leading-relaxed text-c7">
          This revision has no plate dimensions to draw.
        </p>
      </div>
    )
  }

  // Model millimetres -> SVG units, with room for dimension lines outside.
  const pad = 22
  const vbW = w + pad * 2
  const vbH = h + pad * 2
  const x0 = -w / 2
  const y0 = -h / 2

  // Chamfered rectangle: corners cut by the chamfer distance in plan.
  const c = Math.min(chamfer, Math.min(w, h) / 2)
  const outline = [
    [x0 + c, y0], [x0 + w - c, y0],
    [x0 + w, y0 + c], [x0 + w, y0 + h - c],
    [x0 + w - c, y0 + h], [x0 + c, y0 + h],
    [x0, y0 + h - c], [x0, y0 + c],
  ].map(([x, y]) => `${x.toFixed(3)},${y.toFixed(3)}`).join(' ')

  const holes = [
    [-sx / 2, -sy / 2], [sx / 2, -sy / 2],
    [sx / 2, sy / 2], [-sx / 2, sy / 2],
  ]

  // Edge clearance: the material between a mounting hole and the nearest edge.
  const clearance = (w - sx) / 2 - holeD / 2

  const T = 1.05          // stroke width in model units, so it scales with the viewBox
  const label = 3.4       // dimension text size in model units

  return (
    <div className="flex h-full w-full flex-col">
      <svg
        viewBox={`${-vbW / 2} ${-vbH / 2} ${vbW} ${vbH}`}
        className="min-h-0 w-full flex-1"
        role="img"
        aria-label={`Dimensioned plan view: ${w} by ${h} millimetre plate with ${holes.length} mounting holes on a ${sx} by ${sy} millimetre pattern`}
      >
        {/* plate */}
        <polygon
          points={outline}
          className="fill-c2 stroke-c9"
          strokeWidth={T}
          strokeLinejoin="round"
        />

        {/* centre shaft opening */}
        {bore > 0 && (
          <circle cx={0} cy={0} r={bore / 2} className="fill-c0 stroke-c9" strokeWidth={T} />
        )}

        {/* mounting holes */}
        {holes.map(([cx, cy], i) => (
          <circle key={i} cx={cx} cy={cy} r={holeD / 2}
                  className="fill-c0 stroke-c9" strokeWidth={T} />
        ))}

        {/* centre lines */}
        <g className="stroke-c5" strokeWidth={T * 0.5} strokeDasharray={`${T * 3} ${T * 2}`}>
          <line x1={-w / 2 - 6} y1={0} x2={w / 2 + 6} y2={0} />
          <line x1={0} y1={-h / 2 - 6} x2={0} y2={h / 2 + 6} />
        </g>

        {/* width dimension, below the plate */}
        <g className="stroke-c7 fill-c8" strokeWidth={T * 0.6}>
          <line x1={x0} y1={y0 + h + 10} x2={x0 + w} y2={y0 + h + 10} />
          <line x1={x0} y1={y0 + h + 6} x2={x0} y2={y0 + h + 14} />
          <line x1={x0 + w} y1={y0 + h + 6} x2={x0 + w} y2={y0 + h + 14} />
          <text x={0} y={y0 + h + 19} textAnchor="middle" fontSize={label}
                className="fill-c9" stroke="none" fontWeight={600}>
            {w} mm
          </text>
        </g>

        {/* hole pattern dimension, above the plate */}
        {sx > 0 && (
          <g className="stroke-accent fill-accent" strokeWidth={T * 0.6}>
            <line x1={-sx / 2} y1={y0 - 10} x2={sx / 2} y2={y0 - 10} />
            <line x1={-sx / 2} y1={y0 - 14} x2={-sx / 2} y2={y0 - 6} />
            <line x1={sx / 2} y1={y0 - 14} x2={sx / 2} y2={y0 - 6} />
            <text x={0} y={y0 - 13} textAnchor="middle" fontSize={label}
                  stroke="none" fontWeight={600}>
              {sx} mm pattern
            </text>
          </g>
        )}

        {/* height dimension, to the right */}
        <g className="stroke-c7" strokeWidth={T * 0.6}>
          <line x1={x0 + w + 10} y1={y0} x2={x0 + w + 10} y2={y0 + h} />
          <line x1={x0 + w + 6} y1={y0} x2={x0 + w + 14} y2={y0} />
          <line x1={x0 + w + 6} y1={y0 + h} x2={x0 + w + 14} y2={y0 + h} />
          <text x={x0 + w + 13} y={2} fontSize={label} className="fill-c9"
                stroke="none" fontWeight={600}
                transform={`rotate(90 ${x0 + w + 13} 0)`} textAnchor="middle">
            {h} mm
          </text>
        </g>
      </svg>

      {/* pb clears the viewport overlay buttons pinned to the bottom edge */}
      <p className="mx-auto max-w-[520px] shrink-0 px-[16px] pb-[47px] text-center
                    text-[12px] leading-relaxed text-c6">
        {note ?? 'Schematic plan view, drawn from the revision parameters.'}
        {clearance > 0 && (
          <>
            {' '}Edge clearance{' '}
            <span className="num font-semibold text-c8">{clearance.toFixed(1)} mm</span> per side.
          </>
        )}
      </p>
    </div>
  )
}
