import { useEffect, useRef, useState } from 'react'
import { Pause, Play } from 'lucide-react'

export const PROOF_FRAMES = [
  {
    term: 'Text', geometry: 'coupling', label: 'a flanged shaft coupling',
    nodes: [
      { kind: 'Requirement', value: 'shaft bore = 20 mm', tone: 'observed', position: 'top-left',
        leader: 'M166 88L270 150', anchor: [270, 150] },
      { kind: 'Intent', value: 'set-screw depth unresolved', tone: 'intent', position: 'top-right',
        leader: 'M548 112L432 180', anchor: [432, 180] },
      { kind: 'Realization', value: 'six typed operations', tone: 'neutral', position: 'bottom-right',
        leader: 'M540 372L420 292', anchor: [420, 292] },
    ],
  },
  {
    term: 'Sketches', geometry: 'bracket', label: 'a mounting bracket',
    nodes: [
      { kind: 'Requirement', value: 'mounting centres = 64 mm', tone: 'observed', position: 'mid-left',
        leader: 'M154 236L268 220', anchor: [268, 220] },
      { kind: 'Intent', value: 'bend radius = 6 mm', tone: 'intent', position: 'top-right',
        leader: 'M548 86L420 144', anchor: [420, 144] },
      { kind: 'Realization', value: 'profile → pad → holes', tone: 'neutral', position: 'bottom-left',
        leader: 'M162 364L300 302', anchor: [300, 302] },
    ],
  },
  {
    term: 'Datasheets', geometry: 'enclosure', label: 'a sheet-metal enclosure',
    nodes: [
      { kind: 'Evidence', value: 'datum A from source face', tone: 'observed', position: 'top-right',
        leader: 'M540 78L448 148', anchor: [448, 148] },
      { kind: 'Intent', value: 'pocket depends on bore', tone: 'intent', position: 'bottom-left',
        leader: 'M160 356L294 284', anchor: [294, 284] },
      { kind: 'Realization', value: 'EIG → Feature IR linked', tone: 'neutral', position: 'mid-right',
        leader: 'M548 248L450 238', anchor: [450, 238] },
    ],
  },
  {
    term: 'Mixed sources', geometry: 'plate', label: 'a patterned mounting plate',
    nodes: [
      { kind: 'Observation', value: 'opening = 20.00 mm', tone: 'observed', position: 'top-left',
        leader: 'M164 80L288 154', anchor: [288, 154] },
      { kind: 'Requirement', value: 'edge clearance ≥ 4 mm', tone: 'intent', position: 'mid-right',
        leader: 'M548 230L456 248', anchor: [456, 248] },
      { kind: 'Decision', value: 'measured agreement', tone: 'success', position: 'bottom-left',
        leader: 'M158 366L300 304', anchor: [300, 304] },
    ],
  },
] as const

function GeometryDrawing({ geometry }: { geometry: typeof PROOF_FRAMES[number]['geometry'] }) {
  if (geometry === 'bracket') {
    return <g className="proof-geometry-lines">
      <path d="M205 310L205 126L418 126L500 190L500 310Z" />
      <path d="M238 286V160H405L466 207V286Z" />
      <path d="M205 126L238 160M418 126L405 160M500 190L466 207" />
      <ellipse cx="300" cy="224" rx="34" ry="34" /><ellipse cx="407" cy="224" rx="34" ry="34" />
      <path d="M250 310v25h216l34-25M205 310l33-24h228l34 24" />
    </g>
  }
  if (geometry === 'enclosure') {
    return <g className="proof-geometry-lines">
      <path d="M190 137L441 112L519 174L519 314L268 339L190 277Z" />
      <path d="M190 137l78 62 251-25M268 199v140M441 112v31" />
      <ellipse cx="381" cy="242" rx="50" ry="43" /><ellipse cx="381" cy="242" rx="27" ry="23" />
      <path d="M220 176v87l48 38M471 181v91M302 164l101-10" />
      <path d="M304 292l29-3M431 279l29-3M304 310l29-3M431 297l29-3" />
    </g>
  }
  if (geometry === 'plate') {
    return <g className="proof-geometry-lines">
      <path d="M180 126L459 103L524 161L524 305L245 328L180 270Z" />
      <path d="M180 126l65 58 279-23M245 184v144" />
      <ellipse cx="353" cy="218" rx="62" ry="51" /><ellipse cx="353" cy="218" rx="31" ry="25" />
      <ellipse cx="241" cy="164" rx="15" ry="12" /><ellipse cx="453" cy="146" rx="15" ry="12" />
      <ellipse cx="453" cy="286" rx="15" ry="12" /><ellipse cx="241" cy="302" rx="15" ry="12" />
    </g>
  }
  return <g className="proof-geometry-lines">
    <ellipse cx="350" cy="278" rx="151" ry="64" />
    <path d="M199 278v35c0 36 68 65 151 65s151-29 151-65v-35" />
    <path d="M271 263V157c0-39 35-71 79-71s79 32 79 71v106" />
    <ellipse cx="350" cy="157" rx="79" ry="51" /><ellipse cx="350" cy="157" rx="40" ry="25" />
    <path d="M310 157v17c0 14 18 25 40 25s40-11 40-25v-17" strokeDasharray="4 6" />
    <ellipse cx="250" cy="281" rx="14" ry="17" /><ellipse cx="350" cy="322" rx="14" ry="17" />
    <ellipse cx="450" cy="281" rx="14" ry="17" />
  </g>
}

