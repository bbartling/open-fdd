/** Inline legend for Niagara point tree badges. */
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
        <span className="badge muted-badge">read-only</span>
        <span className="bacnet-tree-legend-desc">Writes and overrides are not implemented (OT-safe)</span>
      </span>
    </div>
  );
}
