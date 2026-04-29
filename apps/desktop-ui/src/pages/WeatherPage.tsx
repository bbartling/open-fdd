import { useEffect, useState } from "react";
import { desktopFetch } from "../lib/api";
import { useSite } from "../contexts/site-context";
import { PointsTreePanel } from "../components/site/PointsTreePanel";

type WeatherConfig = {
  latitude: string | number;
  longitude: string | number;
  timezone: string;
  base_url: string;
};

type ModelExportResponse = {
  equipment: Array<{ id?: string; site_id?: string; name?: string; equipment_type?: string | null }>;
  points: Array<{
    id?: string;
    site_id?: string;
    equipment_id?: string | null;
    external_id?: string;
    brick_type?: string | null;
    metadata?: Record<string, unknown> | null;
  }>;
};

export function WeatherPage() {
  const { sites, selectedSiteId } = useSite();
  const [siteId, setSiteId] = useState("");
  const [daysBack, setDaysBack] = useState("7");
  const [latitude, setLatitude] = useState("");
  const [longitude, setLongitude] = useState("");
  const [timezone, setTimezone] = useState("UTC");
  const [baseUrl, setBaseUrl] = useState("https://archive-api.open-meteo.com/v1/archive");
  const [status, setStatus] = useState("Configure Open-Meteo coordinates, then ingest weather for your selected site.");
  const [modelPoints, setModelPoints] = useState<ModelExportResponse["points"]>([]);
  const [modelEquipment, setModelEquipment] = useState<ModelExportResponse["equipment"]>([]);
  const [selectedWeatherExternalIds, setSelectedWeatherExternalIds] = useState<string[]>([]);

  useEffect(() => {
    if (!siteId && selectedSiteId) {
      setSiteId(selectedSiteId);
    }
  }, [siteId, selectedSiteId]);

  useEffect(() => {
    void (async () => {
      try {
        const cfg = await desktopFetch<WeatherConfig>("/config/weather");
        setLatitude(String(cfg.latitude ?? ""));
        setLongitude(String(cfg.longitude ?? ""));
        setTimezone(String(cfg.timezone ?? "UTC"));
        setBaseUrl(String(cfg.base_url ?? "https://archive-api.open-meteo.com/v1/archive"));
      } catch (error) {
        setStatus(error instanceof Error ? error.message : String(error));
      }
    })();
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const model = await desktopFetch<ModelExportResponse>("/model/export");
        setModelPoints(model.points || []);
        setModelEquipment(model.equipment || []);
      } catch {
        // non-fatal
      }
    })();
  }, []);

  async function saveConfig() {
    try {
      const out = await desktopFetch<WeatherConfig>("/config/weather", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          latitude: Number(latitude),
          longitude: Number(longitude),
          timezone: timezone.trim() || "UTC",
          base_url: baseUrl.trim() || "https://archive-api.open-meteo.com/v1/archive",
        }),
      });
      setLatitude(String(out.latitude ?? ""));
      setLongitude(String(out.longitude ?? ""));
      setTimezone(String(out.timezone ?? "UTC"));
      setBaseUrl(String(out.base_url ?? "https://archive-api.open-meteo.com/v1/archive"));
      setStatus("Saved weather config.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  async function fetchWeather() {
    const effectiveSiteId = siteId || selectedSiteId || "";
    if (!effectiveSiteId) {
      setStatus("Select a site first.");
      return;
    }
    try {
      const out = await desktopFetch<{ rows: number; source: string }>("/ingest/weather", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          site_id: effectiveSiteId,
          days_back: Number(daysBack || "7"),
        }),
      });
      setStatus(`Weather ingest complete: rows=${out.rows}, source=${out.source}.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <div className="stack-page">
      <div className="card">
        <h2 className="title">Weather data (Open-Meteo)</h2>
        <p className="muted">Set location once, then ingest weather to Feather for the selected site.</p>
        <div className="grid-two">
          <div>
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
          <div>
            <label>Days back</label>
            <input value={daysBack} onChange={(e) => setDaysBack(e.target.value)} placeholder="7" />
          </div>
          <div>
            <label>Latitude</label>
            <input value={latitude} onChange={(e) => setLatitude(e.target.value)} placeholder="42.36" />
          </div>
          <div>
            <label>Longitude</label>
            <input value={longitude} onChange={(e) => setLongitude(e.target.value)} placeholder="-71.06" />
          </div>
          <div>
            <label>Timezone</label>
            <input value={timezone} onChange={(e) => setTimezone(e.target.value)} placeholder="UTC" />
          </div>
          <div>
            <label>Open-Meteo base URL</label>
            <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://archive-api.open-meteo.com/v1/archive" />
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <button onClick={() => void saveConfig()}>Save weather config</button>
          <button className="secondary-btn" onClick={() => void fetchWeather()}>
            Download weather for site
          </button>
        </div>
        <div style={{ marginTop: 10 }}>
          <PointsTreePanel
            points={modelPoints}
            equipment={modelEquipment}
            selectedSiteId={siteId || selectedSiteId || ""}
            selectedExternalIds={selectedWeatherExternalIds}
            onSelectedExternalIdsChange={setSelectedWeatherExternalIds}
            title="Points tree (weather-focused)"
            description="Quickly inspect/select weather points grouped by equipment (typically unassigned for weather)."
            pointFilter={(point) => {
              const md = point.metadata && typeof point.metadata === "object" ? point.metadata : null;
              return String((md as Record<string, unknown> | null)?.source || "").toLowerCase() === "weather";
            }}
          />
        </div>
        <textarea readOnly value={status} style={{ marginTop: 10, minHeight: 90 }} />
      </div>
    </div>
  );
}
