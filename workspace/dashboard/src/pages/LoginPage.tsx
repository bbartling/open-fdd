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
        <p className="muted">{authRequired ? "Sign in to continue." : "Auth disabled on bridge (dev only)."}</p>
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
        <p className="muted login-hint">
          Passwords live in <code>workspace/auth.env.local</code> (bcrypt only). If sign-in fails after a rotate,
          restart the bridge and use the password printed by{" "}
          <code>./scripts/openfdd_auth_init.sh --rotate --all --show-secrets</code>.
        </p>
        <button type="submit">Sign in</button>
      </form>
    </div>
  );
}