export function KineticCadProof() {
  const proofRef = useRef<HTMLElement>(null)
  const [frame, setFrame] = useState(0)
  const [paused, setPaused] = useState(false)
  const [suspended, setSuspended] = useState(false)
  const [sceneEpoch, setSceneEpoch] = useState(0)

  useEffect(() => {
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
    let visible = true
    let interval = 0
    const stop = () => { window.clearInterval(interval); interval = 0 }
    const start = () => {
      stop()
      if (paused || reducedMotion.matches || document.hidden || !visible) return
      interval = window.setInterval(
        () => setFrame((current) => (current + 1) % PROOF_FRAMES.length), 6800,
      )
    }
    const handleVisibility = () => {
      const nextSuspended = document.hidden || !visible
      setSuspended(nextSuspended)
      if (!nextSuspended && !paused && !reducedMotion.matches) {
        setSceneEpoch((current) => current + 1)
      }
      start()
    }
    const handleMotion = () => { if (reducedMotion.matches) setFrame(0); start() }
    const observer = new IntersectionObserver(([entry]) => {
      const wasVisible = visible
      visible = entry.isIntersecting
      const nextSuspended = document.hidden || !visible
      setSuspended(nextSuspended)
      if (!wasVisible && visible && !paused && !reducedMotion.matches) {
        setSceneEpoch((current) => current + 1)
      }
      start()
    }, { threshold: 0.2 })

    if (proofRef.current) observer.observe(proofRef.current)
    document.addEventListener('visibilitychange', handleVisibility)
    reducedMotion.addEventListener('change', handleMotion)
    start()
    return () => {
      stop(); observer.disconnect()
      document.removeEventListener('visibilitychange', handleVisibility)
      reducedMotion.removeEventListener('change', handleMotion)
    }
  }, [paused])

  const active = PROOF_FRAMES[frame]
  const togglePaused = () => {
    if (paused) setSceneEpoch((current) => current + 1)
    setPaused((current) => !current)
  }

  return <figure ref={proofRef} className="kinetic-proof" data-paused={paused}
                 data-suspended={suspended}
                 aria-labelledby="kinetic-proof-caption">
    <div className="kinetic-proof-stage">
      <button type="button" className="proof-motion-control" aria-pressed={paused}
              aria-label={paused ? 'Play proof' : 'Pause proof'}
              onClick={togglePaused}>
        {paused
          ? <Play size={14} strokeWidth={1.8} aria-hidden />
          : <Pause size={14} strokeWidth={1.8} aria-hidden />}
      </button>
      <div key={`${active.geometry}-${sceneEpoch}`} className="proof-scene">
        <svg className="proof-scene-drawing" viewBox="0 0 700 430" role="img"
             aria-label={`An illustrative line drawing of ${active.label}`}>
          <GeometryDrawing geometry={active.geometry} />
        </svg>
        <svg className="proof-scene-leaders" viewBox="0 0 700 430" aria-hidden>
          {active.nodes.map((node, index) => <g key={`${active.geometry}-${node.kind}-leader`}>
            <path className={`proof-leader proof-leader-${String.fromCharCode(97 + index)} proof-tone-${node.tone}`}
                  pathLength="1" d={node.leader} />
            <circle className={`proof-anchor proof-anchor-${String.fromCharCode(97 + index)} proof-tone-${node.tone}`}
                    cx={node.anchor[0]} cy={node.anchor[1]} r="5" />
          </g>)}
        </svg>
        {active.nodes.map((node, index) => <div key={`${active.geometry}-${node.kind}`}
          className={`proof-node proof-node-${String.fromCharCode(97 + index)} proof-node-${node.position} proof-tone-${node.tone}`}>
          <span className="proof-node-kind num">{node.kind}</span>
          <strong className="num">{node.value}</strong>
        </div>)}
      </div>
    </div>

    <figcaption id="kinetic-proof-caption" className="sr-only">
      An illustrative sequence of engineering evidence, intent, realization, and measured
      decisions attaching to changing CAD geometry.
    </figcaption>
  </figure>
}
