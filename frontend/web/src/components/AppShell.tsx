import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router";
import { SectionTabs } from "./SectionTabs";
import { OracleSidebar } from "./OracleSidebar";
import { SIDEBAR_NAV } from "../nav/sections";
import { hrefWithSession } from "../session/sessionQuery";
import { apiFetch } from "../api/client";

function shortRevision(version: string): { full: string; display: string; collapsed: string } {
  const raw = version.trim();
  const plus = raw.indexOf("+");
  if (plus < 0) {
    return { full: raw, display: raw, collapsed: raw };
  }
  const semver = raw.slice(0, plus);
  const sha = raw.slice(plus + 1).replace(/[^a-zA-Z0-9]/g, "").slice(0, 7);
  const display = sha ? `${semver}+${sha}` : semver;
  return { full: raw, display, collapsed: sha ? `+${sha}` : display };
}

interface AppShellProps {
  title: string;
  caption?: string;
  children: React.ReactNode;
  /** Main section id for top tab highlight */
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
  const [revision, setRevision] = useState<{
    full: string;
    display: string;
    collapsed: string;
  } | null>(null);
  const location = useLocation();

  useEffect(() => {
    let cancelled = false;
    void apiFetch<{ version?: string }>("/api/health")
      .then((h) => {
        if (cancelled) return;
        const v = String(h.version ?? "").trim();
        if (v) setRevision(shortRevision(v));
      })
      .catch(async () => {
        try {
          const r = await fetch("/version.json");
          if (!r.ok) return;
          const j = (await r.json()) as {
            version?: string;
            git?: string;
            git_sha?: string;
          };
          if (cancelled) return;
          const sha = String(j.git ?? j.git_sha ?? "").trim();
          const ver = String(j.version ?? "openfdd-web").trim();
          setRevision(shortRevision(sha ? `${ver}+${sha}` : ver));
        } catch {
          /* keep brand-only */
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div
      className={`app-shell${collapsed ? " app-shell--sidebar-collapsed" : ""}`}
      data-testid="app-shell"
      data-sidebar-collapsed={collapsed ? "true" : "false"}
    >
      <aside className="app-sidebar" aria-label="Sites and controls">
        <div className="app-sidebar__brand-row">
          <div className="app-sidebar__brand-block">
            <div className="app-sidebar__brand">Open-FDD</div>
            {revision ? (
              <div
                className="app-sidebar__revision"
                data-testid="app-revision"
                title={revision.full}
              >
                {collapsed ? revision.collapsed : revision.display}
              </div>
            ) : null}
          </div>
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
