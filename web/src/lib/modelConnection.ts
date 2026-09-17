import type { ModelConnectionInput } from '../api'

export type ModelConnectionMode = 'server' | 'own'

export interface ModelConnectionSettings {
  mode: ModelConnectionMode
  provider: ModelConnectionInput['provider']
  apiKey: string
  model: string
  baseUrl: string
}
export function defaultModelConnectionSettings(): ModelConnectionSettings {
  return {
    mode: 'server',
    provider: 'openai',
    apiKey: '',
    model: 'gpt-4o',
    baseUrl: '',
  }
}

export function isOwnConnectionReady(settings: ModelConnectionSettings): boolean {
  return Boolean(
    settings.apiKey.trim()
    && settings.model.trim()
    && (settings.provider === 'openai' || settings.baseUrl.trim()),
  )
}

export function modelConnectionInput(
  settings: ModelConnectionSettings,
): ModelConnectionInput | null {
  if (settings.mode === 'server') return null
  if (!isOwnConnectionReady(settings)) return null
  return {
    provider: settings.provider,
    apiKey: settings.apiKey.trim(),
    model: settings.model.trim(),
    ...(settings.provider === 'openai_compatible'
      ? { baseUrl: settings.baseUrl.trim() }
      : {}),
  }
}
