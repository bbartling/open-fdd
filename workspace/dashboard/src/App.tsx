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
import PlotPage from "./pages/PlotPage";
import RuleLabPage from "./pages/RuleLabPage";
import { TabErrorBoundary } from "./components/TabDebugPanel";

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
            <Route path="data-model" element={<TabErrorBoundary tab="data-model"><DataModelPage /></TabErrorBoundary>} />
            <Route path="rule-lab" element={<TabErrorBoundary tab="rule-lab"><RuleLabPage /></TabErrorBoundary>} />
            <Route path="plot" element={<TabErrorBoundary tab="plot"><PlotPage /></TabErrorBoundary>} />
            <Route path="bacnet" element={<TabErrorBoundary tab="bacnet"><BacnetPage /></TabErrorBoundary>} />
            <Route path="agent" element={<TabErrorBoundary tab="agent"><AgentPage /></TabErrorBoundary>} />
            <Route path="host" element={<TabErrorBoundary tab="host"><HostStatsPage /></TabErrorBoundary>} />
            <Route path="fdd" element={<Navigate to="/rule-lab" replace />} />
          </Route>
        </Route>
      </Routes>
    </DashboardStreamProvider>
  );
}
