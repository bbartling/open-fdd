import { useCallback, useEffect, useState } from "react";
import { AppShell } from "../components/AppShell";
import { Button, InlineAlert, Metric } from "../components/widgets";
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

export function AuthPage() {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [me, setMe] = useState<AuthMe | null>(null);
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onLogin = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await login(username, password);
      setNotice(`Logged in as ${res.subject} (${res.role})`);
      await refresh();
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setBusy(false);
    }
  };

  const onLogout = () => {
    logout();
    setMe(null);
    setNotice("Cleared session token");
  };

  return (
    <AppShell
      title="Auth"
      caption="Thin login against /api/auth/* (P1-M5-F)"
      activeSectionId="overview"
    >
      <div className="page-stack" data-testid="auth-page">
        <InlineAlert id="auth-hint" variant="info">
          When auth is not required, login mints a placeholder Bearer token for
          local session storage.
        </InlineAlert>

        <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
          <Metric
            id="auth-required"
            label="auth_required"
            value={
              status == null ? "—" : status.auth_required ? "true" : "false"
            }
            testId="auth-required"
          />
          <Metric
            id="auth-user"
            label="username"
            value={me?.username ?? "—"}
            testId="auth-user"
          />
          <Metric
            id="auth-role"
            label="role"
            value={me?.role ?? "—"}
            testId="auth-role"
          />
        </div>

        <label htmlFor="auth-username">
          username
          <input
            id="auth-username"
            data-testid="auth-username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </label>
        <label htmlFor="auth-password">
          password
          <input
            id="auth-password"
            data-testid="auth-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>

        <div style={{ display: "flex", gap: "0.5rem" }}>
          <Button
            id="auth-login"
            label={busy ? "…" : "Login"}
            onClick={() => void onLogin()}
            disabled={busy}
            testId="auth-login"
          />
          <Button
            id="auth-logout"
            label="Logout"
            variant="secondary"
            onClick={onLogout}
            testId="auth-logout"
          />
          <Button
            id="auth-refresh"
            label="Refresh"
            variant="secondary"
            onClick={() => void refresh()}
            testId="auth-refresh"
          />
        </div>

        {error ? (
          <InlineAlert id="auth-error" variant="danger" testId="auth-error">
            {error}
          </InlineAlert>
        ) : null}
        {notice ? (
          <InlineAlert id="auth-notice" variant="success" testId="auth-notice">
            {notice}
          </InlineAlert>
        ) : null}
      </div>
    </AppShell>
  );
}
