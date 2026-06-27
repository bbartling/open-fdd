import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";

type WiresheetNodeData = {
  label: string;
  nodeType: string;
  accent: string;
  validation?: { status?: string; message?: string };
};

function WiresheetNodeComponent({ data, selected }: NodeProps) {
  const d = data as WiresheetNodeData;
  const status = d.validation?.status;
  return (
    <div
      className={`wiresheet-node${selected ? " wiresheet-node--selected" : ""}`}
      style={{ borderColor: d.accent }}
    >
      <Handle type="target" position={Position.Left} className="wiresheet-handle" />
      <div className="wiresheet-node__type" style={{ color: d.accent }}>
        {d.nodeType.replace(/_/g, " ")}
      </div>
      <div className="wiresheet-node__label">{d.label}</div>
      {status ? (
        <div className={`wiresheet-node__status wiresheet-node__status--${status}`}>{status}</div>
      ) : null}
      <Handle type="source" position={Position.Right} className="wiresheet-handle" />
    </div>
  );
}

export default memo(WiresheetNodeComponent);
