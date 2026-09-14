import { useEffect, useMemo, useRef, useState } from 'react'
import {
  BookOpen, Bot, FileText, Image as ImageIcon, Paperclip, Play,
  RotateCcw, X,
} from 'lucide-react'
import { api } from '../api'
import { cn } from '../lib/cn'
import type { Evidence, RunState } from '../types'
import { Button, Mark, Num, Tip } from './ui'

interface SourceWorkspaceProps {
  busy: boolean
  replayMode: boolean
  visionAvailable: boolean
  state: RunState | null
  onDemo: () => void
  onCompile: (sketch: File | null, datasheet: File | null, instruction: string) => void
}

/**
 * The Sources editor: an agent composer with optional context attachments.
 *
 * Files are supporting context, not required form fields. A user can start from
 * one sentence, one document, or any combination and let the pipeline report
 * what it knows and what is still missing.
 */
export function SourceWorkspace({
  busy, replayMode, visionAvailable, state, onDemo, onCompile,
}: SourceWorkspaceProps) {
  const [sketch, setSketch] = useState<File | null>(null)
  const [datasheet, setDatasheet] = useState<File | null>(null)
  const [instruction, setInstruction] = useState('')
  const sketchInput = useRef<HTMLInputElement>(null)
  const datasheetInput = useRef<HTMLInputElement>(null)
  const canCompile = !replayMode && !busy && Boolean(
    sketch || datasheet || instruction.trim(),
  )

  const clear = () => {
    setSketch(null)
    setDatasheet(null)
    setInstruction('')
  }

  return (
    <section className="flex h-full min-h-0 flex-col bg-c0" aria-label="Source workspace">
      <EditorTabs
        tabs={[{ id: 'agent', label: 'Spec2CAD Agent', kind: 'agent' }]}
        active="agent"
        onSelect={() => {}}
      />

      <div className="min-h-0 flex-1 overflow-y-auto bg-c1 px-[21px] py-[34px]">
        <div className="mx-auto max-w-[720px]">
          <div className="flex gap-[13px]">
            <span className="grid h-[29px] w-[29px] shrink-0 place-items-center rounded-[6px]
                             border border-accent-line bg-accent-wash text-accent">
              <Bot size={16} strokeWidth={1.8} aria-hidden />
            </span>
            <div className="min-w-0">
              <h1 className="text-[17.8px] font-semibold tracking-[-0.02em] text-c9">
                Start with whatever you have
              </h1>
              <p className="mt-[5px] max-w-[610px] text-[13.5px] leading-relaxed text-c7">
                Describe the part, attach a sketch or datasheet, or combine them.
                Spec2CAD will extract the available evidence and mark missing inputs
                explicitly instead of blocking the run.
              </p>
            </div>
          </div>

          <div className="ml-[42px] mt-[21px] grid gap-[8px] sm:grid-cols-3">
            {[
              ['Instruction only', 'Extract dimensions and constraints from text.'],
              ['One document', 'Inspect a sketch or datasheet on its own.'],
              ['Mixed context', 'Reconcile any two or all three sources.'],
            ].map(([title, detail]) => (
              <div key={title} className="border-l-2 border-c4 pl-[10px]">
                <div className="text-[12.5px] font-medium text-c8">{title}</div>
                <div className="mt-[2px] text-[12px] leading-snug text-c6">{detail}</div>
              </div>
            ))}
          </div>

          {state && (
            <div className="ml-[42px] mt-[21px] border border-success-line bg-success-wash
                            px-[13px] py-[10px]">
              <div className="flex items-center gap-[8px]">
                <Mark state="pass" glyph>Evidence captured</Mark>
                <span className="num text-[12px] text-c7">
                  {state.evidence.length} observations · {state.revisions.length} revision
                  {state.revisions.length === 1 ? '' : 's'}
                </span>
              </div>
              <p className="mt-[4px] text-[12px] text-c7">
                Open Evidence to inspect each value in its source.
              </p>
            </div>
          )}
        </div>
      </div>

      <div className="border-t border-c3 bg-c0 px-[21px] py-[13px]">
        <div className="mx-auto mb-[8px] flex max-w-[760px] flex-wrap items-center gap-[10px]
                        rounded-[8px] border border-accent-line bg-accent-wash px-[11px] py-[9px]">
          <div className="min-w-[180px] flex-1">
            <div className="text-[12.5px] font-semibold text-c9">Recorded example</div>
            <p className="mt-[1px] text-[11.5px] leading-snug text-c7">
              Run the bundled sketch, motor datasheet and requirement.
            </p>
          </div>
          <Button intent="solid" size="sm" onClick={onDemo} disabled={busy}>
            <Play size={13} fill="currentColor" aria-hidden />
            {busy ? 'Compiling…' : 'Compile recorded example'}
          </Button>
        </div>

        <div className="mx-auto max-w-[760px] rounded-[10px] border border-c4 bg-c0
                        shadow-[var(--shadow-float)] focus-within:border-accent">
          <label htmlFor="source-instruction" className="sr-only">
            Describe what to generate
          </label>
          <textarea
            id="source-instruction"
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && canCompile) {
                onCompile(sketch, datasheet, instruction)
              }
            }}
            disabled={replayMode || busy}
            placeholder="Describe the part or paste a requirement…"
            className="min-h-[76px] w-full resize-y bg-transparent px-[13px] py-[10px]
                       text-[13.5px] leading-relaxed text-c9 outline-none
                       placeholder:text-c6 disabled:cursor-not-allowed"
          />

          {(sketch || datasheet) && (
            <div className="flex flex-wrap gap-[6px] border-t border-c3 px-[10px] py-[8px]">
              {sketch && (
                <AttachmentChip icon={ImageIcon} file={sketch} onRemove={() => setSketch(null)} />
              )}
              {datasheet && (
                <AttachmentChip icon={FileText} file={datasheet}
                                onRemove={() => setDatasheet(null)} />
              )}
            </div>
          )}

          <div className="flex items-center gap-[5px] border-t border-c3 px-[8px] py-[7px]">
            <Tip label={visionAvailable
              ? 'Attach a sketch image'
              : 'Sketch extraction needs a vision API key; text and datasheets still work'}>
              <button
                type="button"
                onClick={() => sketchInput.current?.click()}
                disabled={replayMode || busy || !visionAvailable}
                className="grid h-[29px] w-[29px] cursor-pointer place-items-center rounded-[5px]
                           text-c7 transition-colors hover:bg-c2 hover:text-c9
                           disabled:cursor-not-allowed disabled:opacity-40"
                aria-label="Attach sketch"
              >
                <ImageIcon size={15} strokeWidth={1.8} aria-hidden />
              </button>
            </Tip>
            <Tip label="Attach a component datasheet">
              <button
                type="button"
                onClick={() => datasheetInput.current?.click()}
                disabled={replayMode || busy}
                className="grid h-[29px] w-[29px] cursor-pointer place-items-center rounded-[5px]
                           text-c7 transition-colors hover:bg-c2 hover:text-c9
                           disabled:cursor-not-allowed disabled:opacity-40"
                aria-label="Attach datasheet"
              >
                <Paperclip size={15} strokeWidth={1.8} aria-hidden />
              </button>
            </Tip>
            {(sketch || datasheet || instruction) && (
              <Button intent="ghost" size="sm" onClick={clear} disabled={busy || replayMode}>
                <RotateCcw size={13} aria-hidden /> Reset
              </Button>
            )}
            <span className="ml-auto hidden text-[11.5px] text-c6 sm:inline">
              Ctrl Enter to compile
            </span>
            <Button
              intent="solid"
              size="sm"
              disabled={!canCompile}
              onClick={() => onCompile(sketch, datasheet, instruction)}
            >
              <Play size={13} fill="currentColor" aria-hidden />
              {busy ? 'Compiling…' : 'Compile'}
            </Button>
          </div>
        </div>
        {replayMode && (
          <p className="mx-auto mt-[8px] max-w-[760px] text-[12px] text-warn">
            Recorded replay cannot process new input. Use “Compile recorded example”
            above, or run against the local backend.
          </p>
        )}
      </div>

      <input ref={sketchInput} className="sr-only" type="file" accept="image/*"
             tabIndex={-1} aria-hidden="true"
             onChange={(event) => setSketch(event.target.files?.[0] ?? null)} />
      <input ref={datasheetInput} className="sr-only" type="file"
             accept="application/pdf,.pdf" tabIndex={-1} aria-hidden="true"
             onChange={(event) => setDatasheet(event.target.files?.[0] ?? null)} />
    </section>
  )
}

