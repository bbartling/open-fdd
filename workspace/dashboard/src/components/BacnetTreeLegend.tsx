/** Inline legend for Devices & points tree badges (polling, overrides, P8). */
export default function BacnetTreeLegend() {
  return (
    <div className="bacnet-tree-legend" aria-label="BACnet tree badge legend">
      <span className="bacnet-tree-legend-title">Legend</span>
      <span className="bacnet-tree-legend-item">
        <span className="badge poll-badge">polling</span>
        <span className="bacnet-tree-legend-desc">Point enabled in poll driver — present value from scheduled BACnet reads</span>
      </span>
      <span className="bacnet-tree-legend-item">
        <span className="badge override-badge">⚠ ovrd</span>
        <span className="bacnet-tree-legend-desc">Priority-array override at any level (hourly supervisory scan)</span>
      </span>
      <span className="bacnet-tree-legend-item">
        <span className="badge operator-override-badge">P8×1</span>
        <span className="bacnet-tree-legend-desc">Operator manual override at BACnet priority 8 — shown on dashboard as P8 alert</span>
      </span>
      <span className="bacnet-tree-legend-item">
        <span className="badge commandable-badge">cmd</span>
        <span className="bacnet-tree-legend-desc">Commandable point — right-click to read priority array or refresh PV on demand</span>
      </span>
    </div>
  );
}
