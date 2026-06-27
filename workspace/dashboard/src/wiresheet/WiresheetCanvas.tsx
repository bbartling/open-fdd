import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  addEdge,
  type Connection,
  type Edge,
  type Node,
  type OnNodesChange,
  type OnEdgesChange,
  type OnSelectionChangeFunc,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import WiresheetNode from "./WiresheetNode";

const nodeTypes = { wiresheet: WiresheetNode };

type Props = {
  nodes: Node[];
  edges: Edge[];
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onConnect: (connection: Connection) => void;
  onSelectionChange: OnSelectionChangeFunc;
};

export default function WiresheetCanvas({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onConnect,
  onSelectionChange,
}: Props) {
  return (
    <div className="wiresheet-canvas-wrap">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onSelectionChange={onSelectionChange}
        nodeTypes={nodeTypes}
        fitView
        proOptions={{ hideAttribution: true }}
        className="wiresheet-flow"
      >
        <Background gap={20} color="var(--border)" />
        <Controls />
        <MiniMap
          pannable
          zoomable
          nodeColor={(n) => (n.data as { accent?: string }).accent ?? "#888"}
        />
      </ReactFlow>
    </div>
  );
}

export function connectEdge(edges: Edge[], connection: Connection, edgeId: string): Edge[] {
  return addEdge(
    {
      ...connection,
      id: edgeId,
      label: "feeds",
      animated: true,
      style: { stroke: "var(--primary)", strokeWidth: 2 },
    },
    edges,
  );
}

export function createFlowNode(
  entry: { type: string; label: string; accent: string; description: string },
  id: string,
  position?: { x: number; y: number },
): Node {
  return {
    id,
    type: "wiresheet",
    position: position ?? { x: 120 + Math.random() * 280, y: 80 + Math.random() * 200 },
    data: {
      label: entry.label,
      nodeType: entry.type,
      accent: entry.accent,
      config: { description: entry.description },
    },
  };
}
