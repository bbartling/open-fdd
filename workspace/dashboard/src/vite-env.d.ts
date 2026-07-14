/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_DESKTOP_BRIDGE_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
