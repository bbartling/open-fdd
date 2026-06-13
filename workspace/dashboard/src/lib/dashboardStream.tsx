import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { apiFetch, fetchWsTicket, getBridgeBase, hasToken } from "./api";
import type { Traffic } from "../components/TrafficLight";

export type ServiceStatus = "green" | "yellow" | "red" | "gray";

export type StackService = {
  id: string;
  label: string;
  status: ServiceStatus;
  configured: boolean;
  optional?: boolean;
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
  min_value_fault?: number;
  max_value_fault?: number;
  value_unit?: string;
  bounds_low?: number;
  bounds_high?: number;
  fault_span_label?: string;
  estimated_fault_duration_label?: string;
  estimated_fault_duration_sec?: number;
  fault_span_sec?: number;
  sample_period_sec?: number;
  value_columns?: string[];
};

export type FaultModelContext = {
  severity?: string;
  rule_id?: string;
  rule_name?: string;
  fault_code?: string;
  site_id?: string;
  equipment?: { id: string; name: string; type: string };
  point?: {
    id: string;
    name: string;
    external_id?: string;
    fdd_input?: string;
    brick_type?: string;
    bacnet_device_id?: number | string | null;
    object_identifier?: string;
  };
  bacnet_summary?: string;
  historian_column?: string;
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
  model_context?: FaultModelContext;
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

function wsBaseUrl(): string {
  const base = getBridgeBase();
  if (base) {
    const parsed = new URL(base);
    parsed.protocol = parsed.protocol === "https:" ? "wss:" : "ws:";
    parsed.pathname = "/ws/dashboard";
    parsed.search = "";
    parsed.hash = "";
    return parsed.toString();
  }
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws/dashboard`;
}

async function fetchSnapshot(authenticated: boolean): Promise<DashboardSnapshot> {
  if (!authenticated) {
    const snap = await apiFetch<DashboardSnapshot & { ok?: boolean }>("/api/building/snapshot");
    const { ok: _ok, ...body } = snap;
    return body as DashboardSnapshot;
  }
  const [stack, faults] = await Promise.all([
    apiFetch<StackHealth>("/health/stack"),
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
    let ws: WebSocket | null = null;
    let pollId = 0;
    let gotData = false;

    const apply = (data: DashboardSnapshot) => {
      if (!cancelled) {
        gotData = true;
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

    const startPolling = () => {
      setLive(false);
      if (!pollId) {
        poll();
        pollId = window.setInterval(poll, pollMs);
      }
    };

    const connectWs = async () => {
      if (cancelled) return;
      const ticket = await fetchWsTicket();
      if (cancelled) return;
      try {
        const url = new URL(wsBaseUrl());
        ws = ticket
          ? new WebSocket(url.toString(), ["ofdd.ws", ticket])
          : new WebSocket(url.toString());
        ws.onopen = () => {
          if (!cancelled) setLive(true);
        };
        ws.onmessage = (ev) => {
          try {
            apply(JSON.parse(ev.data) as DashboardSnapshot);
          } catch {
            /* ignore malformed frame */
          }
        };
        ws.onerror = () => ws?.close();
        ws.onclose = () => {
          if (!cancelled) startPolling();
        };
      } catch {
        if (!cancelled) startPolling();
      }
    };

    if (authenticated) {
      void connectWs();
    } else {
      startPolling();
    }

    const fallbackTimer = authenticated
      ? window.setTimeout(() => {
          if (!cancelled && !gotData) startPolling();
        }, 2500)
      : 0;

    return () => {
      cancelled = true;
      ws?.close();
      window.clearInterval(pollId);
      if (fallbackTimer) window.clearTimeout(fallbackTimer);
    };
  }, [pollMs, authenticated]);

  const value = useMemo(() => ({ snapshot, error, live }), [snapshot, error, live]);
  return <DashboardStreamContext.Provider value={value}>{children}</DashboardStreamContext.Provider>;
}

export function useDashboardStream(): DashboardStreamValue {
  return useContext(DashboardStreamContext);
}
