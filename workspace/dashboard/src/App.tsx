import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./components/AppLayout";
import { fetchAuthStatus, hasToken, setToken } from "./lib/api";
import AgentPage from "./pages/AgentPage";
import BacnetPage from "./pages/BacnetPage";
import FddPage from "./pages/FddPage";
import HomePage from "./pages/HomePage";
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
      .catch(() => setAuthRequired(false));
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
        <Route path="rule-lab" element={<RuleLabPage />} />
        <Route path="fdd" element={<FddPage />} />
        <Route path="bacnet" element={<BacnetPage />} />
        <Route path="agent" element={<AgentPage />} />
      </Route>
    </Routes>
  );
}
