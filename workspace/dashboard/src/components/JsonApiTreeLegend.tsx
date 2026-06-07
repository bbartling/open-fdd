export default function JsonApiTreeLegend() {
  return (
    <div className="bacnet-tree-legend" aria-label="JSON API tree badge legend">
      <span className="bacnet-tree-legend-title">Legend</span>
      <span className="bacnet-tree-legend-item">
        <span className="badge pv-badge">value</span>
        <span className="bacnet-tree-legend-desc">Extracted JSON field from poll or on-demand Refresh</span>
      </span>
      <span className="bacnet-tree-legend-item">
        <span className="badge poll-badge">⏱ 5 min</span>
        <span className="bacnet-tree-legend-desc">HTTP GET/POST on interval — feather source=json_api</span>
      </span>
      <span className="bacnet-tree-legend-item">
        <span className="badge muted-badge">idle</span>
        <span className="bacnet-tree-legend-desc">Not polling — right-click Refresh or enable poll</span>
      </span>
    </div>
  );
}
