import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Button,
  ConfirmModal,
  InlineAlert,
} from "./widgets";
import { deleteDataset } from "../api/datasetsApi";
import { listPackageBuildings } from "../api/mappingApi";
import { fetchProviderSites, type ProviderSiteConfig } from "../api/providersApi";
import { siteSourceLabels } from "../lib/providerDisplay";
import { useDatasetWriteAllowed } from "../hooks/useDatasetWriteAllowed";
import { useSessionQuery } from "../session";

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * CAP-SITE: list / switch / delete loaded package sites.
 * site id ≡ building_id ≡ dataset id.
 * Embedded under Operations (Sites radio).
 */
export function SitesPanel() {
  const { query, setQuery } = useSessionQuery();
  const canWrite = useDatasetWriteAllowed();
  const activeSite = query.siteId ?? "";

  const [sites, setSites] = useState<string[]>([]);
  const [providerBySite, setProviderBySite] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    const [pkgResult, providerBody] = await Promise.all([
      listPackageBuildings()
        .then((ids) => ({ ok: true as const, ids }))
        .catch((err: unknown) => ({ ok: false as const, err })),
      fetchProviderSites().catch(() => null),
    ]);
    const providers: Record<string, string> = {};
    const providerConfigs: ProviderSiteConfig[] = [
      ...(providerBody?.sites ?? []),
      ...(providerBody?.health ?? []),
    ];
    for (const site of providerConfigs) {
      const id = (site.building_id ?? "").trim();
      if (!id) continue;
      if (!providers[id] && site.provider) providers[id] = site.provider;
    }
    if (!pkgResult.ok) {
      const msg = formatErr(pkgResult.err);
      const providerIds = Object.keys(providers);
      if (/building_id required/i.test(msg) && providerIds.length === 0) {
        setSites([]);
        setProviderBySite(providers);
        setError(null);
        setNotice(
          "No sites loaded yet. Portal sites appear from server provider configuration. CSV packages appear after a zip import.",
        );
      } else if (providerIds.length === 0) {
        setSites([]);
        setError(msg);
      } else {
        setSites([]);
        setError(null);
      }
    } else {
      setSites(pkgResult.ids);
      setError(null);
    }
    setProviderBySite(providers);
    const visible = new Set<string>([
      ...(pkgResult.ok ? pkgResult.ids : []),
      ...Object.keys(providers),
    ]);
    if (!activeSite && visible.size === 1) {
      setQuery({ siteId: [...visible][0] }, true);
    }
    setLoading(false);
  }, [activeSite, setQuery]);

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
      setNotice(`Deleted site ${id}.`);
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

  const rows = useMemo(() => {
    const all = new Set<string>([...sites, ...Object.keys(providerBySite)]);
    return Array.from(all).sort((a, b) => a.localeCompare(b));
  }, [providerBySite, sites]);

  return (
    <div className="page-stack" data-testid="sites-page">
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

      {loading && rows.length === 0 ? (
        <p data-testid="sites-loading">Loading sites…</p>
      ) : rows.length === 0 ? (
        <InlineAlert id="sites-empty" variant="info" testId="sites-empty">
          No sites loaded. Portal sites appear from server provider configuration. CSV
          packages appear after a zip import.
        </InlineAlert>
      ) : (
        <div className="widget-table-wrap" data-testid="sites-table">
          <table className="widget-table">
            <thead>
              <tr>
                <th scope="col">Site</th>
                <th scope="col">Sources</th>
                <th scope="col">Active</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((id) => {
                const isActive = activeSite === id;
                const labels = siteSourceLabels({
                  hasPackage: sites.includes(id),
                  provider: providerBySite[id],
                });
                return (
                  <tr key={id} data-testid={`sites-row-${id}`}>
                    <td>
                      <code>{id}</code>
                    </td>
                    <td data-testid={`sites-sources-${id}`}>
                      {labels.length > 0 ? labels.join(", ") : "—"}
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
                        {canWrite ? (
                          <Button
                            id={`sites-delete-${id}`}
                            label="Delete site…"
                            variant="danger"
                            density="compact"
                            disabled={actionLoading || !sites.includes(id)}
                            onClick={() => setDeleteTarget(id)}
                            testId={`sites-delete-${id}`}
                          />
                        ) : null}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {canWrite ? (
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
      ) : null}
    </div>
  );
}
