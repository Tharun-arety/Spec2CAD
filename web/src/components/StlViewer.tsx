import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'

interface Props {
  url: string
}

export function StlViewer({ url }: Props) {
  const host = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = host.current
    if (!el) return

    const scene = new THREE.Scene()
    scene.background = null   // the dotted grid behind it shows through

    const camera = new THREE.PerspectiveCamera(
      42, el.clientWidth / el.clientHeight, 0.1, 5000,
    )
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    renderer.setPixelRatio(window.devicePixelRatio)
    renderer.setSize(el.clientWidth, el.clientHeight)
    el.appendChild(renderer.domElement)

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true

    scene.add(new THREE.AmbientLight(0xffffff, 0.82))
    const key = new THREE.DirectionalLight(0xffffff, 1.5)
    key.position.set(90, 120, 140)
    scene.add(key)
    const fill = new THREE.DirectionalLight(0xe8ecf5, 0.55)
    fill.position.set(-110, -70, -90)
    scene.add(fill)

    let mesh: THREE.Mesh | null = null
    let frame = 0
    let disposed = false

    new STLLoader().load(
      url,
      (geometry) => {
        if (disposed) return
        geometry.computeVertexNormals()
        geometry.center()
        mesh = new THREE.Mesh(
          geometry,
          new THREE.MeshStandardMaterial({
            color: 0xdfe1e6, metalness: 0.14, roughness: 0.55,
            flatShading: false,
          }),
        )
        // CAD Z-up -> viewer Y-up
        mesh.rotation.x = -Math.PI / 2
        scene.add(mesh)

        const edges = new THREE.LineSegments(
          new THREE.EdgesGeometry(geometry, 24),
          new THREE.LineBasicMaterial({ color: 0x3a3f4a, transparent: true, opacity: 0.72 }),
        )
        edges.rotation.x = -Math.PI / 2
        scene.add(edges)

        geometry.computeBoundingSphere()
        const r = geometry.boundingSphere?.radius ?? 50
        camera.position.set(r * 1.5, r * 1.35, r * 1.9)
        camera.lookAt(0, 0, 0)
        controls.update()
      },
      undefined,
      (err) => console.error('STL load failed', err),
    )

    const animate = () => {
      frame = requestAnimationFrame(animate)
      controls.update()
      renderer.render(scene, camera)
    }
    animate()

    const onResize = () => {
      if (!el.clientWidth) return
      camera.aspect = el.clientWidth / el.clientHeight
      camera.updateProjectionMatrix()
      renderer.setSize(el.clientWidth, el.clientHeight)
    }
    window.addEventListener('resize', onResize)

    return () => {
      disposed = true
      cancelAnimationFrame(frame)
      window.removeEventListener('resize', onResize)
      controls.dispose()
      renderer.dispose()
      mesh?.geometry.dispose()
      if (renderer.domElement.parentNode === el) el.removeChild(renderer.domElement)
    }
  }, [url])

  return <div ref={host} className="h-full w-full" />
}
