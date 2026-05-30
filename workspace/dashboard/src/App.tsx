import { Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./components/AppLayout";
import RequireAuth from "./components/RequireAuth";
import { DashboardStreamProvider } from "./lib/dashboardStream";
import AgentPage from "./pages/AgentPage";
import BacnetPage from "./pages/BacnetPage";
import DataModelPage from "./pages/DataModelPage";
import FaultsPage from "./pages/FaultsPage";
import HomePage from "./pages/HomePage";
import HostStatsPage from "./pages/HostStatsPage";
import LoginPage from "./pages/LoginPage";
import RuleLabPage from "./pages/RuleLabPage";

export default function App() {
  return (
    <DashboardStreamProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        {/* Public check-engine views — no sign-in required */}
        <Route element={<AppLayout />}>
          <Route index element={<HomePage />} />
          <Route path="faults" element={<FaultsPage />} />
          <Route element={<RequireAuth />}>
            <Route path="data-model" element={<DataModelPage />} />
            <Route path="rule-lab" element={<RuleLabPage />} />
            <Route path="bacnet" element={<BacnetPage />} />
            <Route path="agent" element={<AgentPage />} />
            <Route path="host" element={<HostStatsPage />} />
            <Route path="fdd" element={<Navigate to="/rule-lab" replace />} />
          </Route>
        </Route>
      </Routes>
    </DashboardStreamProvider>
  );
}
