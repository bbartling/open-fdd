import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate, useParams } from "react-router-dom";
import { SiteProvider } from "@/contexts/site-context";
import { ThemeProvider } from "@/contexts/theme-context";
import { AppLayout } from "@/components/layout/AppLayout";
import { OverviewPage } from "@/components/pages/OverviewPage";
import { EquipmentPage } from "@/components/pages/EquipmentPage";
import { PointsPage } from "@/components/pages/PointsPage";
import { FaultsPage } from "@/components/pages/FaultsPage";
import { TrendingPage } from "@/components/pages/TrendingPage";
import { useWebSocket } from "@/hooks/use-websocket";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
});

/** Redirect legacy /sites/:siteId URLs to /?site=<id> */
function LegacySiteRedirect() {
  const { siteId } = useParams<{ siteId: string }>();
  return <Navigate to={`/?site=${siteId}`} replace />;
}

function AppRoutes() {
  useWebSocket();

  return (
    <SiteProvider>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<OverviewPage />} />
          <Route path="equipment" element={<EquipmentPage />} />
          <Route path="points" element={<PointsPage />} />
          <Route path="faults" element={<FaultsPage />} />
          <Route path="trending" element={<TrendingPage />} />
        </Route>
        <Route path="sites/:siteId" element={<LegacySiteRedirect />} />
      </Routes>
    </SiteProvider>
  );
}

function App() {
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

export default App;
