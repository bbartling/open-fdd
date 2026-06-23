type Props = {
  siteName: string;
  siteDetail?: string;
  equipmentCount?: number;
  pointCount?: number;
  activeFaults: number;
  faultBreakdown: string;
  live?: boolean;
  lastSyncLabel?: string;
};

export default function BuildingStrip({
  siteName,
  siteDetail,
  equipmentCount,
  pointCount,
  activeFaults,
  faultBreakdown,
  live,
  lastSyncLabel,
}: Props) {
  return (
    <section className="bis-building-strip">
      <div className="bis-b-name">
        <div className="bis-b-icon" aria-hidden>
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
            <rect x="4" y="3" width="16" height="18" rx="1" stroke="currentColor" strokeWidth="1.8" />
            <rect x="7" y="6" width="2.5" height="2.5" fill="currentColor" />
            <rect x="11.5" y="6" width="2.5" height="2.5" fill="currentColor" />
            <rect x="7" y="10.5" width="2.5" height="2.5" fill="currentColor" opacity="0.6" />
            <rect x="11.5" y="10.5" width="2.5" height="2.5" fill="currentColor" />
          </svg>
        </div>
        <div>
          <h2>{siteName}</h2>
          {siteDetail ? <p>{siteDetail}</p> : null}
        </div>
      </div>
      <div className="bis-b-stat">
        <div className="label">Equipment</div>
        <div className="value">{equipmentCount != null ? equipmentCount : "—"}</div>
        <div className="sub">BRICK model</div>
      </div>
      <div className="bis-b-stat">
        <div className="label">Points</div>
        <div className="value">{pointCount != null ? pointCount.toLocaleString() : "—"}</div>
        <div className="sub">mapped to historian</div>
      </div>
      <div className="bis-b-stat">
        <div className="label">Telemetry</div>
        <div className="value">
          {live ? (
            <span className="bis-live-inline">
              <span className="bis-live-dot" /> Live
            </span>
          ) : (
            "Polling"
          )}
        </div>
        <div className="sub">{lastSyncLabel || "BACnet poll cycle"}</div>
      </div>
      <div className="bis-b-stat">
        <div className="label">Active issues</div>
        <div className={`value ${activeFaults > 0 ? "bis-warn-value" : ""}`}>{activeFaults}</div>
        <div className="sub">{faultBreakdown || "all clear"}</div>
      </div>
    </section>
  );
}
