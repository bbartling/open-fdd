import { bridgeFetch, bridgeBase, desktopFetch } from "../lib/api";
import { classifyOpenfddTaskPreview } from "../lib/openfdd-agent-route-preview";
import {
  loadCodexSessionBundle,
  persistCodexSessionBundle,
  pushNewAgentSession,
  selectSession,
  titleFromFirstUserMessage,
  updateActiveSession,
  updateSessionById,
  type AgentRouteMeta,
  type ChatLine,
  type CodexSessionBundle,
} from "../lib/local-codex-sessions";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

const WORKDIR_STORAGE_KEY = "ofdd-local-codex-workdir";

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

type CodexExecEnvPayload = {
  ask_for_approval: string;
  sandbox_mode: string;
  workspace_write_network?: boolean | null;
  model_simple?: string;
  model_complex_primary?: string;
  model_complex_fallback?: string;
  llm_route_classify?: boolean;
  /** Bridge retries once as COMPLEX when auto SIMPLE Codex fails (`OFDD_AGENT_ESCALATE_ON_FAILURE`). */
  escalate_simple_failure_to_complex?: boolean;
};

type DiagnosticsPayload = {
  codex_path: string | null;
  login_status: { returncode: number; stdout: string; stderr: string; logged_in: boolean } | null;
  hints: string[];
  exec_env?: CodexExecEnvPayload | null;
};

type AiDepsHealthPayload = {
  mcp_rest_base: string;
  mcp_reachable: boolean;
  mcp_error?: string | null;
  openclaw_gateway_url: string;
  openclaw_reachable: boolean;
  openclaw_error?: string | null;
  openclaw_token_set: boolean;
};

type ChatResponse = {
  run_id?: string;
  status?: "queued" | "running" | "completed";
  returncode: number;
  stdout: string;
  stderr: string;
  ok?: boolean;
  task_class?: string;
  route_reason?: string;
  codex_model?: string;
  codex_model_attempts?: string[];
  codex_model_fallback_used?: boolean;
  human_route?: boolean;
  simple_failure_escalated?: boolean;
  result?: ChatResponse;
  critic_used?: boolean;
  critic_model?: string;
};

type AgentQueueStatus = {
  paused: boolean;
  queue_size: number;
  queued_run_ids: string[];
  running?: { run_id: string; started_at?: string } | null;
};

function routeMetaFromAgentResponse(data: ChatResponse): AgentRouteMeta | undefined {
  const tc = data.task_class;
  if (tc !== "simple" && tc !== "complex") return undefined;
  const meta: AgentRouteMeta = { task_class: tc };
  if (typeof data.codex_model === "string" && data.codex_model.trim()) {
    meta.codex_model = data.codex_model.trim();
  }
  if (typeof data.route_reason === "string" && data.route_reason.trim()) {
    meta.route_reason = data.route_reason.trim();
  }
  if (Array.isArray(data.codex_model_attempts) && data.codex_model_attempts.length > 0) {
    meta.attempts = data.codex_model_attempts.map(String);
  }
  if (data.codex_model_fallback_used === true) {
    meta.fallback_used = true;
  }
  if (data.human_route === true) {
    meta.human_requested = true;
  }
  if (data.simple_failure_escalated === true) {
    meta.simple_failure_escalated = true;
  }
  return meta;
}

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
    return {
      state: "no_cli",
      line: "The built-in agent CLI is not installed on the bridge PC (or not on PATH).",
    };
  }
  const st = d.login_status;
  if (!st) {
    return { state: "needs_login", line: "Agent CLI is present; sign in on the bridge to continue." };
  }
  if (st.logged_in) {
    return { state: "signed_in", line: "Signed in." };
  }
  return { state: "needs_login", line: "Agent CLI is present; sign in on the bridge to continue." };
}

