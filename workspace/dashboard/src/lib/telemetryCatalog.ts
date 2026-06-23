import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "./api";
import { formatApiError } from "./formatApiError";

const LOG = (...args: unknown[]) => {
  if (import.meta.env.DEV || localStorage.getItem("ofdd_debug_plot") === "1") {
    console.debug("[telemetry]", ...args);
  }
};

export type SiteRow = { site_id: string; name: string };

export type SeriesOption = {
  key: string;
  column: string;
  equipment_id: string;
  label: string;
  brick_type?: string;
};

export type EquipmentGroup = {
  equipment_id: string;
  name: string;
  label: string;
  bacnet_device_instance?: number | null;
  keys: string[];
  columns: string[];
};

type SeriesCatalogResponse = {
  columns: string[];
  labels: Record<string, string>;
  kinds?: Record<string, string>;
  series_options?: SeriesOption[];
  equipment_groups?: EquipmentGroup[];
};

export type TelemetryCatalog = {
  sites: SiteRow[];
  siteId: string;
  setSiteId: (id: string) => void;
  seriesOptions: SeriesOption[];
  equipmentGroups: EquipmentGroup[];
  equipmentId: string;
  setEquipmentId: (id: string) => void;
  labels: Record<string, string>;
  kinds: Record<string, string>;
  loading: boolean;
  error: string;
  visibleOptions: SeriesOption[];
  activeGroup: EquipmentGroup | undefined;
  reload: () => Promise<void>;
};

export function useTelemetryCatalog(initialSiteId?: string): TelemetryCatalog {
  const [sites, setSites] = useState<SiteRow[]>([]);
  const [siteId, setSiteId] = useState(initialSiteId || "");
  const [seriesOptions, setSeriesOptions] = useState<SeriesOption[]>([]);
  const [equipmentGroups, setEquipmentGroups] = useState<EquipmentGroup[]>([]);
  const [equipmentId, setEquipmentId] = useState("");
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [kinds, setKinds] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    apiFetch<{ sites: SiteRow[] }>("/api/timeseries/sites")
      .then((res) => {
        const list = res.sites ?? [];
        setSites(list);
        if (!siteId && list.length) setSiteId(list[0].site_id);
        LOG("sites loaded", list.length);
      })
      .catch((e) => setError(formatApiError(e)));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const loadCatalog = useCallback(async (sid: string) => {
    if (!sid) return;
    setLoading(true);
    setError("");
    const t0 = performance.now();
    try {
      const res = await apiFetch<SeriesCatalogResponse>(
        `/api/timeseries/series?site_id=${encodeURIComponent(sid)}`,
      );
      const options = res.series_options ?? [];
      const groups = res.equipment_groups ?? [];
      setSeriesOptions(options);
      setEquipmentGroups(groups);
      setLabels(res.labels ?? {});
      setKinds(res.kinds ?? {});
      const firstEq = groups.find((g) => g.equipment_id)?.equipment_id ?? "";
      setEquipmentId((prev) => {
        if (prev && (prev === "__all__" || groups.some((g) => g.equipment_id === prev))) return prev;
        return firstEq || (options.length ? "__all__" : "");
      });
      LOG("catalog", sid, `${options.length} series`, `${groups.length} devices`, `${Math.round(performance.now() - t0)}ms`);
    } catch (e) {
      const msg = formatApiError(e);
      setError(msg);
      LOG("catalog error", sid, msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (siteId) void loadCatalog(siteId);
  }, [siteId, loadCatalog]);

  const visibleOptions =
    !equipmentId || equipmentId === "__all__"
      ? seriesOptions
      : seriesOptions.filter((o) => o.equipment_id === equipmentId);

  const activeGroup = equipmentGroups.find((g) => g.equipment_id === equipmentId);

  return {
    sites,
    siteId,
    setSiteId,
    seriesOptions,
    equipmentGroups,
    equipmentId,
    setEquipmentId,
    labels,
    kinds,
    loading,
    error,
    visibleOptions,
    activeGroup,
    reload: () => loadCatalog(siteId),
  };
}

export function defaultKeysForEquipment(
  options: SeriesOption[],
  equipmentId: string,
  max = 6,
): string[] {
  const pool =
    equipmentId && equipmentId !== "__all__"
      ? options.filter((o) => o.equipment_id === equipmentId)
      : options;
  return pool.slice(0, max).map((o) => o.key);
}
