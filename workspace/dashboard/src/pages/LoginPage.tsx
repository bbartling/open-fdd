import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchAuthStatus, login, setToken } from "../lib/api";

export default function LoginPage() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("operator");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [authRequired, setAuthRequired] = useState(true);

  useEffect(() => {
    fetchAuthStatus()
      .then((s) => {
        setAuthRequired(s.auth_required);
        if (!s.auth_required) {
          setToken("open");
          navigate("/");
        }
      })
      .catch(() => setAuthRequired(false));
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
        <h2>Operator sign-in</h2>
        <p className="muted">
          {authRequired
            ? "LAN-only dashboard. Set OFDD_AUTH_SECRET, OFDD_WEB_USER, OFDD_WEB_PASSWORD on the bridge host."
            : "Auth disabled on bridge (dev only)."}
        </p>
        <div className="row">
          <label>
            Username
            <input value={username} onChange={(e) => setUsername(e.target.value)} />
          </label>
        </div>
        <div className="row">
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
        </div>
        {error ? <p className="error">{error}</p> : null}
        <button type="submit">Sign in</button>
      </form>
    </div>
  );
}
