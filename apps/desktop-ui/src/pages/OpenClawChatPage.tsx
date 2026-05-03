import { bridgeBase, desktopFetch } from "../lib/api";
import { useCallback, useEffect, useRef, useState } from "react";

const WORKDIR_STORAGE_KEY = "ofdd-local-codex-workdir";
const CHAT_STORAGE_KEY = "ofdd-local-codex-chat-v1";
/** Cap stored turns so localStorage stays bounded (UI only; bridge still gets one message per send). */
const MAX_STORED_CHAT_LINES = 120;
const MAX_STORED_CHAT_CHARS = 320_000;

type ChatLine = { role: "user" | "assistant"; text: string };

const DEFAULT_WORKDIR_FROM_VITE =
  typeof import.meta.env.VITE_OPENFDD_AGENT_WORKDIR === "string"
    ? import.meta.env.VITE_OPENFDD_AGENT_WORKDIR.trim()
    : "";

function readInitialWorkdir(): string {
  try {
    const stored = localStorage.getItem(WORKDIR_STORAGE_KEY);
    if (stored != null && stored !== "") {
      return stored;
    }
  } catch {
    /* private mode */
  }
  return DEFAULT_WORKDIR_FROM_VITE;
}

function trimStoredChatLines(lines: ChatLine[]): ChatLine[] {
  let out = lines.length > MAX_STORED_CHAT_LINES ? lines.slice(-MAX_STORED_CHAT_LINES) : lines;
  let chars = out.reduce((n, l) => n + l.text.length, 0);
  while (chars > MAX_STORED_CHAT_CHARS && out.length > 1) {
    out = out.slice(1);
    chars = out.reduce((n, l) => n + l.text.length, 0);
  }
  return out;
}

function readStoredChat(): { lines: ChatLine[]; draft: string } {
  try {
    const raw = localStorage.getItem(CHAT_STORAGE_KEY);
    if (!raw) {
      return { lines: [], draft: "" };
    }
    const parsed = JSON.parse(raw) as { v?: number; lines?: unknown; draft?: unknown };
    if (parsed.v !== 1 || !Array.isArray(parsed.lines)) {
      return { lines: [], draft: "" };
    }
    const lines: ChatLine[] = [];
    for (const item of parsed.lines) {
      if (!item || typeof item !== "object") continue;
      const role = (item as { role?: unknown }).role;
      const text = (item as { text?: unknown }).text;
      if (role !== "user" && role !== "assistant") continue;
      if (typeof text !== "string") continue;
      lines.push({ role, text });
    }
    const draft = typeof parsed.draft === "string" ? parsed.draft : "";
    return { lines: trimStoredChatLines(lines), draft };
  } catch {
    return { lines: [], draft: "" };
  }
}

function persistChatSnapshot(lines: ChatLine[], draft: string) {
  try {
    const payload = JSON.stringify({
      v: 1 as const,
      lines: trimStoredChatLines(lines),
      draft,
    });
    localStorage.setItem(CHAT_STORAGE_KEY, payload);
  } catch {
    /* quota / private mode */
  }
}

type CodexExecEnvPayload = {
  ask_for_approval: string;
  sandbox_mode: string;
  workspace_write_network?: boolean | null;
};

type DiagnosticsPayload = {
  codex_path: string | null;
  login_status: { returncode: number; stdout: string; stderr: string; logged_in: boolean } | null;
  hints: string[];
  exec_env?: CodexExecEnvPayload | null;
};

type ChatResponse = {
  returncode: number;
  stdout: string;
  stderr: string;
  ok?: boolean;
};

type AuthUiState = "loading" | "signed_in" | "needs_login" | "no_cli" | "error";

type DeviceSession = {
  sessionId: string;
  userCode: string;
  verificationUrl: string;
  pollMs: number;
};

const THINKING_PHASES = [
  "Sending your message to the bridge…",
  "Running Codex in your workdir (repo files, scripts, curl/IRM)…",
  "Working through FDD, plots, data cleaning, or modeling…",
  "Waiting for Codex (can take several minutes on complex tasks)…",
] as const;

function authStateFromDiagnostics(d: DiagnosticsPayload): { state: AuthUiState; line: string } {
  if (!d.codex_path) {
    return { state: "no_cli", line: "Codex CLI is not installed on the bridge PC (or not on PATH)." };
  }
  const st = d.login_status;
  if (!st) {
    return { state: "needs_login", line: "Codex is installed; sign in with your OpenAI account to continue." };
  }
  if (st.logged_in) {
    return { state: "signed_in", line: "Signed in with Codex." };
  }
  return { state: "needs_login", line: "Codex is installed; sign in with your OpenAI account to continue." };
}

