import { openClawUiUrl } from "../lib/openfdd-claw";
import { useState } from "react";
import { OpenFddClawAdvancedPanel } from "./OpenFddClawAdvancedPanel";
import { OpenFddCodexSignIn } from "./OpenFddCodexSignIn";

export function OpenClawChatPage() {
  const [advancedOpen, setAdvancedOpen] = useState(false);
  return (
    <section className="stack-page">
      <div className="card">
        <h2 className="title">Open-FDD Claw</h2>
        <p className="muted">
          Chat with your OpenClaw agent for data modeling, FDD, ingest, and SPARQL — the same Codex-backed setup as the
          OpenClaw desktop. Open-FDD bridge stays on <code className="inline-code">8765</code>; OpenClaw gateway is usually{" "}
          <code className="inline-code">18789</code>.
        </p>
        <div className="openclaw-actions">
          <a href={openClawUiUrl} target="_blank" rel="noreferrer" className="link-btn">
            Open chat in new tab
          </a>
        </div>
        <p className="muted" style={{ marginTop: 10 }}>
          Optional: set <code className="inline-code">VITE_OPENFDDCLAW_UI_URL</code> (or <code className="inline-code">VITE_OPENCLAW_UI_URL</code>)
          if your OpenClaw UI is not at the default. Current: <code className="inline-code">{openClawUiUrl}</code>
        </p>
      </div>

      <OpenFddCodexSignIn />

      <div className="card openclaw-frame-card">
        <iframe
          title="Open-FDD Claw UI"
          src={openClawUiUrl}
          className="openclaw-iframe"
          loading="lazy"
          referrerPolicy="no-referrer"
        />
      </div>

      <details className="openfdd-advanced" data-testid="ofdd-claw-advanced" open={advancedOpen}>
        <summary
          onClick={(e) => {
            e.preventDefault();
            setAdvancedOpen((v) => !v);
          }}
        >
          Advanced — cron helpers, API, and policy presets (optional)
        </summary>
        <div
          aria-hidden={!advancedOpen}
          style={{ display: advancedOpen ? "block" : "none" }}
        >
          <OpenFddClawAdvancedPanel />
        </div>
      </details>
    </section>
  );
}
