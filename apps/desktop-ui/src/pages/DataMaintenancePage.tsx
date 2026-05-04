import { useEffect, useState } from "react";
import { desktopFetch } from "../lib/api";
import { useSite } from "../contexts/site-context";
import { purgeTimeseries } from "../lib/crud-api";

export function DataMaintenancePage() {
  const siteContext = useSite();
  const [siteId, setSiteId] = useState(() => siteContext.selectedSiteId ?? "");
  const [prunePoints, setPrunePoints] = useState(false);
  const [purging, setPurging] = useState(false);
  const [status, setStatus] = useState("");

  useEffect(() => {
    if (!siteId && siteContext.selectedSiteId) {
      setSiteId(siteContext.selectedSiteId);
    }
  }, [siteId, siteContext.selectedSiteId]);

  async function purgeSiteTimeseries() {
    const effectiveSiteId = siteId || siteContext.selectedSiteId || "";
    if (!effectiveSiteId) {
      setStatus("Set or select a site first.");
      return;
    }
    const msg = prunePoints
      ? "Purge timeseries for selected site and remove matching model points? This WILL alter the data model and trigger BRICK TTL sync."
      : "Purge timeseries for selected site? This keeps sites/equipment/points and BRICK model/TTL intact.";
    if (!window.confirm(msg)) return;
    try {
      setPurging(true);
      const out = await purgeTimeseries(effectiveSiteId, prunePoints);
      let msg = `Purged site timeseries: files=${out.files_deleted}, dirs=${out.dirs_deleted}, bytes=${out.bytes_deleted}, points_removed=${out.points_removed}`;
      if (out.ttl_sync_warning) {
        msg += ` TTL sync warning: ${out.ttl_sync_warning}`;
      }
      setStatus(msg);
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    } finally {
      setPurging(false);
    }
  }

  async function deleteEntireSite() {
    const effectiveSiteId = siteId || siteContext.selectedSiteId || "";
    if (!effectiveSiteId) {
      setStatus("Set or select a site first.");
      return;
    }
    const siteName = siteContext.sites.find((s) => s.id === effectiveSiteId)?.name ?? "selected site";
    if (!window.confirm(`Delete site "${siteName}" and all associated data? This is destructive.`)) return;
    try {
      const data = await desktopFetch<{
        sites_deleted?: number;
        feather_purge?:
          | { files_deleted: number; dirs_deleted: number; bytes_deleted: number }
          | { error: string };
        ttl_sync_warning?: string;
      }>(`/sites/${encodeURIComponent(effectiveSiteId)}`, { method: "DELETE" });
      await siteContext.refreshSites();
      const sitesDeleted = data.sites_deleted ?? 0;
      const fpErr = data.feather_purge && "error" in data.feather_purge ? String(data.feather_purge.error) : null;
      if (sitesDeleted <= 0 || fpErr) {
        if (fpErr) {
          setStatus(
            `Delete did not complete: Feather purge failed (${fpErr}). The site record was left unchanged — fix the bridge error and retry.`,
          );
        } else {
          setStatus(
            `No site was deleted (sites_deleted=${sitesDeleted}). Confirm the ID still exists after refresh, then retry.`,
          );
        }
        return;
      }
      setSiteId("");
      let msg = `Deleted site "${siteName}" from the stored model (equipment/points removed; BRICK TTL resync attempted).`;
      const fpOk = data.feather_purge && "files_deleted" in data.feather_purge ? data.feather_purge : null;
      if (fpOk) {
        msg += ` Feather timeseries removed: files=${fpOk.files_deleted}, dirs=${fpOk.dirs_deleted}, bytes=${fpOk.bytes_deleted}.`;
      }
      if (data.ttl_sync_warning) {
        msg +=
          ` TTL was not fully resynced: ${data.ttl_sync_warning}`;
      }
      setStatus(msg);
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="card">
      <h2 className="title">Data &amp; model maintenance</h2>
      <p className="muted">
        Feather files (timeseries) and the JSON model (sites, equipment, points) are stored separately on disk. Purge
        targets Feather only (optional pruning also edits model points). <strong>Delete entire site</strong> removes the
        site from the model and also deletes that site&apos;s Feather timeseries under the bridge so System resources
        counts stay aligned.
      </p>
      <div className="grid-two" style={{ marginTop: 12 }}>
        <div>
          <label>Site</label>
          <select value={siteId || siteContext.selectedSiteId || ""} onChange={(e) => setSiteId(e.target.value)}>
            {siteContext.sites.length === 0 && <option value="">No sites</option>}
            {siteContext.sites.map((site) => (
              <option key={site.id} value={site.id}>
                {site.name}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 14, flexWrap: "wrap" }}>
        <button type="button" onClick={() => void purgeSiteTimeseries()} disabled={purging}>
          {purging ? "Purging..." : "Purge timeseries (site)"}
        </button>
        <button type="button" className="danger-btn" onClick={() => void deleteEntireSite()}>
          Delete entire site
        </button>
      </div>
      <label style={{ display: "inline-flex", alignItems: "center", gap: 8, marginTop: 10, marginBottom: 4 }}>
        <input
          style={{ width: "auto" }}
          type="checkbox"
          checked={prunePoints}
          onChange={(e) => setPrunePoints(e.target.checked)}
        />
        Also remove matching points from model and resync BRICK TTL (destructive)
      </label>
      {!prunePoints ? (
        <p className="muted" style={{ marginTop: 0 }}>
          Purge alone removes Feather for the selected site without deleting the site record. Use Delete entire site to wipe
          the model row and its Feather shards together.
        </p>
      ) : (
        <p className="muted" style={{ marginTop: 0 }}>
          With pruning enabled, points tied to removed series are dropped from the model so TTL and Feather references stay aligned.
        </p>
      )}
      <textarea readOnly value={status} placeholder="Status after an action…" style={{ marginTop: 12, minHeight: 100 }} />
    </div>
  );
}
