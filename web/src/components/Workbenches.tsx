import { useEffect, useMemo, useRef, useState } from 'react'
import {
  BookOpen, Bot, FileText, Image as ImageIcon, Paperclip, Play,
  RotateCcw, X,
} from 'lucide-react'
import { api } from '../api'
import { cn } from '../lib/cn'
import type { ReplayCatalog } from '../replay'
import type { CapabilityRegistry, Evidence, RunState } from '../types'
import { Button, Mark, Num, Tip } from './ui'
import { CapabilityTags } from './CapabilityTags'

interface SourceWorkspaceProps {
  busy: boolean
  replayMode: boolean
  visionAvailable: boolean
  state: RunState | null
  replayCatalog: ReplayCatalog | null
  capabilityRegistry: CapabilityRegistry | null
  activeScenarioId: string | null
  onDemo: (scenarioId: string) => void
  onCompile: (sketch: File | null, datasheet: File | null, instruction: string) => void
  onContinue: (message: string) => void
  onNew: () => void
}

/**
 * The Sources editor: an agent composer with optional context attachments.
 *
 * Files are supporting context, not required form fields. A user can start from
 * one sentence, one document, or any combination and let the pipeline report
 * what it knows and what is still missing.
 */
export function SourceWorkspace({
  busy, replayMode, visionAvailable, state, replayCatalog, activeScenarioId,
  capabilityRegistry,
  onDemo, onCompile, onContinue, onNew,
}: SourceWorkspaceProps) {
  const [sketch, setSketch] = useState<File | null>(null)
  const [datasheet, setDatasheet] = useState<File | null>(null)
  const [instruction, setInstruction] = useState('')
  const sketchInput = useRef<HTMLInputElement>(null)
  const datasheetInput = useRef<HTMLInputElement>(null)
  const instructionInput = useRef<HTMLTextAreaElement>(null)
  const hasDraft = Boolean(sketch || datasheet || instruction.trim())
  const latestRevision = state?.revisions.find((revision) =>
    revision.revision === state.latest_revision)
  const missingForBuild = latestRevision
    ? ['plate_width', 'plate_height', 'plate_thickness'].filter(
        (name) => latestRevision.parameters[name]?.value == null,
      )
    : []
  const clarificationQuestions = state?.clarification_questions ?? []
  const messages = state?.messages ?? []
  const continuing = messages.length > 0 && !sketch && !datasheet
  const canCompile = !replayMode && !busy && Boolean(
    sketch || datasheet || instruction.trim(),
  )

  const submit = () => {
    if (!canCompile) return
    if (continuing) onContinue(instruction.trim())
    else onCompile(sketch, datasheet, instruction)
    setInstruction('')
  }

  useEffect(() => {
    if (clarificationQuestions.length > 0) {
      requestAnimationFrame(() => instructionInput.current?.focus())
    }
  }, [clarificationQuestions.length])

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
            <span className="grid h-[34px] w-[34px] shrink-0 place-items-center rounded-[7px]
                             border border-accent-line bg-accent-wash text-accent">
              <Bot size={17} strokeWidth={1.8} aria-hidden />
            </span>
            <div className="min-w-0">
              <h1 className="text-[25px] font-semibold leading-[1.12] tracking-[-0.03em] text-c9">
                Start with whatever you have
              </h1>
              <p className="mt-[8px] max-w-[610px] text-[14px] leading-[1.75] text-c7">
                Describe the part, attach a sketch or datasheet, or combine them.
                Spec2CAD will extract the available evidence and mark missing inputs
                explicitly instead of blocking the run.
              </p>
            </div>
          </div>

          {messages.length > 0 && (
            <div className="ml-[47px] mt-[24px] space-y-[12px]" aria-live="polite"
                 aria-label="Engineering conversation">
              <div className="flex items-center justify-between">
                <span className="text-[12px] font-semibold text-c7">Conversation</span>
                <Button intent="ghost" size="sm" onClick={onNew} disabled={busy}>
                  Start new design
                </Button>
              </div>
              {messages.map((message) => (
                <article key={message.id} className={cn(
                  'max-w-[88%] rounded-[10px] border px-[13px] py-[10px]',
                  message.role === 'user'
                    ? 'ml-auto border-accent-line bg-accent-wash'
                    : message.kind === 'clarification'
                      ? 'border-warn-line bg-warn-wash'
                      : 'border-c3 bg-c0',
                )}>
                  <div className="mb-[4px] text-[11px] font-semibold uppercase tracking-[0.08em] text-c6">
                    {message.role === 'user' ? 'You' : 'Spec2CAD'}
                  </div>
                  <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-c9">
                    {message.content}
                  </p>
                </article>
              ))}
              {busy && (
                <div role="status" className="text-[12.5px] text-c6">
                  Spec2CAD is interpreting your answer…
                </div>
              )}
            </div>
          )}

          {!replayMode && (
          <div className="ml-[47px] mt-[21px] grid gap-[8px] sm:grid-cols-3">
            <button
              type="button"
              onClick={() => {
                setInstruction('Create a manufacturable part from this requirement: ')
                requestAnimationFrame(() => instructionInput.current?.focus())
              }}
              disabled={replayMode || busy}
              className="group rounded-[6px] border border-c3 bg-c0 px-[11px] py-[10px]
                         text-left transition-colors hover:border-accent-line hover:bg-accent-wash
                         disabled:cursor-not-allowed disabled:opacity-40"
            >
              <span className="block text-[13px] font-medium text-c8 group-hover:text-accent">
                Describe a part
              </span>
              <span className="mt-[3px] block text-[12px] leading-snug text-c6">
                Start with dimensions and constraints.
              </span>
            </button>
            <button
              type="button"
              onClick={() => datasheetInput.current?.click()}
              disabled={replayMode || busy}
              className="group rounded-[6px] border border-c3 bg-c0 px-[11px] py-[10px]
                         text-left transition-colors hover:border-accent-line hover:bg-accent-wash
                         disabled:cursor-not-allowed disabled:opacity-40"
            >
              <span className="block text-[13px] font-medium text-c8 group-hover:text-accent">
                Open a document
              </span>
              <span className="mt-[3px] block text-[12px] leading-snug text-c6">
                Inspect one datasheet on its own.
              </span>
            </button>
            <button
              type="button"
              onClick={() => {
                setInstruction('Reconcile the attached sources, resolve matching dimensions, and flag any missing or conflicting inputs.')
                requestAnimationFrame(() => instructionInput.current?.focus())
              }}
              disabled={replayMode || busy}
              className="group rounded-[6px] border border-c3 bg-c0 px-[11px] py-[10px]
                         text-left transition-colors hover:border-accent-line hover:bg-accent-wash
                         disabled:cursor-not-allowed disabled:opacity-40"
            >
              <span className="block text-[13px] font-medium text-c8 group-hover:text-accent">
                Combine sources
              </span>
              <span className="mt-[3px] block text-[12px] leading-snug text-c6">
                Reconcile any two or all three inputs.
              </span>
            </button>
          </div>
          )}

          {replayCatalog && (
            <section className="ml-[47px] mt-[26px]" aria-labelledby="recorded-showcase-title">
              <div className="flex items-end justify-between gap-[13px] border-b border-c3 pb-[9px]">
                <div>
                  <h2 id="recorded-showcase-title" className="text-[15px] font-semibold text-c9">
                    Five evidence conditions
                  </h2>
                  <p className="mt-[2px] text-[12px] leading-relaxed text-c6">
                    From language alone to full multimodal fusion—each recording tests a different kind of uncertainty.
                  </p>
                </div>
                <span className="num shrink-0 text-[11px] text-c6">
                  {replayCatalog.scenarios.length} scenarios
                </span>
              </div>

              <div className="mt-[9px] grid gap-[8px] sm:grid-cols-2">
                {replayCatalog.scenarios.map((scenario, index) => {
                  const active = activeScenarioId === scenario.id && state?.run_id === `recorded-${scenario.id}`
                  const featured = index === 0
                  return (
                    <article
                      key={scenario.id}
                      className={cn(
                        'group relative flex min-h-[142px] flex-col overflow-hidden rounded-[7px]',
                        'border bg-c0 px-[13px] py-[12px] shadow-[var(--shadow-raised)]',
                        'transition-colors duration-150',
                        featured && 'sm:col-span-2 sm:min-h-[126px]',
                        active
                          ? 'border-accent bg-accent-wash'
                          : 'border-c3 hover:border-c5 hover:bg-c2',
                      )}
                    >
                      <div className="flex items-start justify-between gap-[13px]">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-[5px]">
                            <span className={cn(
                              'num mr-[3px] text-[11px] font-semibold',
                              active ? 'text-accent' : 'text-c6',
                            )}>{scenario.step}</span>
                            {scenario.inputs.map((input) => (
                              <span key={input}
                                    className="rounded-[3px] border border-c4 bg-c1 px-[5px] py-[1px]
                                               text-[10px] font-medium text-c7">
                                {input === 'document' ? 'technical document' : input}
                              </span>
                            ))}
                          </div>
                          <h3 className="mt-[2px] text-[14px] font-semibold text-c9">
                            {scenario.title}
                          </h3>
                          <div className="mt-[2px] text-[11px] font-medium text-accent">
                            {scenario.proof}
                          </div>
                        </div>
                        {active && <Mark state="pass" glyph>Loaded</Mark>}
                      </div>
                      <p className={cn(
                        'mt-[6px] text-[12px] leading-[1.55] text-c7',
                        featured && 'sm:max-w-[590px]',
                      )}>
                        {scenario.description}
                      </p>
                      <div className="mt-[7px] border-l-2 border-warn-line pl-[7px]
                                      text-[10.5px] leading-relaxed text-c6">
                        {scenario.uncertainty}
                      </div>
                      <div className="mt-auto flex flex-wrap items-end gap-x-[8px] gap-y-[7px] pt-[10px]">
                        <div className="min-w-[220px] flex-1">
                          <CapabilityTags ids={scenario.capability_ids} registry={capabilityRegistry} />
                          <div className="num mt-[6px] text-[10px] text-c6">
                            CAD construction · {scenario.operation}
                          </div>
                        </div>
                        <Button
                          intent={active ? 'outline' : featured ? 'solid' : 'outline'}
                          size="sm"
                          onClick={() => onDemo(scenario.id)}
                          disabled={busy}
                        >
                          <Play size={12} fill="currentColor" aria-hidden />
                          {busy && active ? 'Loading…' : active ? 'Replay again' : 'Open run'}
                        </Button>
                      </div>
                    </article>
                  )
                })}
              </div>
            </section>
          )}

          {state && latestRevision?.build_error && clarificationQuestions.length > 0 && (
            <div role="status" aria-live="polite"
                 className="ml-[47px] mt-[21px] border border-warn-line bg-warn-wash
                            px-[13px] py-[11px]">
              <div className="flex items-start gap-[9px]">
                <Bot size={16} strokeWidth={1.8} className="mt-[2px] shrink-0 text-warn" aria-hidden />
                <div className="min-w-0">
                  <div className="text-[13px] font-semibold text-c9">
                    I need your engineering decision before I plan the CAD.
                  </div>
                  <ul className="mt-[5px] space-y-[4px] text-[12.5px] leading-relaxed text-c8">
                    {clarificationQuestions.map((question) => (
                      <li key={question}>{question}</li>
                    ))}
                  </ul>
                  <p className="mt-[6px] text-[12px] leading-relaxed text-c7">
                    Answer below. The conversation and extracted facts stay attached to this run.
                  </p>
                  <button
                    type="button"
                    onClick={() => instructionInput.current?.focus()}
                    className="mt-[7px] cursor-pointer text-[12.5px] font-medium text-warn
                               underline decoration-warn/50 underline-offset-[3px]"
                  >
                    Answer in the prompt
                  </button>
                </div>
              </div>
            </div>
          )}

          {state && latestRevision?.build_error && clarificationQuestions.length === 0 && (
            <div role="status" className="ml-[47px] mt-[21px] border border-warn-line bg-warn-wash
                                      px-[13px] py-[11px]">
              <div className="flex items-start gap-[9px]">
                <Bot size={16} strokeWidth={1.8} className="mt-[2px] shrink-0 text-warn" aria-hidden />
                <div>
                  <div className="text-[13px] font-semibold text-c9">
                    I need {missingForBuild.length ? missingForBuild.map(humanise).join(' and ') : 'more geometry'} before I can build this.
                  </div>
                  <p className="mt-[3px] text-[12.5px] leading-relaxed text-c7">
                    I kept the {state.evidence.length} facts I could extract. Add the missing
                    dimensions to your prompt and compile again.
                  </p>
                  <button
                    type="button"
                    onClick={() => instructionInput.current?.focus()}
                    className="mt-[7px] cursor-pointer text-[12.5px] font-medium text-warn
                               underline decoration-warn/50 underline-offset-[3px]"
                  >
                    Continue the prompt
                  </button>
                </div>
              </div>
            </div>
          )}

          {state && latestRevision && !latestRevision.build_error && (
            <div className="ml-[47px] mt-[21px] border border-success-line bg-success-wash
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
        <div className="mx-auto max-w-[760px] rounded-[10px] border border-c4 bg-c0
                        shadow-[var(--shadow-float)] focus-within:border-accent">
          <label htmlFor="source-instruction" className="sr-only">
            Describe what to generate
          </label>
          <textarea
            ref={instructionInput}
            id="source-instruction"
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && canCompile) {
                submit()
              }
            }}
            disabled={replayMode || busy}
            placeholder={clarificationQuestions.length > 0
              ? 'Answer the clarification…'
              : continuing ? 'Refine this design…' : 'Describe the part or paste a requirement…'}
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
              onClick={submit}
            >
              <Play size={13} fill="currentColor" aria-hidden />
              {busy ? 'Interpreting…' : continuing ? 'Send' : 'Compile'}
            </Button>
          </div>
        </div>
        {replayMode && (
          <p className="mx-auto mt-[8px] max-w-[760px] text-[12px] text-warn">
            Recorded replay cannot process new input. Choose any showcase run above,
            or run against the local backend to compile your own sources.
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
  mode?: 'sources' | 'evidence'
}

/** Main editor for source-backed evidence, with one tab per source document. */
export function EvidenceWorkbench({ state, picked, onPick, mode = 'evidence' }: EvidenceWorkbenchProps) {
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
    <section className="flex h-full min-h-0 flex-col bg-c0"
             aria-label={mode === 'sources' ? 'Source explorer' : 'Evidence editor'}>
      <EditorTabs tabs={sources} active={active} onSelect={selectTab} />

      <div className="flex h-[34px] shrink-0 items-center gap-[6px] border-b border-c3
                      bg-c1 px-[13px] text-[11.5px] text-c6">
        <span>{mode}</span><span>/</span>
        <span className="min-w-0 truncate text-c8" title={active}>{active}</span>
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
            ) : extension === 'txt' ? (
              <TextSource
                url={api.sourceUrl(state.run_id, active)}
                label={active}
                highlight={selected?.raw_text}
              />
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
        const displayLabel = compactTabLabel(tab.label)
        return (
          <Tip key={tab.id} label={tab.label} side="bottom">
            <button
              type="button"
              role="tab"
              aria-selected={selected}
              aria-label={tab.label}
              onClick={() => onSelect(tab.id)}
              className={cn(
                'relative flex h-full min-w-[118px] max-w-[210px] cursor-pointer items-center',
                'gap-[7px] border-r border-c3 px-[11px] text-[12.5px] transition-colors',
                selected ? 'bg-c0 text-c9' : 'bg-c1 text-c7 hover:bg-c2 hover:text-c9',
              )}
            >
              <Icon size={13} strokeWidth={1.7} className="shrink-0 text-c6" aria-hidden />
              <span className="truncate">{displayLabel}</span>
              {selected && <span className="absolute inset-x-0 top-0 h-[2px] bg-accent" />}
            </button>
          </Tip>
        )
      })}
    </div>
  )
}

