import { NavLink } from "react-router-dom";

const NAV_ITEMS = [
  { to: "/", label: "Home", testId: "nav-home" },
  { to: "/jobs", label: "Jobs", testId: "nav-jobs" },
  { to: "/upload", label: "Upload", testId: "nav-upload" },
  { to: "/mapping", label: "Mapping", testId: "nav-mapping" },
  { to: "/rules", label: "Rules", testId: "nav-rules" },
  { to: "/findings", label: "Findings", testId: "nav-findings" },
  { to: "/reports", label: "Reports", testId: "nav-reports" },
  { to: "/wattlab", label: "WattLab", testId: "nav-wattlab" },
] as const;

interface AppShellProps {
  title: string;
  children: React.ReactNode;
}

export function AppShell({ title, children }: AppShellProps) {
  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="app-sidebar__brand">Open-FDD</div>
        <nav className="app-sidebar__nav" aria-label="Main">
          {NAV_ITEMS.map(({ to, label, testId }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                `app-sidebar__link${isActive ? " app-sidebar__link--active" : ""}`
              }
              data-testid={testId}
            >
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="app-main">
        <header className="app-header">
          <h1 className="app-header__title">{title}</h1>
        </header>
        <main className="app-content">{children}</main>
      </div>
    </div>
  );
}
