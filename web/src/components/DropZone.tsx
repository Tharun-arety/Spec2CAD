import { useRef, useState, type DragEvent } from 'react'
import { cn } from '../lib/cn'

/**
 * A compact file drop zone.
 *
 * Replaces the native "Choose File / No file chosen" control, which is the one
 * element on screen that cannot be styled and reads as unfinished next to
 * everything around it. Dropping and browsing both work, and once a file is
 * chosen the zone shows what was actually accepted -- name, size, and a
 * thumbnail for images -- rather than a filename alone.
 */

const KB = 1024

function humanSize(bytes: number): string {
  if (bytes < KB) return `${bytes} B`
  if (bytes < KB * KB) return `${(bytes / KB).toFixed(0)} kB`
  return `${(bytes / KB / KB).toFixed(1)} MB`
}

export function DropZone({
  label, hint, accept, file, onChange, disabled,
}: {
  label: string
  hint: string
  accept: string
  file: File | null
  onChange: (f: File | null) => void
  disabled?: boolean
}) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const [rejected, setRejected] = useState<string | null>(null)

  // Accept is a hint to the file picker but not enforced on drop, so dropped
  // files are checked here too rather than failing later in the pipeline.
  const matches = (f: File) => {
    const patterns = accept.split(',').map((a) => a.trim()).filter(Boolean)
    if (patterns.length === 0) return true
    return patterns.some((p) =>
      p.endsWith('/*') ? f.type.startsWith(p.slice(0, -1))
                       : p.startsWith('.') ? f.name.toLowerCase().endsWith(p.toLowerCase())
                                           : f.type === p)
  }

  const take = (f: File | null) => {
    if (!f) return
    if (!matches(f)) {
      setRejected(`${f.name} is not ${hint.toLowerCase()}`)
      return
    }
    setRejected(null)
    onChange(f)
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setOver(false)
    if (disabled) return
    take(e.dataTransfer.files?.[0] ?? null)
  }

  const preview = file && file.type.startsWith('image/')
    ? URL.createObjectURL(file)
    : null

  return (
    <div>
      <span className="mb-[5px] block text-[12.5px] font-medium text-c8">{label}</span>

      {file ? (
        <div className="flex items-center gap-[10px] rounded-[6px] border border-c4 bg-c0 p-[8px]">
          {preview ? (
            <img src={preview} alt=""
                 onLoad={(e) => URL.revokeObjectURL((e.target as HTMLImageElement).src)}
                 className="h-[34px] w-[34px] shrink-0 rounded-[4px] border border-c3 object-cover" />
          ) : (
            <span aria-hidden
                  className="num grid h-[34px] w-[34px] shrink-0 place-items-center rounded-[4px]
                             border border-c3 bg-c2 text-[10px] font-semibold text-c7">
              {(file.name.split('.').pop() ?? '?').slice(0, 4).toUpperCase()}
            </span>
          )}
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[12.5px] font-medium text-c9">{file.name}</span>
            <span className="num block text-[11.5px] text-c6">{humanSize(file.size)} · ready</span>
          </span>
          <span className="flex shrink-0 gap-[4px]">
            <button type="button" onClick={() => input.current?.click()} disabled={disabled}
                    className="cursor-pointer rounded-[4px] border border-c4 px-[7px] py-[2px]
                               text-[11.5px] text-c7 transition-colors duration-150
                               hover:border-c6 hover:text-c9">
              Replace
            </button>
            <button type="button" onClick={() => { onChange(null); setRejected(null) }}
                    aria-label={`Remove ${file.name}`} disabled={disabled}
                    className="cursor-pointer rounded-[4px] border border-c4 px-[7px] py-[2px]
                               text-[11.5px] text-c7 transition-colors duration-150
                               hover:border-danger hover:text-danger">
              Remove
            </button>
          </span>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => input.current?.click()}
          onDragOver={(e) => { e.preventDefault(); if (!disabled) setOver(true) }}
          onDragLeave={() => setOver(false)}
          onDrop={onDrop}
          disabled={disabled}
          className={cn(
            'flex w-full cursor-pointer flex-col items-center justify-center gap-[2px]',
            'rounded-[6px] border border-dashed px-[10px] py-[13px] text-center',
            'transition-colors duration-150',
            over ? 'border-accent bg-accent-wash' : 'border-c4 bg-c0 hover:border-c6',
            disabled && 'cursor-not-allowed opacity-60',
          )}
        >
          <span className="text-[12.5px] font-medium text-c8">Drop {hint} or browse</span>
          <span className="text-[11.5px] text-c6">{accept}</span>
        </button>
      )}

      {rejected && (
        <p role="alert" className="mt-[4px] text-[11.5px] text-danger">{rejected}</p>
      )}

      <input
        ref={input}
        type="file"
        accept={accept}
        className="sr-only"
        onChange={(e) => take(e.target.files?.[0] ?? null)}
      />
    </div>
  )
}
