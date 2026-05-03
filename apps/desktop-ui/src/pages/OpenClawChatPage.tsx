import { bridgeBase, desktopFetch } from "../lib/api";
import { openClawUiUrl } from "../lib/openfdd-claw";
import { useCallback, useEffect, useState } from "react";
import { OpenFddClawAdvancedPanel } from "./OpenFddClawAdvancedPanel";

const WORKDIR_STORAGE_KEY = "ofdd-local-codex-workdir";

type PlotsQuicklink = { site_id: string; label: string; href: string };

type ReadinessPayload = {
  message_markdown?: string;
  deep_links?: Record<string, string>;
  plots_quicklinks?: PlotsQuicklink[];
  suggested_actions?: string[];
  ui_public_base_url?: string;
};

type DiagnosticsPayload = {
  codex_path: string | null;
  login_status: { returncode: number; stdout: string; stderr: string; logged_in: boolean } | null;
  hints: string[];
};

type ChatLine = { role: "user" | "assistant"; text: string };

type ChatResponse = {
  returncode: number;
  stdout: string;
  stderr: string;
  ok?: boolean;
};

type AuthUiState = "loading" | "signed_in" | "needs_login" | "no_cli" | "error";

function authStateFromDiagnostics(d: DiagnosticsPayload): { state: AuthUiState; line: string } {
  if (!d.codex_path) {
    return { state: "no_cli", line: "Codex CLI not found on the bridge PC." };
  }
  const st = d.login_status;
  if (!st) {
    return { state: "needs_login", line: "Could not read sign-in status." };
  }
  if (st.logged_in) {
    return { state: "signed_in", line: "Signed in with Codex." };
  }
  return { state: "needs_login", line: "Not signed in yet — use the steps below once in a terminal." };
}