/** Stylized “code” mark for the tab (not an official third-party logo). */
function CodexBrandMark() {
  return (
    <svg className="local-codex-brand-mark" viewBox="0 0 48 48" fill="none" aria-hidden>
      <defs>
        <linearGradient id="lcxBrandFill" x1="8" y1="8" x2="40" y2="40" gradientUnits="userSpaceOnUse">
          <stop stopColor="var(--primary)" stopOpacity="0.35" />
          <stop offset="1" stopColor="var(--primary-strong)" stopOpacity="0.12" />
        </linearGradient>
      </defs>
      <rect x="4" y="4" width="40" height="40" rx="12" fill="url(#lcxBrandFill)" stroke="var(--primary)" strokeWidth="1.25" strokeOpacity="0.45" />
      <path
        d="M18 17l-6 7 6 7M30 17l6 7-6 7M27 15l-6 18"
        stroke="var(--primary)"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function AgentRouteCallout({ route }: { route: AgentRouteMeta }) {
  const tier = route.task_class;
  const label = tier === "simple" ? "SIMPLE" : "COMPLEX";
  return (
    <div className={`local-codex-route-bar local-codex-route-bar--${tier}`} title={route.route_reason || undefined}>
      <span className="local-codex-route-tier">{label}</span>
      {route.codex_model ? <span className="local-codex-route-model">{route.codex_model}</span> : null}
      {route.human_requested ? <span className="local-codex-route-human-flag">human-requested</span> : null}
      {route.simple_failure_escalated ? <span className="local-codex-route-escalated-flag">auto-escalated</span> : null}
      {route.fallback_used ? <span className="local-codex-route-fallback-flag">fallback</span> : null}
      {route.route_reason ? <span className="local-codex-route-reason">{route.route_reason}</span> : null}
    </div>
  );
}

function renderRichMessageContent(text: string): ReactNode {
  const parts = text.split(/(`[^`]*`)/g);
  return parts.map((part, i) => {
    if (part.length >= 2 && part.startsWith("`") && part.endsWith("`")) {
      return (
        <code key={i} className="local-codex-msg-code">
          {part.slice(1, -1)}
        </code>
      );
    }
    return <span key={i}>{part}</span>;
  });
}

function AgentBrainIcon() {
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

export function AiAgentChatPage() {
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
  const [signInBusy, setSignInBusy] = useState(false);
  const signInInFlightRef = useRef(false);
  const [deviceSession, setDeviceSession] = useState<DeviceSession | null>(null);
  const [signInActionError, setSignInActionError] = useState<string | null>(null);
  const [signOutBusy, setSignOutBusy] = useState(false);
  const [signOutError, setSignOutError] = useState<string | null>(null);
  const [execEnv, setExecEnv] = useState<CodexExecEnvPayload | null>(null);
  const [aiDeps, setAiDeps] = useState<AiDepsHealthPayload | null>(null);
  const [agentQueue, setAgentQueue] = useState<AgentQueueStatus | null>(null);
  const [agentControlBusy, setAgentControlBusy] = useState(false);
  const [agentControlError, setAgentControlError] = useState<string | null>(null);

  const [sessionBundle, setSessionBundle] = useState<CodexSessionBundle>(() => loadCodexSessionBundle());
  const bundleRef = useRef(sessionBundle);
  bundleRef.current = sessionBundle;

  const activeSession = useMemo(
    () => sessionBundle.sessions.find((s) => s.id === sessionBundle.activeId) ?? sessionBundle.sessions[0],
    [sessionBundle],
  );
  const lines = activeSession.lines;
  const draft = activeSession.draft;

  const [sending, setSending] = useState(false);
  /** Heuristic preview only; bridge may differ when LLM classify or OFDD_AGENT_ROUTE_DEFAULT is set. */
  const [sendingRoutePreview, setSendingRoutePreview] = useState<"simple" | "complex" | null>(null);
  const [sendMode, setSendMode] = useState<"run_now" | "queue">("run_now");
  /** True when the last send used the split-button COMPLEX (human-requested) path. */
  const [thinkingHumanRequested, setThinkingHumanRequested] = useState(false);
  const [sendMenuOpen, setSendMenuOpen] = useState(false);
  const sendSplitRef = useRef<HTMLDivElement | null>(null);
  const [thinkingPhase, setThinkingPhase] = useState(0);
  const phaseTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const devicePollMounted = useRef(true);

  useEffect(() => {
    const persistNow = () => persistCodexSessionBundle(bundleRef.current);
    const id = window.setTimeout(persistNow, 320);
    return () => {
      window.clearTimeout(id);
      persistNow();
    };
  }, [sessionBundle]);

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
      try {
        const deps = await desktopFetch<AiDepsHealthPayload>("/assistant/ai-health");
        setAiDeps(deps);
      } catch {
        setAiDeps(null);
      }
      try {
        const q = await desktopFetch<AgentQueueStatus>("/openfdd-agent/status");
        setAgentQueue(q);
      } catch {
        setAgentQueue(null);
      }
    } catch (e) {
      setAuthState("error");
      setAuthLine(e instanceof Error ? e.message : String(e));
    }
  }, [pullDiagnostics]);

  const setAgentPaused = useCallback(async (paused: boolean) => {
    setAgentControlBusy(true);
    setAgentControlError(null);
    try {
      const data = await desktopFetch<AgentQueueStatus>("/openfdd-agent/control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paused }),
      });
      setAgentQueue(data);
    } catch (e) {
      setAgentControlError(e instanceof Error ? e.message : String(e));
    } finally {
      setAgentControlBusy(false);
    }
  }, []);

  const signOutAgentCli = useCallback(async () => {
    setSignOutError(null);
    setSignOutBusy(true);
    try {
      const res = await fetch(`${bridgeBase}/local-codex/logout`, { method: "POST" });
      const data = (await res.json()) as {
        ok?: boolean;
        stdout?: string;
        stderr?: string;
        returncode?: number;
        detail?: string;
      };
      if (!res.ok) {
        setSignOutError(typeof data.detail === "string" ? data.detail : `Request failed (${res.status}).`);
        return;
      }
      if (data.ok === false) {
        setSignOutError([data.stderr, data.stdout].filter(Boolean).join("\n").trim() || "Sign out failed.");
        return;
      }
      await pullDiagnostics({ silent: false });
    } catch (e) {
      setSignOutError(e instanceof Error ? e.message : String(e));
    } finally {
      setSignOutBusy(false);
    }
  }, [bridgeBase, pullDiagnostics]);

  useEffect(() => {
    void refreshAuth();
  }, [refreshAuth]);

  useEffect(() => {
    if (!deviceSession) {
      return undefined;
    }
    const { sessionId, pollMs } = deviceSession;
    let cancelled = false;

    const tick = async (): Promise<boolean> => {
      try {
        const res = await fetch(`${bridgeBase}/openfdd-claw/codex/device/poll`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId }),
        });
        const body = (await res.json()) as { status?: string; message?: string; detail?: string };
        if (cancelled || !devicePollMounted.current) {
          return false;
        }
        if (!res.ok) {
          setDeviceSession(null);
          setAuthState("error");
          setAuthLine(typeof body.detail === "string" ? body.detail : JSON.stringify(body));
          return false;
        }
        if (body.status === "complete") {
          setDeviceSession(null);
          try {
            const st = await pullDiagnostics({ silent: true });
            if (st === "needs_login") {
              setPostOAuthHint(
                "Browser sign-in finished. If the agent still shows as signed out, on the bridge PC run: codex login — then use Retry below.",
              );
            }
          } catch (e) {
            setAuthState("error");
            setAuthLine(e instanceof Error ? e.message : String(e));
          }
          return false;
        }
        if (body.status === "error") {
          setDeviceSession(null);
          setAuthState("error");
          setAuthLine(body.message || "Device sign-in failed.");
          return false;
        }
        return true;
      } catch (e) {
        if (cancelled || !devicePollMounted.current) {
          return false;
        }
        setDeviceSession(null);
        setAuthState("error");
        setAuthLine(e instanceof Error ? e.message : String(e));
        return false;
      }
    };

    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    const runSequentialPoll = async () => {
      if (cancelled || !devicePollMounted.current) {
        return;
      }
      const continuePolling = await tick();
      if (cancelled || !devicePollMounted.current || !continuePolling) {
        return;
      }
      timeoutId = window.setTimeout(() => void runSequentialPoll(), pollMs);
    };
    void runSequentialPoll();
    return () => {
      cancelled = true;
      if (timeoutId != null) {
        window.clearTimeout(timeoutId);
        timeoutId = null;
      }
    };
  }, [deviceSession, bridgeBase, pullDiagnostics]);

  const runAutomatedSignIn = useCallback(async () => {
    if (signInInFlightRef.current) {
      return;
    }
    signInInFlightRef.current = true;
    setSignInBusy(true);
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
            setAuthLine("Could not install the agent CLI via npm.");
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
          "Agent CLI is still not on PATH after install. Restart the bridge process or set OFDD_CODEX_CMD to the full path to the codex executable (e.g. codex or codex.cmd).",
        );
        setAuthState("error");
        setAuthLine("Agent CLI not found after npm install.");
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
    } finally {
      signInInFlightRef.current = false;
      setSignInBusy(false);
    }
  }, [bridgeBase, pullDiagnostics]);

  const sendMessage = useCallback(async (humanRequestedComplex = false) => {
    const b = bundleRef.current;
    const sessionId = b.activeId;
    const active = b.sessions.find((s) => s.id === sessionId);
    const text = (active?.draft ?? "").trim();
    if (!active || !text || sending || authState !== "signed_in") {
      return;
    }
    setSendMenuOpen(false);
    const workdirSnapshot = workdir.trim() || null;
    const conversationHistory = active.lines.slice(-120).map((ln) => ({ role: ln.role, text: ln.text }));
    const requestedHumanComplex = humanRequestedComplex;
    setSending(true);
    setThinkingHumanRequested(requestedHumanComplex);
    setSendingRoutePreview(requestedHumanComplex ? "complex" : classifyOpenfddTaskPreview(text));
    setSessionBundle((prev) =>
      updateSessionById(prev, sessionId, (s) => {
        const nextLines: ChatLine[] = [...s.lines, { role: "user", text }];
        const title =
          s.title === "New agent" && s.lines.length === 0
            ? titleFromFirstUserMessage(nextLines, "New agent")
            : s.title;
        return { ...s, draft: "", lines: nextLines, title, updatedAt: Date.now() };
      }),
    );
    try {
      const res = await fetch(`${bridgeBase}/openfdd-agent/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          mode: sendMode,
          workdir: workdirSnapshot,
          task_summary: null,
          conversation_history: conversationHistory,
          human_requested_complex: requestedHumanComplex,
        }),
      });
      const data = (await res.json()) as ChatResponse & { detail?: string };
      if (!res.ok) {
        const detail = typeof data?.detail === "string" ? data.detail : JSON.stringify(data);
        setSessionBundle((prev) =>
          updateSessionById(prev, sessionId, (s) => ({
            ...s,
            lines: [...s.lines, { role: "assistant", text: `Request failed (${res.status}):\n${detail}` }],
            updatedAt: Date.now(),
          })),
        );
        return;
      }
      if (data.status === "queued" && data.run_id) {
        const pollSessionId = sessionId;
        setSessionBundle((prev) =>
          updateSessionById(prev, sessionId, (s) => ({
            ...s,
            lines: [...s.lines, { role: "assistant", text: `Queued: ${data.run_id}. Waiting for runner…` }],
            updatedAt: Date.now(),
          })),
        );
        let delayMs = 900;
        const maxDelayMs = 12_000;
        const deadline = Date.now() + 12 * 60 * 1000;
        let done: ChatResponse | null = null;
        while (Date.now() < deadline) {
          if (!devicePollMounted.current || bundleRef.current.activeId !== pollSessionId) {
            return;
          }
          await new Promise((resolve) => window.setTimeout(resolve, delayMs));
          delayMs = Math.min(Math.floor(delayMs * 1.38), maxDelayMs);
          if (!devicePollMounted.current || bundleRef.current.activeId !== pollSessionId) {
            return;
          }
          try {
            const poll = await bridgeFetch(`/openfdd-agent/runs/${encodeURIComponent(data.run_id)}`);
            if (!poll.ok) {
              continue;
            }
            const row = (await poll.json()) as ChatResponse;
            if (row.status === "completed") {
              done = (row.result ?? row) as ChatResponse;
              break;
            }
          } catch {
            continue;
          }
        }
        if (!done) {
          setSessionBundle((prev) =>
            updateSessionById(prev, pollSessionId, (s) => ({
              ...s,
              lines: [
                ...s.lines,
                {
                  role: "assistant",
                  text: `Run ${data.run_id} still pending after an extended wait (backoff polling, up to ~12 minutes). Check runner queue or retry shortly.`,
                },
              ],
              updatedAt: Date.now(),
            })),
          );
          return;
        }
        const doneOut =
          done.stdout?.trim() ||
          (done.stderr?.trim() ? `Agent CLI exited ${done.returncode}.\n\nstderr:\n${done.stderr.trim()}` : "(No output.)");
        const doneRoute = routeMetaFromAgentResponse(done);
        setSessionBundle((prev) =>
          updateSessionById(prev, pollSessionId, (s) => ({
            ...s,
            lines: [
              ...s.lines,
              doneRoute ? { role: "assistant", text: doneOut, route: doneRoute } : { role: "assistant", text: doneOut },
            ],
            updatedAt: Date.now(),
          })),
        );
        return;
      }
      const out =
        data.stdout?.trim() ||
        (data.stderr?.trim()
          ? `Agent CLI exited ${data.returncode}.\n\nstderr:\n${data.stderr.trim()}`
          : "(No output.)");
      const outWithCritic =
        data.critic_used && data.critic_model
          ? `${out}\n\n---\nFinal-pass critique applied (${data.critic_model}).`
          : out;
      const route = routeMetaFromAgentResponse(data);
      setSessionBundle((prev) =>
        updateSessionById(prev, sessionId, (s) => ({
          ...s,
          lines: [
            ...s.lines,
            route ? { role: "assistant", text: outWithCritic, route } : { role: "assistant", text: outWithCritic },
          ],
          updatedAt: Date.now(),
        })),
      );
    } catch (e) {
      setSessionBundle((prev) =>
        updateSessionById(prev, sessionId, (s) => ({
          ...s,
          lines: [...s.lines, { role: "assistant", text: e instanceof Error ? e.message : String(e) }],
          updatedAt: Date.now(),
        })),
      );
    } finally {
      setThinkingHumanRequested(false);
      setSendingRoutePreview(null);
      setSending(false);
    }
  }, [authState, sending, workdir, bridgeBase, sendMode]);

  useEffect(() => {
    if (!sendMenuOpen) return;
    const onDoc = (ev: MouseEvent) => {
      if (sendSplitRef.current && !sendSplitRef.current.contains(ev.target as Node)) {
        setSendMenuOpen(false);
      }
    };
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") setSendMenuOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [sendMenuOpen]);

  const chatEnabled = authState === "signed_in";
  const devicePending = deviceSession !== null;
  const signInControlsBusy = authState === "loading" || npmBusy || signInBusy || devicePending;

  const signInButtonLabel =
    authState === "error"
      ? "Try sign-in again"
      : authState === "no_cli"
        ? "Install agent CLI & sign in"
        : "Sign into OpenAI";

  return (
    <section className="stack-page local-codex-page" data-testid="ofdd-agent-page">
      <div className="card local-codex-auth-card">
        <div className="local-codex-auth-header">
          <div className="local-codex-auth-brand" aria-hidden>
            <CodexBrandMark />
          </div>
          <div className="local-codex-auth-titles">
            <h2 className="title local-codex-auth-title" data-testid="ofdd-agent-chat-heading">
              AI Agent
            </h2>
            <p className="local-codex-auth-subtitle">OpenAI Codex on the bridge · local CLI</p>
          </div>
        </div>

        {authState === "loading" ? (
          <p className="muted local-codex-auth-loading" style={{ margin: 0 }}>
            Checking Codex on the bridge…
          </p>
        ) : authState === "signed_in" ? (
          <>
            <div className="local-codex-auth-status-row">
              <span className="local-codex-status-pill local-codex-status-pill--ok">Signed in</span>
              <button
                type="button"
                className="local-codex-btn-outline"
                disabled={agentControlBusy || sending || agentQueue === null}
                onClick={() => {
                  if (agentQueue === null) return;
                  void setAgentPaused(!agentQueue.paused);
                }}
                title={
                  agentQueue === null
                    ? "Runner status unavailable (refresh signing block above)."
                    : "Pause/resume agent runner; queued requests wait while paused."
                }
              >
                {agentControlBusy ? "Updating…" : agentQueue === null ? "Runner status unavailable" : agentQueue.paused ? "Resume runner" : "Pause runner"}
              </button>
              <button
                type="button"
                className="local-codex-btn-outline"
                data-testid="local-codex-sign-out"
                disabled={signOutBusy || sending}
                onClick={() => void signOutAgentCli()}
              >
                {signOutBusy ? "Signing out…" : "Sign out of Codex"}
              </button>
            </div>
            {agentQueue ? (
              <p className="muted" style={{ margin: "8px 0 0", fontSize: 12 }}>
                Runner: {agentQueue.paused ? "paused" : "active"} · queued: {agentQueue.queue_size}
              </p>
            ) : null}
            {agentControlError ? (
              <p className="muted local-codex-auth-error" style={{ margin: "8px 0 0", whiteSpace: "pre-wrap" }}>
                {agentControlError}
              </p>
            ) : null}
            {signOutError ? (
              <p className="muted local-codex-auth-error" style={{ margin: "8px 0 0", whiteSpace: "pre-wrap" }}>
                {signOutError}
              </p>
            ) : null}
            {execEnv?.model_simple && execEnv.model_complex_primary ? (
              <div className="local-codex-model-chips" data-testid="local-codex-model-chips" aria-label="Model routing">
                <span className="local-codex-model-chip local-codex-model-chip--simple">
                  SIMPLE <span className="local-codex-model-chip-mono">{execEnv.model_simple}</span>
                </span>
                <span className="local-codex-model-chip local-codex-model-chip--complex">
                  COMPLEX <span className="local-codex-model-chip-mono">{execEnv.model_complex_primary}</span>
                </span>
                {execEnv.model_complex_fallback ? (
                  <span className="local-codex-model-chip local-codex-model-chip--fallback">
                    fallback <span className="local-codex-model-chip-mono">{execEnv.model_complex_fallback}</span>
                  </span>
                ) : null}
                {execEnv.llm_route_classify ? (
                  <span className="local-codex-model-chip local-codex-model-chip--accent">LLM classify</span>
                ) : null}
                {execEnv.escalate_simple_failure_to_complex === false ? (
                  <span
                    className="local-codex-model-chip"
                    title="OFDD_AGENT_ESCALATE_ON_FAILURE=0 — no automatic COMPLEX retry after SIMPLE failure"
                  >
                    no auto-escalate
                  </span>
                ) : null}
              </div>
            ) : null}
            {aiDeps ? (
              <div className="local-codex-model-chips" style={{ marginTop: 8 }}>
                <span className={`local-codex-model-chip ${aiDeps.mcp_reachable ? "local-codex-model-chip--simple" : "local-codex-model-chip--fallback"}`}>
                  MCP {aiDeps.mcp_reachable ? "ok" : "down"}
                </span>
                <span
                  className={`local-codex-model-chip ${aiDeps.openclaw_reachable ? "local-codex-model-chip--complex" : "local-codex-model-chip--fallback"}`}
                  title={aiDeps.openclaw_gateway_url}
                >
                  OpenClaw {aiDeps.openclaw_reachable ? "ok" : "down"}
                </span>
                <span className={`local-codex-model-chip ${aiDeps.openclaw_token_set ? "local-codex-model-chip--simple" : "local-codex-model-chip--fallback"}`}>
                  Token {aiDeps.openclaw_token_set ? "set" : "missing"}
                </span>
              </div>
            ) : null}
          </>
        ) : (
          <>
            <p className="muted" style={{ margin: "0 0 10px", color: "var(--danger)" }}>
              {authLine}
            </p>
            {npmBusy ? (
              <p className="muted" style={{ margin: "0 0 10px", fontSize: 13 }}>
                Installing agent CLI on the bridge: <code className="inline-code">npm install -g @openai/codex</code>
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
            <div className="local-codex-auth-actions">
              <button
                type="button"
                className="local-codex-btn-primary local-codex-signin-primary"
                disabled={signInControlsBusy}
                onClick={() => void runAutomatedSignIn()}
              >
                {signInControlsBusy && !deviceSession ? "Please wait…" : signInButtonLabel}
              </button>
              <button
                type="button"
                className="local-codex-btn-outline"
                disabled={signInControlsBusy}
                onClick={() => void refreshAuth()}
              >
                Retry check
              </button>
            </div>
          </>
        )}
      </div>

      <div className="card local-codex-chat-card">
        <div className="local-codex-layout">
          {chatEnabled ? (
            <aside className="local-codex-agents-rail" data-testid="local-codex-agents-rail" aria-label="Agent sessions">
              <button
                type="button"
                className="local-codex-new-agent-btn local-codex-btn-primary"
                data-testid="local-codex-new-agent"
                disabled={sending}
                onClick={() => setSessionBundle((b) => pushNewAgentSession(b))}
              >
                New agent
              </button>
              <ul className="local-codex-agents-list">
                {sessionBundle.sessions.map((s) => (
                  <li key={s.id}>
                    <button
                      type="button"
                      className={`local-codex-agent-row${s.id === sessionBundle.activeId ? " is-active" : ""}`}
                      data-testid="local-codex-agent-row"
                      data-session-id={s.id}
                      onClick={() => setSessionBundle((b) => selectSession(b, s.id))}
                    >
                      <span className="local-codex-agent-title">{s.title}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </aside>
          ) : null}
          <div className="local-codex-chat-main">
        <div className="local-codex-workdir-block">
          <label className="local-codex-workdir-label" htmlFor="ofdd-codex-workdir-input">
            Open-FDD path
          </label>
          <input
            id="ofdd-codex-workdir-input"
            type="text"
            className="local-codex-workdir-input"
            value={workdir}
            onChange={(e) => onWorkdirChange(e.target.value)}
            placeholder={"C:\\path\\to\\open-fdd"}
            aria-label="Open-FDD repository path on the bridge"
            disabled={sending || !chatEnabled}
            autoComplete="off"
          />
        </div>

        <div className="local-codex-thread" data-testid="local-codex-thread">
          <p className="local-codex-thread-hint muted">
            Up to five threads saved in this browser (oldest dropped when you start a sixth). Drafts persist across tabs.
            <strong> Auto routing</strong> picks SIMPLE vs COMPLEX from your text (and optional bridge LLM classify); if SIMPLE
            Codex exits with an error, the bridge retries once as <strong>COMPLEX</strong> (
            <code className="inline-code">OFDD_AGENT_ESCALATE_ON_FAILURE</code>, default on). The <strong>Send ▾</strong> menu
            offers a <strong> human-requested COMPLEX</strong> pass. While Codex runs, the colored strip previews the tier; reply
            headers show the bridge&apos;s actual route and chips for human-requested or auto-escalation.
          </p>
          {!chatEnabled && authState !== "loading" ? (
            <p className="muted" style={{ margin: 0 }}>
              Sign in above to chat. Codex runs on the bridge with your OpenAI subscription.
            </p>
          ) : lines.length === 0 ? (
            <p className="local-codex-empty-hint muted">
              Ask anything. Codex can use the bridge, MCP RAG, and this repo path on the bridge PC.
            </p>
          ) : (
            lines.map((ln, i) => (
              <div
                key={`${activeSession.id}-${i}-${ln.role}`}
                className={`local-codex-msg ${ln.role === "user" ? "local-codex-msg-user" : "local-codex-msg-ai"}`}
              >
                <div className="local-codex-msg-label">{ln.role === "user" ? "You" : "Codex"}</div>
                <div className="local-codex-msg-body">
                  {ln.role === "assistant" && ln.route ? <AgentRouteCallout route={ln.route} /> : null}
                  {renderRichMessageContent(ln.text)}
                </div>
              </div>
            ))
          )}
          {sending ? (
            <div
              className={`local-codex-msg local-codex-msg-ai local-codex-thinking${
                sendingRoutePreview === "simple"
                  ? " local-codex-thinking--simple"
                  : sendingRoutePreview === "complex"
                    ? " local-codex-thinking--complex"
                    : " local-codex-thinking--neutral"
              }`}
              data-testid="ofdd-agent-thinking"
              aria-live="polite"
              aria-busy="true"
            >
              <div className="local-codex-msg-label">Codex</div>
              <div className="local-codex-thinking-row">
                <AgentBrainIcon />
                <span
                  className={`local-codex-thinking-text${
                    sendingRoutePreview === "simple"
                      ? " local-codex-thinking-text--simple"
                      : sendingRoutePreview === "complex"
                        ? " local-codex-thinking-text--complex"
                        : ""
                  }`}
                >
                  {THINKING_PHASES[thinkingPhase]}
                  {thinkingHumanRequested ? (
                    <span className="muted" style={{ display: "block", marginTop: 4, fontSize: 11, fontWeight: 500 }}>
                      Sending as human-requested <strong>COMPLEX</strong> (strong model on the bridge)
                    </span>
                  ) : sendingRoutePreview ? (
                    <span className="muted" style={{ display: "block", marginTop: 4, fontSize: 11, fontWeight: 500 }}>
                      Preview route: {sendingRoutePreview === "simple" ? "SIMPLE" : "COMPLEX"} (bridge may override)
                    </span>
                  ) : null}
                </span>
              </div>
            </div>
          ) : null}
        </div>
        <div className="local-codex-compose">
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
            <label htmlFor="ofdd-agent-send-mode" className="muted" style={{ fontSize: 12 }}>
              Delivery
            </label>
            <select
              id="ofdd-agent-send-mode"
              value={sendMode}
              disabled={sending || !chatEnabled}
              onChange={(e) => setSendMode(e.target.value === "queue" ? "queue" : "run_now")}
              style={{ minWidth: 120 }}
            >
              <option value="run_now">Run now</option>
              <option value="queue">Queued mode</option>
            </select>
            <span className="muted" style={{ fontSize: 12 }}>
              {sendMode === "queue" ? "Message enqueued for worker." : "Runs immediately unless runner is busy."}
            </span>
          </div>
          <div className="local-codex-compose-row">
            <textarea
              className="local-codex-compose-input"
              value={draft}
              onChange={(e) =>
                setSessionBundle((prev) => updateActiveSession(prev, (s) => ({ ...s, draft: e.target.value })))
              }
              placeholder="Message Codex… (Shift+Enter for newline)"
              aria-label="Chat message"
              rows={3}
              disabled={sending || !chatEnabled}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void sendMessage(false);
                }
              }}
            />
            <div className="local-codex-send-split" ref={sendSplitRef}>
              <button
                type="button"
                className="local-codex-send-split-main"
                data-testid="ofdd-agent-send"
                disabled={sending || !chatEnabled || !draft.trim()}
                onClick={() => void sendMessage(false)}
              >
                {sending ? "…" : "Send"}
              </button>
              <button
                type="button"
                className="local-codex-send-split-trigger"
                data-testid="ofdd-agent-send-menu-trigger"
                disabled={sending || !chatEnabled || !draft.trim()}
                aria-label="Send options"
                aria-haspopup="menu"
                aria-expanded={sendMenuOpen}
                onClick={() => setSendMenuOpen((o) => !o)}
              >
                ▾
              </button>
              {sendMenuOpen ? (
                <div className="local-codex-send-split-menu" role="menu" aria-label="Send with routing">
                  <button
                    type="button"
                    role="menuitem"
                    className="local-codex-send-split-menu-item"
                    data-testid="ofdd-send-complex-review"
                    title="Uses the bridge COMPLEX tier and strong model for this message only."
                    onClick={() => void sendMessage(true)}
                  >
                    COMPLEX review
                    <span className="local-codex-send-split-menu-desc">
                      Strong model · audits &amp; second opinions
                    </span>
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        </div>
          </div>
        </div>
      </div>
    </section>
  );
}
