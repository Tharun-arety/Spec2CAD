export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') return String(+value.toFixed(4))
  if (typeof value === 'object') {
    const encoded = JSON.stringify(value)
    return encoded.length > 140 ? `${encoded.slice(0, 137)}…` : encoded
  }
  return String(value)
}
