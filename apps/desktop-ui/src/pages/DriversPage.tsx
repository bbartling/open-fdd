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
const ONBOARD_LOG_MAX = 28;

type OnboardOp = "idle" | "auth" | "save" | "buildings" | "availability" | "feather" | "tree" | "bulk";

function onboardLogLine(message: string): string {
  return `${new Date().toLocaleTimeString()} ${message}`;
}

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

function localDayBoundsToIso(startYmd: string, endYmd: string): { startTs: string; endTs: string } | null {
  const parts = (s: string): { y: number; m: number; d: number } | null => {
    const seg = s.split("-");
    if (seg.length !== 3) return null;
    const y = Number(seg[0]);
    const m = Number(seg[1]);
    const d = Number(seg[2]);
    if (!Number.isInteger(y) || !Number.isInteger(m) || !Number.isInteger(d)) return null;
    return { y, m, d };
  };
  const a = parts(startYmd);
  const b = parts(endYmd);
  if (!a || !b) return null;
  const start = new Date(a.y, a.m - 1, a.d, 0, 0, 0, 0);
  const end = new Date(b.y, b.m - 1, b.d, 23, 59, 59, 999);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return null;
  if (end.getTime() < start.getTime()) return null;
  return { startTs: start.toISOString(), endTs: end.toISOString() };
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
  const [onboardOp, setOnboardOp] = useState<OnboardOp>("idle");
  const [onboardStartDate, setOnboardStartDate] = useState(initialRange.start);
  const [onboardEndDate, setOnboardEndDate] = useState(initialRange.end);
  const [onboardRangeReady, setOnboardRangeReady] = useState(false);
  const [onboardPrefillFlashOn, setOnboardPrefillFlashOn] = useState(true);
  const [onboardBuildings, setOnboardBuildings] = useState<OnboardBuilding[]>([]);
  const [onboardBuildingInspectId, setOnboardBuildingInspectId] = useState<string>("");
  const [onboardEquipmentTree, setOnboardEquipmentTree] = useState<OnboardEquipment[]>([]);
  const [onboardDataBounds, setOnboardDataBounds] = useState<SourceBounds | null>(null);
  const [onboardActionLog, setOnboardActionLog] = useState<string[]>([]);
  const [onboardDiscoveryResult, setOnboardDiscoveryResult] = useState("");
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
    if (onboardRangeReady) {
      setOnboardPrefillFlashOn(false);
      return;
    }
    const id = window.setInterval(() => setOnboardPrefillFlashOn((v) => !v), 520);
    return () => window.clearInterval(id);
  }, [onboardRangeReady]);

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
    setOnboardOp("save");
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
      if (out.api_key_set) {
        setOnboardApiKey("");
      }
      setStatus("Saved Onboard driver config.");
      setOnboardActionLog((prev) => [
        onboardLogLine(`POST /config/onboard OK (building_ids=${selectedBuilding || "none"}, lookback=${parsedLookback}h).`),
        ...prev.slice(0, ONBOARD_LOG_MAX - 1),
      ]);
      await refreshConfigs();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
      setOnboardActionLog((prev) => [
        onboardLogLine(`POST /config/onboard FAILED: ${error instanceof Error ? error.message : String(error)}`),
        ...prev.slice(0, ONBOARD_LOG_MAX - 1),
      ]);
    } finally {
      setOnboardOp("idle");
    }
  }

  async function runOnboardIngest() {
    const effectiveSiteId = embedded ? (selectedSiteId || "") : (siteId || selectedSiteId || "");
    if (!effectiveSiteId) {
      setStatus("Select a site first.");
      return;
    }
    const bounds = localDayBoundsToIso(onboardStartDate, onboardEndDate);
    if (!bounds) {
      setStatus("Onboard date range must be valid YYYY-MM-DD and end date must be on/after start date.");
      return;
    }
    const { startTs, endTs } = bounds;
    if (!onboardRangeReady) {
      setStatus("Step 1 required: click 'Prefill from Onboard availability' before bulk download.");
      return;
    }
    setOnboardOp("bulk");
    const buildingForIngest = String(onboardBuildingInspectId || "").trim();
    try {
      setOnboardActionLog((prev) => [
        onboardLogLine(
          `POST /ingest/onboard starting site_id=${effectiveSiteId} building_ids=${buildingForIngest || "(saved config)"} start=${startTs} end=${endTs} …`,
        ),
        ...prev.slice(0, ONBOARD_LOG_MAX - 1),
      ]);
      const out = await desktopFetch<{ rows: number; source: string; success: boolean; error?: string }>("/ingest/onboard", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          site_id: effectiveSiteId,
          start_ts: startTs,
          end_ts: endTs,
          ...(buildingForIngest ? { building_ids: buildingForIngest } : {}),
        }),
      });
      setStatus(
        out.success
          ? `Onboard ingest complete: rows=${out.rows}, source=${out.source}.`
          : `Onboard ingest failed: ${out.error || "Missing credentials or source error."}`,
      );
      setOnboardActionLog((prev) => [
        onboardLogLine(
          `POST /ingest/onboard ${out.success ? "OK" : "FAILED"} site_id=${effectiveSiteId} building_ids=${buildingForIngest || "(saved config)"} rows=${out.rows} source=${out.source ?? "?"} err=${out.error ?? "-"}`,
        ),
        ...prev.slice(0, ONBOARD_LOG_MAX - 1),
      ]);
      await refreshOnboardDataPresence({ manageOp: false });
      await refreshConfigs();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
      setOnboardActionLog((prev) => [
        onboardLogLine(`POST /ingest/onboard FAILED: ${error instanceof Error ? error.message : String(error)}`),
        ...prev.slice(0, ONBOARD_LOG_MAX - 1),
      ]);
    } finally {
      setOnboardOp("idle");
    }
  }

  async function refreshOnboardDataPresence(opts?: { manageOp?: boolean }) {
    const manageOp = opts?.manageOp !== false;
    const effectiveSiteId = embedded ? (selectedSiteId || "") : (siteId || selectedSiteId || "");
    if (!effectiveSiteId) {
      setOnboardDataBounds(null);
      setStatus("Pick a site in the selector above, then refresh Feather status.");
      setOnboardActionLog((prev) => [
        onboardLogLine("POST /timeseries/bounds skipped: no site_id (select a site first)."),
        ...prev.slice(0, ONBOARD_LOG_MAX - 1),
      ]);
      return;
    }
    if (manageOp) {
      setOnboardOp("feather");
    }
    try {
      setOnboardActionLog((prev) => [
        onboardLogLine(`POST /timeseries/bounds starting site_id=${effectiveSiteId} source=onboard …`),
        ...prev.slice(0, ONBOARD_LOG_MAX - 1),
      ]);
      const out = await desktopFetch<SourceBounds>("/timeseries/bounds", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ site_id: effectiveSiteId, source: "onboard" }),
      });
      setOnboardDataBounds(out);
      setOnboardActionLog((prev) => [
        onboardLogLine(
          `POST /timeseries/bounds OK site_id=${effectiveSiteId} source=onboard rows=${out.rows} start=${out.start ?? "-"} end=${out.end ?? "-"}`,
        ),
        ...prev.slice(0, ONBOARD_LOG_MAX - 1),
      ]);
    } catch (error) {
      setOnboardDataBounds(null);
      const msg = error instanceof Error ? error.message : String(error);
      setOnboardActionLog((prev) => [onboardLogLine(`POST /timeseries/bounds FAILED: ${msg}`), ...prev.slice(0, ONBOARD_LOG_MAX - 1)]);
      setStatus(`Feather bounds failed: ${msg}`);
    } finally {
      if (manageOp) {
        setOnboardOp("idle");
      }
    }
  }

  async function discoverOnboardBuildings() {
    setOnboardOp("buildings");
    try {
      setOnboardActionLog((prev) => [onboardLogLine("GET /config/onboard/buildings …"), ...prev.slice(0, ONBOARD_LOG_MAX - 1)]);
      const out = await desktopFetch<{ count: number; buildings: OnboardBuilding[] }>("/config/onboard/buildings");
      setOnboardBuildings(out.buildings || []);
      const selectedId = String(onboardBuildingInspectId || out.buildings?.[0]?.id || "").trim();
      if (selectedId) {
        setOnboardBuildingInspectId(selectedId);
        setOnboardRangeReady(false);
      }
      setOnboardDiscoveryResult(`Found ${out.count || 0} buildings from Onboard.`);
      setOnboardActionLog((prev) => [
        onboardLogLine(`GET /config/onboard/buildings OK count=${out.count || 0}.`),
        ...prev.slice(0, ONBOARD_LOG_MAX - 1),
      ]);
      if (selectedId) {
        await loadOnboardEquipmentTree(selectedId);
        await prefillOnboardDateRange(selectedId);
      }
    } catch (error) {
      setOnboardDiscoveryResult(error instanceof Error ? error.message : String(error));
      setOnboardActionLog((prev) => [
        onboardLogLine(`GET /config/onboard/buildings FAILED: ${error instanceof Error ? error.message : String(error)}`),
        ...prev.slice(0, ONBOARD_LOG_MAX - 1),
      ]);
    } finally {
      setOnboardOp("idle");
    }
  }

  async function prefillOnboardDateRange(buildingIdOverride?: string) {
    const buildingId = String(buildingIdOverride || onboardBuildingInspectId || "").trim();
    if (!buildingId) {
      setStatus("Pick a building first.");
      return;
    }
    setOnboardOp("availability");
    try {
      const path = `/config/onboard/buildings/${encodeURIComponent(buildingId)}/availability?search_back_days=365&sample_points=14`;
      setOnboardActionLog((prev) => [onboardLogLine(`GET ${path} …`), ...prev.slice(0, ONBOARD_LOG_MAX - 1)]);
      const out = await desktopFetch<{
        earliest_seen?: string | null;
        latest_seen?: string | null;
        sampled_point_ids: number[];
      }>(path);
      const toDateInput = (raw: string | null | undefined): string => {
        if (!raw) return "";
        const d = new Date(raw);
        if (Number.isNaN(d.getTime())) return "";
        const y = d.getFullYear();
        const m = String(d.getMonth() + 1).padStart(2, "0");
        const day = String(d.getDate()).padStart(2, "0");
        return `${y}-${m}-${day}`;
      };
      const start = toDateInput(out.earliest_seen || null);
      const end = toDateInput(out.latest_seen || null);
      if (start) setOnboardStartDate(start);
      if (end) setOnboardEndDate(end);
      setOnboardRangeReady(Boolean(start && end));
      setOnboardActionLog((prev) => [
        onboardLogLine(
          `GET …/availability OK sampled=${(out.sampled_point_ids || []).length} earliest=${out.earliest_seen ?? "-"} latest=${out.latest_seen ?? "-"}`,
        ),
        ...prev.slice(0, ONBOARD_LOG_MAX - 1),
      ]);
    } catch (error) {
      setOnboardActionLog((prev) => [
        onboardLogLine(`GET …/availability FAILED: ${error instanceof Error ? error.message : String(error)}`),
        ...prev.slice(0, ONBOARD_LOG_MAX - 1),
      ]);
    } finally {
      setOnboardOp("idle");
    }
  }

  async function testOnboardAuth() {
    const parsedLookback = Number(onboardLookbackHours || "24");
    const safeLookback = Number.isFinite(parsedLookback) && parsedLookback >= 1 ? parsedLookback : 24;
    const selectedBuilding = String(onboardBuildingInspectId || "").trim();
    setOnboardAuthStatus("testing");
    setOnboardAuthMessage("Testing API key...");
    setOnboardOp("auth");
    try {
      setOnboardActionLog((prev) => [
        onboardLogLine("POST /config/onboard (save draft) then GET /config/onboard/auth-test …"),
        ...prev.slice(0, ONBOARD_LOG_MAX - 1),
      ]);
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
        onboardLogLine(`GET /config/onboard/auth-test OK buildings=${out.building_count} msg=${out.message}`),
        ...prev.slice(0, ONBOARD_LOG_MAX - 1),
      ]);
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      setOnboardDiscoveryResult(msg);
      setOnboardAuthStatus("error");
      setOnboardAuthMessage(msg);
      setStatus(`Onboard auth failed: ${msg}`);
      setOnboardActionLog((prev) => [
        onboardLogLine(`GET /config/onboard/auth-test FAILED: ${msg}`),
        ...prev.slice(0, ONBOARD_LOG_MAX - 1),
      ]);
    } finally {
      setOnboardOp("idle");
    }
  }

  async function loadOnboardEquipmentTree(buildingIdOverride?: string) {
    const buildingId = String(buildingIdOverride || onboardBuildingInspectId || "").trim();
    if (!buildingId) {
      setOnboardDiscoveryResult("Pick a building first.");
      return;
    }
    const qs = new URLSearchParams();
    qs.set("include_points", "true");
    setOnboardOp("tree");
    try {
      const path = `/config/onboard/buildings/${encodeURIComponent(buildingId)}/equipment?${qs.toString()}`;
      setOnboardActionLog((prev) => [onboardLogLine(`GET ${path.split("?")[0]} …`), ...prev.slice(0, ONBOARD_LOG_MAX - 1)]);
      const out = await desktopFetch<{ equipment_count: number; equipment: OnboardEquipment[] }>(path);
      setOnboardEquipmentTree(out.equipment || []);
      setOnboardDiscoveryResult(`Loaded equipment tree rows=${out.equipment_count}.`);
      setOnboardActionLog((prev) => [
        onboardLogLine(`GET …/equipment OK building=${buildingId} equipment_count=${out.equipment_count}`),
        ...prev.slice(0, ONBOARD_LOG_MAX - 1),
      ]);
    } catch (error) {
      setOnboardDiscoveryResult(error instanceof Error ? error.message : String(error));
      setOnboardActionLog((prev) => [
        onboardLogLine(`GET …/equipment FAILED: ${error instanceof Error ? error.message : String(error)}`),
        ...prev.slice(0, ONBOARD_LOG_MAX - 1),
      ]);
    } finally {
      setOnboardOp("idle");
    }
  }

  const onboardWorking = onboardOp !== "idle";
  const onboardOpLabel =
    onboardOp === "idle"
      ? "Ready"
      : onboardOp === "auth"
        ? "Authenticating"
        : onboardOp === "save"
          ? "Saving config"
          : onboardOp === "buildings"
            ? "Fetching buildings"
            : onboardOp === "availability"
              ? "Prefilling date range"
              : onboardOp === "bulk"
                ? "Running bulk download"
                : "Working";

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
  const titleBySection: Record<DriversPageSection, string> = {
    all: embedded ? "Driver Control Center" : "Drivers",
    weather: "Open-Meteo Driver",
    bacnet: "BACnet Driver (diy-bacnet-server)",
    onboard: "Onboard Driver",
  };

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
          Workflow: paste API key, test auth, fetch buildings, prefill date range, then bulk download to Feather.
        </p>
        <div style={{ display: "inline-flex", alignItems: "center", gap: 8, border: "1px solid var(--border-color)", borderRadius: 999, padding: "4px 10px", marginBottom: 10 }}>
          <span aria-hidden style={{ width: 8, height: 8, borderRadius: 999, background: onboardWorking ? "var(--warning-600)" : "var(--success-600)" }} />
          <span style={{ fontSize: 12, fontWeight: 600 }}>{onboardOpLabel}</span>
        </div>
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
            <label>Headless default window (hours, UTC)</label>
            <input
              value={onboardLookbackHours}
              onChange={(e) => setOnboardLookbackHours(e.target.value)}
              inputMode="numeric"
              style={{ maxWidth: 120 }}
            />
            <p className="muted" style={{ margin: "6px 0 0", fontSize: 12 }}>
              Used only when ingest is called without start/end timestamps (for example{" "}
              <code className="inline-code">POST /ingest/onboard</code> with <code className="inline-code">site_id</code> only). Then the
              window is “now” back N hours. Bulk download always uses the calendar Start / End dates after prefill, not this value.
            </p>
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
              <button type="button" className="secondary-btn" onClick={() => void testOnboardAuth()} disabled={onboardWorking} aria-busy={onboardOp === "auth"}>
                {onboardOp === "auth" ? "Testing…" : "Test API auth"}
              </button>
              <button
                type="button"
                className="secondary-btn"
                onClick={() => void saveOnboardConfig()}
                disabled={onboardWorking}
                aria-busy={onboardOp === "save"}
              >
                {onboardOp === "save" ? "Saving…" : "Save config"}
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
              onChange={(e) => {
                setOnboardBuildingInspectId(e.target.value);
                setOnboardRangeReady(false);
              }}
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
          <button
            type="button"
            className="secondary-btn"
            onClick={() => void discoverOnboardBuildings()}
            disabled={onboardWorking}
            aria-busy={onboardOp === "buildings"}
          >
            {onboardOp === "buildings" ? "Fetching…" : "Fetch buildings"}
          </button>
        </div>
        <div style={{ marginTop: 14, borderTop: "1px solid var(--border-color)", paddingTop: 12 }}>
          <h4 style={{ margin: "0 0 8px" }}>Onboard equipment summary</h4>
          <div style={{ fontSize: 13, marginBottom: 8 }}>
            Building ID: {onboardBuildingInspectId || "-"}
          </div>
          <div style={{ marginBottom: 8 }}>
            <strong>Equipment type counts</strong>
            <div style={{ marginTop: 6, display: "flex", gap: 8, flexWrap: "wrap" }}>
              {onboardTypeSummary.length === 0 ? (
                <span className="muted" style={{ fontSize: 12 }}>
                  No equipment loaded yet. Fetch buildings and build the summary first.
                </span>
              ) : (
                onboardTypeSummary.slice(0, 20).map((row) => (
                  <span
                    key={`summary-${row.type}`}
                    style={{ fontSize: 12, border: "1px solid var(--border-color)", borderRadius: 999, padding: "2px 8px" }}
                  >
                    {row.type}: {row.equipmentCount}
                  </span>
                ))
              )}
            </div>
          </div>
          <div style={{ marginTop: 8 }}>
            <strong>Notes</strong>
            <p className="muted" style={{ margin: "4px 0 0", fontSize: 12 }}>
              Bulk download uses the selected site and the Start / End calendar range (from prefill or your edits), then writes Feather rows under{" "}
              <code className="inline-code">source=onboard</code>. Once this summary looks right, the AI agent has enough structure to help with BRICK
              modeling and FDD on this building.
            </p>
          </div>
        </div>
          <div style={{ marginTop: 12, borderTop: "1px solid var(--border-color)", paddingTop: 12 }}>
            <h4 style={{ margin: "0 0 8px" }}>Bulk data download</h4>
            <p className="muted" style={{ margin: "0 0 10px", fontSize: 12 }}>
              The Onboard <code className="inline-code">query-v2</code> API returns JSON time-series samples. The bridge turns that into a wide
              timestamped table, appends a Feather shard under <code className="inline-code">source=onboard</code>, and upserts point metadata
              (BRICK / FDD hints) in the local model. This path does not read or write CSV; use the CSV import flow if your data is already in a CSV
              file (that path also lands in Feather).
            </p>
            <div
              style={{
                display: "flex",
                gap: 8,
                flexWrap: "wrap",
                alignItems: "flex-end",
                marginBottom: 8,
                border: onboardRangeReady ? "1px solid var(--border-color)" : `2px solid ${onboardPrefillFlashOn ? "var(--warning-600)" : "var(--danger-600)"}`,
                borderRadius: 10,
                padding: 10,
                background: onboardRangeReady ? "transparent" : onboardPrefillFlashOn ? "rgba(250, 173, 20, 0.13)" : "rgba(255, 77, 79, 0.08)",
                transition: "all 120ms linear",
              }}
            >
              <button
                type="button"
                className="secondary-btn"
                onClick={() => void prefillOnboardDateRange()}
                disabled={onboardWorking || !onboardBuildingInspectId}
                aria-busy={onboardOp === "availability"}
              >
                {onboardOp === "availability" ? "Prefilling…" : onboardRangeReady ? "Prefill from Onboard availability" : "STEP 1: Prefill from Onboard availability"}
              </button>
              <span className="muted" style={{ fontSize: 12 }}>
                {onboardRangeReady
                  ? "Date window is ready. You can safely run bulk download."
                  : "Required safety step: prefill index start/end timestamps before bulk download."}
              </span>
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
              <div>
                <label>Start date</label>
                <input type="date" value={onboardStartDate} onChange={(e) => setOnboardStartDate(e.target.value)} />
              </div>
              <div>
                <label>End date</label>
                <input type="date" value={onboardEndDate} onChange={(e) => setOnboardEndDate(e.target.value)} />
              </div>
              <button
                className="secondary-btn"
                onClick={() => void runOnboardIngest()}
                disabled={onboardWorking || !onboardRangeReady}
                aria-busy={onboardOp === "bulk"}
                title={onboardRangeReady ? "Run synchronized bulk download." : "Locked until Step 1 prefill finishes."}
              >
                {onboardOp === "bulk" ? "Downloading…" : onboardRangeReady ? "Bulk download now" : "Bulk download locked (complete Step 1)"}
              </button>
            </div>
          </div>
          <div style={{ marginTop: 12, borderTop: "1px solid var(--border-color)", paddingTop: 12 }}>
            <h4 style={{ margin: "0 0 8px" }}>Action log (console)</h4>
            <textarea
              readOnly
              value={onboardActionLog.length ? onboardActionLog.join("\n") : "No onboard actions yet."}
              style={{ minHeight: 110, fontFamily: "ui-monospace, monospace", fontSize: 12 }}
            />
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
