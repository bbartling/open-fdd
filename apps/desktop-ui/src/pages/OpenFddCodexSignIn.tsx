import { bridgeBase } from "../lib/api";
import { useCallback, useEffect, useRef, useState } from "react";

type StartResponse = {
  session_id: string;
  user_code: string;
  verification_url: string;
  interval_ms: number;
  expires_in_seconds: number;
};

type PollResponse = {
  status: "pending" | "complete" | "error";
  message?: string;
  access_token?: string;
  refresh_token?: string;
  expires_at_ms?: number;
};

const OPENCLAW_CODEX_DOC = "https://docs.openclaw.ai/providers/openai";

/**
 * Browser-assisted ChatGPT / Codex device login (same OpenAI device endpoints as OpenClaw).
 * Completes in the Open-FDD bridge; use only on a trusted localhost setup.
 */
export function OpenFddCodexSignIn() {
  const [phase, setPhase] = useState<"idle" | "waiting" | "done" | "err">("idle");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [userCode, setUserCode] = useState("");
  const [verificationUrl, setVerificationUrl] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [statusLine, setStatusLine] = useState("");
  const [tokensJson, setTokensJson] = useState("");
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPoll = useCallback(() => {
    if (pollTimer.current) {
      clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
  }, []);

  const pollOnce = useCallback(
    async (sid: string) => {
      try {
        const res = await fetch(`${bridgeBase}/openfdd-claw/codex/device/poll`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sid }),
        });
        const data = (await res.json()) as PollResponse;
        if (!res.ok) {
          throw new Error((data as { detail?: string }).detail ?? JSON.stringify(data));
        }
        if (data.status === "complete" && data.access_token && data.refresh_token) {
          stopPoll();
          setPhase("done");
          setStatusLine(data.message ?? "Signed in.");
          setTokensJson(
            JSON.stringify(
              {
                access_token: data.access_token,
                refresh_token: data.refresh_token,
                expires_at_ms: data.expires_at_ms,
              },
              null,
              2,
            ),
          );
          return;
        }
        if (data.status === "error") {
          stopPoll();
          setPhase("err");
          setErr(data.message ?? "Sign-in failed.");
          return;
        }
        setStatusLine(data.message ?? "Waiting for browser…");
      } catch (e) {
        stopPoll();
        setPhase("err");
        setErr(e instanceof Error ? e.message : String(e));
      }
    },
    [stopPoll],
  );

  useEffect(() => () => stopPoll(), [stopPoll]);

  async function startSignIn() {
    setBusy(true);
    setErr("");
    setTokensJson("");
    setUserCode("");
    setVerificationUrl("");
    setSessionId("");
    setStatusLine("");
    stopPoll();
    try {
      const res = await fetch(`${bridgeBase}/openfdd-claw/codex/device/start`, { method: "POST" });
      const raw = await res.json();
      if (!res.ok) {
        const detail = typeof raw?.detail === "string" ? raw.detail : JSON.stringify(raw);
        throw new Error(detail);
      }
      const data = raw as StartResponse;
      setSessionId(data.session_id);
      setUserCode(data.user_code);
      setVerificationUrl(data.verification_url);
      setPhase("waiting");
      setStatusLine("Open the sign-in page and log in with your ChatGPT account.");
      pollTimer.current = setInterval(() => {
        void pollOnce(data.session_id);
      }, Math.max(1500, data.interval_ms ?? 5000));
      void pollOnce(data.session_id);
    } catch (e) {
      setPhase("err");
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function openBrowser() {
    if (verificationUrl) {
      window.open(verificationUrl, "_blank", "noopener,noreferrer");
    }
  }

  function reset() {
    stopPoll();
    setPhase("idle");
    setErr("");
    setUserCode("");
    setVerificationUrl("");
    setSessionId("");
    setStatusLine("");
    setTokensJson("");
  }

  return (
    <div className="card openfdd-codex-card">
      <h3 className="title">Sign in with ChatGPT / Codex</h3>
      <p className="muted">
        Same device login OpenClaw uses for <code>openai-codex</code>: we request a short code, you finish in the browser,
        then OpenClaw can call models with your subscription. On a headless Pi, open the link on your phone or laptop.
      </p>
      <ol className="openfdd-codex-steps">
        <li>Click <strong>Start sign-in</strong> below.</li>
        <li>
          Click <strong>Open sign-in page</strong> and log in with OpenAI (enter the code if the page asks for it).
        </li>
        <li>Return here — we detect when you are done.</li>
        <li>
          Keep using <strong>OpenClaw chat</strong> below. If the gateway still says re-auth, run once on the OpenClaw
          host:{" "}
          <code className="inline-code">openclaw models auth login --provider openai-codex</code> — or merge tokens per{" "}
          <a href={OPENCLAW_CODEX_DOC} target="_blank" rel="noreferrer">
            OpenClaw OpenAI provider docs
          </a>
          .
        </li>
      </ol>
      {phase === "idle" || phase === "err" ? (
        <div className="openclaw-actions">
          <button type="button" className="link-btn" disabled={busy} onClick={() => void startSignIn()}>
            {busy ? "Starting…" : "Start sign-in"}
          </button>
          {phase === "err" ? (
            <button type="button" className="secondary-btn" onClick={reset}>
              Try again
            </button>
          ) : null}
        </div>
      ) : null}
      {err ? <p className="cron-hint-box warn">{err}</p> : null}
      {phase === "waiting" ? (
        <div className="openfdd-codex-active">
          <div className="openfdd-user-code">{userCode}</div>
          <p className="muted">{statusLine}</p>
          <div className="openclaw-actions">
            <button type="button" className="link-btn" onClick={openBrowser} disabled={!verificationUrl}>
              Open sign-in page
            </button>
            <button type="button" className="secondary-btn" onClick={reset}>
              Cancel
            </button>
            <span className="muted mono small">session: {sessionId.slice(0, 12)}…</span>
          </div>
        </div>
      ) : null}
      {phase === "done" ? <p className="cron-hint-box ok">{statusLine || "Signed in."}</p> : null}
      {phase === "done" && tokensJson ? (
        <details className="openfdd-token-details">
          <summary>Advanced: OAuth token JSON (local use only)</summary>
          <p className="muted">
            For most setups you do not need this — OpenClaw stores profiles after{" "}
            <code>openclaw models auth login</code>. Power users can merge into <code>~/.openclaw/</code> per OpenClaw
            docs.
          </p>
          <textarea readOnly rows={8} className="mono" value={tokensJson} />
          <div className="openclaw-actions">
            <button
              type="button"
              className="secondary-btn"
              onClick={() => void navigator.clipboard?.writeText(tokensJson)}
            >
              Copy JSON
            </button>
            <button type="button" className="secondary-btn" onClick={reset}>
              Done
            </button>
          </div>
        </details>
      ) : null}
    </div>
  );
}
