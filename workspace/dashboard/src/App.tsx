import { Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./components/AppLayout";
import RequireAuth from "./components/RequireAuth";
import { DashboardStreamProvider } from "./lib/dashboardStream";
import AgentPage from "./pages/AgentPage";
import DriversPage from "./pages/DriversPage";
import JsonApiPage from "./pages/JsonApiPage";
import BacnetPage from "./pages/BacnetPage";
import HaystackPage from "./pages/HaystackPage";
import ModbusPage from "./pages/ModbusPage";
import DataModelPage from "./pages/DataModelPage";
import HomePage from "./pages/HomePage";
import HostStatsPage from "./pages/HostStatsPage";
import LoginPage from "./pages/LoginPage";
import PlotPage from "./pages/PlotPage";
import SqlFddRulesPage from "./pages/SqlFddRulesPage";
import LiveFddValidationPage from "./pages/LiveFddValidationPage";
import DataManagementPage from "./pages/DataManagementPage";
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
          <Route path="faults" element={<Navigate to="/" replace />} />
          <Route element={<RequireAuth />}>
            <Route path="live-fdd-validation" element={<TabErrorBoundary tab="live-fdd-validation"><LiveFddValidationPage /></TabErrorBoundary>} />
            <Route path="bench-5007" element={<Navigate to="/live-fdd-validation" replace />} />
            <Route path="sql-fdd" element={<TabErrorBoundary tab="sql-fdd"><SqlFddRulesPage /></TabErrorBoundary>} />
            <Route path="rule-lab" element={<Navigate to="/sql-fdd" replace />} />
            <Route path="model" element={<TabErrorBoundary tab="model"><DataModelPage /></TabErrorBoundary>} />
            <Route path="algorithms" element={<TabErrorBoundary tab="algorithms"><AlgorithmsPage /></TabErrorBoundary>} />
            <Route path="data-model" element={<Navigate to="/model" replace />} />
            <Route path="fdd-assignments" element={<Navigate to="/model" replace />} />
            <Route path="plot" element={<TabErrorBoundary tab="plot"><PlotPage /></TabErrorBoundary>} />
            <Route path="drivers" element={<TabErrorBoundary tab="drivers"><DriversPage /></TabErrorBoundary>} />
            <Route path="haystack" element={<TabErrorBoundary tab="haystack"><HaystackPage /></TabErrorBoundary>} />
            <Route path="bacnet" element={<TabErrorBoundary tab="bacnet"><BacnetPage /></TabErrorBoundary>} />
            <Route path="modbus" element={<TabErrorBoundary tab="modbus"><ModbusPage /></TabErrorBoundary>} />
            <Route path="json-api" element={<TabErrorBoundary tab="json-api"><JsonApiPage /></TabErrorBoundary>} />
            <Route path="data-management" element={<TabErrorBoundary tab="data-management"><DataManagementPage /></TabErrorBoundary>} />
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
