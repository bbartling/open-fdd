import BacnetTreeLegend from "./BacnetTreeLegend";
import ModbusTreeLegend from "./ModbusTreeLegend";
import JsonApiTreeLegend from "./JsonApiTreeLegend";

export default function UnifiedDriverTreeLegend() {
  return (
    <div className="unified-driver-legend">
      <BacnetTreeLegend />
      <ModbusTreeLegend />
      <JsonApiTreeLegend />
      <div className="bacnet-tree-legend" aria-label="Haystack tree badge legend">
        <span className="bacnet-tree-legend-title">Haystack</span>
        <span className="bacnet-tree-legend-item">
          <span className="badge poll-badge">polling</span>
          <span className="bacnet-tree-legend-desc">Point value refreshed on poll cadence</span>
        </span>
        <span className="bacnet-tree-legend-item">
          <span className="badge mapped-badge">mapped</span>
          <span className="bacnet-tree-legend-desc">Linked to BACnet/Modbus ref in Open-FDD model</span>
        </span>
        <span className="bacnet-tree-legend-item">
          <span className="badge muted-badge">unmapped</span>
          <span className="bacnet-tree-legend-desc">Haystack point not yet bound to a driver ref</span>
        </span>
      </div>
    </div>
  );
}
