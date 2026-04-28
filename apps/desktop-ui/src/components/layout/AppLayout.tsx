import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

export function AppLayout() {
  return (
    <div className="app-shell">
      <Sidebar />
      <div className="app-main">
        <TopBar />
        <div className="status-strip">Desktop bridge mode active: optimized for local large-file ingestion workflows.</div>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
