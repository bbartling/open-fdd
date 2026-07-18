import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { clearToken, fetchAuthMe, fetchAuthStatus, getBridgeBase, hasToken } from "../lib/api";
import { useTheme } from "../contexts/theme-context";
import StackStatusStrip from "./StackStatusStrip";

type HealthInfo = { version?: string; image_tag?: string };

type NavItem = {
  to: string;
  end?: boolean;
  label: string;
  protected?: boolean;
  disabled?: boolean;
  disabledHint?: string;
};

/* Streamlit-parity nav: plain text labels, no emoji icons. */
const NAV_SECTIONS: { title: string; items: NavItem[] }[] = [
  {
    title: "Overview",
    items: [{ to: "/", end: true, label: "Dashboard" }],
  },
  {
    title: "Integrations",
    items: [
      { to: "/edge-fleet", label: "Edge fleet", protected: true },
      { to: "/bacnet", label: "BACnet (legacy)", protected: true },
      { to: "/haystack", label: "Haystack (legacy)", protected: true },
      { to: "/modbus", label: "Modbus (legacy)", protected: true },
      { to: "/json-api", label: "JSON API", protected: true },
    ],
  },
  {
    title: "Model & rules",
    items: [
      { to: "/lab", label: "Open-FDD Lab (vibe19)", protected: true },
      { to: "/csv", label: "CSV job upload", protected: true },
      { to: "/model", label: "Model & FDD assignments", protected: true },
      { to: "/sql-fdd", label: "SQL FDD lab (integrator)", protected: true },
      { to: "/plot", label: "Plots", protected: true },
      { to: "/reports", label: "Reports", protected: true },
    ],
  },
  {
    title: "Data & ops",
    items: [
      { to: "/exports", label: "Data export", protected: true },
      { to: "/data-management", label: "Historian storage", protected: true },
      { to: "/host", label: "Host stats", protected: true },
      { to: "/algorithms", label: "Algorithms", protected: true },
    ],
  },
  {
    title: "Settings",
    items: [
      { to: "/agent", label: "External agents", protected: true },
    ],
  },
];

export default function AppLayout() {
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();
  const [authRequired, setAuthRequired] = useState<boolean | null>(null);
  const [tokenPresent, setTokenPresent] = useState(hasToken());
  const [sessionRole, setSessionRole] = useState<string | null>(null);
  const [sessionUser, setSessionUser] = useState<string | null>(null);
  const [edgeVersion, setEdgeVersion] = useState<string | null>(null);

  useEffect(() => {
    const base = getBridgeBase();
    fetch(`${base}/api/health`)
      .then((r) => r.json())
      .then((h: HealthInfo) => setEdgeVersion(h.version || h.image_tag || null))
      .catch(() => setEdgeVersion(null));
  }, []);

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
        <div className="brand-block">
          <div className="brand-row">
            <span className="brand">Open-FDD</span>
            <div className="brand-meta">
              {edgeVersion ? (
                <span className="brand-chip muted" title="Edge release">
                  v{edgeVersion}
                </span>
              ) : null}
              {roleChip ? (
                <span className="brand-chip" title={sessionUser ? `${sessionUser}` : undefined}>
                  {roleChip}
                </span>
              ) : null}
            </div>
          </div>
        </div>
        <p className="sidebar-hint">Building summary is public; sign in to browse all tabs (operator read-only).</p>
        <StackStatusStrip />
        <nav className="sidebar-nav">
          {NAV_SECTIONS.map((section) => (
            <div key={section.title} className="nav-section">
              <div className="nav-section-title">{section.title}</div>
              {section.items.map((item) =>
                item.disabled ? (
                  <span
                    key={item.to}
                    className="nav-item nav-item-disabled"
                    title={item.disabledHint ?? "Coming soon"}
                    aria-disabled="true"
                  >
                    {item.label}
                    <span className="nav-soon">Soon</span>
                  </span>
                ) : (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
                  >
                    {item.label}
                  </NavLink>
                ),
              )}
            </div>
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
        <div className="content-row">
          <div className="content">
            <Outlet />
          </div>
        </div>
      </main>
    </div>
  );
}
