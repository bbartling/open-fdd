/** Inline legend for Niagara point tree badges (matches BACnet tree legend). */
export default function NiagaraTreeLegend() {
  return (
    <div className="bacnet-tree-legend" aria-label="Niagara tree badge legend">
      <span className="bacnet-tree-legend-title">Legend</span>
      <span className="bacnet-tree-legend-item">
        <span className="badge pv-badge">72.5</span>
        <span className="bacnet-tree-legend-desc">Live value from poll or on-demand read</span>
      </span>
      <span className="bacnet-tree-legend-item">
        <span className="badge poll-badge">⏱ polling</span>
        <span className="bacnet-tree-legend-desc">Background poll enabled for this station</span>
      </span>
      <span className="bacnet-tree-legend-item">
        <span className="badge commandable-badge">cmd</span>
        <span className="bacnet-tree-legend-desc">Writable on the station — supervisory writes are not enabled (OT-safe)</span>
      </span>
    </div>
  );
}
