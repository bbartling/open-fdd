/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_DESKTOP_BRIDGE_BASE?: string;
  readonly VITE_OPENCLAW_UI_URL?: string;
  readonly VITE_OPENCLAW_GATEWAY_BASE?: string;
  /** Default Codex cwd on the bridge PC for local AI chat (repo root). */
  readonly VITE_OPENFDD_AGENT_WORKDIR?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
