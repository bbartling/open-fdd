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
      await desktopFetch(`/sites/${encodeURIComponent(effectiveSiteId)}`, { method: "DELETE" });
      await siteContext.refreshSites();
      setSiteId("");
      setStatus(
        `Deleted site "${siteName}" from the stored model (equipment/points for that site removed; BRICK TTL resynced). `
          + "Feather timeseries files for that site are not removed by this action alone — use Purge timeseries first if you need disk cleared.",
      );
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="card">
      <h2 className="title">Data &amp; model maintenance</h2>
      <p className="muted">
        Feather files (timeseries) and the JSON model (sites, equipment, points) are separate layers. Purge targets Feather
        storage; optional pruning removes model points that referenced purged series and resyncs TTL. Delete entire site
        removes the site and related model rows only — purge first if you want timeseries files gone too.
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
          Default purge is site-scoped timeseries only; data model (sites/equipment/points) is retained. Use Delete entire site
          for a full model wipe for that site (then purge if you also need Feather data removed).
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
