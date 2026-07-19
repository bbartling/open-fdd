import { Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./components/AppLayout";
import RequireAuth from "./components/RequireAuth";
import { DashboardStreamProvider } from "./lib/dashboardStream";
import AgentPage from "./pages/AgentPage";
import JsonApiPage from "./pages/JsonApiPage";
import HaystackPage from "./pages/HaystackPage";
import BacnetPage from "./pages/BacnetPage";
import ModbusPage from "./pages/ModbusPage";
import DataModelPage from "./pages/DataModelPage";
import HomePage from "./pages/HomePage";
import HostStatsPage from "./pages/HostStatsPage";
import LoginPage from "./pages/LoginPage";
import PlotPage from "./pages/PlotPage";
import SqlFddRulesPage from "./pages/SqlFddRulesPage";
import Vibe19LabPage from "./pages/Vibe19LabPage";
import LiveFddValidationPage from "./pages/LiveFddValidationPage";
import CsvWorkbenchPage from "./pages/CsvWorkbenchPage";
import DataManagementPage from "./pages/DataManagementPage";
import ReportBuilderPage from "./pages/ReportBuilderPage";
import AlgorithmsPage from "./pages/AlgorithmsPage";
import DataExportPage from "./pages/DataExportPage";
import EdgeFleetPage from "./pages/EdgeFleet";
import { TabErrorBoundary } from "./components/TabDebugPanel";
import LabShell from "./components/LabShell";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<LabShell />}>
          <Route
            path="lab"
            element={
              <TabErrorBoundary tab="lab">
                <Vibe19LabPage />
              </TabErrorBoundary>
            }
          />
        </Route>
      </Route>
      <Route
        element={
          <DashboardStreamProvider>
            <AppLayout />
          </DashboardStreamProvider>
        }
      >
        {/* Public check-engine views — no sign-in required */}
        <Route index element={<HomePage />} />
        <Route path="faults" element={<Navigate to="/" replace />} />
        <Route element={<RequireAuth />}>
          <Route path="live-fdd-validation" element={<TabErrorBoundary tab="live-fdd-validation"><LiveFddValidationPage /></TabErrorBoundary>} />
            <Route path="bench-5007" element={<Navigate to="/live-fdd-validation" replace />} />
            <Route path="sql-fdd" element={<TabErrorBoundary tab="sql-fdd"><SqlFddRulesPage /></TabErrorBoundary>} />
            <Route path="rule-lab" element={<Navigate to="/lab" replace />} />
            <Route path="model" element={<TabErrorBoundary tab="model"><DataModelPage /></TabErrorBoundary>} />
            <Route path="algorithms" element={<TabErrorBoundary tab="algorithms"><AlgorithmsPage /></TabErrorBoundary>} />
            <Route path="data-model" element={<Navigate to="/model" replace />} />
            <Route path="fdd-assignments" element={<Navigate to="/model" replace />} />
            <Route path="plot" element={<TabErrorBoundary tab="plot"><PlotPage /></TabErrorBoundary>} />
            <Route path="drivers" element={<Navigate to="/bacnet" replace />} />
            <Route path="exports" element={<TabErrorBoundary tab="exports"><DataExportPage /></TabErrorBoundary>} />
            <Route path="edge-fleet" element={<TabErrorBoundary tab="edge-fleet"><EdgeFleetPage /></TabErrorBoundary>} />
            <Route path="haystack" element={<TabErrorBoundary tab="haystack"><HaystackPage /></TabErrorBoundary>} />
            <Route path="bacnet" element={<TabErrorBoundary tab="bacnet"><BacnetPage /></TabErrorBoundary>} />
            <Route path="modbus" element={<TabErrorBoundary tab="modbus"><ModbusPage /></TabErrorBoundary>} />
            <Route path="json-api" element={<TabErrorBoundary tab="json-api"><JsonApiPage /></TabErrorBoundary>} />
            <Route path="csv" element={<TabErrorBoundary tab="csv"><CsvWorkbenchPage /></TabErrorBoundary>} />
            <Route path="wiresheet" element={<Navigate to="/model" replace />} />
            <Route path="wiresheet/haystack" element={<Navigate to="/model" replace />} />
            <Route path="wiresheet/rules" element={<Navigate to="/model" replace />} />
            <Route path="data-management" element={<TabErrorBoundary tab="data-management"><DataManagementPage /></TabErrorBoundary>} />
            <Route path="reports" element={<TabErrorBoundary tab="reports"><ReportBuilderPage /></TabErrorBoundary>} />
            <Route path="agent" element={<TabErrorBoundary tab="agent"><AgentPage /></TabErrorBoundary>} />
            <Route path="host" element={<TabErrorBoundary tab="host"><HostStatsPage /></TabErrorBoundary>} />
            <Route path="fdd" element={<Navigate to="/lab" replace />} />
            <Route path="fdd-wires" element={<Navigate to="/model" replace />} />
            <Route path="rules" element={<Navigate to="/model" replace />} />
        </Route>
      </Route>
    </Routes>
  );
}
