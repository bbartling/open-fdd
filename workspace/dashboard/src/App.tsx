import { Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./components/AppLayout";
import RequireAuth from "./components/RequireAuth";
import { DashboardStreamProvider } from "./lib/dashboardStream";
import AgentPage from "./pages/AgentPage";
import DriversPage from "./pages/DriversPage";
import JsonApiPage from "./pages/JsonApiPage";
import ModbusPage from "./pages/ModbusPage";
import DataModelPage from "./pages/DataModelPage";
import FaultsPage from "./pages/FaultsPage";
import HomePage from "./pages/HomePage";
import HostStatsPage from "./pages/HostStatsPage";
import LoginPage from "./pages/LoginPage";
import PlotPage from "./pages/PlotPage";
import RuleLabPage from "./pages/RuleLabPage";
import SqlFddRulesPage from "./pages/SqlFddRulesPage";
import Bench5007SmokePage from "./pages/Bench5007SmokePage";
import DataExportPage from "./pages/DataExportPage";
import AlgorithmsPage from "./pages/AlgorithmsPage";
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
            <Route path="bench-5007" element={<TabErrorBoundary tab="bench-5007"><Bench5007SmokePage /></TabErrorBoundary>} />
            <Route path="sql-fdd" element={<TabErrorBoundary tab="sql-fdd"><SqlFddRulesPage /></TabErrorBoundary>} />
            <Route path="rule-lab" element={<TabErrorBoundary tab="rule-lab"><RuleLabPage /></TabErrorBoundary>} />
            <Route path="model" element={<TabErrorBoundary tab="model"><DataModelPage /></TabErrorBoundary>} />
            <Route path="algorithms" element={<TabErrorBoundary tab="algorithms"><AlgorithmsPage /></TabErrorBoundary>} />
            <Route path="data-model" element={<Navigate to="/model" replace />} />
            <Route path="fdd-assignments" element={<Navigate to="/model" replace />} />
            <Route path="plot" element={<TabErrorBoundary tab="plot"><PlotPage /></TabErrorBoundary>} />
            <Route path="exports" element={<TabErrorBoundary tab="exports"><DataExportPage /></TabErrorBoundary>} />
            <Route path="downloads" element={<Navigate to="/exports" replace />} />
            <Route path="drivers" element={<TabErrorBoundary tab="drivers"><DriversPage /></TabErrorBoundary>} />
            <Route path="bacnet" element={<TabErrorBoundary tab="drivers"><DriversPage /></TabErrorBoundary>} />
            <Route path="modbus" element={<TabErrorBoundary tab="modbus"><ModbusPage /></TabErrorBoundary>} />
            <Route path="json-api" element={<TabErrorBoundary tab="json-api"><JsonApiPage /></TabErrorBoundary>} />
            <Route path="agent" element={<TabErrorBoundary tab="agent"><AgentPage /></TabErrorBoundary>} />
            <Route path="host" element={<TabErrorBoundary tab="host"><HostStatsPage /></TabErrorBoundary>} />
            <Route path="fdd" element={<Navigate to="/sql-fdd" replace />} />
            <Route path="fdd-wires" element={<Navigate to="/sql-fdd" replace />} />
            <Route path="rules" element={<Navigate to="/sql-fdd" replace />} />
          </Route>
        </Route>
      </Routes>
    </DashboardStreamProvider>
  );
}
