import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { apiFetch, fetchAuthStatus, fetchWsTicket, getBridgeBase, hasToken } from "./api";
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

export type SensorInsight = {
  column?: string;
  label?: string;
  brick_type?: string;
  fdd_input?: string;
  equipment_name?: string;
  avg_overall?: number;
  min_overall?: number;
  max_overall?: number;
  avg_while_fault?: number;
  avg_while_ok?: number;
  avg_while_motor_run?: number;
  avg_while_motor_run_fault?: number;
  fault_sample_pct?: number;
  sample_count?: number;
};

export type FaultInsight = {
  sensor_column?: string;
  lookback_hours?: number;
  sensor_count?: number;
  sensors?: SensorInsight[];
  bounds_low?: number;
  bounds_high?: number;
  avg_while_fault?: number;
  avg_while_ok?: number;
  avg_overall?: number;
  avg_while_motor_run?: number;
  avg_while_motor_run_fault?: number;
  min_overall?: number;
  max_overall?: number;
  fault_sample_pct?: number;
  motor_runtime_hours?: number;
  motor_label?: string;
  motor_equipment?: string;
  rule_bounds_low?: number | string;
  rule_bounds_high?: number | string;
  rule_window_samples?: number | string;
  rule_flatline_tolerance?: number | string;
  value_unit?: string;
  historian_source?: string;
};

export type FaultModelContext = {
  severity?: string;
  rule_id?: string;
  rule_name?: string;
  short_description?: string;
  symptom?: string;
  short_description?: string;
  data_source?: string;
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
  insight?: FaultInsight;
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
  symptom?: string;
  data_source?: string;
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
  const path = authenticated ? "/api/building/snapshot" : "/api/building/public-snapshot";
  const base = getBridgeBase();
  const url = `${base}${path}`;
  const token = authenticated ? sessionStorage.getItem("ofdd_token") : null;
  const res = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  const snap = (await res.json()) as DashboardSnapshot & { ok?: boolean };
  const { ok: _ok, ...body } = snap;
  return body as DashboardSnapshot;
}

export function DashboardStreamProvider({ children, pollMs = 15000 }: { children: ReactNode; pollMs?: number }) {
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null);
  const [error, setError] = useState("");
  const [live, setLive] = useState(false);
  const [authenticated, setAuthenticated] = useState(hasToken());
  const [authRequired, setAuthRequired] = useState<boolean | null>(null);

  useEffect(() => {
    fetchAuthStatus()
      .then((s) => setAuthRequired(s.auth_required))
      .catch(() => setAuthRequired(true));
  }, []);

  useEffect(() => {
    const sync = () => setAuthenticated(hasToken());
    sync();
    window.addEventListener("ofdd-auth", sync);
    return () => window.removeEventListener("ofdd-auth", sync);
  }, []);

  useEffect(() => {
    if (authRequired === null) return;

    let cancelled = false;
    let ws: WebSocket | null = null;
    let pollId = 0;
    let gotData = false;
    let wsAttempt = 0;

    const detachWs = (socket: WebSocket) => {
      socket.onopen = null;
      socket.onmessage = null;
      socket.onerror = null;
      socket.onclose = null;
    };

    const teardownWs = (socket: WebSocket | null) => {
      if (!socket) return;
      detachWs(socket);
      if (socket.readyState === WebSocket.OPEN) {
        socket.close(1000, "teardown");
      } else if (socket.readyState === WebSocket.CONNECTING) {
        // Defer close until open — avoids StrictMode "closed before connection established" noise.
        socket.onopen = () => socket.close(1000, "teardown");
      }
    };

    const apply = (data: DashboardSnapshot) => {
      if (!cancelled) {
        gotData = true;
        setSnapshot(data);
        setError("");
      }
    };

    const poll = () => {
      if (authRequired && !authenticated) {
        if (!cancelled) setError("Sign in to load building status.");
        return;
      }
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
      const attempt = ++wsAttempt;
      try {
        const ticket = authenticated ? await fetchWsTicket() : null;
        if (cancelled || attempt !== wsAttempt) return;
        if (authenticated && authRequired && !ticket) {
          startPolling();
          return;
        }
        const url = new URL(wsBaseUrl());
        const socket = ticket
          ? new WebSocket(url.toString(), ["ofdd.ws", ticket])
          : new WebSocket(url.toString());
        ws = socket;
        socket.onopen = () => {
          if (cancelled || attempt !== wsAttempt) {
            teardownWs(socket);
            return;
          }
          setLive(true);
        };
        socket.onmessage = (ev) => {
          try {
            apply(JSON.parse(ev.data) as DashboardSnapshot);
          } catch {
            /* ignore malformed frame */
          }
        };
        socket.onerror = () => {
          if (attempt === wsAttempt) socket.close();
        };
        socket.onclose = () => {
          if (cancelled || attempt !== wsAttempt) return;
          setLive(false);
          startPolling();
        };
      } catch {
        if (!cancelled && attempt === wsAttempt) startPolling();
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
      wsAttempt += 1;
      teardownWs(ws);
      ws = null;
      window.clearInterval(pollId);
      if (fallbackTimer) window.clearTimeout(fallbackTimer);
    };
  }, [pollMs, authenticated, authRequired]);

  const value = useMemo(() => ({ snapshot, error, live }), [snapshot, error, live]);
  return <DashboardStreamContext.Provider value={value}>{children}</DashboardStreamContext.Provider>;
}

export function useDashboardStream(): DashboardStreamValue {
  return useContext(DashboardStreamContext);
}
