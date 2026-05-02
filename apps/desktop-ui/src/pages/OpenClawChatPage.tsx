import { openClawUiUrl } from "../lib/openfdd-claw";
import { useCallback, useState } from "react";
import { desktopFetch } from "../lib/api";
import { OpenFddClawAdvancedPanel } from "./OpenFddClawAdvancedPanel";
import { OpenFddCodexSignIn } from "./OpenFddCodexSignIn";

type PlotsQuicklink = { site_id: string; label: string; href: string };

type ReadinessPayload = {
  message_markdown?: string;
  deep_links?: Record<string, string>;
  plots_quicklinks?: PlotsQuicklink[];
  suggested_actions?: string[];
};

export function OpenClawChatPage() {
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [handoffMd, setHandoffMd] = useState("");
  const [handoffErr, setHandoffErr] = useState("");
  const [plotsQuicklinks, setPlotsQuicklinks] = useState<PlotsQuicklink[]>([]);

  const fetchLocalHandoff = useCallback(async () => {
    setHandoffErr("");
    setHandoffMd("");
    setPlotsQuicklinks([]);
    try {
      const data = await desktopFetch<ReadinessPayload>("/assistant/readiness");
      setHandoffMd(data.message_markdown ?? "");
      setPlotsQuicklinks(Array.isArray(data.plots_quicklinks) ? data.plots_quicklinks : []);
    } catch (e) {
      setHandoffErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  return (
    <section className="stack-page">
      <div className="card">
        <h2 className="title">Open-FDD Claw</h2>
        <p className="muted">
          Same stack as OpenClaw desktop: <strong>Codex / ChatGPT</strong> in the embedded UI below, plus Open-FDD bridge
          on <code className="inline-code">8765</code> and gateway usually on <code className="inline-code">18789</code>.
          One browser sign-in to OpenAI unlocks models; then use the chat iframe.
        </p>
        <div className="openclaw-actions">
          <a href={openClawUiUrl} target="_blank" rel="noreferrer" className="link-btn">
            Open Claw chat (new tab)
          </a>
          <a href="#openfdd-codex-auth" className="link-btn">
            Sign in to OpenAI (Codex)
          </a>
        </div>
        <p className="muted" style={{ marginTop: 10 }}>
          <strong>Flow:</strong> optional <strong>Sign in to OpenAI</strong> → section below starts device login → then
          embedded <strong>OpenClaw</strong> chat. Copy <code>contrib/openclaw-workspace/</code> into your OpenClaw
          workspace for <code>AGENTS.md</code>, <code>SOUL.md</code>, <code>MEMORY.md</code>, and tool hints.
        </p>
        <p className="muted" style={{ marginTop: 6 }}>
          Optional: set <code className="inline-code">VITE_OPENFDDCLAW_UI_URL</code> (or{" "}
          <code className="inline-code">VITE_OPENCLAW_UI_URL</code>) if your OpenClaw UI is not at the default. Current:{" "}
          <code className="inline-code">{openClawUiUrl}</code>
        </p>
      </div>

      <OpenFddCodexSignIn />

      <div className="card">
        <h3 className="title" style={{ marginBottom: 8 }}>Local bridge handoff (stand-in for OpenClaw)</h3>
        <p className="muted">
          Until the remote agent is wired end-to-end, pull a <strong>readiness snippet</strong> from the Open-FDD bridge: sites, deep links to Plots / CSV import / data model,
          and a short message you can paste into chat for the human reviewer (“blessing”, follow-up yes/no). Use <strong>Plots</strong> links with <code>?fdd=1</code> to open trends and auto-run <strong>Run FDD &amp; refresh chart</strong>, or <strong>POST /plots/share</strong> to mint a reopenable <code>?share=</code> handoff for the team.
        </p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
          <button type="button" className="secondary-btn" onClick={() => void fetchLocalHandoff()}>
            Fetch readiness from bridge
          </button>
        </div>
        {handoffErr ? <p className="muted" style={{ marginTop: 8, color: "var(--danger)" }}>{handoffErr}</p> : null}
        {plotsQuicklinks.length > 0 ? (
          <div style={{ marginTop: 10 }}>
            <p className="muted" style={{ marginBottom: 6 }}>Plots + FDD (one click per site)</p>
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {plotsQuicklinks.map((q) => (
                <li key={q.site_id} style={{ marginBottom: 4 }}>
                  <a href={q.href} target="_blank" rel="noreferrer">
                    {q.label}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {handoffMd ? (
          <textarea
            readOnly
            value={handoffMd}
            style={{ marginTop: 10, width: "100%", minHeight: 220, fontFamily: "ui-monospace, monospace", fontSize: 13 }}
            aria-label="Readiness markdown for chat handoff"
          />
        ) : null}
      </div>

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
