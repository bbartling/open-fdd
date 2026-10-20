import { lazy, Suspense, type ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";
import { AuthGate } from "./components/AuthGate";
import { RouteErrorBoundary } from "./components/RouteErrorBoundary";
import { HomePage } from "./pages/HomePage";
import { JobsPage } from "./pages/JobsPage";
import { UploadPage } from "./pages/UploadPage";
import { MappingPage } from "./pages/MappingPage";
import { ActionsPage } from "./pages/ActionsPage";
import { FindingsPage } from "./pages/FindingsPage";
import { ExportPage } from "./pages/WattLabPage";
import { AuthPage } from "./pages/AuthPage";
import { SitesPage } from "./pages/SitesPage";
import { OperationsPage } from "./pages/OperationsPage";
import { AdminPage } from "./pages/AdminPage";
import { REPORTS_API_ROOT, REPORTS_ROUTE } from "./api/reportsApi";

/** Bundle anchors for nightly gate 11 (#549). */
void REPORTS_ROUTE;
void REPORTS_API_ROOT;

const ReportsPage = lazy(() =>
  import("./pages/ReportsPage").then((m) => ({ default: m.ReportsPage })),
);
const RcxPage = lazy(() =>
  import("./pages/RcxPage").then((m) => ({ default: m.RcxPage })),
);
const InspectPage = lazy(() =>
  import("./pages/InspectPage").then((m) => ({ default: m.InspectPage })),
);
const MeteringPage = lazy(() =>
  import("./pages/MeteringPage").then((m) => ({ default: m.MeteringPage })),
);

function PageFallback() {
  return (
    <div role="status" className="muted" data-testid="route-loading">
      Loading
    </div>
  );
}

function gated(element: ReactNode) {
  return (
    <AuthGate>
      <RouteErrorBoundary>
        <Suspense fallback={<PageFallback />}>{element}</Suspense>
      </RouteErrorBoundary>
    </AuthGate>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/auth" element={<AuthPage />} />
        <Route path="/login" element={<Navigate to="/auth" replace />} />
        <Route path="/" element={gated(<HomePage />)} />
        <Route path="/inspect" element={gated(<InspectPage />)} />
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
        <Route path="/export" element={gated(<ExportPage />)} />
        <Route path="/wattlab" element={<Navigate to="/export" replace />} />
        <Route path="/twin" element={<Navigate to="/export" replace />} />
        <Route path="/operations" element={gated(<OperationsPage />)} />
        <Route path="/admin" element={gated(<AdminPage />)} />
      </Routes>
    </BrowserRouter>
  );
}