export function OpenClawChatPage() {
  const [devOpen, setDevOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [handoffMd, setHandoffMd] = useState("");
  const [handoffErr, setHandoffErr] = useState("");
  const [plotsQuicklinks, setPlotsQuicklinks] = useState<PlotsQuicklink[]>([]);
  const [deepLinks, setDeepLinks] = useState<Record<string, string>>({});
  const [suggestedActions, setSuggestedActions] = useState<string[]>([]);
  const [readinessUiBase, setReadinessUiBase] = useState("");

  const [workdir] = useState(() => {
    try {
      return localStorage.getItem(WORKDIR_STORAGE_KEY) ?? "";
    } catch {
      return "";
    }
  });

  const [authState, setAuthState] = useState<AuthUiState>("loading");
  const [authLine, setAuthLine] = useState("Checking…");
  const [lines, setLines] = useState<ChatLine[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);

  const refreshAuth = useCallback(async () => {
    setAuthState("loading");
    setAuthLine("Checking…");
    try {
      const d = await desktopFetch<DiagnosticsPayload>("/local-codex/diagnostics");
      const { state, line } = authStateFromDiagnostics(d);
      setAuthState(state);
      setAuthLine(line);
    } catch (e) {
      setAuthState("error");
      setAuthLine(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void refreshAuth();
  }, [refreshAuth]);

  const fetchLocalHandoff = useCallback(async () => {
    setHandoffErr("");
    setHandoffMd("");
    setPlotsQuicklinks([]);
    setDeepLinks({});
    setSuggestedActions([]);
    setReadinessUiBase("");
    try {
      const data = await desktopFetch<ReadinessPayload>("/assistant/readiness");
      setHandoffMd(data.message_markdown ?? "");
      setPlotsQuicklinks(Array.isArray(data.plots_quicklinks) ? data.plots_quicklinks : []);
      setReadinessUiBase(typeof data.ui_public_base_url === "string" ? data.ui_public_base_url : "");
      if (data.deep_links && typeof data.deep_links === "object" && !Array.isArray(data.deep_links)) {
        const entries: Record<string, string> = {};
        for (const [k, v] of Object.entries(data.deep_links)) {
          if (typeof v === "string" && v.trim()) {
            entries[k] = v.trim();
          }
        }
        setDeepLinks(entries);
      }
      setSuggestedActions(Array.isArray(data.suggested_actions) ? data.suggested_actions : []);
    } catch (e) {
      setHandoffErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const sendMessage = useCallback(async () => {
    const text = draft.trim();
    if (!text || sending) {
      return;
    }
    setDraft("");
    setSending(true);
    setLines((prev) => [...prev, { role: "user", text }]);
    try {
      const res = await fetch(`${bridgeBase}/openfdd-agent/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          workdir: workdir.trim() || null,
          task_summary: null,
        }),
      });
      const data = (await res.json()) as ChatResponse & { detail?: string };
      if (!res.ok) {
        const detail = typeof data?.detail === "string" ? data.detail : JSON.stringify(data);
        setLines((prev) => [...prev, { role: "assistant", text: `Request failed (${res.status}):\n${detail}` }]);
        return;
      }
      const out =
        data.stdout?.trim() ||
        (data.stderr?.trim()
          ? `codex exited ${data.returncode}.\n\nstderr:\n${data.stderr.trim()}`
          : "(No output.)");
      setLines((prev) => [...prev, { role: "assistant", text: out }]);
    } catch (e) {
      setLines((prev) => [
        ...prev,
        { role: "assistant", text: e instanceof Error ? e.message : String(e) },
      ]);
    } finally {
      setSending(false);
    }
  }, [draft, sending, workdir]);

  const authColor =
    authState === "signed_in"
      ? "var(--muted)"
      : authState === "loading"
        ? "var(--muted)"
        : "var(--danger)";

  return (
    <section className="stack-page local-codex-page" data-testid="ofdd-ai-page">
      <div className="card">
        <h2 className="title" data-testid="ofdd-ai-chat-heading">
          Codex
        </h2>
        <p className="muted" style={{ marginBottom: 12, color: authColor }}>
          {authLine}
        </p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <button type="button" onClick={() => void refreshAuth()}>
            Check sign-in
          </button>
        </div>
        <details style={{ marginTop: 14 }}>
          <summary className="muted" style={{ cursor: "pointer", fontSize: 13 }}>
            First-time sign-in (run once in PowerShell on the bridge PC)
          </summary>
          <ol className="muted" style={{ margin: "10px 0 0 18px", fontSize: 13, lineHeight: 1.7 }}>
            <li>
              <code className="inline-code">npm install -g @openai/codex</code>
            </li>
            <li>
              <code className="inline-code">codex login</code> (or <code className="inline-code">codex login --device-auth</code>)
            </li>
            <li>
              <code className="inline-code">codex login status</code>
            </li>
          </ol>
          <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
            The <strong>Check sign-in</strong> button only asks the bridge to run that last step (<code className="inline-code">codex login status</code>) and see if the CLI is installed — same idea as your local script, not a separate OAuth system.
          </p>
        </details>
      </div>

      <div className="card local-codex-chat-card">
        <div className="local-codex-thread" data-testid="local-codex-thread">
          {lines.length === 0 ? (
            <p className="muted" style={{ margin: 0 }}>
              Ask anything. The agent uses the Open-FDD bridge and your Codex subscription in the background.
            </p>
          ) : (
            lines.map((ln, i) => (
              <div
                key={`${i}-${ln.role}`}
                className={`local-codex-msg ${ln.role === "user" ? "local-codex-msg-user" : "local-codex-msg-ai"}`}
              >
                <div className="local-codex-msg-label">{ln.role === "user" ? "You" : "Codex"}</div>
                <div style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{ln.text}</div>
              </div>
            ))
          )}
        </div>
        <div className="local-codex-compose">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Message…"
            aria-label="Chat message"
            rows={3}
            disabled={sending}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void sendMessage();
              }
            }}
          />
          <button type="button" disabled={sending || !draft.trim()} onClick={() => void sendMessage()}>
            {sending ? "…" : "Send"}
          </button>
        </div>
      </div>

      <details className="card" data-testid="ofdd-dev-details">
        <summary
          style={{ cursor: "pointer", fontWeight: 600 }}
          onClick={(e) => {
            e.preventDefault();
            setDevOpen((v) => !v);
          }}
        >
          Developer — OpenClaw, readiness, stack, advanced
        </summary>
        <div style={{ display: devOpen ? "block" : "none" }} aria-hidden={!devOpen}>
          <p className="muted" style={{ marginTop: 10 }}>
            OpenClaw UI: <a href={openClawUiUrl} target="_blank" rel="noreferrer">{openClawUiUrl}</a>
          </p>
          <div className="openclaw-frame-card" style={{ minHeight: "36vh", marginTop: 8 }}>
            <iframe title="OpenClaw (optional)" src={openClawUiUrl} className="openclaw-iframe" loading="lazy" referrerPolicy="no-referrer" />
          </div>

          <h3 className="title" style={{ marginTop: 16 }}>Bridge handoff</h3>
          <button type="button" className="secondary-btn" onClick={() => void fetchLocalHandoff()}>
            Fetch readiness
          </button>
          {handoffErr ? <p className="muted" style={{ color: "var(--danger)" }}>{handoffErr}</p> : null}
          {readinessUiBase ? <p className="muted"><code>{readinessUiBase}</code></p> : null}
          {Object.keys(deepLinks).length > 0 ? (
            <ul>
              {Object.entries(deepLinks).map(([k, value]) => {
                const isUrl = /^https?:\/\//i.test(value);
                return (
                  <li key={k}>
                    {isUrl ? (
                      <a href={value} target="_blank" rel="noreferrer">{k}</a>
                    ) : (
                      <><strong>{k}</strong> <span className="muted">{value}</span></>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : null}
          {plotsQuicklinks.length > 0 ? (
            <ul>
              {plotsQuicklinks.map((q) => (
                <li key={q.site_id}>
                  <a href={q.href} target="_blank" rel="noreferrer">{q.label}</a>
                </li>
              ))}
            </ul>
          ) : null}
          {handoffMd ? <textarea readOnly value={handoffMd} style={{ width: "100%", minHeight: 160, marginTop: 8 }} /> : null}

          <details className="openfdd-advanced" data-testid="ofdd-claw-advanced" open={advancedOpen} style={{ marginTop: 16 }}>
            <summary
              onClick={(e) => {
                e.preventDefault();
                setAdvancedOpen((v) => !v);
              }}
            >
              Advanced — cron, API, policy
            </summary>
            <div aria-hidden={!advancedOpen} style={{ display: advancedOpen ? "block" : "none" }}>
              <OpenFddClawAdvancedPanel />
            </div>
          </details>
        </div>
      </details>
    </section>
  );
}
