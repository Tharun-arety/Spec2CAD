import { Component, type ErrorInfo, type ReactNode } from 'react'

/**
 * Contains a render failure to one subtree.
 *
 * Scoped deliberately tight: this wraps the 3D viewport and nothing else. A
 * viewer that cannot get a WebGL context is a degraded panel, not a broken
 * application, and the evidence, intent, validation and release panels must all
 * keep working around it.
 *
 * Only class components can catch render errors, which is why this is the one
 * class component in the codebase.
 */
export class ErrorBoundary extends Component<
  { children: ReactNode; fallback: (error: Error) => ReactNode; label?: string },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Kept: a silently swallowed viewer failure is much harder to diagnose than
    // a noisy one, and this never reaches the user's screen.
    console.error(`[${this.props.label ?? 'ErrorBoundary'}]`, error, info.componentStack)
  }

  render() {
    if (this.state.error) return this.props.fallback(this.state.error)
    return this.props.children
  }
}