function CodexBrainIcon() {
  return (
    <svg
      className="local-codex-brain-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.35"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M12 5a3 3 0 0 0-3 3v1a3 3 0 1 0 6 0V8a3 3 0 0 0-3-3Z" />
      <path d="M9 9c-2 0-3.5 1.6-3.5 3.5S7 16 9 16h.5" />
      <path d="M15 9c2 0 3.5 1.6 3.5 3.5S17 16 15 16h-.5" />
      <path d="M9 16v2a2 2 0 0 0 2 2h2a2 2 0 0 0 2-2v-2" />
      <path d="M12 11v3" />
    </svg>
  );
}

export function OpenClawChatPage() {
  const [workdir, setWorkdir] = useState(readInitialWorkdir);

  const onWorkdirChange = useCallback((value: string) => {
    setWorkdir(value);
    try {
      localStorage.setItem(WORKDIR_STORAGE_KEY, value);
    } catch {
      /* ignore */
    }
  }, []);

  const [authState, setAuthState] = useState<AuthUiState>("loading");
  const [authLine, setAuthLine] = useState("Checking Codex on the bridge…");
  const [postOAuthHint, setPostOAuthHint] = useState<string | null>(null);
  const [npmBusy, setNpmBusy] = useState(false);
  const [deviceSession, setDeviceSession] = useState<DeviceSession | null>(null);
  const [signInActionError, setSignInActionError] = useState<string | null>(null);
  const [execEnv, setExecEnv] = useState<CodexExecEnvPayload | null>(null);

  const [lines, setLines] = useState<ChatLine[]>(() => readStoredChat().lines);
  const [draft, setDraft] = useState(() => readStoredChat().draft);
  const [sending, setSending] = useState(false);
  const [thinkingPhase, setThinkingPhase] = useState(0);
  const phaseTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const devicePollMounted = useRef(true);
  const linesRef = useRef(lines);
  const draftRef = useRef(draft);
  linesRef.current = lines;
  draftRef.current = draft;

  useEffect(() => {
    const persistNow = () => persistChatSnapshot(linesRef.current, draftRef.current);
    const id = window.setTimeout(persistNow, 320);
    return () => {
      window.clearTimeout(id);
      persistNow();
    };
  }, [lines, draft]);

  useEffect(() => {
    devicePollMounted.current = true;
    return () => {
      devicePollMounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (!sending) {
      if (phaseTimerRef.current) {
        clearInterval(phaseTimerRef.current);
        phaseTimerRef.current = null;
      }
      setThinkingPhase(0);
      return;
    }
    setThinkingPhase(0);
    phaseTimerRef.current = setInterval(() => {
      setThinkingPhase((i) => (i + 1) % THINKING_PHASES.length);
    }, 2200);
    return () => {
      if (phaseTimerRef.current) {
        clearInterval(phaseTimerRef.current);
        phaseTimerRef.current = null;
      }
    };
  }, [sending]);

  const pullDiagnostics = useCallback(async (opts: { silent?: boolean } = {}): Promise<AuthUiState> => {
    if (!opts.silent) {
      setAuthState("loading");
      setAuthLine("Checking Codex on the bridge…");
    }
    const d = await desktopFetch<DiagnosticsPayload>("/local-codex/diagnostics");
    setExecEnv(d.exec_env ?? null);
    const r = authStateFromDiagnostics(d);
    setAuthState(r.state);
    setAuthLine(r.line);
    if (r.state === "signed_in") {
      setPostOAuthHint(null);
    }
    return r.state;
  }, []);

  const refreshAuth = useCallback(async () => {
    setSignInActionError(null);
    try {
      await pullDiagnostics({ silent: false });
    } catch (e) {
      setAuthState("error");
      setAuthLine(e instanceof Error ? e.message : String(e));
    }
  }, [pullDiagnostics]);

  useEffect(() => {
    void refreshAuth();
  }, [refreshAuth]);

  useEffect(() => {
    if (!deviceSession) {
      return undefined;
    }
    const { sessionId, pollMs } = deviceSession;
    let cancelled = false;

    const tick = async () => {
      try {
        const res = await fetch(`${bridgeBase}/openfdd-claw/codex/device/poll`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId }),
        });
        const body = (await res.json()) as { status?: string; message?: string; detail?: string };
        if (cancelled || !devicePollMounted.current) {
          return;
        }
        if (!res.ok) {
          setDeviceSession(null);
          setAuthState("error");
          setAuthLine(typeof body.detail === "string" ? body.detail : JSON.stringify(body));
          return;
        }
        if (body.status === "complete") {
          setDeviceSession(null);
          try {
            const st = await pullDiagnostics({ silent: true });
            if (st === "needs_login") {
              setPostOAuthHint(
                "Browser sign-in finished. If Codex still shows as signed out, open PowerShell on the bridge PC and run: codex login — then use Retry below.",
              );
            }
          } catch (e) {
            setAuthState("error");
            setAuthLine(e instanceof Error ? e.message : String(e));
          }
          return;
        }
        if (body.status === "error") {
          setDeviceSession(null);
          setAuthState("error");
          setAuthLine(body.message || "Device sign-in failed.");
        }
      } catch (e) {
        if (cancelled || !devicePollMounted.current) {
          return;
        }
        setDeviceSession(null);
        setAuthState("error");
        setAuthLine(e instanceof Error ? e.message : String(e));
      }
    };

    const id = window.setInterval(() => void tick(), pollMs);
    void tick();
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [deviceSession, bridgeBase, pullDiagnostics]);

  const runAutomatedSignIn = useCallback(async () => {
    setSignInActionError(null);
    setPostOAuthHint(null);
    try {
      let st = await pullDiagnostics({ silent: true });

      if (st === "no_cli") {
        setNpmBusy(true);
        try {
          const ins = await fetch(`${bridgeBase}/local-codex/install-cli`, { method: "POST" });
          const j = (await ins.json()) as { ok?: boolean; stdout?: string; stderr?: string; returncode?: number };
          if (!ins.ok || j.ok === false) {
            const msg = [j.stderr, j.stdout].filter(Boolean).join("\n").trim() || "npm install failed.";
            setSignInActionError(msg);
            setAuthState("error");
            setAuthLine("Could not install Codex CLI via npm.");
            return;
          }
        } finally {
          setNpmBusy(false);
        }
        st = await pullDiagnostics({ silent: true });
      }

      if (st === "signed_in") {
        return;
      }
      if (st === "no_cli") {
        setSignInActionError(
          "Codex is still not on PATH after install. Restart the bridge process or set OFDD_CODEX_CMD to the full path to codex.cmd.",
        );
        setAuthState("error");
        setAuthLine("Codex CLI not found after npm install.");
        return;
      }

      if (st !== "needs_login") {
        return;
      }

      const start = await fetch(`${bridgeBase}/openfdd-claw/codex/device/start`, { method: "POST" });
      const data = (await start.json()) as {
        session_id?: string;
        user_code?: string;
        verification_url?: string;
        interval_ms?: number;
        detail?: string;
      };
      if (!start.ok) {
        const msg = typeof data.detail === "string" ? data.detail : JSON.stringify(data);
        setSignInActionError(msg);
        setAuthState("error");
        setAuthLine("Could not start OpenAI device sign-in.");
        return;
      }
      const sid = (data.session_id || "").trim();
      const code = (data.user_code || "").trim();
      const url = (data.verification_url || "").trim();
      if (!sid || !code || !url) {
        setSignInActionError("Bridge returned an incomplete device sign-in payload.");
        setAuthState("error");
        setAuthLine("Device sign-in could not start.");
        return;
      }
      const pollMs = Math.max(1500, Math.min(Number(data.interval_ms) || 5000, 30_000));
      window.open(url, "_blank", "noopener,noreferrer");
      setDeviceSession({ sessionId: sid, userCode: code, verificationUrl: url, pollMs });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setSignInActionError(msg);
      setAuthState("error");
      setAuthLine(msg);
    }
  }, [bridgeBase, pullDiagnostics]);

  const sendMessage = useCallback(async () => {
    const text = draft.trim();
    if (!text || sending || authState !== "signed_in") {
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
  }, [authState, draft, sending, workdir]);

  const chatEnabled = authState === "signed_in";
  const devicePending = deviceSession !== null;
  const signInControlsBusy = authState === "loading" || npmBusy || devicePending;

  const signInButtonLabel =
    authState === "error"
      ? "Try sign-in again"
      : authState === "no_cli"
        ? "Install Codex & sign into OpenAI"
        : "Sign into OpenAI";

  return (
    <section className="stack-page local-codex-page" data-testid="ofdd-ai-page">
      <div className="card local-codex-auth-card">
        <h2 className="title" data-testid="ofdd-ai-chat-heading">
          Codex
        </h2>

        {authState === "loading" ? (
          <p className="muted" style={{ margin: 0 }}>
            Checking Codex on the bridge…
          </p>
        ) : authState === "signed_in" ? (
          <>
            <p className="muted" style={{ margin: 0, color: "var(--muted)" }}>
              Signed in with Codex.
            </p>
            {execEnv ? (
              <p className="muted" style={{ margin: "8px 0 0", fontSize: 11, lineHeight: 1.45 }}>
                Bridge runs Codex with <code className="inline-code">{execEnv.ask_for_approval}</code> approval and{" "}
                <code className="inline-code">{execEnv.sandbox_mode}</code> sandbox so it can call your local bridge and edit the workdir (
                <code className="inline-code">OFDD_CODEX_EXEC_*</code> on the gateway).
              </p>
            ) : null}
          </>
        ) : (
          <>
            <p className="muted" style={{ margin: "0 0 10px", color: "var(--danger)" }}>
              {authLine}
            </p>
            {npmBusy ? (
              <p className="muted" style={{ margin: "0 0 10px", fontSize: 13 }}>
                Installing Codex CLI on the bridge: <code className="inline-code">npm install -g @openai/codex</code>
                … This can take a few minutes.
              </p>
            ) : null}
            {deviceSession ? (
              <div
                className="local-codex-device-pending"
                style={{ marginBottom: 10, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--border)", background: "var(--panel-soft)" }}
              >
                <p className="muted" style={{ margin: "0 0 6px", fontSize: 13 }}>
                  Finish sign-in in the browser tab that just opened, then keep this page open.
                </p>
                <p style={{ margin: 0, fontSize: 15, fontWeight: 600, letterSpacing: "0.06em" }}>{deviceSession.userCode}</p>
                <a href={deviceSession.verificationUrl} target="_blank" rel="noreferrer" className="muted" style={{ fontSize: 12 }}>
                  Open sign-in link again
                </a>
              </div>
            ) : null}
            {postOAuthHint ? (
              <p className="muted" style={{ margin: "0 0 10px", fontSize: 12, lineHeight: 1.5 }}>
                {postOAuthHint}
              </p>
            ) : null}
            {signInActionError ? (
              <p className="muted" style={{ margin: "0 0 10px", fontSize: 12, color: "var(--danger)", whiteSpace: "pre-wrap" }}>
                {signInActionError}
              </p>
            ) : null}
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
              <button
                type="button"
                className="local-codex-signin-primary"
                disabled={signInControlsBusy}
                onClick={() => void runAutomatedSignIn()}
              >
                {signInControlsBusy && !deviceSession ? "Please wait…" : signInButtonLabel}
              </button>
              <button type="button" className="secondary-btn" disabled={signInControlsBusy} onClick={() => void refreshAuth()}>
                Retry check
              </button>
            </div>
          </>
        )}
      </div>

      <div className="card local-codex-chat-card">
        <div className="local-codex-workdir-block">
          <div className="local-codex-workdir-heading">Codex workdir on the bridge</div>
          <p className="muted" style={{ margin: "0 0 8px", fontSize: 12, lineHeight: 1.5 }}>
            Repo root for <code className="inline-code">codex exec</code> (default <code className="inline-code">VITE_OPENFDD_AGENT_WORKDIR</code> in{" "}
            <code className="inline-code">.env.local</code>). Stack URLs are injected every turn. For string metrics / Feather fixes, use the{" "}
            <strong>Plots</strong> page after you load a chart — not here.
          </p>
          <label className="local-codex-workdir-label" htmlFor="ofdd-codex-workdir-input">
            Repo path
          </label>
          <input
            id="ofdd-codex-workdir-input"
            type="text"
            className="local-codex-workdir-input"
            value={workdir}
            onChange={(e) => onWorkdirChange(e.target.value)}
            placeholder="C:\path\to\open-fdd"
            aria-label="Codex working directory on the bridge"
            disabled={sending || !chatEnabled}
            autoComplete="off"
          />
        </div>

        <div className="local-codex-thread" data-testid="local-codex-thread">
          <p className="muted" style={{ margin: "0 0 8px", fontSize: 11, lineHeight: 1.4 }}>
            Conversation and draft are saved in this browser (capped for size). Leaving for Plots or other tabs does not clear it.
          </p>
          {!chatEnabled && authState !== "loading" ? (
            <p className="muted" style={{ margin: 0 }}>
              Sign in above to chat. The bridge runs Codex on this PC using your OpenAI subscription.
            </p>
          ) : lines.length === 0 ? (
            <p className="muted" style={{ margin: 0 }}>
              Ask anything. The agent uses the bridge, MCP RAG (when you call it), and this workdir on the bridge PC.
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
          {sending ? (
            <div
              className="local-codex-msg local-codex-msg-ai local-codex-thinking"
              data-testid="ofdd-codex-thinking"
              aria-live="polite"
              aria-busy="true"
            >
              <div className="local-codex-msg-label">Codex</div>
              <div className="local-codex-thinking-row">
                <CodexBrainIcon />
                <span className="local-codex-thinking-text">{THINKING_PHASES[thinkingPhase]}</span>
              </div>
            </div>
          ) : null}
        </div>
        <div className="local-codex-compose">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Message…"
            aria-label="Chat message"
            rows={3}
            disabled={sending || !chatEnabled}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void sendMessage();
              }
            }}
          />
          <button type="button" disabled={sending || !chatEnabled || !draft.trim()} onClick={() => void sendMessage()}>
            {sending ? "…" : "Send"}
          </button>
        </div>
      </div>
    </section>
  );
}
