import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route } from "react-router-dom";
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
