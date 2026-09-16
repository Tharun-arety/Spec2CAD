import type { CapabilityRegistry } from '../types'

const DISPLAY = (value: string) => value.split('_').join(' ')

export function CapabilityTags({
  ids, registry,
}: {
  ids: string[] | undefined
  registry: CapabilityRegistry | null
}) {
  if (!registry || !ids?.length) return null
  const records = new Map(registry.capabilities.map((item) => [item.id, item]))
  const resolved = ids.flatMap((id) => {
    const item = records.get(id)
    return item && item.implementation_maturity !== 'unavailable' ? [item] : []
  })
  if (!resolved.length) return null

  return (
    <ul aria-label="Capability scope" className="flex flex-wrap gap-[5px]">
      {resolved.map((item) => (
        <li key={item.id}
            className="inline-flex max-w-full items-center gap-[5px] rounded-[4px]
                       border border-c4 bg-c1 px-[6px] py-[2px] text-[10.5px] text-c7">
          <span className="whitespace-nowrap font-medium text-c8">{item.label}</span>
          <span className="whitespace-nowrap text-c6">
            {DISPLAY(item.implementation_maturity)} · {DISPLAY(item.integration)}
          </span>
        </li>
      ))}
    </ul>
  )
}
