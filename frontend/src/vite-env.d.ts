/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_HTTP_URL?: string
  readonly VITE_API_WS_URL?: string
  readonly VITE_GROQ_API_KEY?: string
  readonly VITE_STAFF_TYPE?: string
  readonly VITE_STAFF_NAME?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
