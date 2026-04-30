/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_DESKTOP_BRIDGE_BASE?: string;
  readonly VITE_OPENCLAW_UI_URL?: string;
  readonly VITE_OPENCLAW_GATEWAY_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
