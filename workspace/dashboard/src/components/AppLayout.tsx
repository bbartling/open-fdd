import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { clearToken } from "../lib/api";

export default function AppLayout() {
  const navigate = useNavigate();

  return (
    <div className="layout">
      <aside className="sidebar">
        <h1>Open-FDD Operator</h1>
        <p className="muted">OT LAN · behind firewall</p>
        <nav>
          <NavLink to="/" end>
            Overview
          </NavLink>
          <NavLink to="/rule-lab">Rule Lab</NavLink>
          <NavLink to="/fdd">YAML FDD</NavLink>
          <NavLink to="/bacnet">BACnet</NavLink>
          <NavLink to="/agent">AI Agent</NavLink>
        </nav>
        <button
          type="button"
          className="secondary"
          style={{ marginTop: "1.5rem" }}
          onClick={() => {
            clearToken();
            navigate("/login");
          }}
        >
          Sign out
        </button>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
