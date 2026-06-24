import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { clearToken, fetchAuthMe, fetchAuthStatus, hasToken } from "../lib/api";
import { useTheme } from "../contexts/theme-context";
import StackStatusStrip from "./StackStatusStrip";

type NavItem = {
  to: string;
  end?: boolean;
  icon: string;
  label: string;
  protected?: boolean;
  disabled?: boolean;
  disabledHint?: string;
};

const NAV_SECTIONS: { title: string; items: NavItem[] }[] = [
  {
    title: "Overview",
    items: [
      { to: "/", end: true, icon: "🏠", label: "Building status" },
      { to: "/live-fdd-validation", icon: "🧪", label: "Live FDD Validation", protected: true },
    ],
  },
  {
    title: "Data & rules",
    items: [
      { to: "/drivers", icon: "🌳", label: "Drivers", protected: true },
      { to: "/sql-fdd", icon: "⚡", label: "SQL FDD Rules", protected: true },
      { to: "/plot", icon: "📈", label: "Trend plot", protected: true },
    ],
  },
  {
    title: "Integrations",
    items: [
      { to: "/json-api", icon: "🌐", label: "JSON API", protected: true },
      { to: "/data-management", icon: "🗄️", label: "Data management", protected: true },
    ],
  },
  {
    title: "Haystack model",
    items: [
      { to: "/model", icon: "📐", label: "Model & assignments", protected: true },
      { to: "/algorithms", icon: "⚙️", label: "Algorithms", protected: true },
    ],
  },
  {
    title: "Ops",
    items: [
      { to: "/agent", icon: "🤖", label: "AI Agent", protected: true, disabled: true, disabledHint: "Coming soon — Ollama & Codex" },
      { to: "/host", icon: "📊", label: "Host stats", protected: true },
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
        <p className="sidebar-hint">Haystack-first operator console</p>
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
                    <span className="nav-icon">{item.icon}</span>
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
                    <span className="nav-icon">{item.icon}</span>
                    {item.label}
                    {item.protected && authRequired && !signedIn ? (
                      <span className="nav-lock" title="Sign in required">
                        🔒
                      </span>
                    ) : null}
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
        <div className="content">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
