import { NavLink } from "react-router-dom";
import { useTheme } from "../../contexts/theme-context";

const navItems = [
  { to: "/site-management", icon: "🏢", label: "Site Management" },
  { to: "/", icon: "📊", label: "Overview", end: true },
  { to: "/csv-import", icon: "📤", label: "CSV Import" },
  { to: "/rule-setup", icon: "🧩", label: "FDD Rule Setup" },
  { to: "/drivers", icon: "🧰", label: "Drivers" },
  { to: "/data-model", icon: "🧱", label: "Data Model BRICK" },
  { to: "/energy-engineering", icon: "⚡", label: "Energy Engineering" },
  { to: "/data-model-testing", icon: "🔎", label: "Data Model Testing" },
  { to: "/weather", icon: "🌤️", label: "Weather data" },
  { to: "/plots", icon: "📈", label: "Plots" },
  { to: "/analytics", icon: "📉", label: "Analytics" },
  { to: "/system", icon: "🖥️", label: "System resources" },
];

export function Sidebar() {
  const { theme, setTheme } = useTheme();

  return (
    <aside className="sidebar">
      <div className="brand-row">
        <span className="brand">Open-FDD</span>
        <span className="brand-chip">Desktop</span>
      </div>
      <nav className="sidebar-nav">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
          >
            <span className="nav-icon" aria-hidden="true">
              {item.icon}
            </span>
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>
      <div className="theme-switcher">
        <button
          className={`theme-btn ${theme === "light" ? "active" : ""}`}
          type="button"
          aria-pressed={theme === "light"}
          onClick={() => setTheme("light")}
        >
          Light
        </button>
        <button
          className={`theme-btn ${theme === "dark" ? "active" : ""}`}
          type="button"
          aria-pressed={theme === "dark"}
          onClick={() => setTheme("dark")}
        >
          Dark
        </button>
        <button
          className={`theme-btn ${theme === "system" ? "active" : ""}`}
          type="button"
          aria-pressed={theme === "system"}
          onClick={() => setTheme("system")}
        >
          System
        </button>
      </div>
    </aside>
  );
}
