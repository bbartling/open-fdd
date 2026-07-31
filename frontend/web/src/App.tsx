import { BrowserRouter, Route, Routes } from "react-router";
import { HomePage } from "./pages/HomePage";
import { JobsPage } from "./pages/JobsPage";
import { UploadPage } from "./pages/UploadPage";
import { MappingPage } from "./pages/MappingPage";
import { RulesPage } from "./pages/RulesPage";
import { FindingsPage } from "./pages/FindingsPage";
import { ReportsPage } from "./pages/ReportsPage";
import { MeteringPage } from "./pages/MeteringPage";
import { WattLabPage } from "./pages/WattLabPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/jobs" element={<JobsPage />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/mapping" element={<MappingPage />} />
        <Route path="/rules" element={<RulesPage />} />
        <Route path="/findings" element={<FindingsPage />} />
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/metering" element={<MeteringPage />} />
        <Route path="/wattlab" element={<WattLabPage />} />
      </Routes>
    </BrowserRouter>
  );
}
