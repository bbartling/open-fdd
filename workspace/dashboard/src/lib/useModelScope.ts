import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "./api";
import { formatApiError } from "./formatApiError";

export type ModelSite = { site_id: string; name: string };

export type ModelEquipment = {
  equipment_id: string;
  name: string;
  label: string;
  equipment_type?: string;
  bacnet_device_instance?: number | string | null;
};

export type ModelSensor = {
  point_id: string;
  name: string;
  label: string;
  brick_type: string;
  timeseries_column: string;
  fdd_input?: string;
  series_id?: string;
};

export type ModelScope = {
  sites: ModelSite[];
  siteId: string;
  setSiteId: (id: string) => void;
  equipment: ModelEquipment[];
  equipmentId: string;
  setEquipmentId: (id: string) => void;
  sensors: ModelSensor[];
  activeEquipment: ModelEquipment | undefined;
  queryEngine: string;
  loading: boolean;
  error: string;
  reload: () => Promise<void>;
};

type ScopeResponse = {
  ok?: boolean;
  site_id?: string;
  equipment_id?: string;
  sites?: ModelSite[];
  equipment?: ModelEquipment[];
  sensors?: ModelSensor[];
  query_engine?: string;
};

export function useModelScope(initialSiteId?: string, brickTypeFilter?: string): ModelScope {
  const [sites, setSites] = useState<ModelSite[]>([]);
  const [siteId, setSiteId] = useState(initialSiteId || "");
  const [siteBootstrapped, setSiteBootstrapped] = useState(Boolean(initialSiteId));
  const [equipment, setEquipment] = useState<ModelEquipment[]>([]);
  const [equipmentId, setEquipmentId] = useState("");
  const [sensors, setSensors] = useState<ModelSensor[]>([]);
  const [queryEngine, setQueryEngine] = useState("json");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadScope = useCallback(async (sid: string, eid: string, brickType?: string) => {
    if (!sid) return;
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ site_id: sid });
      if (eid) params.set("equipment_id", eid);
      if (brickType?.trim()) params.set("brick_type", brickType.trim());
      const res = await apiFetch<ScopeResponse>(`/api/model/scope?${params}`);
      const siteList = res.sites ?? [];
      setSites(siteList);
      setEquipment(res.equipment ?? []);
      setSensors(res.sensors ?? []);
      setQueryEngine(res.query_engine || "json");
      if (!siteId && res.site_id) {
        setSiteId(res.site_id);
      }
      const nextEq = eid || res.equipment_id || res.equipment?.[0]?.equipment_id || "";
      setEquipmentId(nextEq);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (siteBootstrapped) return;
    let cancelled = false;
    apiFetch<{ active_site_id?: string; sites?: ModelSite[] }>("/api/model/sites")
      .then((res) => {
        if (cancelled) return;
        const first = res.sites?.[0] as { site_id?: string; id?: string } | undefined;
        const sid = res.active_site_id || first?.site_id || first?.id || initialSiteId || "";
        if (sid) setSiteId(sid);
        if (res.sites?.length) setSites(res.sites);
        setSiteBootstrapped(true);
      })
      .catch(() => setSiteBootstrapped(true));
    return () => {
      cancelled = true;
    };
  }, [siteBootstrapped, initialSiteId]);

  useEffect(() => {
    if (!siteId) return;
    void loadScope(siteId, equipmentId, brickTypeFilter);
  }, [siteId, equipmentId, brickTypeFilter, loadScope]);

  const activeEquipment = equipment.find((e) => e.equipment_id === equipmentId);

  return {
    sites,
    siteId,
    setSiteId: (id: string) => {
      setEquipmentId("");
      setSiteId(id);
    },
    equipment,
    equipmentId,
    setEquipmentId,
    sensors,
    activeEquipment,
    queryEngine,
    loading,
    error,
    reload: () => loadScope(siteId, equipmentId, brickTypeFilter),
  };
}
