import { useEffect, useState } from "react";
import { apiFetch } from "../lib/api";

type BacnetConfig = {
  points_exists: boolean;
  poll_exists: boolean;
  poll_csv: string;
  toolshed_readme: string;
};

export default function BacnetPage() {
  const [cfg, setCfg] = useState<BacnetConfig | null>(null);
  const [log, setLog] = useState("");

  useEffect(() => {
    apiFetch<BacnetConfig>("/config/bacnet").then(setCfg).catch((e) => setLog(String(e)));
  }, []);

  async function ingest() {
    try {
      const res = await apiFetch<{ ok: boolean; rows: number; feather_path: string }>(
        "/ingest/bacnet?site_id=demo",
        { method: "POST" },
      );
      setLog(`Ingested ${res.rows} rows → ${res.feather_path}`);
    } catch (e) {
      setLog(String(e));
    }
  }

  return (
    <div>
      <h2>BACnet toolshed</h2>
      <p className="muted">
        Edge CLIs live in <code>bacnet_toolshed/</code>. Poll CSV → bridge ingest → feather store.
      </p>
      <div className="panel">
        {cfg ? (
          <ul>
            <li>points.csv: {String(cfg.points_exists)}</li>
            <li>poll CSV: {cfg.poll_csv} ({String(cfg.poll_exists)})</li>
          </ul>
        ) : (
          <p className="muted">Loading…</p>
        )}
        <div className="row">
          <button type="button" onClick={ingest} disabled={!cfg?.poll_exists}>
            Ingest poll CSV
          </button>
        </div>
        <pre className="console">{log}</pre>
      </div>
    </div>
  );
}
