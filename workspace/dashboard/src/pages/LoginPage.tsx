import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  devQuickLogin,
  devRunScript,
  fetchAuthStatus,
  isLocalhostHost,
  login,
  sanitizeBridgeBaseOverride,
  setToken,
} from "../lib/api";

export default function LoginPage() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [authRequired, setAuthRequired] = useState(true);
  const [hint, setHint] = useState("");
  const [devBusy, setDevBusy] = useState<string | null>(null);
  const showDevShortcuts =
    typeof window !== "undefined" && isLocalhostHost(window.location.hostname);

  useEffect(() => {
    if (sanitizeBridgeBaseOverride()) {
      setHint("Cleared stale API override — retry sign-in.");
    }
    fetchAuthStatus()
      .then((s) => {
        setAuthRequired(s.auth_required);
        if (!s.auth_required) {
          setToken("open");
          navigate("/");
        }
      })
      .catch((e) => {
        setAuthRequired(true);
        setError(String(e));
      });
  }, [navigate]);

  async function completeLogin(token: string | undefined) {
    if (!token) {
      throw new Error("Login succeeded but no session token was returned.");
    }
    setToken(token);
    navigate("/");
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    const user = username.trim();
    const pass = password.trimEnd();
    if (pass.startsWith("$2b$") || (pass.includes("OFDD_") && pass.includes("PASSWORD_HASH"))) {
      setError(
        "That value is a bcrypt hash, not a login password. Use workspace/bootstrap_credentials.once.txt.",
      );
      return;
    }
    try {
      const res = await login(user, pass);
      await completeLogin(res.token ?? res.access_token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "login failed");
    }
  }

  async function quickSignIn(role: "integrator" | "admin") {
    setDevBusy(role);
    setError("");
    try {
      const res = await devQuickLogin(role);
      if (!res.ok) {
        throw new Error(res.error ?? "dev quick-login failed");
      }
      await completeLogin(res.token ?? res.access_token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "dev quick-login failed");
    } finally {
      setDevBusy(null);
    }
  }

  async function startUiDev() {
    setDevBusy("ui");
    setHint("");
    try {
      const res = await devRunScript("ui_dev");
      if (!res.ok) throw new Error(res.error ?? "failed to start UI dev");
      setHint(res.hint ?? "UI dev server starting — open http://127.0.0.1:5173/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "UI dev start failed");
    } finally {
      setDevBusy(null);
    }
  }

  return (
    <div className="login-page">
      <form className="panel login-card" onSubmit={onSubmit}>
        <h2>Open-FDD sign-in</h2>
        <p className="muted">{authRequired ? "Sign in to continue." : "Auth disabled on bridge (dev only)."}</p>
        {authRequired ? (
          <p className="muted">
            First run: use a password from{" "}
            <code>workspace/bootstrap_credentials.once.txt</code> (created by{" "}
            <code>./scripts/openfdd_auth_init.sh --show-secrets</code>). Do not paste bcrypt hashes
            from <code>auth.env.local</code>.
          </p>
        ) : null}
        {hint ? <p className="muted">{hint}</p> : null}
        <div className="field">
          <label className="field-label" htmlFor="login-username">
            Username
          </label>
          <input
            id="login-username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
          />
        </div>
        <div className="field">
          <label className="field-label" htmlFor="login-password">
            Password
          </label>
          <input
            id="login-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </div>
        {error ? <p className="error">{error}</p> : null}
        <button type="submit">Sign in</button>

        {showDevShortcuts ? (
        <div className="login-dev-actions">
          <p className="muted">Local dev (requires edge OPENFDD_ALLOW_INSECURE_AUTH=1):</p>
          <div className="toolbar">
            <button
              type="button"
              className="secondary-btn"
              disabled={devBusy !== null}
              onClick={() => void quickSignIn("integrator")}
            >
              {devBusy === "integrator" ? "Signing in…" : "Sign in as integrator"}
            </button>
            <button
              type="button"
              className="secondary-btn"
              disabled={devBusy !== null}
              onClick={() => void quickSignIn("admin")}
            >
              {devBusy === "admin" ? "Signing in…" : "Sign in as admin"}
            </button>
            <button
              type="button"
              className="secondary-btn"
              disabled={devBusy !== null}
              onClick={() => void startUiDev()}
            >
              {devBusy === "ui" ? "Starting…" : "Start UI dev (5173)"}
            </button>
          </div>
          <p className="muted">
            Manual password: <code>workspace/bootstrap_credentials.once.txt</code>
          </p>
        </div>
        ) : null}
      </form>
    </div>
  );
}
