import { useEffect, useState } from "react";
import { desktopFetch } from "../lib/api";
import { useSite } from "../contexts/site-context";

type BacnetConfig = {
  enabled: boolean;
  interval_seconds: number;
  site_id: string;
  server_url: string;
  api_key_set: boolean;
  last_error?: string;
};

export function BacnetDriverPage() {
  const { sites, selectedSiteId } = useSite();
  const [siteId, setSiteId] = useState("");
  const [status, setStatus] = useState("Configure and run BACnet ingest.");
  const [enabled, setEnabled] = useState(false);
  const [interval, setInterval] = useState("300");
  const [serverUrl, setServerUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [apiKeySet, setApiKeySet] = useState(false);
  const [lastError, setLastError] = useState("");

  useEffect(() => {
    if (!siteId && selectedSiteId) setSiteId(selectedSiteId);
  }, [siteId, selectedSiteId]);

  useEffect(() => {
    void (async () => {
      try {
        const cfg = await desktopFetch<BacnetConfig>("/config/bacnet");
        setEnabled(Boolean(cfg.enabled));
        setInterval(String(cfg.interval_seconds ?? 300));
        setServerUrl(String(cfg.server_url ?? ""));
        setApiKeySet(Boolean(cfg.api_key_set));
        setLastError(String(cfg.last_error ?? ""));
      } catch (e) {
        setStatus(e instanceof Error ? e.message : String(e));
      }
    })();
  }, []);

  async function saveConfig() {
    const effectiveSiteId = siteId || selectedSiteId || "";
    const parsedInterval = Number(interval || "300");
    if (!Number.isFinite(parsedInterval) || parsedInterval < 5) {
      setStatus("BACnet polling interval must be a valid number >= 5 seconds.");
      return;
    }
    const out = await desktopFetch<BacnetConfig>("/config/bacnet", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        enabled,
        interval_seconds: parsedInterval,
        site_id: effectiveSiteId,
        server_url: serverUrl.trim(),
        api_key: apiKey.trim() || undefined,
      }),
    });
    setApiKey("");
    setApiKeySet(Boolean(out.api_key_set));
    setLastError(String(out.last_error || ""));
    setStatus("Saved BACnet driver config.");
  }

  async function runIngest() {
    const effectiveSiteId = siteId || selectedSiteId || "";
    if (!effectiveSiteId) return setStatus("Select a site first.");
    const out = await desktopFetch<{ rows: number; source: string; success: boolean; error?: string }>("/ingest/bacnet", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ site_id: effectiveSiteId }),
    });
    setStatus(out.success ? `BACnet ingest complete: rows=${out.rows}, source=${out.source}.` : `BACnet ingest failed: ${out.error || "Unknown error."}`);
  }

  return (
    <div className="stack-page">
      <div className="card">
        <h2 className="title">BACnet Driver (diy-bacnet-server)</h2>
        <p className="muted">Standalone BACnet driver settings for Open-FDD desktop ingest.</p>
        <div>
          <label>Site</label>
          <select value={siteId || selectedSiteId || ""} onChange={(e) => setSiteId(e.target.value)}>
            {sites.length === 0 && <option value="">No sites</option>}
            {sites.map((site) => (
              <option key={site.id} value={site.id}>{site.name}</option>
            ))}
          </select>
        </div>
        <div className="grid-two" style={{ marginTop: 10 }}>
          <div><label>Server URL</label><input value={serverUrl} onChange={(e) => setServerUrl(e.target.value)} placeholder="http://192.168.x.x:8080" /></div>
          <div><label>Polling interval seconds (min 5)</label><input value={interval} onChange={(e) => setInterval(e.target.value)} /></div>
          <div><label>API key (optional to update)</label><input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder={apiKeySet ? "Saved key present" : "Paste token"} /></div>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 8 }}>
            <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
              Enable background polling
            </label>
          </div>
        </div>
        {lastError ? <p style={{ color: "var(--danger-700)" }}>Last BACnet error: {lastError}</p> : null}
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <button onClick={() => void saveConfig()}>Save BACnet config</button>
          <button className="secondary-btn" onClick={() => void runIngest()}>Run BACnet ingest now</button>
        </div>
      </div>
      <div className="card"><textarea readOnly value={status} style={{ minHeight: 96 }} /></div>
    </div>
  );
}
