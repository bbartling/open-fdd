import { useEffect, useState } from "react";
import { desktopFetch } from "../lib/api";

type Site = {
  id: string;
  name: string;
};

export function ConfigPage() {
  const [sites, setSites] = useState<Site[]>([]);
  const [siteName, setSiteName] = useState("");
  const [status, setStatus] = useState("Create/delete sites here. TTL sync runs automatically.");

  async function refresh() {
    try {
      const out = await desktopFetch<Site[]>("/sites");
      setSites(out);
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function onCreate() {
    try {
      const site = await desktopFetch<Site>("/sites", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: siteName }),
      });
      setSiteName("");
      setStatus(`Created site ${site.name} (${site.id.slice(0, 8)}), TTL synced.`);
      void refresh();
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    }
  }

  async function onDelete(id: string) {
    try {
      await desktopFetch(`/sites/${id}`, { method: "DELETE" });
      setStatus(`Deleted site ${id.slice(0, 8)}, TTL synced.`);
      void refresh();
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="card">
      <h2 className="title">OpenFDD Config</h2>
      <p style={{ color: "var(--muted)" }}>
        This tab is site-first for desktop: manage BRICK sites, and keep the TTL model current automatically.
      </p>
      <div className="grid-two" style={{ marginBottom: 10 }}>
        <input value={siteName} onChange={(e) => setSiteName(e.target.value)} placeholder="new site name" />
        <button onClick={() => void onCreate()}>Create site</button>
      </div>
      <div style={{ border: "1px solid var(--border)", borderRadius: 10, overflow: "hidden" }}>
        {sites.map((site) => (
          <div
            key={site.id}
            style={{
              display: "grid",
              gridTemplateColumns: "1fr auto",
              padding: "10px 12px",
              borderBottom: "1px solid var(--border)",
              alignItems: "center",
              gap: 8,
            }}
          >
            <div>
              <strong>{site.name}</strong>
              <div style={{ color: "var(--muted)", fontSize: 12 }}>{site.id}</div>
            </div>
            <button onClick={() => void onDelete(site.id)}>Delete</button>
          </div>
        ))}
        {sites.length === 0 && <div style={{ padding: 12, color: "var(--muted)" }}>No sites yet.</div>}
      </div>
      <textarea readOnly value={status} style={{ marginTop: 10, minHeight: 72 }} />
    </div>
  );
}
