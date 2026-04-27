import { NavLink, Route, Routes } from "react-router-dom";
import { CsvImportPage } from "./pages/CsvImportPage";
import { DataModelPage } from "./pages/DataModelPage";
import { FaultsPage } from "./pages/FaultsPage";
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { ConfigPage } from "./pages/ConfigPage";
import { DataModelTestingPage } from "./pages/DataModelTestingPage";
import { useEffect, useState } from "react";
import { RuleSetupPage } from "./pages/RuleSetupPage";
import { SystemResourcesPage } from "./pages/SystemResourcesPage";

const navItems = [
  { to: "/", label: "Overview" },
  { to: "/config", label: "OpenFDD Config" },
  { to: "/csv-import", label: "CSV Import" },
  { to: "/rule-setup", label: "FDD Rule Setup" },
  { to: "/bacnet-tools", label: "BACnet tools" },
  { to: "/data-model", label: "Data Model BRICK" },
  { to: "/energy-engineering", label: "Energy Engineering" },
  { to: "/data-model-testing", label: "Data Model Testing" },
  { to: "/points", label: "Points" },
  { to: "/faults", label: "Faults" },
  { to: "/plots", label: "Plots" },
  { to: "/weather", label: "Weather data" },
  { to: "/analytics", label: "Analytics" },
  { to: "/system", label: "System resources" },
];

function Layout() {
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    const saved = window.localStorage.getItem("openfdd-desktop-theme");
    if (saved === "dark" || saved === "light") return saved;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    window.localStorage.setItem("openfdd-desktop-theme", theme);
  }, [theme]);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">Open-FDD Desktop</div>
        <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
          <button onClick={() => setTheme("dark")} style={{ flex: 1, opacity: theme === "dark" ? 1 : 0.7 }}>
            Dark
          </button>
          <button onClick={() => setTheme("light")} style={{ flex: 1, opacity: theme === "light" ? 1 : 0.7 }}>
            Light
          </button>
        </div>
        {navItems.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.to === "/"} className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}>
            {item.label}
          </NavLink>
        ))}
      </aside>
      <main className="content">
        <Routes>
          <Route path="/" element={<PlaceholderPage title="Overview" description="Frontend parity shell running in desktop mode." />} />
          <Route path="/config" element={<ConfigPage />} />
          <Route path="/csv-import" element={<CsvImportPage />} />
          <Route path="/rule-setup" element={<RuleSetupPage />} />
          <Route path="/bacnet-tools" element={<PlaceholderPage title="BACnet tools" description="BACnet feature parity page scaffold." />} />
          <Route path="/data-model" element={<DataModelPage />} />
          <Route path="/energy-engineering" element={<PlaceholderPage title="Energy Engineering" description="Engineering workflow page scaffold." />} />
          <Route path="/data-model-testing" element={<DataModelTestingPage />} />
          <Route path="/points" element={<PlaceholderPage title="Points" description="Points inventory page scaffold." />} />
          <Route path="/faults" element={<FaultsPage />} />
          <Route path="/plots" element={<PlaceholderPage title="Plots" description="Timeseries plotting page scaffold." />} />
          <Route path="/weather" element={<PlaceholderPage title="Weather data" description="Weather diagnostics page scaffold." />} />
          <Route path="/analytics" element={<PlaceholderPage title="Analytics" description="Analytics page scaffold." />} />
          <Route path="/system" element={<SystemResourcesPage />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return <Layout />;
}
