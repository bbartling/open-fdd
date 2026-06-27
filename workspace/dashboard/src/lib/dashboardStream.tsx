import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { apiFetch, hasToken } from "./api";
import type { Traffic } from "../components/TrafficLight";

export type ServiceStatus = "green" | "yellow" | "red" | "gray";

export type StackService = {
  id: string;
  label: string;
  status: ServiceStatus;
  configured: boolean;
  detail: string | Record<string, unknown>;
  url?: string;
};

export type StackHealth = {
  ok: boolean;
  overall: ServiceStatus;
  services: StackService[];
  bacnet_bind?: string | null;
};

export type FaultAnalytics = {
  fault_samples?: number;
  total_samples?: number;
  avg_value_fault?: number;
  avg_value_normal?: number;
  min_value_fault?: number;
  max_value_fault?: number;
  value_unit?: string;
  bounds_low?: number;
  bounds_high?: number;
  fault_span_label?: string;
  estimated_fault_duration_label?: string;
  estimated_fault_duration_sec?: number;
  estimated_fault_duration_hours?: number;
  hours_in_fault?: number;
  first_seen_at?: string;
  last_seen_at?: string;
  fault_span_sec?: number;
  sample_period_sec?: number;
  value_columns?: string[];
};

export type FaultAlert = {
  id?: string;
  severity: string;
  title: string;
  detail?: string;
  source?: string;
  code?: string;
  rule_id?: string;
  rule_name?: string;
  equipment_id?: string;
  equipment_name?: string;
  equipment_family?: string;
  analytics?: FaultAnalytics;
};

export type FaultFamily = {
  family: string;
  label: string;
  worst: string;
  traffic: Traffic;
  count: number;
  faults: FaultAlert[];
};

export type FaultsStatus = {
  status: "ok" | "warning" | "critical";
  traffic: Traffic;
  check_engine: boolean;
  alert_count: number;
  model_configured: boolean;
  families: FaultFamily[];
};

export type DashboardSnapshot = {
  stack: StackHealth;
  faults: FaultsStatus;
};

type DashboardStreamValue = {
  snapshot: DashboardSnapshot | null;
  error: string;
  live: boolean;
};

const DashboardStreamContext = createContext<DashboardStreamValue>({
  snapshot: null,
  error: "",
  live: false,
});

async function fetchSnapshot(authenticated: boolean): Promise<DashboardSnapshot> {
  if (!authenticated) {
    const snap = await apiFetch<DashboardSnapshot & { ok?: boolean }>("/api/building/snapshot");
    const { ok: _ok, ...body } = snap;
    return body as DashboardSnapshot;
  }
  const [stack, faults] = await Promise.all([
    apiFetch<StackHealth>("/api/health/stack"),
    apiFetch<FaultsStatus & { ok?: boolean }>("/api/faults/status"),
  ]);
  const { ok: _ok, ...faultBody } = faults;
  return { stack, faults: faultBody as FaultsStatus };
}

export function DashboardStreamProvider({ children, pollMs = 15000 }: { children: ReactNode; pollMs?: number }) {
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null);
  const [error, setError] = useState("");
  const [live, setLive] = useState(false);
  const [authenticated, setAuthenticated] = useState(hasToken());

  useEffect(() => {
    const sync = () => setAuthenticated(hasToken());
    sync();
    window.addEventListener("ofdd-auth", sync);
    return () => window.removeEventListener("ofdd-auth", sync);
  }, []);

  useEffect(() => {
    let cancelled = false;
    let pollId = 0;

    const apply = (data: DashboardSnapshot) => {
      if (!cancelled) {
        setSnapshot(data);
        setError("");
      }
    };

    const poll = () => {
      fetchSnapshot(authenticated)
        .then(apply)
        .catch((e) => {
          if (!cancelled) setError(String(e));
        });
    };

    poll();
    pollId = window.setInterval(poll, pollMs);
    setLive(false);
    const onRefresh = () => poll();
    window.addEventListener("ofdd-dashboard-refresh", onRefresh);

    return () => {
      cancelled = true;
      window.removeEventListener("ofdd-dashboard-refresh", onRefresh);
      window.clearInterval(pollId);
    };
  }, [pollMs, authenticated]);

  const value = useMemo(() => ({ snapshot, error, live }), [snapshot, error, live]);
  return <DashboardStreamContext.Provider value={value}>{children}</DashboardStreamContext.Provider>;
}

export function useDashboardStream(): DashboardStreamValue {
  return useContext(DashboardStreamContext);
}
