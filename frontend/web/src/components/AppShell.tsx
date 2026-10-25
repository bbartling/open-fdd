import { useCallback, useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router";
import { SectionTabs } from "./SectionTabs";
import { OracleSidebar } from "./OracleSidebar";
import { TenantSwitcher, type TenantOption } from "./TenantSwitcher";
import { SIDEBAR_NAV } from "../nav/sections";
import { buildSessionSearch, hrefWithSession, parseSessionSearch } from "../session/sessionQuery";
import { leaveBuildingSession } from "../api/sessionsApi";
import { apiFetch, isCentralUnavailable } from "../api/client";
import {
  getAuthMe,
  getStoredToken,
  logout,
  type AuthMe,
} from "../api/authApi";
import {
  clearTenantScopedClientState,
  getStoredActiveTenant,
  selectTenant,
  setStoredActiveTenant,
  type TenantsListResponse,
} from "../api/tenantApi";

/** Keep wheel scrolling inside a pane so the document does not chain-scroll. */
function useWheelScrollContainment(ref: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const onWheel = (event: WheelEvent) => {
      event.stopPropagation();
      if (el.scrollHeight <= el.clientHeight) {
        event.preventDefault();
        return;
      }
      const atTop = el.scrollTop <= 0;
      const atBottom =
        el.scrollTop + el.clientHeight >= el.scrollHeight - 1;
      const up = event.deltaY < 0;
      const down = event.deltaY > 0;
      if ((up && atTop) || (down && atBottom)) {
        event.preventDefault();
      }
    };

    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  });
}

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
  const [sidebarWidthPx, setSidebarWidthPx] = useState<number>(() => {
    try {
      const raw = localStorage.getItem("openfdd.ui.sidebar_width_px");
      const n = raw ? Number(raw) : NaN;
      if (!Number.isFinite(n) || n <= 0) return 300;
      return Math.min(720, Math.max(180, Math.round(n)));
    } catch {
      return 300;
    }
  });
  const [sidebarResizing, setSidebarResizing] = useState(false);
  const [sidebarRight, setSidebarRight] = useState<boolean>(() => {
    try {
      const v = localStorage.getItem("openfdd.ui.sidebar_right");
      return v === "1" || v === "true";
    } catch {
      return false;
    }
  });
  const [revision, setRevision] = useState<{
    full: string;
    display: string;
    collapsed: string;
  } | null>(null);
  const [updateAvailable, setUpdateAvailable] = useState<string | null>(null);
  const [centralNotice, setCentralNotice] = useState<string | null>(null);
  const [timescaleOk, setTimescaleOk] = useState(false);
  const [activeTenantId, setActiveTenantId] = useState<string | null>(() => {
    return getStoredActiveTenant();
  });
  const [memberships, setMemberships] = useState<TenantOption[]>([]);
  const [multiTenant, setMultiTenant] = useState(false);
  const [hubAdmin, setHubAdmin] = useState(false);
  const [tenantIds, setTenantIds] = useState<string[]>([]);
  const [tenantListDenied, setTenantListDenied] = useState(false);
  const [tenantSwitching, setTenantSwitching] = useState(false);
  const [tenantSwitchError, setTenantSwitchError] = useState<string | null>(null);
  const [sessionUser, setSessionUser] = useState<string | null>(null);
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    let cancelled = false;
    if (!getStoredToken()) {
      setSessionUser(null);
      setTenantIds([]);
      return;
    }
    void getAuthMe()
      .then((me: AuthMe) => {
        if (cancelled) return;
        setHubAdmin(me.hub_admin === true);
        if (typeof me.multi_tenant === "boolean") {
          setMultiTenant(me.multi_tenant);
        }
        setTenantIds(
          Array.isArray(me.tenant_ids)
            ? me.tenant_ids.map((id) => String(id).trim()).filter(Boolean)
            : [],
        );
        if (me.username) setSessionUser(me.username);
      })
      .catch(() => {
        if (!cancelled) {
          setSessionUser(null);
          setHubAdmin(false);
          setTenantIds([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [location.pathname]);

  const onSignOut = () => {
    logout();
    setSessionUser(null);
    navigate("/auth");
  };

  const resizeStateRef = useRef<{ startX: number; startWidth: number } | null>(null);
  const pendingWidthRef = useRef<number | null>(null);
  const resizeRafRef = useRef<number | null>(null);
  const sidebarScrollRef = useRef<HTMLDivElement>(null);
  const mainPaneRef = useRef<HTMLDivElement>(null);
  useWheelScrollContainment(sidebarScrollRef);
  useWheelScrollContainment(mainPaneRef);

  const onSidebarResizeStart = (e: React.MouseEvent<HTMLElement>) => {
    if (collapsed) return;
    // Starting width is captured once, then direction is decided by sidebarLeft vs sidebarRight.
    resizeStateRef.current = { startX: e.clientX, startWidth: sidebarWidthPx };
    pendingWidthRef.current = null;
    setSidebarResizing(true);
    e.preventDefault();
  };

  useEffect(() => {
    if (!sidebarResizing) return;
    const st = resizeStateRef.current;
    if (!st) return;

    const { startX, startWidth } = st;
    const minW = 180;
    const maxW = 720;

    const onMove = (ev: MouseEvent) => {
      const delta = ev.clientX - startX;
      const raw = sidebarRight ? startWidth - delta : startWidth + delta;
      const next = Math.round(Math.min(maxW, Math.max(minW, raw)));
      pendingWidthRef.current = next;

      if (resizeRafRef.current != null) return;
      resizeRafRef.current = window.requestAnimationFrame(() => {
        resizeRafRef.current = null;
        const w = pendingWidthRef.current;
        if (w != null) setSidebarWidthPx(w);
      });
    };

    const onUp = () => {
      setSidebarResizing(false);
      const w = pendingWidthRef.current ?? sidebarWidthPx;
      try {
        localStorage.setItem("openfdd.ui.sidebar_width_px", String(w));
      } catch {
        /* ignore */
      }
      resizeStateRef.current = null;
      pendingWidthRef.current = null;
    };

    const prevCursor = document.body.style.cursor;
    const prevUserSelect = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);

    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      document.body.style.cursor = prevCursor;
      document.body.style.userSelect = prevUserSelect;
      if (resizeRafRef.current != null) {
        window.cancelAnimationFrame(resizeRafRef.current);
        resizeRafRef.current = null;
      }
    };
  }, [sidebarResizing, sidebarRight, sidebarWidthPx]);

  useEffect(() => {
    try {
      localStorage.setItem(
        "openfdd.ui.sidebar_right",
        sidebarRight ? "1" : "0",
      );
    } catch {
      /* ignore */
    }
  }, [sidebarRight]);

  useEffect(() => {
    let cancelled = false;
    const reloadKey = "openfdd.ui.version_reload_at";
    void (async () => {
      let centralVer = "";
      try {
        const h = await apiFetch<{ version?: string; timescale_ok?: boolean; historian?: string }>(
          "/api/health",
        );
        centralVer = String(h.version ?? "").trim();
        if (!cancelled && centralVer) setRevision(shortRevision(centralVer));
        if (!cancelled) {
          setTimescaleOk(h.timescale_ok === true && h.historian === "timescale");
          setCentralNotice(null);
        }
      } catch (err) {
        if (!cancelled && isCentralUnavailable(err)) {
          setCentralNotice(
            "Central is not answering. This page stays up; API calls fail until it is back.",
          );
        }
      }
      try {
        const r = await fetch(`/version.json?t=${Date.now()}`, {
          cache: "no-store",
        });
        if (!r.ok) return;
        const j = (await r.json()) as {
          version?: string;
          git?: string;
          git_sha?: string;
        };
        const sha = String(j.git ?? j.git_sha ?? "").trim();
        const ver = String(j.version ?? "").trim();
        const webLabel = sha ? `${ver}+${sha}` : ver;
        if (!cancelled && !centralVer && webLabel) {
          setRevision(shortRevision(webLabel));
        }
        // Controlled update UX: when web assets and central disagree, offer reload
        // with backoff so unsaved edits are not loop-reloaded.
        if (!cancelled && centralVer && webLabel) {
          const centralSha = centralVer.includes("+")
            ? centralVer.slice(centralVer.indexOf("+") + 1).slice(0, 7)
            : "";
          const webSha = sha.slice(0, 7);
          if (centralSha && webSha && centralSha !== webSha) {
            setUpdateAvailable(
              `UI ${webSha} vs central ${centralSha} — reload when ready`,
            );
            try {
              const last = Number(sessionStorage.getItem(reloadKey) || "0");
              if (Date.now() - last > 5 * 60_000) {
                // Soft notice only — never auto-reload in a loop.
              }
            } catch {
              /* ignore */
            }
          }
        }
      } catch {
        /* keep brand-only */
      }
    })();
    void apiFetch<TenantsListResponse>("/api/tenants")
      .then((t) => {
        if (cancelled) return;
        setTenantListDenied(false);
        const id = (t.active_tenant_id || "legacy").trim();
        setActiveTenantId(id);
        setStoredActiveTenant(id);
        setMultiTenant(t.multi_tenant === true);
        setMemberships(
          (t.tenants ?? []).map((row) => ({
            id: row.id,
            name: row.name || row.id,
          })),
        );
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const status =
          err && typeof err === "object" && "status" in err
            ? Number((err as { status?: unknown }).status)
            : NaN;
        const message = err instanceof Error ? err.message : String(err ?? "");
        const membershipDenied =
          status === 403 ||
          /membership|tenant/i.test(message);
        setTenantListDenied(membershipDenied);
        if (membershipDenied) {
          setMemberships([]);
        }
        /* otherwise keep stored / null */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const onTenantSelect = useCallback(
    (tenantId: string) => {
      if (!tenantId || tenantId === activeTenantId || tenantSwitching) return;
      setTenantSwitching(true);
      setTenantSwitchError(null);
      const currentSite = parseSessionSearch(location.search).siteId ?? "";
      void selectTenant(tenantId)
        .then(async (body) => {
          if (!body.ok || !body.active_tenant_id) {
            setTenantSwitchError(body.error || "Could not switch tenant");
            return;
          }
          if (currentSite) leaveBuildingSession(currentSite);
          clearTenantScopedClientState();
          const next = body.active_tenant_id.trim();
          setActiveTenantId(next);
          navigate(
            {
              pathname: location.pathname,
              search: buildSessionSearch(location.search, {
                siteId: "",
                equipment: "",
                jobId: "",
              }),
            },
            { replace: true },
          );
          try {
            const listed = await apiFetch<TenantsListResponse>("/api/tenants");
            setMultiTenant(listed.multi_tenant === true);
            setMemberships(
              (listed.tenants ?? []).map((row) => ({
                id: row.id,
                name: row.name || row.id,
              })),
            );
            const listedId = (listed.active_tenant_id || next).trim();
            if (listedId) setActiveTenantId(listedId);
          } catch {
            // A list refresh is not the switch. Membership stays as last known.
          }
        })
        .catch((err: unknown) => {
          const msg = err instanceof Error ? err.message : "Could not switch tenant";
          setTenantSwitchError(msg);
        })
        .finally(() => {
          setTenantSwitching(false);
        });
    },
    [activeTenantId, location.pathname, location.search, navigate, tenantSwitching],
  );

  const showTenantLabel = Boolean(activeTenantId && activeTenantId !== "legacy");
  const showTenantSwitcher =
    !collapsed && multiTenant && !hubAdmin && memberships.length > 1;
  /** Operator/viewer with multi-tenant on and no membership needs hub-admin assignment. */
  const needsTenantAssignment =
    multiTenant &&
    !hubAdmin &&
    (tenantListDenied || (tenantIds.length === 0 && memberships.length === 0));

  return (
    <div
      className={`app-shell${
        collapsed ? " app-shell--sidebar-collapsed" : ""
      }${sidebarRight ? " app-shell--sidebar-right" : ""}${
        sidebarResizing ? " app-shell--sidebar-resizing" : ""
      }`}
      data-testid="app-shell"
      data-sidebar-collapsed={collapsed ? "true" : "false"}
      style={
        {
          "--sidebar-width": `${sidebarWidthPx}px`,
        } as React.CSSProperties
      }
    >
      {centralNotice ? (
        <div
          className="app-shell__update-banner"
          data-testid="central-unavailable-banner"
          role="status"
        >
          <span>{centralNotice}</span>
          <button
            type="button"
            className="button button--small button--ghost"
            onClick={() => setCentralNotice(null)}
          >
            Dismiss
          </button>
        </div>
      ) : null}
      {updateAvailable ? (
        <div
          className="app-shell__update-banner"
          data-testid="app-update-banner"
          role="status"
        >
          <span>{updateAvailable}</span>
          <button
            type="button"
            className="button button--small"
            onClick={() => {
              try {
                sessionStorage.setItem(
                  "openfdd.ui.version_reload_at",
                  String(Date.now()),
                );
              } catch {
                /* ignore */
              }
              window.location.reload();
            }}
          >
            Reload UI
          </button>
          <button
            type="button"
            className="button button--small button--ghost"
            onClick={() => setUpdateAvailable(null)}
          >
            Dismiss
          </button>
        </div>
      ) : null}
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
            {timescaleOk ? (
              <div className="app-sidebar__revision" data-testid="historian-timescale">
                Timescale connected
              </div>
            ) : null}
            {showTenantSwitcher && activeTenantId ? (
              <TenantSwitcher
                tenants={memberships}
                activeTenantId={activeTenantId}
                disabled={tenantSwitching}
                onSelect={onTenantSelect}
              />
            ) : showTenantLabel && activeTenantId ? (
              <div
                className="app-sidebar__tenant"
                data-testid="app-tenant"
                title={`Active tenant: ${activeTenantId}`}
              >
                {collapsed ? activeTenantId.slice(0, 3) : `tenant:${activeTenantId}`}
              </div>
            ) : null}
            {tenantSwitchError ? (
              <div
                className="app-sidebar__tenant-error"
                role="alert"
                data-testid="app-tenant-switch-error"
              >
                {tenantSwitchError}
              </div>
            ) : null}
            {sessionUser ? (
              <div
                className="app-sidebar__session"
                data-testid="app-session-user"
                title={`Signed in as ${sessionUser}`}
              >
                {collapsed ? sessionUser.slice(0, 3) : sessionUser}
              </div>
            ) : null}
            <div className="app-sidebar__auth-row" data-testid="app-account">
              {sessionUser ? (
                <button
                  type="button"
                  className="button button--small"
                  data-testid="app-sign-out"
                  onClick={onSignOut}
                  title="Sign out"
                >
                  {collapsed ? "Out" : "Sign out"}
                </button>
              ) : (
                <Link
                  to={hrefWithSession("/auth", location.search)}
                  className="button button--small"
                  data-testid="app-sign-in"
                >
                  {collapsed ? "In" : "Sign in"}
                </Link>
              )}
            </div>
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
          <button
            type="button"
            className="app-sidebar__collapse"
            aria-pressed={sidebarRight}
            onClick={() => setSidebarRight((v) => !v)}
            title={sidebarRight ? "Move sidebar to the left" : "Move sidebar to the right"}
            data-testid="sidebar-side-toggle"
          >
            {sidebarRight ? "◀" : "▶"}
          </button>
        </div>

        <button
          type="button"
          className="app-sidebar__resizer"
          aria-label="Resize sidebar"
          data-testid="sidebar-resizer"
          onMouseDown={onSidebarResizeStart}
        />

        <div
          id="app-sidebar-oracle"
          ref={sidebarScrollRef}
          className="app-sidebar__scroll"
        >
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
      <div className="app-main" ref={mainPaneRef} data-testid="app-main">
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
        {needsTenantAssignment ? (
          <div
            className="inline-alert"
            role="status"
            data-testid="tenant-assignment-guidance"
          >
            This account has no tenant assignment. Ask a hub admin to add you to
            a tenant under Admin → Users, then sign out and sign back in. Sites
            and analytics stay unavailable until a tenant is assigned.
          </div>
        ) : null}
        <main className="app-content">{children}</main>
      </div>
    </div>
  );
}
