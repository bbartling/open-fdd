import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./components/AppLayout";
import { fetchAuthStatus, hasToken, setToken } from "./lib/api";
import AgentPage from "./pages/AgentPage";
import BacnetPage from "./pages/BacnetPage";
import DataModelPage from "./pages/DataModelPage";
import FaultsPage from "./pages/FaultsPage";
import HomePage from "./pages/HomePage";
import HostStatsPage from "./pages/HostStatsPage";
import LoginPage from "./pages/LoginPage";
import RuleLabPage from "./pages/RuleLabPage";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const [authRequired, setAuthRequired] = useState<boolean | null>(null);

  useEffect(() => {
    fetchAuthStatus()
      .then((s) => {
        setAuthRequired(s.auth_required);
        if (!s.auth_required) setToken("open");
      })
      .catch(() => setAuthRequired(true));
  }, []);

  if (authRequired === null) return <p className="muted">Loading…</p>;
  if (authRequired && !hasToken()) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route index element={<HomePage />} />
        <Route path="faults" element={<FaultsPage />} />
        <Route path="data-model" element={<DataModelPage />} />
        <Route path="rule-lab" element={<RuleLabPage />} />
        <Route path="bacnet" element={<BacnetPage />} />
        <Route path="agent" element={<AgentPage />} />
        <Route path="host" element={<HostStatsPage />} />
        <Route path="fdd" element={<Navigate to="/rule-lab" replace />} />
      </Route>
    </Routes>
  );
}
