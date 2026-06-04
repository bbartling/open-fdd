import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import Spinner from "./Spinner";

type SyncStatus = {
  in_sync: boolean;
  poll_enabled_count: number;
  model_bacnet_count: number;
  missing_in_model_total: number;
  extra_in_model_total: number;
  ttl_exists: boolean;
  ttl_path: string;
};

type Health = {
  status: string;
  score: number | null;
  configured: boolean;
  issues: Array<{ severity: string; title: string }>;
};

type Props = {
  onStatus?: (msg: string) => void;
  refreshKey?: number;
};

export default function ModelSyncBar({ onStatus, refreshKey = 0 }: Props) {
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, h] = await Promise.all([
        apiFetch<SyncStatus>("/api/model/bacnet-sync"),
        apiFetch<Health>("/api/model/health"),
      ]);
      setSync(s);
      setHealth(h);
      setError("");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load().catch((e) => setError(formatApiError(e)));
  }, [load, refreshKey]);

  async function resync() {
    setBusy(true);
    setError("");
    try {
      const res = await apiFetch<{ points_added: number; points_updated: number; points_removed: number }>(
        "/api/model/bacnet-sync",
        { method: "POST" },
      );
      onStatus?.(
        `BACnet sync — added=${res.points_added ?? 0} updated=${res.points_updated ?? 0} removed=${res.points_removed ?? 0}; TTL refreshed.`,
      );
      await load();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function syncTtl() {
    setBusy(true);
    try {
      const res = await apiFetch<{ path: string }>("/api/model/sync-ttl", { method: "POST" });
      onStatus?.(`TTL written to ${res.path}`);
      await load();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  const pillClass = sync?.in_sync ? "status-pill status-green" : "status-pill status-yellow";

  return (
    <div className="dm-sync-bar panel">
      {loading && !sync ? <Spinner label="Loading BACnet ↔ model sync status…" /> : null}
      <div className="dm-sync-row">
        <span className={pillClass}>
          <span className="status-dot" />
          BACnet poll CSV ↔ model.json {sync?.in_sync ? "in sync" : "drift"}
        </span>
        {sync ? (
          <span className="muted dm-sync-meta">
            {sync.poll_enabled_count} enabled in poll CSV · {sync.model_bacnet_count} BACnet points in model
            {!sync.in_sync ? (
              <>
                {" "}
                · {sync.missing_in_model_total} missing · {sync.extra_in_model_total} extra
              </>
            ) : null}
            {sync.ttl_exists ? " · TTL on disk" : " · TTL not saved yet"}
          </span>
        ) : null}
        <div className="dm-sync-actions">
          <button type="button" className="secondary-btn" disabled={busy} onClick={() => void resync()}>
            {busy ? "Syncing…" : "Sync poll → model"}
          </button>
          <button type="button" className="secondary-btn" disabled={busy} onClick={() => void syncTtl()}>
            Write TTL
          </button>
        </div>
      </div>
      {health?.configured && health.issues.length ? (
        <ul className="dm-health-issues">
          {health.issues.slice(0, 4).map((issue) => (
            <li key={issue.title} className={issue.severity === "critical" ? "error" : "muted"}>
              {issue.title}
            </li>
          ))}
        </ul>
      ) : null}
      {error ? <p className="error">{error}</p> : null}
    </div>
  );
}
