import { NavLink } from "react-router-dom";
import { useTheme } from "../../contexts/theme-context";

type NavItem = { to: string; icon: string; label: string; end?: boolean };

const navItems: NavItem[] = [
  { to: "/site-management", icon: "🏢", label: "Site Management" },
  { to: "/csv-import", icon: "📤", label: "CSV Import" },
  { to: "/weather", icon: "🌤️", label: "Open-Meteo Driver" },
  { to: "/bacnet-tools", icon: "📡", label: "BACnet Driver" },
  { to: "/onboard-driver", icon: "🛰️", label: "Onboard Driver" },
  { to: "/rule-setup", icon: "🧩", label: "FDD Rule Setup" },
  { to: "/data-model", icon: "🧱", label: "Data Model BRICK" },
  { to: "/data-model-testing", icon: "🔎", label: "Data Model Testing" },
  { to: "/plots", icon: "📈", label: "Plots" },
  { to: "/data-maintenance", icon: "🧹", label: "Data & model maintenance" },
  { to: "/ml-lab", icon: "🤖", label: "ML Lab" },
  { to: "/energy-engineering", icon: "⚡", label: "Energy and Analytics" },
  { to: "/ai-agent", icon: "💬", label: "AI Agent" },
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
      </div>
    </aside>
  );
}
