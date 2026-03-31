import { useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { SiteProvider } from "@/contexts/site-context";
import { ThemeProvider } from "@/contexts/theme-context";
import { AppLayout } from "@/components/layout/AppLayout";
import { OverviewPage } from "@/components/pages/OverviewPage";
import { ConfigPage } from "@/components/pages/ConfigPage";
import { PointsPage } from "@/components/pages/PointsPage";
import { FaultsPage } from "@/components/pages/FaultsPage";
import { SystemResourcesPage } from "@/components/pages/SystemResourcesPage";
import { DataModelPage } from "@/components/pages/DataModelPage";
import { DataModelEngineeringPage } from "@/components/pages/DataModelEngineeringPage";
import { DataModelTestingPage } from "@/components/pages/DataModelTestingPage";
import { PlotsPage } from "@/components/pages/PlotsPage";
import { DiagnosticsPage } from "@/components/pages/DiagnosticsPage";
import { WeatherDataPage } from "@/components/pages/WeatherDataPage";
import { useWebSocket } from "@/hooks/use-websocket";
import {
  clearAuthTokens,
  getAccessToken,
  setAuthTokens,
  subscribeAuth,
} from "@/lib/auth";
import { apiFetch } from "@/lib/api";

function LoginPage() {
  const [username, setUsername] = useState("openfdd");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body = await apiFetch<{
        access_token: string;
      }>("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      setAuthTokens(body.access_token);
      window.location.assign("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto mt-20 w-full max-w-sm rounded-lg border border-border bg-card p-6">
      <h1 className="mb-4 text-xl font-semibold">Open-FDD Login</h1>
      <form onSubmit={submit} className="space-y-3">
        <input
          className="h-9 w-full rounded border border-border/60 bg-background px-3 text-sm"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="Username"
        />
        <input
          className="h-9 w-full rounded border border-border/60 bg-background px-3 text-sm"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          type="password"
          placeholder="Password"
        />
        <button
          type="submit"
          className="w-full rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          disabled={busy}
        >
          {busy ? "Signing in..." : "Sign in"}
        </button>
      </form>
      {error ? <p className="mt-3 text-xs text-destructive">{error}</p> : null}
    </div>
  );
}

function RequireAuth({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => getAccessToken());
  useEffect(() => subscribeAuth(() => setToken(getAccessToken())), []);
  if (!token) return <Navigate to="/login" replace />;
  return children;
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
});

function AppRoutes() {
  useWebSocket();

  return (
    <SiteProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/logout" element={<LogoutPage />} />
        <Route
          element={
            <RequireAuth>
              <AppLayout />
            </RequireAuth>
          }
        >
          <Route index element={<OverviewPage />} />
          <Route path="config" element={<ConfigPage />} />
          <Route path="equipment" element={<Navigate to="/config" replace />} />
          <Route path="points" element={<PointsPage />} />
          <Route path="faults" element={<FaultsPage />} />
          <Route path="plots" element={<PlotsPage />} />
          <Route path="weather" element={<WeatherDataPage />} />
          <Route path="diagnostics" element={<DiagnosticsPage />} />
          <Route path="system" element={<SystemResourcesPage />} />
          <Route path="data-model" element={<DataModelPage />} />
          <Route path="data-model-engineering" element={<DataModelEngineeringPage />} />
          <Route path="data-model-testing" element={<DataModelTestingPage />} />
        </Route>
        <Route
          path="*"
          element={<Navigate to={(getAccessToken() ? "/" : "/login")} replace />}
        />
      </Routes>
    </SiteProvider>
  );
}

function LogoutPage() {
  useEffect(() => {
    apiFetch<{ ok: boolean }>("/auth/logout", { method: "POST" }).finally(() => {
      clearAuthTokens();
      window.location.assign("/login");
    });
  }, []);
  return null;
}

function App() {
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

export default App;
