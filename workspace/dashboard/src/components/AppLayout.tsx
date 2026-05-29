import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { clearToken } from "../lib/api";
import StackStatusStrip from "./StackStatusStrip";

const NAV = [
  { to: "/", end: true, icon: "🏠", label: "Building status" },
  { to: "/data-model", icon: "🧱", label: "Data Model BRICK" },
  { to: "/rule-lab", icon: "🐍", label: "Rule Lab" },
  { to: "/bacnet", icon: "📡", label: "BACnet" },
  { to: "/agent", icon: "🤖", label: "AI Agent" },
];

export default function AppLayout() {
  const navigate = useNavigate();

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-row">
          <span className="brand">Open-FDD</span>
          <span className="brand-chip">Operator</span>
        </div>
        <p className="muted sidebar-hint">OT LAN · behind firewall</p>
        <StackStatusStrip />
        <nav className="sidebar-nav">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
            >
              <span className="nav-icon">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <button
          type="button"
          className="secondary-btn sign-out-btn"
          onClick={() => {
            clearToken();
            navigate("/login");
          }}
        >
          Sign out
        </button>
      </aside>
      <main className="app-main">
        <div className="content">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
