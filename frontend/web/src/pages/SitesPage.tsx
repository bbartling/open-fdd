import { useCallback, useEffect, useState } from "react";
import { AppShell } from "../components/AppShell";
import {
  Button,
  ConfirmModal,
  InlineAlert,
} from "../components/widgets";
import { deleteDataset } from "../api/datasetsApi";
import { listPackageBuildings } from "../api/mappingApi";
import { useSessionQuery } from "../session";

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * CAP-SITE: list / switch / delete loaded package sites.
 * site id ≡ building_id ≡ dataset id.
 */
export function SitesPage() {
  const { query, setQuery } = useSessionQuery();
  const activeSite = query.siteId ?? "";

  const [sites, setSites] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const ids = await listPackageBuildings();
      setSites(ids);
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onSetActive = (id: string) => {
    setQuery({ siteId: id }, true);
    setNotice(`Active site set to ${id}.`);
  };

  const onConfirmDelete = async () => {
    const id = deleteTarget?.trim();
    if (!id) return;
    setActionLoading(true);
    setError(null);
    setNotice(null);
    try {
      const body = await deleteDataset(id);
      if (!body.ok) {
        throw new Error(body.error || "Delete failed");
      }
      setDeleteTarget(null);
      const remaining = sites.filter((s) => s !== id);
      setSites(remaining);
      if (activeSite === id) {
        setQuery({ siteId: remaining[0] ?? "", equipment: "" }, true);
      }
      setNotice(
        `Deleted site ${id} (feathers, FDD results, parquet, site-linked jobs).`,
      );
      try {
        window.dispatchEvent(
          new CustomEvent("openfdd:package-deleted", {
            detail: { buildingId: id },
          }),
        );
      } catch {
        /* ignore */
      }
      await refresh();
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <AppShell
      title="Sites"
      caption="Loaded packages stay on disk — switch Active site anytime; Delete site purges model data."
      activeSectionId="sites"
    >
      <div className="page-stack" data-testid="sites-page">
        <p className="oracle-sidebar__caption">
          Each site is a package <code>building_id</code> (same as dataset id). Load more
          via the sidebar zip picker (<strong>Load package</strong>). Manage delete here —
          not on the CSV/zip picker.
        </p>

        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <Button
            id="sites-refresh"
            label={loading ? "Loading…" : "Refresh"}
            onClick={() => void refresh()}
            testId="sites-refresh"
          />
          {activeSite ? (
            <p className="oracle-sidebar__caption" data-testid="sites-active-hint">
              Active site: <strong>{activeSite}</strong>
            </p>
          ) : (
            <p className="oracle-sidebar__caption" data-testid="sites-active-hint">
              No Active site selected
            </p>
          )}
        </div>

        {error ? (
          <InlineAlert id="sites-error" variant="danger" testId="sites-error">
            {error}
          </InlineAlert>
        ) : null}
        {notice ? (
          <InlineAlert id="sites-notice" variant="success" testId="sites-notice">
            {notice}
          </InlineAlert>
        ) : null}

        {loading && sites.length === 0 ? (
          <p data-testid="sites-loading">Loading sites…</p>
        ) : sites.length === 0 ? (
          <InlineAlert id="sites-empty" variant="info" testId="sites-empty">
            No sites loaded. Import an <code>openfdd_package_v1</code> zip from the sidebar
            Load package control.
          </InlineAlert>
        ) : (
          <div className="widget-table-wrap" data-testid="sites-table">
            <table className="widget-table">
              <thead>
                <tr>
                  <th scope="col">Site</th>
                  <th scope="col">Active</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {sites.map((id) => {
                  const isActive = activeSite === id;
                  return (
                    <tr key={id} data-testid={`sites-row-${id}`}>
                      <td>
                        <code>{id}</code>
                      </td>
                      <td data-testid={`sites-active-${id}`}>
                        {isActive ? "yes" : "—"}
                      </td>
                      <td>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.35rem" }}>
                          <Button
                            id={`sites-set-active-${id}`}
                            label="Set active"
                            variant="secondary"
                            density="compact"
                            disabled={isActive}
                            onClick={() => onSetActive(id)}
                            testId={`sites-set-active-${id}`}
                          />
                          <Button
                            id={`sites-delete-${id}`}
                            label="Delete site…"
                            variant="danger"
                            density="compact"
                            disabled={actionLoading}
                            onClick={() => setDeleteTarget(id)}
                            testId={`sites-delete-${id}`}
                          />
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        <ConfirmModal
          id="sites-delete-modal"
          open={deleteTarget != null}
          title="Delete site"
          message={
            deleteTarget
              ? `Permanently delete site "${deleteTarget}"? This removes feathers, FDD rule results, analytics parquet, csv package data, and jobs linked to this site. This cannot be undone.`
              : "Delete this site?"
          }
          confirmLabel="Delete site"
          loading={actionLoading}
          onConfirm={() => void onConfirmDelete()}
          onCancel={() => setDeleteTarget(null)}
          testId="sites-delete-modal"
        />
      </div>
    </AppShell>
  );
}
