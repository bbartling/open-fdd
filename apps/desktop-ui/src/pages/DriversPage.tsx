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
};
type OnboardBuilding = {
  id: string;
  name: string;
  point_count?: number | null;
  equip_count?: number | null;
  timezone?: string | null;
};
type OnboardEquipmentPoint = {
  id?: number | string | null;
  name?: string | null;
  point_type?: string | null;
  topic?: string | null;
  tagged_units?: string | null;
};
type OnboardEquipment = {
  id?: number | string | null;
  name: string;
  equip_type_name?: string | null;
  equip_type_abbr?: string | null;
  points: OnboardEquipmentPoint[];
};
type SourceBounds = {
  rows: number;
  timestamp_col?: string | null;
  start?: string | null;
  end?: string | null;
};

type DriverHealthEntry = {
  last_run: string;
  rows: number;
  success: boolean | null;
  last_error: string;
};

type DriverHealthMap = Record<string, DriverHealthEntry>;

type DriversPageSection = "all" | "weather" | "bacnet" | "onboard";
const ONBOARD_API_KEY_STORAGE_KEY = "ofdd-onboard-api-key-draft";

function defaultDateRange(): { start: string; end: string } {
  const toLocalDateInput = (value: Date) => {
    const year = value.getFullYear();
    const month = String(value.getMonth() + 1).padStart(2, "0");
    const day = String(value.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  };
  const end = new Date();
  const start = new Date();
  start.setDate(end.getDate() - 7);
  return {
    start: toLocalDateInput(start),
    end: toLocalDateInput(end),
  };
}

function daysBackFromRange(startDate: string, endDate: string): number | null {
  if (!startDate || !endDate) {
    return null;
  }
  const parseUtcMidnight = (raw: string): number | null => {
    const [yearText, monthText, dayText] = raw.split("-");
    const year = Number(yearText);
    const month = Number(monthText);
    const day = Number(dayText);
    if (!Number.isInteger(year) || !Number.isInteger(month) || !Number.isInteger(day)) {
      return null;
    }
    const utc = Date.UTC(year, month - 1, day);
    const check = new Date(utc);
    if (
      check.getUTCFullYear() !== year
      || check.getUTCMonth() !== month - 1
      || check.getUTCDate() !== day
    ) {
      return null;
    }
    return utc;
  };
  const startUtc = parseUtcMidnight(startDate);
  const endUtc = parseUtcMidnight(endDate);
  if (startUtc === null || endUtc === null || endUtc < startUtc) {
    return null;
  }
  const msPerDay = 24 * 60 * 60 * 1000;
  return Math.floor((endUtc - startUtc) / msPerDay) + 1;
}

export function DriversPage({ embedded = false, section = "all" }: { embedded?: boolean; section?: DriversPageSection }) {
  const { sites, selectedSiteId } = useSite();
  const [siteId, setSiteId] = useState("");
  const [status, setStatus] = useState("Configure drivers and run ingest jobs from one place.");

  const [weather, setWeather] = useState<WeatherConfig>({
    latitude: "",
    longitude: "",
    timezone: "UTC",
    base_url: "https://archive-api.open-meteo.com/v1/archive",
  });
  const initialRange = defaultDateRange();
  const [weatherStartDate, setWeatherStartDate] = useState(initialRange.start);
  const [weatherEndDate, setWeatherEndDate] = useState(initialRange.end);

  const [bacnetEnabled, setBacnetEnabled] = useState(false);
  const [bacnetInterval, setBacnetInterval] = useState("300");
  const [bacnetServerUrl, setBacnetServerUrl] = useState("");
  const [bacnetApiKey, setBacnetApiKey] = useState("");
  const [bacnetApiKeySet, setBacnetApiKeySet] = useState(false);
  const [bacnetLastError, setBacnetLastError] = useState("");

  const [onboardBaseUrl, setOnboardBaseUrl] = useState("https://api.onboarddata.io");
  const [onboardLookbackHours, setOnboardLookbackHours] = useState("24");
  const [onboardApiKey, setOnboardApiKey] = useState("");
  const [onboardApiKeySet, setOnboardApiKeySet] = useState(false);
  const [onboardAuthStatus, setOnboardAuthStatus] = useState<"idle" | "ok" | "error" | "testing">("idle");
  const [onboardAuthMessage, setOnboardAuthMessage] = useState("");
  const [onboardBusy, setOnboardBusy] = useState(false);
  const [onboardBuildings, setOnboardBuildings] = useState<OnboardBuilding[]>([]);
  const [onboardBuildingInspectId, setOnboardBuildingInspectId] = useState<string>("");
  const [onboardPointTypeFilter, setOnboardPointTypeFilter] = useState("zone_air_temperature_sensor");
  const [onboardEquipmentTree, setOnboardEquipmentTree] = useState<OnboardEquipment[]>([]);
  const [onboardEquipFilter, setOnboardEquipFilter] = useState("");
  const [onboardLivePointIds, setOnboardLivePointIds] = useState("");
  const [onboardLiveValues, setOnboardLiveValues] = useState("");
  const [onboardDataBounds, setOnboardDataBounds] = useState<SourceBounds | null>(null);
  const [onboardActionLog, setOnboardActionLog] = useState<string[]>([]);
  const [onboardDiscoveryResult, setOnboardDiscoveryResult] = useState("");
  const [onboardSmokeResult, setOnboardSmokeResult] = useState("");
  const [driverHealth, setDriverHealth] = useState<DriverHealthMap>({});

  useEffect(() => {
    if (embedded) {
      setSiteId(selectedSiteId || "");
      return;
    }
    if (!siteId && selectedSiteId) {
      setSiteId(selectedSiteId);
    }
  }, [embedded, siteId, selectedSiteId]);

  useEffect(() => {
    void refreshConfigs();
  }, []);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(ONBOARD_API_KEY_STORAGE_KEY) || "";
      if (raw) {
        setOnboardApiKey(raw);
      }
    } catch {
      // Ignore storage errors in restricted browser contexts.
    }
  }, []);

  useEffect(() => {
    try {
      if (onboardApiKey) {
        window.localStorage.setItem(ONBOARD_API_KEY_STORAGE_KEY, onboardApiKey);
      } else {
        window.localStorage.removeItem(ONBOARD_API_KEY_STORAGE_KEY);
      }
    } catch {
      // Ignore storage errors in restricted browser contexts.
    }
  }, [onboardApiKey]);

  async function refreshConfigs() {
    try {
      const [weatherCfg, bacnetCfg, onboardCfg, health] = await Promise.all([
        desktopFetch<WeatherConfig>("/config/weather"),
        desktopFetch<BacnetConfig>("/config/bacnet"),
        desktopFetch<OnboardConfig>("/config/onboard"),
        desktopFetch<DriverHealthMap>("/config/drivers/health"),
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
      setOnboardLookbackHours(String(onboardCfg.lookback_hours || 24));
      setOnboardApiKeySet(Boolean(onboardCfg.api_key_set));
      setDriverHealth(health || {});
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  async function saveWeatherConfig() {
    const latitude = Number(weather.latitude);
    const longitude = Number(weather.longitude);
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
      setStatus("Latitude and longitude must be valid numbers.");
      return;
    }
    try {
      await desktopFetch("/config/weather", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          latitude,
          longitude,
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
    const effectiveSiteId = embedded ? (selectedSiteId || "") : (siteId || selectedSiteId || "");
    if (!effectiveSiteId) {
      setStatus("Select a site first.");
      return;
    }
    const parsedDaysBack = daysBackFromRange(weatherStartDate, weatherEndDate);
    if (!parsedDaysBack) {
      setStatus("Weather date range must be valid and end date must be on/after start date.");
      return;
    }
    try {
      const out = await desktopFetch<{ rows: number; source: string }>("/ingest/weather", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ site_id: effectiveSiteId, days_back: parsedDaysBack }),
      });
      setStatus(
        `Weather ingest complete for ${weatherStartDate} to ${weatherEndDate}: rows=${out.rows}, source=${out.source}.`,
      );
      await refreshConfigs();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  async function saveBacnetConfig() {
    const effectiveSiteId = embedded ? (selectedSiteId || "") : (siteId || selectedSiteId || "");
    const parsedInterval = Number(bacnetInterval || "300");
    if (!Number.isFinite(parsedInterval) || parsedInterval < 5) {
      setStatus("BACnet polling interval must be a valid number >= 5 seconds.");
      return;
    }
    try {
      const out = await desktopFetch<BacnetConfig>("/config/bacnet", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: bacnetEnabled,
          interval_seconds: parsedInterval,
          site_id: effectiveSiteId,
          server_url: bacnetServerUrl.trim(),
          api_key: bacnetApiKey.trim() || undefined,
        }),
      });
      setBacnetApiKey("");
      setBacnetApiKeySet(Boolean(out.api_key_set));
      setBacnetLastError(String(out.last_error || ""));
      setStatus("Saved BACnet driver config.");
      await refreshConfigs();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  async function runBacnetIngest() {
    const effectiveSiteId = embedded ? (selectedSiteId || "") : (siteId || selectedSiteId || "");
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
    const parsedLookback = Number(onboardLookbackHours || "24");
    if (!Number.isFinite(parsedLookback) || parsedLookback < 1) {
      setStatus("Onboard lookback hours must be a valid number >= 1.");
      return;
    }
    const selectedBuilding = String(onboardBuildingInspectId || "").trim();
    setOnboardBusy(true);
    try {
      const out = await desktopFetch<OnboardConfig>("/config/onboard", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_url: onboardBaseUrl.trim(),
          building_ids: selectedBuilding,
          lookback_hours: parsedLookback,
          api_key: onboardApiKey.trim() || undefined,
        }),
      });
      setOnboardApiKeySet(Boolean(out.api_key_set));
      setStatus("Saved Onboard driver config.");
      setOnboardActionLog((prev) => [
        `${new Date().toLocaleTimeString()} Saved config (building=${selectedBuilding || "none"}).`,
        ...prev.slice(0, 11),
      ]);
      await refreshConfigs();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setOnboardBusy(false);
    }
  }

  async function runOnboardIngest() {
    const effectiveSiteId = embedded ? (selectedSiteId || "") : (siteId || selectedSiteId || "");
    if (!effectiveSiteId) {
      setStatus("Select a site first.");
      return;
    }
    setOnboardBusy(true);
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
      setOnboardActionLog((prev) => [
        `${new Date().toLocaleTimeString()} Bulk download ${out.success ? "OK" : "failed"} (rows=${out.rows}).`,
        ...prev.slice(0, 11),
      ]);
      await refreshOnboardDataPresence();
      await refreshConfigs();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setOnboardBusy(false);
    }
  }

  async function refreshOnboardDataPresence() {
    const effectiveSiteId = embedded ? (selectedSiteId || "") : (siteId || selectedSiteId || "");
    if (!effectiveSiteId) {
      setOnboardDataBounds(null);
      return;
    }
    try {
      const out = await desktopFetch<SourceBounds>("/timeseries/bounds", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ site_id: effectiveSiteId, source: "onboard" }),
      });
      setOnboardDataBounds(out);
      setOnboardActionLog((prev) => [
        `${new Date().toLocaleTimeString()} Refreshed Feather status (rows=${out.rows}).`,
        ...prev.slice(0, 11),
      ]);
    } catch {
      setOnboardDataBounds(null);
    }
  }

  async function discoverOnboardBuildings() {
    setOnboardBusy(true);
    try {
      const out = await desktopFetch<{ count: number; buildings: OnboardBuilding[] }>("/config/onboard/buildings");
      setOnboardBuildings(out.buildings || []);
      if (!onboardBuildingInspectId && out.buildings?.length) {
        setOnboardBuildingInspectId(String(out.buildings[0].id || ""));
      }
      setOnboardDiscoveryResult(`Found ${out.count || 0} buildings from Onboard.`);
      setOnboardActionLog((prev) => [
        `${new Date().toLocaleTimeString()} Fetched buildings (${out.count || 0}).`,
        ...prev.slice(0, 11),
      ]);
    } catch (error) {
      setOnboardDiscoveryResult(error instanceof Error ? error.message : String(error));
    } finally {
      setOnboardBusy(false);
    }
  }

  async function testOnboardAuth() {
    const parsedLookback = Number(onboardLookbackHours || "24");
    const safeLookback = Number.isFinite(parsedLookback) && parsedLookback >= 1 ? parsedLookback : 24;
    const selectedBuilding = String(onboardBuildingInspectId || "").trim();
    setOnboardAuthStatus("testing");
    setOnboardAuthMessage("Testing API key...");
    setOnboardBusy(true);
    try {
      // Apply the currently pasted key/base URL before auth test so users can test in one click.
      await desktopFetch<OnboardConfig>("/config/onboard", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_url: onboardBaseUrl.trim(),
          building_ids: selectedBuilding,
          lookback_hours: safeLookback,
          api_key: onboardApiKey.trim() || undefined,
        }),
      });
      const out = await desktopFetch<{ ok: boolean; building_count: number; message: string }>("/config/onboard/auth-test");
      const msg = `${out.message} buildings=${out.building_count}`;
      setOnboardDiscoveryResult(msg);
      setOnboardAuthStatus("ok");
      setOnboardAuthMessage(msg);
      setStatus(`Onboard auth OK (${out.building_count} buildings visible).`);
      setOnboardApiKeySet(true);
      setOnboardActionLog((prev) => [
        `${new Date().toLocaleTimeString()} API auth OK (${out.building_count} buildings).`,
        ...prev.slice(0, 11),
      ]);
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      setOnboardDiscoveryResult(msg);
      setOnboardAuthStatus("error");
      setOnboardAuthMessage(msg);
      setStatus(`Onboard auth failed: ${msg}`);
      setOnboardActionLog((prev) => [
        `${new Date().toLocaleTimeString()} API auth failed: ${msg}`,
        ...prev.slice(0, 11),
      ]);
    } finally {
      setOnboardBusy(false);
    }
  }

  async function inspectOnboardBuildingPoints() {
    if (!onboardBuildingInspectId) {
      setOnboardDiscoveryResult("Pick a building first.");
      return;
    }
    const filter = onboardPointTypeFilter.trim();
    const qs = filter ? `?point_type=${encodeURIComponent(filter)}` : "";
    try {
      const out = await desktopFetch<{
        building_id: number;
        point_count: number;
        point_type_counts: Array<{ point_type: string; count: number }>;
        sample_points: Array<Record<string, unknown>>;
      }>(`/config/onboard/buildings/${encodeURIComponent(onboardBuildingInspectId)}/points${qs}`);
      const topTypes = (out.point_type_counts || []).slice(0, 12)
        .map((row) => `${row.point_type}: ${row.count}`)
        .join(", ");
      const sampleIds = (out.sample_points || [])
        .slice(0, 10)
        .map((row) => String(row.id ?? ""))
        .filter(Boolean)
        .join(", ");
      setOnboardDiscoveryResult(
        [
          `Building ${out.building_id} point_count=${out.point_count}.`,
          topTypes ? `Top point types: ${topTypes}` : "Top point types: none",
          sampleIds ? `Sample point IDs (${filter || "all"}): [${sampleIds}]` : `Sample point IDs (${filter || "all"}): none`,
        ].join("\n"),
      );
    } catch (error) {
      setOnboardDiscoveryResult(error instanceof Error ? error.message : String(error));
    }
  }

  async function loadOnboardEquipmentTree() {
    if (!onboardBuildingInspectId) {
      setOnboardDiscoveryResult("Pick a building first.");
      return;
    }
    const qs = new URLSearchParams();
    qs.set("include_points", "true");
    if (onboardPointTypeFilter.trim()) {
      qs.set("point_type", onboardPointTypeFilter.trim());
    }
    if (onboardEquipFilter.trim()) {
      qs.set("equip_name_contains", onboardEquipFilter.trim());
    }
    try {
      const out = await desktopFetch<{ equipment_count: number; equipment: OnboardEquipment[] }>(
        `/config/onboard/buildings/${encodeURIComponent(onboardBuildingInspectId)}/equipment?${qs.toString()}`,
      );
      setOnboardEquipmentTree(out.equipment || []);
      const firstPointIds = (out.equipment || [])
        .flatMap((eq) => (eq.points || []).map((p) => p.id))
        .filter((v): v is number | string => v !== null && v !== undefined)
        .slice(0, 5)
        .map((v) => String(v));
      if (firstPointIds.length) {
        setOnboardLivePointIds(firstPointIds.join(","));
      }
      setOnboardDiscoveryResult(`Loaded equipment tree rows=${out.equipment_count}.`);
    } catch (error) {
      setOnboardDiscoveryResult(error instanceof Error ? error.message : String(error));
    }
  }

  async function refreshOnboardLivePoints() {
    const ids = onboardLivePointIds.trim();
    if (!ids) {
      setOnboardLiveValues("Enter point IDs first (comma-separated).");
      return;
    }
    try {
      const out = await desktopFetch<{
        ok: boolean;
        lookback_minutes: number;
        series: Array<{ point_id: number | string; sample_count: number; last_timestamp?: string | null; last_value?: unknown }>;
      }>(`/config/onboard/points/live?point_ids=${encodeURIComponent(ids)}&lookback_minutes=30`);
      const lines = (out.series || []).map(
        (s) => `point_id=${s.point_id} samples=${s.sample_count} last=${s.last_value ?? "null"} at ${s.last_timestamp ?? "-"}`,
      );
      setOnboardLiveValues(lines.join("\n") || "No series returned.");
    } catch (error) {
      setOnboardLiveValues(error instanceof Error ? error.message : String(error));
    }
  }

  const showWeather = section === "all" || section === "weather";
  const showBacnet = section === "all" || section === "bacnet";
  const showOnboard = section === "all" || section === "onboard";
  const onboardTreeByType = onboardEquipmentTree.reduce<Record<string, OnboardEquipment[]>>((acc, eq) => {
    const key = String(eq.equip_type_abbr || eq.equip_type_name || "UNKNOWN").trim() || "UNKNOWN";
    if (!acc[key]) {
      acc[key] = [];
    }
    acc[key].push(eq);
    return acc;
  }, {});
  const onboardTypeSummary = Object.entries(onboardTreeByType)
    .map(([type, rows]) => ({
      type,
      equipmentCount: rows.length,
      pointCount: rows.reduce((n, row) => n + (row.points?.length || 0), 0),
    }))
    .sort((a, b) => b.equipmentCount - a.equipmentCount);
  const onboardSampleDevices = onboardEquipmentTree.slice(0, 15).map((eq) => {
    const equipType = String(eq.equip_type_abbr || eq.equip_type_name || "UNKNOWN");
    return `${eq.name} | ${equipType} | points=${eq.points?.length || 0}`;
  });
  const titleBySection: Record<DriversPageSection, string> = {
    all: embedded ? "Driver Control Center" : "Drivers",
    weather: "Open-Meteo Driver",
    bacnet: "BACnet Driver (diy-bacnet-server)",
    onboard: "Onboard Driver",
  };

  async function runOnboardSmokeTest() {
    if (!onboardBuildingInspectId) {
      setOnboardSmokeResult("Pick a building first.");
      return;
    }
    setOnboardBusy(true);
    setOnboardSmokeResult("Running smoke test...");
    try {
      const auth = await desktopFetch<{ ok: boolean; building_count: number; message: string }>("/config/onboard/auth-test");
      const points = await desktopFetch<{
        building_id: number;
        point_count: number;
        point_type_counts: Array<{ point_type: string; count: number }>;
        sample_points: Array<Record<string, unknown>>;
      }>(
        `/config/onboard/buildings/${encodeURIComponent(onboardBuildingInspectId)}/points?point_type=${encodeURIComponent(onboardPointTypeFilter || "zone_air_temperature_sensor")}`,
      );
      const sampleIds = (points.sample_points || [])
        .slice(0, 5)
        .map((row) => String(row.id ?? ""))
        .filter(Boolean);
      let liveSummary = "no sample point IDs available";
      if (sampleIds.length) {
        const live = await desktopFetch<{
          series: Array<{ point_id: number | string; sample_count: number; last_value?: unknown; last_timestamp?: string | null }>;
        }>(`/config/onboard/points/live?point_ids=${encodeURIComponent(sampleIds.join(","))}&lookback_minutes=30`);
        liveSummary = `streamed blocks: ${live.series?.length || 0}, value rows: ${(live.series || []).reduce((n, s) => n + (s.sample_count || 0), 0)}`;
      }
      const msg = [
        "1) auth_test",
        `   ${auth.message} buildings visible: ${auth.building_count}`,
        "2) select_points",
        `   point IDs for ${onboardPointTypeFilter || "zone_air_temperature_sensor"}: ${points.sample_points?.length || 0}`,
        `   sampling IDs: ${sampleIds.length ? `[${sampleIds.join(", ")}]` : "[]"}`,
        "3) stream_point_timeseries",
        `   ${liveSummary}`,
        "",
        "Smoke test complete.",
      ].join("\n");
      setOnboardSmokeResult(msg);
      setOnboardActionLog((prev) => [
        `${new Date().toLocaleTimeString()} Smoke test complete.`,
        ...prev.slice(0, 11),
      ]);
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      setOnboardSmokeResult(`Smoke test failed: ${msg}`);
      setOnboardActionLog((prev) => [
        `${new Date().toLocaleTimeString()} Smoke test failed: ${msg}`,
        ...prev.slice(0, 11),
      ]);
    } finally {
      setOnboardBusy(false);
    }
  }

  const content = (
    <>
      <div className="card">
        <h2 className="title">{titleBySection[section]}</h2>
        <p className="muted">
          Supported now: CSV import, Open-Meteo weather, BACnet via diy-bacnet-server, and Onboard API ingest.
        </p>
        {!embedded ? (
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
        ) : null}
        <div style={{ marginTop: 12 }}>
          <h3 className="title" style={{ marginTop: 0 }}>Driver health</h3>
          <div className="grid-two">
            {(section === "onboard" ? ["onboard"] : ["csv", "weather", "bacnet", "onboard"]).map((driver) => {
              const h = driverHealth[driver];
              return (
                <div key={driver} className="card" style={{ padding: 10 }}>
                  <strong style={{ textTransform: "uppercase" }}>{driver}</strong>
                  <div style={{ fontSize: 13, marginTop: 6 }}>
                    <div>Last run: {h?.last_run ? new Date(h.last_run).toLocaleString() : "Never"}</div>
                    <div>Rows ingested: {typeof h?.rows === "number" ? h.rows : 0}</div>
                    <div>Status: {h?.success === null || h?.success === undefined ? "Unknown" : h.success ? "OK" : "Error"}</div>
                    <div>Last error: {h?.last_error || "-"}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {showWeather ? <div className="card">
        <h3 className="title">Open-Meteo Driver</h3>
        <div className="grid-two">
          <div>
            <label>Start date</label>
            <input type="date" value={weatherStartDate} onChange={(e) => setWeatherStartDate(e.target.value)} />
          </div>
          <div>
            <label>End date</label>
            <input type="date" value={weatherEndDate} onChange={(e) => setWeatherEndDate(e.target.value)} />
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
            Run weather ingest now
          </button>
        </div>
      </div> : null}

      {showBacnet ? <div className="card">
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
            <input
              type="password"
              value={bacnetApiKey}
              onChange={(e) => setBacnetApiKey(e.target.value)}
              placeholder={bacnetApiKeySet ? "Saved key present" : "Paste token"}
            />
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
      </div> : null}

      {showOnboard ? <div className="card">
        <h3 className="title">Onboard Driver</h3>
        <p className="muted" style={{ marginTop: 0 }}>
          Workflow: paste API key, test auth, browse building/equipment/points, live-check point values, then bulk ingest to Feather.
        </p>
        <div style={{ display: "grid", gap: 10 }}>
          <div>
            <label>API base URL</label>
            <input
              value={onboardBaseUrl}
              onChange={(e) => setOnboardBaseUrl(e.target.value)}
              style={{ width: "100%" }}
            />
          </div>
          <div>
            <label>API key</label>
            <div style={{ display: "flex", gap: 8 }}>
              <input
                type="password"
                value={onboardApiKey}
                onChange={(e) => setOnboardApiKey(e.target.value)}
                placeholder={onboardApiKeySet ? "Saved key present" : "Paste token"}
                style={{ flex: 1 }}
              />
              <button type="button" onClick={() => void testOnboardAuth()} disabled={onboardBusy}>Test API auth</button>
              <button type="button" className="secondary-btn" onClick={() => void saveOnboardConfig()} disabled={onboardBusy}>
                Save config
              </button>
            </div>
            <div
              style={{
                marginTop: 6,
                fontSize: 12,
                color:
                  onboardAuthStatus === "ok"
                    ? "var(--success-700)"
                    : onboardAuthStatus === "error"
                      ? "var(--danger-700)"
                      : "var(--muted-foreground)",
              }}
            >
              {onboardAuthMessage || "Paste key, then click Test API auth."}
            </div>
          </div>
        </div>
        <div className="grid-two" style={{ marginTop: 10 }}>
          <div>
            <label>Selected building</label>
            <select
              value={onboardBuildingInspectId}
              onChange={(e) => setOnboardBuildingInspectId(e.target.value)}
            >
              <option value="">Select building</option>
              {onboardBuildings.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name} (id={b.id}, points={b.point_count ?? "?"})
                </option>
              ))}
            </select>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <button type="button" className="secondary-btn" onClick={() => void discoverOnboardBuildings()} disabled={onboardBusy}>
            Fetch buildings
          </button>
        </div>
        <div
          style={{
            marginTop: 10,
            border: "1px solid var(--border-color)",
            borderRadius: 6,
            padding: 10,
            background: "var(--panel-bg, transparent)",
          }}
        >
          <strong>Onboard data in Feather (selected site)</strong>
          <div style={{ marginTop: 6, fontSize: 13 }}>
            <div>Rows: {typeof onboardDataBounds?.rows === "number" ? onboardDataBounds.rows : 0}</div>
            <div>Latest timestamp: {onboardDataBounds?.end ? new Date(onboardDataBounds.end).toLocaleString() : "-"}</div>
            <div>Earliest timestamp: {onboardDataBounds?.start ? new Date(onboardDataBounds.start).toLocaleString() : "-"}</div>
          </div>
          <div style={{ marginTop: 8 }}>
            <button type="button" className="secondary-btn" onClick={() => void refreshOnboardDataPresence()} disabled={onboardBusy}>
              Refresh onboard data status
            </button>
          </div>
        </div>
        <div style={{ marginTop: 14, borderTop: "1px solid var(--border-color)", paddingTop: 12 }}>
          <h4 style={{ margin: "0 0 8px" }}>Points tree</h4>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <button
              type="button"
              className="secondary-btn"
              onClick={() => {
                setOnboardPointTypeFilter("");
                setOnboardEquipFilter("");
                void loadOnboardEquipmentTree();
              }}
              disabled={onboardBusy || !onboardBuildingInspectId}
            >
              Build points tree for selected building
            </button>
            <span className="muted" style={{ fontSize: 12 }}>
              Loads all equipment and points for the selected building.
            </span>
          </div>
          <textarea readOnly value={onboardDiscoveryResult} style={{ minHeight: 90, marginTop: 10 }} />
          <div style={{ marginTop: 10, border: "1px solid var(--border-color)", borderRadius: 6, padding: 10 }}>
            <h4 style={{ margin: "0 0 8px" }}>Discovery summary</h4>
            <div style={{ fontSize: 13, marginBottom: 8 }}>
              Building ID: {onboardBuildingInspectId || "-"}<br />
              Equipment count: {onboardEquipmentTree.length}<br />
              Point count: {onboardEquipmentTree.reduce((n, eq) => n + (eq.points?.length || 0), 0)}
            </div>
            <div style={{ marginBottom: 8 }}>
              <strong>Equipment type counts</strong>
              <div style={{ marginTop: 6, display: "flex", gap: 8, flexWrap: "wrap" }}>
                {onboardTypeSummary.slice(0, 20).map((row) => (
                  <span
                    key={`summary-${row.type}`}
                    style={{ fontSize: 12, border: "1px solid var(--border-color)", borderRadius: 999, padding: "2px 8px" }}
                  >
                    {row.type}: {row.equipmentCount}
                  </span>
                ))}
              </div>
            </div>
            <div>
              <strong>Sample devices</strong>
              <textarea
                readOnly
                value={onboardSampleDevices.length ? onboardSampleDevices.join("\n") : "No sample devices loaded yet."}
                style={{ minHeight: 90, marginTop: 6 }}
              />
            </div>
          </div>
          <div style={{ marginTop: 10, maxHeight: 420, overflow: "auto", border: "1px solid var(--border-color)", borderRadius: 6, padding: 8 }}>
            {onboardTypeSummary.length > 0 ? (
              <div style={{ marginBottom: 10, display: "flex", gap: 8, flexWrap: "wrap" }}>
                {onboardTypeSummary.slice(0, 12).map((row) => (
                  <span
                    key={row.type}
                    style={{
                      fontSize: 12,
                      border: "1px solid var(--border-color)",
                      borderRadius: 999,
                      padding: "2px 8px",
                    }}
                  >
                    {row.type}: {row.equipmentCount} equip / {row.pointCount} pts
                  </span>
                ))}
              </div>
            ) : null}
            {onboardEquipmentTree.length === 0 ? (
              <div className="muted">No equipment tree loaded yet.</div>
            ) : (
              Object.entries(onboardTreeByType)
                .sort((a, b) => b[1].length - a[1].length)
                .map(([type, rows]) => (
                  <details key={type} open style={{ marginBottom: 8 }}>
                    <summary>
                      <strong>{type}</strong>{" "}
                      <span className="muted">({rows.length} equipment)</span>
                    </summary>
                    <div style={{ paddingLeft: 10, marginTop: 6 }}>
                      {rows.map((eq) => {
                        const countsByPointType = (eq.points || []).reduce<Record<string, number>>((acc, pt) => {
                          const key = String(pt.point_type || "unknown").trim() || "unknown";
                          acc[key] = (acc[key] || 0) + 1;
                          return acc;
                        }, {});
                        return (
                          <details key={`${eq.id ?? eq.name}`} style={{ marginBottom: 6 }}>
                            <summary>
                              <strong>{eq.name}</strong>{" "}
                              <span className="muted">(points={eq.points?.length || 0})</span>
                            </summary>
                            <div style={{ paddingLeft: 12, marginTop: 6 }}>
                              {Object.keys(countsByPointType).length > 0 ? (
                                <div style={{ marginBottom: 6, display: "flex", gap: 6, flexWrap: "wrap" }}>
                                  {Object.entries(countsByPointType)
                                    .sort((a, b) => b[1] - a[1])
                                    .slice(0, 10)
                                    .map(([pt, n]) => (
                                      <span
                                        key={`${eq.id ?? eq.name}-${pt}`}
                                        style={{
                                          fontSize: 11,
                                          border: "1px solid var(--border-color)",
                                          borderRadius: 999,
                                          padding: "1px 7px",
                                        }}
                                      >
                                        {pt}: {n}
                                      </span>
                                    ))}
                                </div>
                              ) : null}
                              {(eq.points || []).slice(0, 120).map((pt, idx) => (
                                <div
                                  key={`${eq.id ?? "e"}-${pt.id ?? pt.name ?? idx}`}
                                  style={{
                                    fontSize: 13,
                                    display: "grid",
                                    gridTemplateColumns: "110px 1fr",
                                    gap: 8,
                                    padding: "2px 0",
                                  }}
                                >
                                  <span className="muted">#{pt.id ?? "-"}</span>
                                  <span>
                                    {pt.name || "unnamed"}{" "}
                                    <span className="muted">[{pt.point_type || "unknown"}]</span>
                                  </span>
                                </div>
                              ))}
                            </div>
                          </details>
                        );
                      })}
                    </div>
                  </details>
                ))
            )}
          </div>
          <div style={{ marginTop: 12, borderTop: "1px solid var(--border-color)", paddingTop: 12 }}>
            <h4 style={{ margin: "0 0 8px" }}>Live point snapshot</h4>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <input
                value={onboardLivePointIds}
                onChange={(e) => setOnboardLivePointIds(e.target.value)}
                placeholder="point IDs (comma-separated)"
                style={{ minWidth: 340 }}
              />
              <button type="button" className="secondary-btn" onClick={() => void refreshOnboardLivePoints()} disabled={onboardBusy}>
                Refresh live points
              </button>
            </div>
            <textarea readOnly value={onboardLiveValues} style={{ minHeight: 90, marginTop: 8 }} />
          </div>
          <div style={{ marginTop: 12, borderTop: "1px solid var(--border-color)", paddingTop: 12 }}>
            <h4 style={{ margin: "0 0 8px" }}>Bulk data download</h4>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
              <div>
                <label>Lookback hours</label>
                <input value={onboardLookbackHours} onChange={(e) => setOnboardLookbackHours(e.target.value)} />
              </div>
              <button className="secondary-btn" onClick={() => void runOnboardIngest()} disabled={onboardBusy}>
                Bulk download now
              </button>
            </div>
          </div>
          <div style={{ marginTop: 12, borderTop: "1px solid var(--border-color)", paddingTop: 12 }}>
            <h4 style={{ margin: "0 0 8px" }}>Action log</h4>
            <textarea
              readOnly
              value={onboardActionLog.length ? onboardActionLog.join("\n") : "No onboard actions yet."}
              style={{ minHeight: 110 }}
            />
          </div>
        </div>
      </div> : null}

      <div className="card">
        <textarea readOnly value={status} style={{ minHeight: 96 }} />
      </div>
    </>
  );
  if (embedded) {
    return <div className="stack-page">{content}</div>;
  }
  return <div className="stack-page">{content}</div>;
}