function compactTabLabel(label: string) {
  if (label.length <= 24) return label
  const dot = label.lastIndexOf('.')
  const extension = dot > 0 ? label.slice(dot) : ''
  const base = dot > 0 ? label.slice(0, dot) : label
  return `${base.slice(0, 12)}…${base.slice(-5)}${extension}`
}

function humanise(value: string) {
  return value.replace(/_/g, ' ')
}

function TextSource({
  url, label, highlight,
}: {
  url: string
  label: string
  highlight?: string | null
}) {
  const [content, setContent] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    setContent(null)
    setFailed(false)
    fetch(url, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`Unable to open ${label}`)
        return response.text()
      })
      .then(setContent)
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return
        setFailed(true)
      })
    return () => controller.abort()
  }, [label, url])

  if (failed) {
    return <p className="px-[21px] text-[13px] text-danger">Unable to display {label}.</p>
  }
  if (content == null) {
    return <p className="px-[21px] text-[13px] text-c6">Loading {label}…</p>
  }

  const needle = highlight?.trim() ?? ''
  const start = needle ? content.toLowerCase().indexOf(needle.toLowerCase()) : -1

  return (
    <pre className="h-full w-full overflow-auto whitespace-pre-wrap p-[34px] font-sans
                    text-[14px] leading-[1.8] text-c8">
      {start >= 0 ? (
        <>
          {content.slice(0, start)}
          <mark className="rounded-[3px] bg-accent/20 px-[2px] text-accent
                           outline outline-1 outline-accent-line">
            {content.slice(start, start + needle.length)}
          </mark>
          {content.slice(start + needle.length)}
        </>
      ) : content}
    </pre>
  )
}
