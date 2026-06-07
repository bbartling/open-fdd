/** Inline legend for Modbus register tree badges (matches BACnet tree styling). */
export default function ModbusTreeLegend() {
  return (
    <div className="bacnet-tree-legend" aria-label="Modbus tree badge legend">
      <span className="bacnet-tree-legend-title">Legend</span>
      <span className="bacnet-tree-legend-item">
        <span className="badge pv-badge">72.5</span>
        <span className="bacnet-tree-legend-desc">Register value from poll or on-demand Refresh value</span>
      </span>
      <span className="bacnet-tree-legend-item">
        <span className="badge poll-badge">⏱ 1 min</span>
        <span className="bacnet-tree-legend-desc">Background poll enabled — same worker pattern as BACnet</span>
      </span>
      <span className="bacnet-tree-legend-item">
        <span className="badge muted-badge">idle</span>
        <span className="bacnet-tree-legend-desc">Not polling — right-click Refresh value or enable poll</span>
      </span>
    </div>
  );
}