function AttachmentChip({
  icon: Icon, file, onRemove,
}: {
  icon: typeof FileText
  file: File
  onRemove: () => void
}) {
  return (
    <span className="inline-flex min-w-0 items-center gap-[6px] rounded-[5px] border
                     border-c4 bg-c1 px-[7px] py-[4px] text-[12px] text-c8">
      <Icon size={13} strokeWidth={1.8} className="shrink-0 text-c6" aria-hidden />
      <span className="max-w-[210px] truncate">{file.name}</span>
      <button type="button" onClick={onRemove} aria-label={`Remove ${file.name}`}
              className="grid h-[18px] w-[18px] cursor-pointer place-items-center rounded-[3px]
                         text-c6 hover:bg-c3 hover:text-c9">
        <X size={11} aria-hidden />
      </button>
    </span>
  )
}

interface EvidenceWorkbenchProps {
  state: RunState
  picked: Evidence | null
  onPick: (evidence: Evidence | null) => void
}

/** Main editor for source-backed evidence, with one tab per source document. */
export function EvidenceWorkbench({ state, picked, onPick }: EvidenceWorkbenchProps) {
  const sources = useMemo(() => {
    const map = new Map<string, { id: string; label: string; kind: string }>()
    for (const evidence of state.evidence) {
      if (!map.has(evidence.source.file)) {
        map.set(evidence.source.file, {
          id: evidence.source.file,
          label: evidence.source.file,
          kind: evidence.source.modality === 'engineering_rule' ? 'rule' : 'source',
        })
      }
    }
    return [...map.values()]
  }, [state.evidence])
  const [active, setActive] = useState(() => picked?.source.file ?? sources[0]?.id ?? '')

  useEffect(() => {
    if (picked) setActive(picked.source.file)
  }, [picked])

  const sourceEvidence = state.evidence.filter((e) => e.source.file === active)
  const selected = picked?.source.file === active ? picked : null
  const derived = sourceEvidence[0]?.source.modality === 'engineering_rule'
  const extension = active.split('.').pop()?.toLowerCase()

  const selectTab = (id: string) => {
    setActive(id)
    onPick(null)
  }

  if (!active) {
    return <div className="grid h-full place-items-center text-[13px] text-c6">No evidence yet.</div>
  }

  return (
    <section className="flex h-full min-h-0 flex-col bg-c0" aria-label="Evidence editor">
      <EditorTabs tabs={sources} active={active} onSelect={selectTab} />

      <div className="flex h-[34px] shrink-0 items-center gap-[6px] border-b border-c3
                      bg-c1 px-[13px] text-[11.5px] text-c6">
        <span>evidence</span><span>/</span><span className="text-c8">{active}</span>
        <span className="ml-auto num">{sourceEvidence.length} observation
          {sourceEvidence.length === 1 ? '' : 's'}</span>
      </div>

      <div className="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)_auto] bg-c2">
        <div className="relative min-h-0 overflow-auto p-[21px]">
          <div className="mx-auto flex h-full min-h-[260px] max-w-[920px] items-center
                          justify-center border border-c4 bg-c0 shadow-[var(--shadow-raised)]">
            {selected?.has_preview ? (
              <img
                key={selected.id}
                src={api.previewUrl(state.run_id, selected.id)}
                alt={`Highlighted source region for ${selected.target.replace(/_/g, ' ')}`}
                className="max-h-full max-w-full object-contain"
              />
            ) : derived ? (
              <div className="max-w-[540px] px-[34px] py-[55px] text-center">
                <BookOpen size={29} strokeWidth={1.5} className="mx-auto text-accent" aria-hidden />
                <h2 className="mt-[13px] text-[17.8px] font-semibold text-c9">{active}</h2>
                <p className="mt-[8px] text-[13px] leading-relaxed text-c7">
                  This value was derived from a cited engineering table, so there is no
                  rectangle in an uploaded document to highlight.
                </p>
              </div>
            ) : extension === 'png' || extension === 'jpg' || extension === 'jpeg' || extension === 'webp' ? (
              <img src={api.sourceUrl(state.run_id, active)} alt={active}
                   className="max-h-full max-w-full object-contain" />
            ) : (
              <iframe src={api.sourceUrl(state.run_id, active)} title={active}
                      className="h-full min-h-[420px] w-full border-0 bg-c0" />
            )}
          </div>
        </div>

        <div className="border-t border-c3 bg-c0">
          {selected ? (
            <>
              <div className="flex flex-wrap items-center gap-x-[21px] gap-y-[6px]
                              px-[13px] py-[10px]">
                <div className="min-w-[190px]">
                  <div className="text-[11px] text-c6">Selected evidence</div>
                  <div className="text-[13px] font-medium text-c9">
                    {selected.target.replace(/_/g, ' ')}
                  </div>
                </div>
                <Num value={selected.value} unit={selected.unit} strong className="text-[17.8px]" />
                <span className="text-[12px] text-c7">
                  confidence <span className="num text-c9">{selected.confidence.toFixed(2)}</span>
                </span>
                <span className="text-[12px] text-c7">
                  authority <span className="text-c9">{selected.authority}</span>
                </span>
                <Mark state={selected.is_fixture ? 'warn' : 'pass'} glyph>
                  {selected.extraction_method.replace(/_/g, ' ')}
                </Mark>
              </div>
              {selected.raw_text && (
                <div className="border-t border-c3 px-[13px] py-[8px] text-[12.5px] text-c7">
                  <span className="mr-[8px] text-c6">Source text</span>
                  “{selected.raw_text}”
                </div>
              )}
            </>
          ) : (
            <div className="px-[13px] py-[11px] text-[12.5px] text-c7">
              Select a spec in the Evidence list to highlight where it was recorded.
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

function EditorTabs({
  tabs, active, onSelect,
}: {
  tabs: { id: string; label: string; kind: string }[]
  active: string
  onSelect: (id: string) => void
}) {
  return (
    <div className="flex h-[37px] shrink-0 overflow-x-auto border-b border-c3 bg-c1"
         role="tablist" aria-label="Open editors">
      {tabs.map((tab) => {
        const selected = tab.id === active
        const lower = tab.label.toLowerCase()
        const Icon = tab.kind === 'agent' ? Bot : tab.kind === 'rule' ? BookOpen
          : lower.endsWith('.pdf') || lower.endsWith('.txt') ? FileText : ImageIcon
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => onSelect(tab.id)}
            className={cn(
              'relative flex h-full min-w-[132px] max-w-[230px] cursor-pointer items-center',
              'gap-[7px] border-r border-c3 px-[11px] text-[12px] transition-colors',
              selected ? 'bg-c0 text-c9' : 'bg-c1 text-c7 hover:bg-c2 hover:text-c9',
            )}
          >
            <Icon size={13} strokeWidth={1.7} className="shrink-0 text-c6" aria-hidden />
            <span className="truncate">{tab.label}</span>
            {selected && <span className="absolute inset-x-0 top-0 h-[2px] bg-accent" />}
          </button>
        )
      })}
    </div>
  )
}
