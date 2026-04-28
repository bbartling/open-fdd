import { useEffect, useState } from "react";
import { desktopFetch } from "../lib/api";
import { useSite } from "../contexts/site-context";

type Site = {
  id: string;
  name: string;
};

type SiteCreateResponse = Site & {
  warning?: string;
  ttl_sync_warning?: string;
  ttlWarning?: string;
  ttl_warnings?: string | string[];
  warnings?: string | string[];
};

type SiteDeleteResponse = {
  deleted_sites: number;
  deleted_equipment: number;
  deleted_points: number;
  ttl_sync_warning?: string;
  warning?: string;
  ttlWarning?: string;
  ttl_warnings?: string | string[];
  warnings?: string | string[];
};

function extractTtlWarning(payload: {
  warning?: string;
  ttl_sync_warning?: string;
  ttlWarning?: string;
  ttl_warnings?: string | string[];
  warnings?: string | string[];
}): string {
  const raw =
    payload.ttl_sync_warning
    ?? payload.ttlWarning
    ?? payload.warning
    ?? payload.ttl_warnings
    ?? payload.warnings;
  if (Array.isArray(raw)) {
    return raw.filter((item) => typeof item === "string" && item.trim().length > 0).join("; ");
  }
  return typeof raw === "string" ? raw.trim() : "";
}

export function SiteManagementPage() {
  const [sites, setSites] = useState<Site[]>([]);
  const [siteName, setSiteName] = useState("");
  const [status, setStatus] = useState("Create/delete sites here. TTL sync runs automatically.");
  const { selectedSiteId, setSelectedSiteId, refreshSites: refreshGlobalSites } = useSite();

  async function refresh() {
    try {
      const out = await refreshGlobalSites();
      setSites(out);
      if (out.length > 0 && !out.some((site) => site.id === selectedSiteId)) {
        setSelectedSiteId(out[0].id);
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function onCreate() {
    try {
      const site = await desktopFetch<SiteCreateResponse>("/sites", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: siteName.trim() || "Site" }),
      });
      const ttlWarning = extractTtlWarning(site);
      setSiteName("");
      setStatus(
        ttlWarning
          ? `Created site ${site.name} (${site.id.slice(0, 8)}). TTL warning: ${ttlWarning}`
          : `Created site ${site.name} (${site.id.slice(0, 8)}), TTL synced.`,
      );
      setSelectedSiteId(site.id);
      void refresh();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  async function onDelete(id: string) {
    try {
      const out = await desktopFetch<SiteDeleteResponse>(`/sites/${id}`, { method: "DELETE" });
      const ttlWarning = extractTtlWarning(out);
      setStatus(
        ttlWarning
          ? `Deleted site ${id.slice(0, 8)}. TTL warning: ${ttlWarning}`
          : `Deleted site ${id.slice(0, 8)}, TTL synced.`,
      );
      if (selectedSiteId === id) {
        setSelectedSiteId("");
      }
      void refresh();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <div className="stack-page">
      <section className="card">
        <h2 className="title">Site Management</h2>
        <p className="muted">Step 1 of desktop workflow: create your BRICK sites before importing local CSV files.</p>
        <div className="grid-two" style={{ marginTop: 10 }}>
          <input
            value={siteName}
            onChange={(event) => setSiteName(event.target.value)}
            placeholder="new site name"
          />
          <button onClick={() => void onCreate()}>Create site</button>
        </div>
      </section>

      <section className="card">
        <h3 style={{ marginTop: 0 }}>Existing sites</h3>
        <div className="site-list">
          {sites.map((site) => (
            <div key={site.id} className={`site-row ${selectedSiteId === site.id ? "active" : ""}`}>
              <button className="site-select" onClick={() => setSelectedSiteId(site.id)}>
                <strong>{site.name}</strong>
                <span className="muted">{site.id}</span>
              </button>
              <button className="danger-btn" onClick={() => void onDelete(site.id)}>
                Delete
              </button>
            </div>
          ))}
          {sites.length === 0 && <div className="muted">No sites yet.</div>}
        </div>
      </section>

      <section className="card">
        <h3 style={{ marginTop: 0 }}>Status</h3>
        <textarea readOnly value={status} style={{ minHeight: 90 }} />
      </section>
    </div>
  );
}
