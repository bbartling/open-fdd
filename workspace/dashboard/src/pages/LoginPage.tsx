import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchAuthStatus, login, sanitizeBridgeBaseOverride, setToken } from "../lib/api";

export default function LoginPage() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [authRequired, setAuthRequired] = useState(true);

  const [hint, setHint] = useState("");

  useEffect(() => {
    if (sanitizeBridgeBaseOverride()) {
      setHint("Cleared stale localhost API override — retry login.");
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

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const res = await login(username, password);
      setToken(res.token);
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "login failed");
    }
  }

  return (
    <div className="login-page">
      <form className="panel login-card" onSubmit={onSubmit}>
        <h2>Open-FDD sign-in</h2>
        <p className="muted">
          {authRequired ? "Sign in to continue." : "Auth disabled on bridge (dev only)."}
        </p>
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
            placeholder="username"
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
      </form>
    </div>
  );
}
