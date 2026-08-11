import { useState } from "react";
import { NavLink, useLocation } from "react-router";
import { SectionTabs } from "./SectionTabs";
import { OracleSidebar } from "./OracleSidebar";
import { SIDEBAR_NAV } from "../nav/sections";
import { hrefWithSession } from "../session/sessionQuery";

interface AppShellProps {
  title: string;
  caption?: string;
  children: React.ReactNode;
  /** Streamlit section id for top tab highlight */
  activeSectionId?: string;
  /** When true, omit page H1 (hero supplies brand on Overview empty state). */
  hideHeader?: boolean;
  /** Overview places radios after Equipment (vibe19); omit the chrome row. */
  hideSectionTabs?: boolean;
}

export function AppShell({
  title,
  caption,
  children,
  activeSectionId,
  hideHeader = false,
  hideSectionTabs = false,
}: AppShellProps) {
  const [collapsed, setCollapsed] = useState(false);
  const location = useLocation();

  return (
    <div
      className={`app-shell${collapsed ? " app-shell--sidebar-collapsed" : ""}`}
      data-testid="app-shell"
      data-sidebar-collapsed={collapsed ? "true" : "false"}
    >
      <aside className="app-sidebar" aria-label="Sites and controls">
        <div className="app-sidebar__brand-row">
          <div className="app-sidebar__brand">Open-FDD</div>
          <button
            type="button"
            className="app-sidebar__collapse"
            aria-expanded={!collapsed}
            aria-controls="app-sidebar-oracle"
            data-testid="sidebar-collapse"
            onClick={() => setCollapsed((v) => !v)}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? "»" : "«"}
          </button>
        </div>

        <div id="app-sidebar-oracle" className="app-sidebar__scroll">
          <OracleSidebar collapsed={collapsed} />
        </div>

        <details className="app-sidebar__pages" open={false}>
          <summary>App pages</summary>
          <nav
            id="app-sidebar-nav"
            className="app-sidebar__nav"
            aria-label="App pages"
          >
            {SIDEBAR_NAV.map(({ to, label, short, testId }) => (
              <NavLink
                key={to}
                to={hrefWithSession(to, location.search)}
                end={to === "/"}
                className={({ isActive }) =>
                  `app-sidebar__link${isActive ? " app-sidebar__link--active" : ""}`
                }
                data-testid={testId}
                title={label}
              >
                {collapsed ? short : label}
              </NavLink>
            ))}
          </nav>
        </details>
      </aside>
      <div className="app-main">
        {!hideHeader ? (
          <header className="app-header">
            <h1 className="app-header__title">{title}</h1>
            {caption ? (
              <p className="app-header__caption" data-testid="page-caption">
                {caption}
              </p>
            ) : null}
          </header>
        ) : null}
        {hideSectionTabs ? null : (
          <SectionTabs activeSectionId={activeSectionId} />
        )}
        <main className="app-content">{children}</main>
      </div>
    </div>
  );
}
