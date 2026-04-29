import { useEffect, useState } from "react";
import { desktopFetch } from "../lib/api";
import { useSite } from "../contexts/site-context";

type WeatherConfig = {
  latitude: string | number;
  longitude: string | number;
  timezone: string;
  base_url: string;
};

type BacnetConfig = {
  enabled: boolean;
  interval_seconds: number;
  site_id: string;
  server_url: string;
  api_key_set: boolean;
  last_error?: string;
};

type OnboardConfig = {
  base_url: string;
  building_ids: string;
  lookback_hours: number;
  api_key_set: boolean;
  allow_synthetic: boolean;
};

export function DriversPage() {
  const { sites, selectedSiteId } = useSite();
  const [siteId, setSiteId] = useState("");
  const [status, setStatus] = useState("Configure drivers and run ingest jobs from one place.");

  const [weather, setWeather] = useState<WeatherConfig>({
    latitude: "",
    longitude: "",
    timezone: "UTC",
    base_url: "https://archive-api.open-meteo.com/v1/archive",
  });
  const [daysBack, setDaysBack] = useState("7");

  const [bacnetEnabled, setBacnetEnabled] = useState(false);
  const [bacnetInterval, setBacnetInterval] = useState("300");
  const [bacnetServerUrl, setBacnetServerUrl] = useState("");
  const [bacnetApiKey, setBacnetApiKey] = useState("");
  const [bacnetApiKeySet, setBacnetApiKeySet] = useState(false);
  const [bacnetLastError, setBacnetLastError] = useState("");

  const [onboardBaseUrl, setOnboardBaseUrl] = useState("https://api.onboarddata.io");
  const [onboardBuildingIds, setOnboardBuildingIds] = useState("");
  const [onboardLookbackHours, setOnboardLookbackHours] = useState("24");
  const [onboardApiKey, setOnboardApiKey] = useState("");
  const [onboardApiKeySet, setOnboardApiKeySet] = useState(false);
  const [onboardAllowSynthetic, setOnboardAllowSynthetic] = useState(false);

  useEffect(() => {
    if (!siteId && selectedSiteId) {
      setSiteId(selectedSiteId);
    }
  }, [siteId, selectedSiteId]);

  useEffect(() => {
    void refreshConfigs();
  }, []);

  async function refreshConfigs() {
    try {
      const [weatherCfg, bacnetCfg, onboardCfg] = await Promise.all([
        desktopFetch<WeatherConfig>("/config/weather"),
        desktopFetch<BacnetConfig>("/config/bacnet"),
        desktopFetch<OnboardConfig>("/config/onboard"),
      ]);
      setWeather({
        latitude: weatherCfg.latitude ?? "",
        longitude: weatherCfg.longitude ?? "",
        timezone: weatherCfg.timezone ?? "UTC",
        base_url: weatherCfg.base_url ?? "https://archive-api.open-meteo.com/v1/archive",
      });
      setBacnetEnabled(Boolean(bacnetCfg.enabled));
      setBacnetInterval(String(bacnetCfg.interval_seconds ?? 300));
      setBacnetServerUrl(String(bacnetCfg.server_url ?? ""));
      setBacnetApiKeySet(Boolean(bacnetCfg.api_key_set));
      setBacnetLastError(String(bacnetCfg.last_error ?? ""));
      if (!siteId && String(bacnetCfg.site_id || "")) {
        setSiteId(String(bacnetCfg.site_id || ""));
      }
      setOnboardBaseUrl(String(onboardCfg.base_url || "https://api.onboarddata.io"));
      setOnboardBuildingIds(String(onboardCfg.building_ids || ""));
      setOnboardLookbackHours(String(onboardCfg.lookback_hours || 24));
      setOnboardApiKeySet(Boolean(onboardCfg.api_key_set));
      setOnboardAllowSynthetic(Boolean(onboardCfg.allow_synthetic));
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  async function saveWeatherConfig() {
    try {
      await desktopFetch("/config/weather", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          latitude: Number(weather.latitude),
          longitude: Number(weather.longitude),
          timezone: String(weather.timezone || "UTC"),
          base_url: String(weather.base_url || "https://archive-api.open-meteo.com/v1/archive"),
        }),
      });
      setStatus("Saved weather driver config.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  async function runWeatherIngest() {
    const effectiveSiteId = siteId || selectedSiteId || "";
    if (!effectiveSiteId) {
      setStatus("Select a site first.");
      return;
    }
    try {
      const out = await desktopFetch<{ rows: number; source: string }>("/ingest/weather", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ site_id: effectiveSiteId, days_back: Number(daysBack || "7") }),
      });
      setStatus(`Weather ingest complete: rows=${out.rows}, source=${out.source}.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  async function saveBacnetConfig() {
    const effectiveSiteId = siteId || selectedSiteId || "";
    try {
      const out = await desktopFetch<BacnetConfig>("/config/bacnet", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: bacnetEnabled,
          interval_seconds: Number(bacnetInterval || "300"),
          site_id: effectiveSiteId,
          server_url: bacnetServerUrl.trim(),
          api_key: bacnetApiKey.trim() || undefined,
        }),
      });
      setBacnetApiKey("");
      setBacnetApiKeySet(Boolean(out.api_key_set));
      setBacnetLastError(String(out.last_error || ""));
      setStatus("Saved BACnet driver config.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  async function runBacnetIngest() {
    const effectiveSiteId = siteId || selectedSiteId || "";
    if (!effectiveSiteId) {
      setStatus("Select a site first.");
      return;
    }
    try {
      const out = await desktopFetch<{ rows: number; source: string; success: boolean; error?: string }>("/ingest/bacnet", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ site_id: effectiveSiteId }),
      });
      setStatus(
        out.success
          ? `BACnet ingest complete: rows=${out.rows}, source=${out.source}.`
          : `BACnet ingest failed: ${out.error || "Unknown error."}`,
      );
      await refreshConfigs();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  async function saveOnboardConfig() {
    try {
      const out = await desktopFetch<OnboardConfig>("/config/onboard", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_url: onboardBaseUrl.trim(),
          building_ids: onboardBuildingIds.trim(),
          lookback_hours: Number(onboardLookbackHours || "24"),
          api_key: onboardApiKey.trim() || undefined,
          allow_synthetic: onboardAllowSynthetic,
        }),
      });
      setOnboardApiKey("");
      setOnboardApiKeySet(Boolean(out.api_key_set));
      setStatus("Saved Onboard driver config.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  async function runOnboardIngest() {
    const effectiveSiteId = siteId || selectedSiteId || "";
    if (!effectiveSiteId) {
      setStatus("Select a site first.");
      return;
    }
    try {
      const out = await desktopFetch<{ rows: number; source: string; success: boolean; error?: string }>("/ingest/onboard", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ site_id: effectiveSiteId }),
      });
      setStatus(
        out.success
          ? `Onboard ingest complete: rows=${out.rows}, source=${out.source}.`
          : `Onboard ingest failed: ${out.error || "Missing credentials or source error."}`,
      );
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <div className="stack-page">
      <div className="card">
        <h2 className="title">Drivers</h2>
        <p className="muted">
          Supported now: CSV import, Open-Meteo weather, BACnet via diy-bacnet-server, and Onboard API ingest.
        </p>
        <div style={{ marginTop: 8 }}>
          <label>Site</label>
          <select value={siteId || selectedSiteId || ""} onChange={(e) => setSiteId(e.target.value)}>
            {sites.length === 0 && <option value="">No sites</option>}
            {sites.map((site) => (
              <option key={site.id} value={site.id}>
                {site.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="card">
        <h3 className="title">CSV Driver</h3>
        <p className="muted">
          CSV is path/upload driven. Use the CSV Import tab for files. Parsed rows are stored in Feather under source keys (default: csv).
        </p>
      </div>

      <div className="card">
        <h3 className="title">Open-Meteo Driver</h3>
        <div className="grid-two">
          <div>
            <label>Days back</label>
            <input value={daysBack} onChange={(e) => setDaysBack(e.target.value)} />
          </div>
          <div>
            <label>Timezone</label>
            <input
              value={String(weather.timezone)}
              onChange={(e) => setWeather((prev) => ({ ...prev, timezone: e.target.value }))}
            />
          </div>
          <div>
            <label>Latitude</label>
            <input
              value={String(weather.latitude)}
              onChange={(e) => setWeather((prev) => ({ ...prev, latitude: e.target.value }))}
            />
          </div>
          <div>
            <label>Longitude</label>
            <input
              value={String(weather.longitude)}
              onChange={(e) => setWeather((prev) => ({ ...prev, longitude: e.target.value }))}
            />
          </div>
          <div>
            <label>Base URL</label>
            <input value={String(weather.base_url)} onChange={(e) => setWeather((prev) => ({ ...prev, base_url: e.target.value }))} />
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <button onClick={() => void saveWeatherConfig()}>Save weather config</button>
          <button className="secondary-btn" onClick={() => void runWeatherIngest()}>
            Run weather ingest
          </button>
        </div>
      </div>

      <div className="card">
        <h3 className="title">BACnet Driver (diy-bacnet-server)</h3>
        <div className="grid-two">
          <div>
            <label>Server URL</label>
            <input value={bacnetServerUrl} onChange={(e) => setBacnetServerUrl(e.target.value)} placeholder="http://192.168.x.x:8080" />
          </div>
          <div>
            <label>Polling interval seconds (min 5)</label>
            <input value={bacnetInterval} onChange={(e) => setBacnetInterval(e.target.value)} />
          </div>
          <div>
            <label>API key (optional to update)</label>
            <input value={bacnetApiKey} onChange={(e) => setBacnetApiKey(e.target.value)} placeholder={bacnetApiKeySet ? "Saved key present" : "Paste token"} />
          </div>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 8 }}>
            <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input type="checkbox" checked={bacnetEnabled} onChange={(e) => setBacnetEnabled(e.target.checked)} />
              Enable background polling
            </label>
          </div>
        </div>
        {bacnetLastError ? <p style={{ color: "var(--danger-700)" }}>Last BACnet error: {bacnetLastError}</p> : null}
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <button onClick={() => void saveBacnetConfig()}>Save BACnet config</button>
          <button className="secondary-btn" onClick={() => void runBacnetIngest()}>
            Run BACnet ingest now
          </button>
        </div>
      </div>

      <div className="card">
        <h3 className="title">Onboard Driver</h3>
        <div className="grid-two">
          <div>
            <label>API base URL</label>
            <input value={onboardBaseUrl} onChange={(e) => setOnboardBaseUrl(e.target.value)} />
          </div>
          <div>
            <label>Building IDs (comma-separated)</label>
            <input value={onboardBuildingIds} onChange={(e) => setOnboardBuildingIds(e.target.value)} placeholder="123,456" />
          </div>
          <div>
            <label>Lookback hours</label>
            <input value={onboardLookbackHours} onChange={(e) => setOnboardLookbackHours(e.target.value)} />
          </div>
          <div>
            <label>API key (optional to update)</label>
            <input
              value={onboardApiKey}
              onChange={(e) => setOnboardApiKey(e.target.value)}
              placeholder={onboardApiKeySet ? "Saved key present" : "Paste token"}
            />
          </div>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 8 }}>
            <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input type="checkbox" checked={onboardAllowSynthetic} onChange={(e) => setOnboardAllowSynthetic(e.target.checked)} />
              Allow synthetic fallback (dev/test only)
            </label>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <button onClick={() => void saveOnboardConfig()}>Save Onboard config</button>
          <button className="secondary-btn" onClick={() => void runOnboardIngest()}>
            Run Onboard ingest now
          </button>
        </div>
      </div>

      <div className="card">
        <textarea readOnly value={status} style={{ minHeight: 96 }} />
      </div>
    </div>
  );
}
