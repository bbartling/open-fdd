import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { SiteProvider } from "@/contexts/site-context";
import { ThemeProvider } from "@/contexts/theme-context";
import { AppLayout } from "@/components/layout/AppLayout";
import { OverviewPage } from "@/components/pages/OverviewPage";
import { ConfigPage } from "@/components/pages/ConfigPage";
import { PointsPage } from "@/components/pages/PointsPage";
import { FaultsPage } from "@/components/pages/FaultsPage";
import { SystemResourcesPage } from "@/components/pages/SystemResourcesPage";
import { DataModelPage } from "@/components/pages/DataModelPage";
import { PlotsPage } from "@/components/pages/PlotsPage";
import { WebWeatherPage } from "@/components/pages/WebWeatherPage";
import { useWebSocket } from "@/hooks/use-websocket";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
});

function AppRoutes() {
  useWebSocket();

  return (
    <SiteProvider>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<OverviewPage />} />
          <Route path="config" element={<ConfigPage />} />
          <Route path="equipment" element={<Navigate to="/config" replace />} />
          <Route path="points" element={<PointsPage />} />
          <Route path="faults" element={<FaultsPage />} />
          <Route path="system" element={<SystemResourcesPage />} />
          <Route path="plots" element={<PlotsPage />} />
          <Route path="web-weather" element={<WebWeatherPage />} />
          <Route path="data-model" element={<DataModelPage />} />
        </Route>
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
