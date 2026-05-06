import { useEffect, useState } from "react";
import { desktopFetch } from "../lib/api";
import { useSite } from "../contexts/site-context";

type WeatherConfig = {
  latitude: string | number;
  longitude: string | number;
  timezone: string;
  base_url: string;
};

function defaultDateRange(): { start: string; end: string } {
  const d = (v: Date) => `${v.getFullYear()}-${String(v.getMonth() + 1).padStart(2, "0")}-${String(v.getDate()).padStart(2, "0")}`;
  const end = new Date();
  const start = new Date();
  start.setDate(end.getDate() - 7);
  return { start: d(start), end: d(end) };
}

function daysBackFromRange(startDate: string, endDate: string): number | null {
  const parse = (s: string): number | null => {
    const [y, m, d] = s.split("-").map(Number);
    if (!Number.isInteger(y) || !Number.isInteger(m) || !Number.isInteger(d)) return null;
    return Date.UTC(y, m - 1, d);
  };
  const a = parse(startDate);
  const b = parse(endDate);
  if (a === null || b === null || b < a) return null;
  return Math.floor((b - a) / 86_400_000) + 1;
}

export function WeatherDriverPage() {
  const { sites, selectedSiteId } = useSite();
  const [siteId, setSiteId] = useState("");
  const [status, setStatus] = useState("Configure and run Open-Meteo weather ingest.");
  const initial = defaultDateRange();
  const [startDate, setStartDate] = useState(initial.start);
  const [endDate, setEndDate] = useState(initial.end);
  const [weather, setWeather] = useState<WeatherConfig>({
    latitude: "",
    longitude: "",
    timezone: "UTC",
    base_url: "https://archive-api.open-meteo.com/v1/archive",
  });

  useEffect(() => {
    if (!siteId && selectedSiteId) setSiteId(selectedSiteId);
  }, [siteId, selectedSiteId]);

  useEffect(() => {
    void (async () => {
      try {
        const cfg = await desktopFetch<WeatherConfig>("/config/weather");
        setWeather({
          latitude: cfg.latitude ?? "",
          longitude: cfg.longitude ?? "",
          timezone: cfg.timezone ?? "UTC",
          base_url: cfg.base_url ?? "https://archive-api.open-meteo.com/v1/archive",
        });
      } catch (e) {
        setStatus(e instanceof Error ? e.message : String(e));
      }
    })();
  }, []);

  async function saveConfig() {
    const latitude = Number(weather.latitude);
    const longitude = Number(weather.longitude);
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
      setStatus("Latitude and longitude must be valid numbers.");
      return;
    }
    await desktopFetch("/config/weather", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ latitude, longitude, timezone: weather.timezone, base_url: weather.base_url }),
    });
    setStatus("Saved weather driver config.");
  }

  async function runIngest() {
    const effectiveSiteId = siteId || selectedSiteId || "";
    if (!effectiveSiteId) return setStatus("Select a site first.");
    const days = daysBackFromRange(startDate, endDate);
    if (!days) return setStatus("Weather date range must be valid and end date must be on/after start date.");
    const out = await desktopFetch<{ rows: number; source: string }>("/ingest/weather", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ site_id: effectiveSiteId, days_back: days }),
    });
    setStatus(`Weather ingest complete: rows=${out.rows}, source=${out.source}.`);
  }

  return (
    <div className="stack-page">
      <div className="card">
        <h2 className="title">Open-Meteo Driver</h2>
        <p className="muted">Standalone weather driver settings for Open-FDD desktop ingest.</p>
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
          <div><label>Start date</label><input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} /></div>
          <div><label>End date</label><input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} /></div>
          <div><label>Timezone</label><input value={String(weather.timezone)} onChange={(e) => setWeather((p) => ({ ...p, timezone: e.target.value }))} /></div>
          <div><label>Latitude</label><input value={String(weather.latitude)} onChange={(e) => setWeather((p) => ({ ...p, latitude: e.target.value }))} /></div>
          <div><label>Longitude</label><input value={String(weather.longitude)} onChange={(e) => setWeather((p) => ({ ...p, longitude: e.target.value }))} /></div>
          <div><label>Base URL</label><input value={String(weather.base_url)} onChange={(e) => setWeather((p) => ({ ...p, base_url: e.target.value }))} /></div>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <button onClick={() => void saveConfig()}>Save weather config</button>
          <button className="secondary-btn" onClick={() => void runIngest()}>Run weather ingest now</button>
        </div>
      </div>
      <div className="card"><textarea readOnly value={status} style={{ minHeight: 96 }} /></div>
    </div>
  );
}
