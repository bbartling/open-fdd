import { Outlet, useLocation } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { StackStatusStrip } from "@/components/dashboard/StackStatusStrip";

export function AppLayout() {
  const { pathname } = useLocation();
  const isPlots = pathname === "/plots";

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <TopBar />
        <StackStatusStrip />
        <main className="flex-1 overflow-y-auto">
          <div
            className={
              isPlots
                ? "w-full px-6 py-8"
                : "mx-auto max-w-7xl px-6 py-8"
            }
          >
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
