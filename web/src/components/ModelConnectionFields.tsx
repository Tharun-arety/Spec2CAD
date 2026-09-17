import { useState } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import {
  isOwnConnectionReady,
  type ModelConnectionSettings,
} from '../lib/modelConnection'

interface ModelConnectionFieldsProps {
  settings: ModelConnectionSettings
  onChange: (settings: ModelConnectionSettings) => void
  disabled?: boolean
  idPrefix: string
  showMode?: boolean
  showStatus?: boolean
  autoFocus?: boolean
  spacious?: boolean
}

const fieldClass =
  'h-[34px] w-full rounded-[5px] border border-c4 bg-c0 px-[8px] text-[12px] ' +
  'text-c9 outline-none placeholder:text-c6 focus:border-accent disabled:cursor-not-allowed ' +
  'disabled:opacity-45'

/** Controlled, reusable form. Credentials remain owned by App memory only. */
export function ModelConnectionFields({
  settings, onChange, disabled = false, idPrefix, showMode = true, showStatus = true,
  autoFocus = false, spacious = false,
}: ModelConnectionFieldsProps) {
  const [showApiKey, setShowApiKey] = useState(false)
  const ownConnectionReady = isOwnConnectionReady(settings)
  const update = (patch: Partial<ModelConnectionSettings>) => {
    onChange({ ...settings, ...patch })
  }
  const inputClass = `${fieldClass} ${spacious ? '!h-[44px]' : ''}`

  return (
    <div className="grid gap-[9px]">
      {showMode ? (
        <label className="grid gap-[4px] text-[11px] font-medium text-c8">
          Connection
          <select
            value={settings.mode}
            onChange={(event) => update({
              mode: event.target.value as ModelConnectionSettings['mode'],
            })}
            disabled={disabled}
            className={inputClass}
          >
            <option value="server">Hosted demo access</option>
            <option value="own">My own model API</option>
          </select>
        </label>
      ) : null}

      {settings.mode === 'own' ? (
        <>
          <label className="grid gap-[4px] text-[11px] font-medium text-c8">
            Provider
            <select
              value={settings.provider}
              autoFocus={autoFocus}
              onChange={(event) => update({
                provider: event.target.value as ModelConnectionSettings['provider'],
              })}
              disabled={disabled}
              className={inputClass}
            >
              <option value="openai">OpenAI</option>
              <option value="openai_compatible">OpenAI-compatible endpoint</option>
            </select>
          </label>

          <div className="grid gap-[4px] text-[11px] font-medium text-c8">
            <label htmlFor={`${idPrefix}-api-key`}>API key</label>
            <span className="relative block">
              <input
                id={`${idPrefix}-api-key`}
                type={showApiKey ? 'text' : 'password'}
                value={settings.apiKey}
                onChange={(event) => update({ apiKey: event.target.value })}
                disabled={disabled}
                autoComplete="off"
                spellCheck={false}
                placeholder="Enter your provider key"
                className={`${inputClass} ${spacious ? 'pr-[48px]' : 'pr-[38px]'}`}
              />
              <button
                type="button"
                onClick={() => setShowApiKey((visible) => !visible)}
                disabled={disabled || !settings.apiKey}
                aria-label={showApiKey ? 'Hide API key' : 'Show API key'}
                className={`absolute inset-y-0 right-0 grid cursor-pointer place-items-center
                           text-c6 transition-colors hover:text-c9 disabled:cursor-not-allowed
                           disabled:opacity-35 ${spacious ? 'w-[44px]' : 'w-[34px]'}`}
              >
                {showApiKey
                  ? <EyeOff size={13} strokeWidth={1.8} aria-hidden />
                  : <Eye size={13} strokeWidth={1.8} aria-hidden />}
              </button>
            </span>
          </div>

          <label className="grid gap-[4px] text-[11px] font-medium text-c8">
            Model
            <input
              type="text"
              value={settings.model}
              onChange={(event) => update({ model: event.target.value })}
              disabled={disabled}
              spellCheck={false}
              placeholder="gpt-4o"
              className={`${inputClass} font-mono text-[11.5px]`}
            />
          </label>

          {settings.provider === 'openai_compatible' ? (
            <label className="grid gap-[4px] text-[11px] font-medium text-c8">
              HTTPS base URL
              <input
                type="url"
                value={settings.baseUrl}
                onChange={(event) => update({ baseUrl: event.target.value })}
                disabled={disabled}
                spellCheck={false}
                placeholder="https://openrouter.ai/api/v1"
                className={`${inputClass} font-mono text-[11px]`}
              />
            </label>
          ) : null}
        </>
      ) : null}

      {showStatus ? (
        <div className="text-[10.5px] leading-[1.45] text-c6">
          {settings.mode === 'server' ? (
            <p>Uses the limited model allowance configured by this deployment.</p>
          ) : (
            <>
              <p>
                Kept only in this tab’s memory and sent with generation requests.
                The key is not saved with the run.
              </p>
              {!ownConnectionReady ? (
                <p role="status" className="mt-[6px] font-medium text-warn">
                  Enter the key, model, and required endpoint before continuing.
                </p>
              ) : null}
            </>
          )}
        </div>
      ) : null}
    </div>
  )
}
