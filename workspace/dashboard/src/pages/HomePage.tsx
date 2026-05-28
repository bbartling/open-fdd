import { useEffect, useState } from "react";
import { apiFetch } from "../lib/api";

type Health = {
  ok: boolean;
  service: string;
  auth_required: boolean;
  bacnet_poll_csv_exists: boolean;
};

export default function HomePage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    apiFetch<Health>("/health")
      .then(setHealth)
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <div>
      <h2>Overview</h2>
      <p className="muted">
        Python runs on the bridge host (pandas + open_fdd.engine). The browser edits code and
        calls Test — never executes Python locally.
      </p>
      <div className="panel">
        {error ? <p className="error">{error}</p> : null}
        {health ? (
          <ul>
            <li className="ok">Bridge: {health.service}</li>
            <li>Auth required: {String(health.auth_required)}</li>
            <li>BACnet poll CSV present: {String(health.bacnet_poll_csv_exists)}</li>
          </ul>
        ) : (
          <p className="muted">Checking bridge…</p>
        )}
      </div>
      <div className="panel">
        <h3>Agent maintainers</h3>
        <p className="muted">
          Codex CLI, Cursor, Claude Code, or OpenClaw can edit{" "}
          <code>workspace/api</code> and <code>workspace/dashboard</code> using skills{" "}
          <code>fastapi-bridge-api</code> and <code>react-operator-dashboard</code>.
        </p>
      </div>
    </div>
  );
}
