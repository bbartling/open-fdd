import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { clearToken, fetchAuthMe, fetchAuthStatus, hasToken } from "../lib/api";
import { useTheme } from "../contexts/theme-context";
import StackStatusStrip from "./StackStatusStrip";

const NAV = [
  { to: "/", end: true, icon: "🏠", label: "Building status" },
  { to: "/bacnet", icon: "📡", label: "BACnet", protected: true },
  { to: "/modbus", icon: "🔌", label: "Modbus", protected: true },
  { to: "/rule-lab", icon: "🐍", label: "Rule Lab", protected: true },
  { to: "/model", icon: "🧱", label: "Model & assignments", protected: true },
  { to: "/faults", icon: "🚦", label: "Fault catalog" },
  { to: "/plot", icon: "📈", label: "Trend plot", protected: true },
  { to: "/agent", icon: "🤖", label: "AI Agent", protected: true },
  { to: "/host", icon: "📊", label: "Host stats", protected: true },
];

export default function AppLayout() {
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();
  const [authRequired, setAuthRequired] = useState<boolean | null>(null);
  const [tokenPresent, setTokenPresent] = useState(hasToken());
  const [sessionRole, setSessionRole] = useState<string | null>(null);
  const [sessionUser, setSessionUser] = useState<string | null>(null);

  useEffect(() => {
    fetchAuthStatus()
      .then((s) => setAuthRequired(s.auth_required))
      .catch(() => setAuthRequired(true));
  }, []);

  useEffect(() => {
    const sync = () => {
      setTokenPresent(hasToken());
      if (!hasToken()) {
        setSessionRole(null);
        setSessionUser(null);
        return;
      }
      fetchAuthMe()
        .then((me) => {
          setSessionRole(me.role);
          setSessionUser(me.username);
        })
        .catch(() => {
          setSessionRole(null);
          setSessionUser(null);
        });
    };
    sync();
    window.addEventListener("storage", sync);
    window.addEventListener("focus", sync);
    window.addEventListener("ofdd-auth", sync);
    return () => {
      window.removeEventListener("storage", sync);
      window.removeEventListener("focus", sync);
      window.removeEventListener("ofdd-auth", sync);
    };
  }, []);

  const signedIn = authRequired === false || tokenPresent;
  const roleChip =
    authRequired === false ? "dev" : sessionRole || (signedIn ? "signed in" : null);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-row">
          <span className="brand">Open-FDD</span>
          {roleChip ? (
            <span className="brand-chip" title={sessionUser ? `${sessionUser}` : undefined}>
              {roleChip}
            </span>
          ) : null}
        </div>
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
              {item.protected && authRequired && !signedIn ? (
                <span className="nav-lock" title="Sign in required">
                  🔒
                </span>
              ) : null}
            </NavLink>
          ))}
        </nav>
        {authRequired === null ? null : authRequired && !signedIn ? (
          <button type="button" className="secondary-btn sign-out-btn" onClick={() => navigate("/login")}>
            Sign in
          </button>
        ) : (
          <>
            <button type="button" className="secondary-btn theme-toggle-btn" onClick={toggleTheme}>
              {theme === "dark" ? "Light UI" : "Dark UI"}
            </button>
            {signedIn && authRequired ? (
              <button
                type="button"
                className="secondary-btn sign-out-btn"
                onClick={() => {
                  clearToken();
                  setTokenPresent(false);
                  navigate("/login");
                }}
              >
                Sign out
              </button>
            ) : null}
          </>
        )}
      </aside>
      <main className="app-main">
        <div className="content">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
