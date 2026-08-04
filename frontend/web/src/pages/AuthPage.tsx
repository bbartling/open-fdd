import { useCallback, useEffect, useId, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import {
  getAuthMe,
  getAuthStatus,
  login,
  logout,
  type AuthMe,
  type AuthStatus,
} from "../api/authApi";

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function safeReturnPath(raw: string | null): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//")) return "/";
  if (raw.startsWith("/auth") || raw.startsWith("/login")) return "/";
  return raw;
}

/**
 * Dedicated sign-in surface (Streamlit-oracle chrome) — not the app shell.
 * AuthGate sends unauthenticated users here when central requires JWT.
 */
export function AuthPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const returnTo = safeReturnPath(searchParams.get("from"));
  const formId = useId();

  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [me, setMe] = useState<AuthMe | null>(null);
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const st = await getAuthStatus();
      setStatus(st);
      try {
        setMe(await getAuthMe());
      } catch {
        setMe(null);
      }
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onLogin = async (event?: React.FormEvent) => {
    event?.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await login(username, password);
      setNotice(`Signed in as ${res.subject}`);
      await refresh();
      navigate(returnTo, { replace: true });
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setBusy(false);
    }
  };

  const onLogout = () => {
    logout();
    setMe(null);
    setNotice("Signed out");
    setPassword("");
  };

  const signedIn = Boolean(me?.username);

  return (
    <div className="auth-screen" data-testid="auth-page">
      <div className="auth-screen__atmosphere" aria-hidden />
      <main className="auth-screen__panel">
        <p className="auth-screen__brand">Open-FDD</p>
        <h1 className="auth-screen__title">
          {signedIn ? "Session" : "Sign in"}
        </h1>
        <p className="auth-screen__lede">
          {signedIn
            ? "You already have an active central session on this browser."
            : status?.auth_required
              ? "Central requires a password before package import and analytics."
              : "Optional local session token for API calls on this browser."}
        </p>

        <dl className="auth-screen__meta" aria-live="polite">
          <div>
            <dt>Auth required</dt>
            <dd data-testid="auth-required">
              {!ready || status == null
                ? "…"
                : status.auth_required
                  ? "true"
                  : "false"}
            </dd>
          </div>
          <div>
            <dt>User</dt>
            <dd data-testid="auth-user">{me?.username ?? "—"}</dd>
          </div>
          <div>
            <dt>Role</dt>
            <dd data-testid="auth-role">{me?.role ?? "—"}</dd>
          </div>
        </dl>

        {signedIn ? (
          <div className="auth-screen__actions">
            <button
              type="button"
              className="auth-screen__btn auth-screen__btn--primary"
              data-testid="auth-continue"
              onClick={() => navigate(returnTo, { replace: true })}
            >
              Continue to app
            </button>
            <button
              type="button"
              className="auth-screen__btn auth-screen__btn--ghost"
              data-testid="auth-logout"
              onClick={onLogout}
            >
              Sign out
            </button>
          </div>
        ) : (
          <form
            className="auth-screen__form"
            onSubmit={(e) => void onLogin(e)}
            noValidate
          >
            <label className="auth-screen__field" htmlFor={`${formId}-user`}>
              <span>Username</span>
              <input
                id={`${formId}-user`}
                data-testid="auth-username"
                name="username"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </label>
            <label className="auth-screen__field" htmlFor={`${formId}-pass`}>
              <span>Password</span>
              <input
                id={`${formId}-pass`}
                data-testid="auth-password"
                name="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            <div className="auth-screen__actions">
              <button
                type="submit"
                className="auth-screen__btn auth-screen__btn--primary"
                data-testid="auth-login"
                disabled={busy || !password}
              >
                {busy ? "Signing in…" : "Sign in"}
              </button>
              <button
                type="button"
                className="auth-screen__btn auth-screen__btn--ghost"
                data-testid="auth-refresh"
                onClick={() => void refresh()}
              >
                Refresh status
              </button>
            </div>
          </form>
        )}

        {error ? (
          <p className="auth-screen__alert auth-screen__alert--danger" role="alert" data-testid="auth-error">
            {error}
          </p>
        ) : null}
        {notice ? (
          <p className="auth-screen__alert auth-screen__alert--ok" data-testid="auth-notice">
            {notice}
          </p>
        ) : null}

        <p className="auth-screen__footnote">
          Bench password handoff:{" "}
          <code>workspace/bootstrap_credentials.once.txt</code>
          {" · "}
          <Link to="/">Overview</Link>
        </p>
      </main>
    </div>
  );
}
