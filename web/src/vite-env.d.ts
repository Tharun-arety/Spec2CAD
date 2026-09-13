/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "1" when this build replays a recorded run instead of calling a backend. */
  readonly VITE_REPLAY?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
