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
import { MlLabPage } from "./pages/MlLabPage";
import { OpenClawChatPage } from "./pages/OpenClawChatPage";
import { WeatherDriverPage } from "./pages/WeatherDriverPage";
import { BacnetDriverPage } from "./pages/BacnetDriverPage";
import { OnboardDriverPage } from "./pages/OnboardDriverPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<Navigate to="/site-management" replace />} />
        <Route path="/site-management" element={<SiteManagementPage />} />
        <Route path="/csv-import" element={<CsvImportPage />} />
        <Route path="/weather" element={<WeatherDriverPage />} />
        <Route path="/bacnet-tools" element={<BacnetDriverPage />} />
        <Route path="/onboard-driver" element={<OnboardDriverPage />} />
        <Route path="/rule-setup" element={<RuleSetupPage />} />
        <Route path="/drivers" element={<Navigate to="/weather" replace />} />
        <Route path="/data-model" element={<DataModelPage />} />
        <Route path="/energy-engineering" element={<PlaceholderPage title="Energy Engineering" description="Engineering workflow page scaffold." />} />
        <Route path="/data-model-testing" element={<DataModelTestingPage />} />
        <Route path="/plots" element={<PlotsPage />} />
        <Route path="/ml-lab" element={<MlLabPage />} />
        <Route path="/openfdd-claw-chat" element={<OpenClawChatPage />} />
        <Route path="/openclaw-chat" element={<Navigate to="/openfdd-claw-chat" replace />} />
        <Route path="/analytics" element={<Navigate to="/ml-lab" replace />} />
        <Route path="/system" element={<SystemResourcesPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/site-management" replace />} />
    </Routes>
  );
}
