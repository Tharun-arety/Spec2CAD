import { useEffect, useRef, useState } from 'react'
import {
  Bot, FileText, Image as ImageIcon, KeyRound, Paperclip, Play, Plus,
  RotateCcw, X,
} from 'lucide-react'
import type { ModelConnectionInput } from '../api'
import type { RunState } from '../types'
import { cn } from '../lib/cn'
import {
  isOwnConnectionReady, modelConnectionInput, type ModelConnectionSettings,
} from '../lib/modelConnection'
import { Button, Tip } from './ui'
import { ModelConnectionFields } from './ModelConnectionFields'

interface AgentPanelProps {
  busy: boolean
  replayMode: boolean
  visionAvailable: boolean
  state: RunState | null
  modelSettings: ModelConnectionSettings
  onModelSettingsChange: (settings: ModelConnectionSettings) => void
  onCompile: (
    sketch: File | null,
    datasheet: File | null,
    instruction: string,
    connection: ModelConnectionInput | null,
  ) => Promise<boolean>
  onContinue: (
    message: string, connection: ModelConnectionInput | null,
  ) => Promise<boolean>
  onNew: () => void
}

/** Persistent conversation surface shared by every engineering stage. */
export function AgentPanel({
  busy, replayMode, visionAvailable, state, modelSettings, onModelSettingsChange,
  onCompile, onContinue, onNew,
}: AgentPanelProps) {
  const [sketch, setSketch] = useState<File | null>(null)
  const [datasheet, setDatasheet] = useState<File | null>(null)
  const [instruction, setInstruction] = useState('')
  const [modelSettingsOpen, setModelSettingsOpen] = useState(false)
  const sketchInput = useRef<HTMLInputElement>(null)
  const datasheetInput = useRef<HTMLInputElement>(null)
  const instructionInput = useRef<HTMLTextAreaElement>(null)
  const threadEnd = useRef<HTMLDivElement>(null)
  const messages = state?.messages ?? []
  const clarificationQuestions = state?.clarification_questions ?? []
  const continuing = messages.length > 0 && !sketch && !datasheet
  const ownConnectionReady = isOwnConnectionReady(modelSettings)
  const connectionReady = modelSettings.mode === 'server' || ownConnectionReady
  const effectiveVisionAvailable = visionAvailable || (
    modelSettings.mode === 'own' && ownConnectionReady
  )
  const canSend = !replayMode && !busy && connectionReady
    && Boolean(sketch || datasheet || instruction.trim())

  useEffect(() => {
    threadEnd.current?.scrollIntoView({ block: 'nearest' })
  }, [messages.length, busy])

  useEffect(() => {
    if (clarificationQuestions.length > 0 && !replayMode) {
      requestAnimationFrame(() => instructionInput.current?.focus())
    }
  }, [clarificationQuestions.length, replayMode])

  const submit = async () => {
    if (!canSend) return
    const connection = modelConnectionInput(modelSettings)
    const succeeded = continuing
      ? await onContinue(instruction.trim(), connection)
      : await onCompile(sketch, datasheet, instruction.trim(), connection)
    if (succeeded) clear()
  }

  const clear = () => {
    setSketch(null)
    setDatasheet(null)
    setInstruction('')
  }

  return (
    <aside className="agent-panel chrome-grain flex min-h-0 shrink-0 flex-col border-l border-c3 bg-c0"
           aria-label="Agent conversation">
      <header className="flex h-[41px] shrink-0 items-center gap-[8px] border-b border-c3 px-[11px]">
        <span className="grid h-[25px] w-[25px] place-items-center rounded-[2px]
                         border border-observed-line bg-observed-wash text-observed">
          <Bot size={15} strokeWidth={1.8} aria-hidden />
        </span>
        <div className="min-w-0">
          <h2 className="text-[13px] font-semibold text-c9">Agent conversation</h2>
          <p className="text-[10.5px] text-c6">
            {replayMode ? 'Recorded actions' : 'Connected to the design pipeline'}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setModelSettingsOpen((open) => !open)}
          disabled={replayMode || busy}
          aria-expanded={modelSettingsOpen}
          aria-controls="model-connection-settings"
          aria-label={`Model connection: ${modelSettings.mode === 'own' ? 'Own API' : 'Demo access'}`}
          title={modelSettings.mode === 'own' ? 'Own API' : 'Demo access'}
          className="ml-auto grid h-[27px] w-[27px] cursor-pointer place-items-center rounded-[2px]
                     border border-c4 bg-c1 text-[11px] font-medium text-c7
                     transition-colors hover:border-c6 hover:text-c9 disabled:cursor-not-allowed
                     disabled:opacity-40"
        >
          <KeyRound size={12} strokeWidth={1.8} aria-hidden />
        </button>
        {state && (
          <Tip label="Start a new design">
            <button type="button" onClick={onNew} disabled={busy}
                    aria-label="Start a new design"
                    className="grid h-[29px] w-[29px] cursor-pointer place-items-center
                               rounded-[5px] border border-c4 bg-c1 text-c7
                               transition-colors hover:border-c6 hover:text-c9 disabled:opacity-40">
              <Plus size={14} strokeWidth={1.8} aria-hidden />
            </button>
          </Tip>
        )}
      </header>

      {modelSettingsOpen && !replayMode && (
        <section
          id="model-connection-settings"
          aria-label="Model connection settings"
          className="shrink-0 border-b border-c3 bg-c1 px-[13px] py-[11px]"
        >
          <ModelConnectionFields
            settings={modelSettings}
            onChange={onModelSettingsChange}
            disabled={busy}
            idPrefix="agent-model"
          />
        </section>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-[13px] py-[13px]">
        {messages.length ? (
          <div className="space-y-[10px]" aria-live="polite">
            {messages.map((message) => (
              <article key={message.id} className={cn(
                'max-w-[94%] rounded-[2px] border px-[9px] py-[8px]',
                message.role === 'user'
                  ? 'ml-auto border-observed-line bg-observed-wash'
                  : message.kind === 'clarification'
                    ? 'border-warn-line bg-warn-wash'
                    : 'border-c3 bg-c1',
              )}>
                <div className="mb-[4px] text-[10.5px] font-semibold text-c6">
                  {message.role === 'user' ? 'You' : 'Spec2CAD'}
                </div>
                <p className="whitespace-pre-wrap text-[12px] leading-[1.5] text-c8">
                  {message.content}
                </p>
              </article>
            ))}
            {busy && (
              <div role="status" className="flex items-center gap-[7px] text-[12px] text-c6">
                <span aria-hidden className="h-[6px] w-[6px] animate-pulse rounded-full bg-accent" />
                Interpreting and planning…
              </div>
            )}
            <div ref={threadEnd} />
          </div>
        ) : (
          <div className="flex h-full min-h-[240px] flex-col justify-center">
            <h2 className="text-[18px] font-semibold tracking-[-0.02em] text-c9">
              Build through conversation
            </h2>
            <p className="mt-[7px] text-[12.5px] leading-relaxed text-c7">
              Describe a part or attach engineering evidence. The agent keeps its
              decisions attached to the resulting revisions.
            </p>
            {!replayMode && (
              <div className="mt-[13px] grid gap-[7px]">
                {[
                  'Create a manufacturable part from this requirement: ',
                  'Reconcile the attached sources and flag conflicts.',
                ].map((prompt) => (
                  <button key={prompt} type="button" onClick={() => {
                    setInstruction(prompt)
                    requestAnimationFrame(() => instructionInput.current?.focus())
                  }} className="rounded-[6px] border border-c3 bg-c1 px-[10px] py-[8px]
                                text-left text-[12px] leading-snug text-c7 transition-colors
                                hover:border-accent-line hover:bg-accent-wash hover:text-c9">
                    {prompt}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {clarificationQuestions.length > 0 && (
          <div className="mt-[11px] border-l-2 border-warn bg-warn-wash px-[10px] py-[8px]">
            <p className="text-[11px] font-semibold text-warn">Decision needed</p>
            {clarificationQuestions.map((question) => (
              <p key={question} className="mt-[3px] text-[12px] leading-relaxed text-c8">
                {question}
              </p>
            ))}
          </div>
        )}
      </div>

      <div className="shrink-0 border-t border-c3 bg-c0 p-[10px]">
        {replayMode && (
          <p className="mb-[7px] text-[11px] leading-relaxed text-warn">
            This conversation is recorded. Open a live run to send new instructions.
          </p>
        )}
        <div className="overflow-hidden rounded-[2px] border border-c4 bg-c1
                        focus-within:border-accent">
          <label htmlFor="agent-instruction" className="sr-only">Message the Spec2CAD agent</label>
          <textarea
            ref={instructionInput}
            id="agent-instruction"
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && canSend) submit()
            }}
            disabled={replayMode || busy}
            placeholder={replayMode ? 'Recorded conversation' : clarificationQuestions.length
              ? 'Answer the clarification…' : continuing
                ? 'Ask for a change…' : 'Describe a part or request an action…'}
            className="min-h-[72px] w-full resize-none bg-transparent px-[10px] py-[9px]
                       text-[12.5px] leading-relaxed text-c9 outline-none placeholder:text-c6
                       disabled:cursor-not-allowed"
          />

          {(sketch || datasheet) && (
            <div className="flex flex-wrap gap-[5px] border-t border-c3 px-[8px] py-[6px]">
              {sketch && <Attachment icon={ImageIcon} file={sketch} onRemove={() => setSketch(null)} />}
              {datasheet && <Attachment icon={FileText} file={datasheet} onRemove={() => setDatasheet(null)} />}
            </div>
          )}

          <div className="flex items-center gap-[3px] border-t border-c3 px-[6px] py-[5px]">
            <Tip label={effectiveVisionAvailable ? 'Attach a sketch' : 'Sketch vision is unavailable'}>
              <button type="button" onClick={() => sketchInput.current?.click()}
                      disabled={replayMode || busy || !effectiveVisionAvailable} aria-label="Attach sketch"
                      className="grid h-[29px] w-[29px] cursor-pointer place-items-center rounded-[5px]
                                 text-c7 hover:bg-c2 hover:text-c9 disabled:cursor-not-allowed disabled:opacity-35">
                <ImageIcon size={14} strokeWidth={1.8} aria-hidden />
              </button>
            </Tip>
            <Tip label="Attach a component datasheet">
              <button type="button" onClick={() => datasheetInput.current?.click()}
                      disabled={replayMode || busy} aria-label="Attach datasheet"
                      className="grid h-[29px] w-[29px] cursor-pointer place-items-center rounded-[5px]
                                 text-c7 hover:bg-c2 hover:text-c9 disabled:cursor-not-allowed disabled:opacity-35">
                <Paperclip size={14} strokeWidth={1.8} aria-hidden />
              </button>
            </Tip>
            {(sketch || datasheet || instruction) && (
              <button type="button" onClick={clear} disabled={replayMode || busy}
                      aria-label="Clear draft"
                      className="grid h-[29px] w-[29px] cursor-pointer place-items-center rounded-[5px]
                                 text-c7 hover:bg-c2 hover:text-c9 disabled:opacity-35">
                <RotateCcw size={13} aria-hidden />
              </button>
            )}
            <Button intent="solid" size="sm" className="ml-auto" disabled={!canSend} onClick={submit}>
              <Play size={12} fill="currentColor" aria-hidden />
              {busy ? 'Working…' : 'Send'}
            </Button>
          </div>
        </div>
      </div>

      <input ref={sketchInput} className="sr-only" type="file" accept="image/*"
             tabIndex={-1} aria-hidden="true"
             onChange={(event) => setSketch(event.target.files?.[0] ?? null)} />
      <input ref={datasheetInput} className="sr-only" type="file" accept="application/pdf,.pdf"
             tabIndex={-1} aria-hidden="true"
             onChange={(event) => setDatasheet(event.target.files?.[0] ?? null)} />
    </aside>
  )
}

function Attachment({
  icon: Icon, file, onRemove,
}: {
  icon: typeof FileText
  file: File
  onRemove: () => void
}) {
  return (
    <span className="inline-flex min-w-0 items-center gap-[5px] rounded-[4px] border
                     border-c4 bg-c0 px-[6px] py-[3px] text-[10.5px] text-c8">
      <Icon size={11} className="shrink-0 text-c6" aria-hidden />
      <span className="max-w-[130px] truncate">{file.name}</span>
      <button type="button" onClick={onRemove} aria-label={`Remove ${file.name}`}
              className="grid h-[17px] w-[17px] cursor-pointer place-items-center text-c6 hover:text-c9">
        <X size={10} aria-hidden />
      </button>
    </span>
  )
}
