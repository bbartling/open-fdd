import { Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./components/AppLayout";
import RequireAuth from "./components/RequireAuth";
import { DashboardStreamProvider } from "./lib/dashboardStream";
import AgentPage from "./pages/AgentPage";
import BacnetPage from "./pages/BacnetPage";
import JsonApiPage from "./pages/JsonApiPage";
import ModbusPage from "./pages/ModbusPage";
import NiagaraPage from "./pages/NiagaraPage";
import DataModelPage from "./pages/DataModelPage";
import HomePage from "./pages/HomePage";
import HostStatsPage from "./pages/HostStatsPage";
import LoginPage from "./pages/LoginPage";
import PlotPage from "./pages/PlotPage";
import RcxReportBuilderPage from "./pages/RcxReportBuilderPage";
import RuleLabPage from "./pages/RuleLabPage";
import { TabErrorBoundary } from "./components/TabDebugPanel";

export default function App() {
  return (
    <DashboardStreamProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<AppLayout />}>
          <Route path="analytics" element={<Navigate to="/#overview" replace />} />
          <Route path="analytics/faults" element={<Navigate to="/#fault-analytics" replace />} />
          <Route path="analytics/equipment" element={<Navigate to="/#equipment" replace />} />
          <Route path="analytics/health" element={<Navigate to="/#model-health" replace />} />
          <Route path="analytics/rcx" element={<RcxReportBuilderPage />} />
          <Route path="faults" element={<Navigate to="/#fault-analytics" replace />} />
          <Route element={<RequireAuth />}>
            <Route index element={<HomePage />} />
            <Route path="rule-lab" element={<TabErrorBoundary tab="rule-lab"><RuleLabPage /></TabErrorBoundary>} />
            <Route path="model" element={<TabErrorBoundary tab="model"><DataModelPage /></TabErrorBoundary>} />
            <Route path="algorithms" element={<Navigate to="/" replace />} />
            <Route path="data-model" element={<Navigate to="/model" replace />} />
            <Route path="fdd-assignments" element={<Navigate to="/model" replace />} />
            <Route path="plot" element={<TabErrorBoundary tab="plot"><PlotPage /></TabErrorBoundary>} />
            <Route path="bacnet" element={<TabErrorBoundary tab="bacnet"><BacnetPage /></TabErrorBoundary>} />
            <Route path="modbus" element={<TabErrorBoundary tab="modbus"><ModbusPage /></TabErrorBoundary>} />
            <Route path="niagara" element={<TabErrorBoundary tab="niagara"><NiagaraPage /></TabErrorBoundary>} />
            <Route path="json-api" element={<TabErrorBoundary tab="json-api"><JsonApiPage /></TabErrorBoundary>} />
            <Route path="agent" element={<TabErrorBoundary tab="agent"><AgentPage /></TabErrorBoundary>} />
            <Route path="host" element={<TabErrorBoundary tab="host"><HostStatsPage /></TabErrorBoundary>} />
            <Route path="fdd" element={<Navigate to="/model" replace />} />
          </Route>
        </Route>
      </Routes>
    </DashboardStreamProvider>
  );
}
