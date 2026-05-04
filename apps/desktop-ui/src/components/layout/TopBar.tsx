import { useSite } from "../../contexts/site-context";

export function TopBar() {
  const { sites, selectedSiteId, setSelectedSiteId, refreshSites } = useSite();

  return (
    <header className="topbar">
      <div>
        <h1 className="topbar-title">Open-FDD Desktop</h1>
        <p className="topbar-subtitle">
          AFDD-style workflow shell for local large-file desktop iteration—this bridge-mode dashboard is for trusted machines
          or private networks only, not hardened for the public internet.
        </p>
      </div>
      <div className="topbar-actions">
        <label className="inline-label" htmlFor="site-selector">
          Active site
        </label>
        <select
          id="site-selector"
          value={selectedSiteId}
          onChange={(event) => setSelectedSiteId(event.target.value)}
          className="site-selector"
        >
          {sites.length === 0 && <option value="">No sites</option>}
          {sites.map((site) => (
            <option key={site.id} value={site.id} title={site.id}>
              {site.name}
            </option>
          ))}
        </select>
        <button type="button" className="secondary-btn" onClick={() => void refreshSites()}>
          Refresh
        </button>
      </div>
    </header>
  );
}
