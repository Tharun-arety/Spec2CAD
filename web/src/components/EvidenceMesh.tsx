import { useEffect, useRef } from 'react'

type Point = { x: number; y: number }

const GRAPHITE = '161, 170, 160'
const ORANGE = '#ef6a3b'
const CYAN = '#63c9c2'

export function EvidenceMesh() {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const context = canvas.getContext('2d')
    if (!context) return

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
    let frame = 0
    let lastFrame = 0

    const draw = (time: number) => {
      const width = canvas.clientWidth
      const height = canvas.clientHeight
      const ratio = Math.min(window.devicePixelRatio || 1, 1.5)
      const targetWidth = Math.round(width * ratio)
      const targetHeight = Math.round(height * ratio)
      if (canvas.width !== targetWidth || canvas.height !== targetHeight) {
        canvas.width = targetWidth
        canvas.height = targetHeight
      }

      context.setTransform(ratio, 0, 0, ratio, 0, 0)
      context.clearRect(0, 0, width, height)

      const columns = width < 700 ? 22 : 36
      const rows = height < 700 ? 14 : 19
      const phase = reducedMotion.matches ? 0 : time * 0.00012
      const points: Point[][] = []

      for (let row = 0; row < rows; row += 1) {
        const v = row / (rows - 1)
        const line: Point[] = []
        for (let column = 0; column < columns; column += 1) {
          const u = column / (columns - 1)
          const spread = 0.72 + v * 0.48
          const x = width * 0.5 + (u - 0.5) * width * spread * 1.22
          const baseY = height * 0.39 + Math.pow(v, 1.48) * height * 0.69
          const longWave = Math.sin(u * 12.4 + phase * 7 + v * 2.2) * (8 + v * 31)
          const fineWave = Math.cos(u * 27 - phase * 4.5 - v * 5) * (3 + v * 11)
          const intentRidge = -Math.exp(-Math.pow(u - 0.57, 2) / 0.017) * (12 + v * 31)
          const evidenceRidge = Math.exp(-Math.pow(u - 0.2, 2) / 0.022) * (5 + v * 18)
          line.push({ x, y: baseY + longWave + fineWave + intentRidge + evidenceRidge })
        }
        points.push(line)
      }

      context.lineWidth = 0.75
      for (let row = 0; row < rows; row += 1) {
        const alpha = 0.1 + (row / rows) * 0.2
        context.strokeStyle = `rgba(${GRAPHITE}, ${alpha})`
        context.beginPath()
        points[row].forEach((point, index) => {
          if (index === 0) context.moveTo(point.x, point.y)
          else context.lineTo(point.x, point.y)
        })
        context.stroke()
      }

      for (let column = 0; column < columns; column += 1) {
        context.strokeStyle = `rgba(${GRAPHITE}, ${0.08 + (column % 4 === 0 ? 0.09 : 0)})`
        context.beginPath()
        points.forEach((line, index) => {
          const point = line[column]
          if (index === 0) context.moveTo(point.x, point.y)
          else context.lineTo(point.x, point.y)
        })
        context.stroke()
      }

      const drawMarker = (point: Point, label: string, color: string, offset: number) => {
        context.save()
        context.translate(point.x, point.y)
        context.strokeStyle = color
        context.fillStyle = color
        context.lineWidth = 1.2
        for (let ring = 0; ring < 3; ring += 1) {
          const pulse = reducedMotion.matches ? 0 : Math.sin(phase * 16 + offset + ring) * 1.5
          context.globalAlpha = 0.8 - ring * 0.2
          context.beginPath()
          context.ellipse(0, -ring * 9, 10 + ring * 5 + pulse, 3.2 + ring, 0, 0, Math.PI * 2)
          context.stroke()
        }
        context.globalAlpha = 1
        context.beginPath()
        context.arc(0, 3, 2.5, 0, Math.PI * 2)
        context.fill()
        context.font = '11px "IBM Plex Mono", monospace'
        context.textAlign = 'center'
        context.fillText(label, 0, -35)
        context.restore()
      }

      if (width >= 1024) {
        drawMarker(points[10][8], 'evidence', CYAN, 0)
        drawMarker(points[8][19], 'intent', ORANGE, 1.8)
        drawMarker(points[11][29], 'measured CAD', CYAN, 3.4)
      }
    }

    const animate = (time: number) => {
      if (time - lastFrame > 32) {
        draw(time)
        lastFrame = time
      }
      if (reducedMotion.matches) frame = 0
      else frame = window.requestAnimationFrame(animate)
    }

    const handleMotionChange = () => {
      window.cancelAnimationFrame(frame)
      frame = 0
      if (reducedMotion.matches) draw(0)
      else frame = window.requestAnimationFrame(animate)
    }

    const resizeObserver = new ResizeObserver(() => draw(performance.now()))
    resizeObserver.observe(canvas)
    reducedMotion.addEventListener('change', handleMotionChange)
    if (reducedMotion.matches) draw(0)
    else frame = window.requestAnimationFrame(animate)

    return () => {
      resizeObserver.disconnect()
      reducedMotion.removeEventListener('change', handleMotionChange)
      window.cancelAnimationFrame(frame)
    }
  }, [])

  return (
    <>
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" aria-hidden />
      <span className="sr-only">
        A decorative evidence mesh traces source observations through editable intent to measured CAD.
      </span>
    </>
  )
}
