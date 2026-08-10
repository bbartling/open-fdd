import { BrowserRouter, Navigate, Route, Routes } from "react-router";
import { AuthGate } from "./components/AuthGate";
import { HomePage } from "./pages/HomePage";
import { JobsPage } from "./pages/JobsPage";
import { UploadPage } from "./pages/UploadPage";
import { MappingPage } from "./pages/MappingPage";
import { ActionsPage } from "./pages/ActionsPage";
import { FindingsPage } from "./pages/FindingsPage";
import { ReportsPage } from "./pages/ReportsPage";
import { MeteringPage } from "./pages/MeteringPage";
import { RcxPage } from "./pages/RcxPage";
import { WattLabPage } from "./pages/WattLabPage";
import { AuthPage } from "./pages/AuthPage";
import { TwinPage } from "./pages/TwinPage";
import { SitesPage } from "./pages/SitesPage";

function gated(element: React.ReactNode) {
  return <AuthGate>{element}</AuthGate>;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/auth" element={<AuthPage />} />
        <Route path="/login" element={<Navigate to="/auth" replace />} />
        <Route path="/" element={gated(<HomePage />)} />
        <Route path="/sites" element={gated(<SitesPage />)} />
        <Route path="/jobs" element={gated(<JobsPage />)} />
        <Route path="/upload" element={gated(<UploadPage />)} />
        <Route path="/mapping" element={gated(<MappingPage />)} />
        <Route path="/rules" element={<Navigate to="/" replace />} />
        <Route path="/actions" element={gated(<ActionsPage />)} />
        <Route path="/findings" element={gated(<FindingsPage />)} />
        <Route path="/reports" element={gated(<ReportsPage />)} />
        <Route path="/rcx" element={gated(<RcxPage />)} />
        <Route path="/metering" element={gated(<MeteringPage />)} />
        <Route path="/wattlab" element={gated(<WattLabPage />)} />
        <Route path="/twin" element={gated(<TwinPage />)} />
      </Routes>
    </BrowserRouter>
  );
}
