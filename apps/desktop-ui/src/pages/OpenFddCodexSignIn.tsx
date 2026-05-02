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

/** Where users fix the one-time “allow Codex device sign-in” switch (same account as ChatGPT). */
const CHATGPT_HOME = "https://chatgpt.com/";

function looksLikeDevicePolicyBlock(message: string): boolean {
  const m = message.toLowerCase();
  return (
    m.includes("device code") ||
    m.includes("device auth") ||
    m.includes("enable device") ||
    m.includes("security settings") ||
    m.includes("codex login")
  );
}

/**
 * One-tap ChatGPT / Codex device login: same OpenAI endpoints as OpenClaw.
 * Opens the verification tab automatically after the bridge returns a session.
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
  const isPollingRef = useRef(false);

  const stopPoll = useCallback(() => {
    if (pollTimer.current) {
      clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
  }, []);

  const pollOnce = useCallback(
    async (sid: string) => {
      if (isPollingRef.current) {
        return;
      }
      isPollingRef.current = true;
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
          setStatusLine("Signed in with ChatGPT.");
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
          setErr(data.message ?? "Sign-in did not complete.");
          return;
        }
        setStatusLine("Waiting for ChatGPT to finish…");
      } catch (e) {
        stopPoll();
        setPhase("err");
        setErr(e instanceof Error ? e.message : String(e));
      } finally {
        isPollingRef.current = false;
      }
    },
    [stopPoll],
  );

  useEffect(() => () => stopPoll(), [stopPoll]);

  function openVerificationTab(url: string) {
    // Omit noopener/noreferrer in the features string: some browsers return null from window.open
    // when those flags are set, which makes popup detection misleading. Manual link is always shown.
    window.open(url, "_blank");
  }

  async function continueWithChatGPT() {
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
      setStatusLine("Use the tab that just opened to sign in with ChatGPT.");
      openVerificationTab(data.verification_url);
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

  function reset() {
    stopPoll();
    isPollingRef.current = false;
    setPhase("idle");
    setErr("");
    setUserCode("");
    setVerificationUrl("");
    setSessionId("");
    setStatusLine("");
    setTokensJson("");
  }

  const showChatgptSettingsHint = phase === "err" && err && looksLikeDevicePolicyBlock(err);

  return (
    <div className="card openfdd-codex-card" id="openfdd-codex-auth">
      <h3 className="title">ChatGPT sign-in</h3>
      <p className="muted" style={{ marginBottom: 14 }}>
        Same sign-in flow as OpenClaw: we open ChatGPT in a new tab. Log in there; this page waits and turns green when
        it is done.
      </p>

      {phase === "idle" || phase === "err" ? (
        <div className="openclaw-actions" style={{ flexDirection: "column", alignItems: "stretch", gap: 10 }}>
          <button
            type="button"
            data-testid="ofdd-codex-continue"
            disabled={busy}
            onClick={() => void continueWithChatGPT()}
          >
            {busy ? "Opening ChatGPT…" : "Continue with ChatGPT"}
          </button>
          {phase === "err" ? (
            <button type="button" className="secondary-btn" onClick={reset}>
              Start over
            </button>
          ) : null}
        </div>
      ) : null}

      {err ? (
        <div style={{ marginTop: 12 }}>
          <p className="cron-hint-box warn" style={{ marginBottom: showChatgptSettingsHint ? 10 : 0 }}>
            {err}
          </p>
          {showChatgptSettingsHint ? (
            <div className="openclaw-actions" style={{ flexWrap: "wrap" }}>
              <a className="link-btn" href={CHATGPT_HOME} target="_blank" rel="noreferrer">
                Open ChatGPT
              </a>
              <span className="muted" style={{ fontSize: 13, flex: "1 1 220px" }}>
                In ChatGPT: <strong>Settings</strong> → find the switch for <strong>Codex</strong> /{" "}
                <strong>device</strong> / <strong>CLI</strong> sign-in and turn it <strong>on</strong> (one time per
                account). Then press <strong>Continue with ChatGPT</strong> again here.
              </span>
            </div>
          ) : null}
        </div>
      ) : null}

      {phase === "waiting" ? (
        <div className="openfdd-codex-active" style={{ marginTop: 12 }}>
          <div className="openclaw-actions" style={{ flexWrap: "wrap", marginBottom: 8 }}>
            <a className="link-btn" href={verificationUrl || "#"} target="_blank" rel="noreferrer">
              Open ChatGPT sign-in
            </a>
            <button type="button" className="secondary-btn" onClick={reset}>
              Cancel
            </button>
          </div>
          <p className="muted" style={{ marginBottom: 6 }}>
            {statusLine}
          </p>
          {userCode ? (
            <p className="muted" style={{ fontSize: 12, marginTop: 0 }}>
              If ChatGPT asks for a code, use: <span className="openfdd-user-code" style={{ fontSize: "1rem" }}>{userCode}</span>
            </p>
          ) : null}
        </div>
      ) : null}

      {phase === "done" ? (
        <div style={{ marginTop: 8 }}>
          <p className="cron-hint-box ok">{statusLine || "Signed in."}</p>
          <p className="muted" style={{ marginTop: 8 }}>
            Scroll down to the OpenClaw chat. If it still asks you to sign in, do that once inside the chat frame.
          </p>
          {tokensJson ? (
            <details className="openfdd-token-details" style={{ marginTop: 10 }}>
              <summary className="muted">Technical: token JSON (optional)</summary>
              <textarea readOnly rows={6} className="mono" value={tokensJson} spellCheck={false} />
              <div className="openclaw-actions" style={{ marginTop: 8 }}>
                <button
                  type="button"
                  className="secondary-btn"
                  onClick={() => void navigator.clipboard?.writeText(tokensJson)}
                >
                  Copy
                </button>
                <button type="button" className="secondary-btn" onClick={reset}>
                  Done
                </button>
              </div>
            </details>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
