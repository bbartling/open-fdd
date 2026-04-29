import { Navigate, Route, Routes } from "react-router-dom";
import { CsvImportPage } from "./pages/CsvImportPage";
import { DataModelPage } from "./pages/DataModelPage";
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { DataModelTestingPage } from "./pages/DataModelTestingPage";
import { RuleSetupPage } from "./pages/RuleSetupPage";
import { SystemResourcesPage } from "./pages/SystemResourcesPage";
import { SiteManagementPage } from "./pages/SiteManagementPage";
import { AppLayout } from "./components/layout/AppLayout";
import { PlotsPage } from "./pages/PlotsPage";
import { WeatherPage } from "./pages/WeatherPage";
import { DriversPage } from "./pages/DriversPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<PlaceholderPage title="Overview" description="Frontend parity shell running in desktop mode." />} />
        <Route path="/site-management" element={<SiteManagementPage />} />
        <Route path="/csv-import" element={<CsvImportPage />} />
        <Route path="/rule-setup" element={<RuleSetupPage />} />
        <Route path="/drivers" element={<DriversPage />} />
        <Route path="/bacnet-tools" element={<Navigate to="/drivers" replace />} />
        <Route path="/data-model" element={<DataModelPage />} />
        <Route path="/energy-engineering" element={<PlaceholderPage title="Energy Engineering" description="Engineering workflow page scaffold." />} />
        <Route path="/data-model-testing" element={<DataModelTestingPage />} />
        <Route path="/plots" element={<PlotsPage />} />
        <Route path="/weather" element={<WeatherPage />} />
        <Route path="/analytics" element={<PlaceholderPage title="Analytics" description="Analytics page scaffold." />} />
        <Route path="/system" element={<SystemResourcesPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/site-management" replace />} />
    </Routes>
  );
}
