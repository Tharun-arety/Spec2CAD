/**
 * WebGL capability probe.
 *
 * Three.js throws from the WebGLRenderer constructor when no context can be
 * created. That happens inside an effect, so React unwinds the whole tree and
 * the app goes white -- a viewer problem taking down the shell. Corporate
 * laptops, remote desktops, VMs and headless/automated browsers all hit this.
 *
 * So availability is decided BEFORE three.js is imported, and the result is
 * cached: creating probe contexts is not free, and browsers cap how many live
 * contexts a page may hold.
 */

let cached: boolean | null = null

export function hasWebGL(): boolean {
  if (cached !== null) return cached
  cached = probe()
  return cached
}

function probe(): boolean {
  if (typeof document === 'undefined') return false
  try {
    const canvas = document.createElement('canvas')
    const gl =
      canvas.getContext('webgl2') ??
      canvas.getContext('webgl') ??
      canvas.getContext('experimental-webgl')
    if (!gl) return false

    // Releasing the probe context explicitly. Without this the canvas holds a
    // context until it is garbage collected, and the real viewer may be refused
    // one on browsers with a tight per-page limit.
    const lose = (gl as WebGLRenderingContext)
      .getExtension('WEBGL_lose_context')
    lose?.loseContext()
    return true
  } catch {
    // Some environments throw rather than returning null.
    return false
  }
}
