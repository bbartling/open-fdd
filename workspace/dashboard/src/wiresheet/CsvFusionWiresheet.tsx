import { useEffect, useMemo } from "react";
import {
  Background,
  Controls,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import WiresheetNode from "./WiresheetNode";
import type { CsvDataset, MergeMode } from "../lib/csvWorkbench";

const nodeTypes = { wiresheet: WiresheetNode };

type Props = {
  datasets: CsvDataset[];
  mergeKey: string;
  mergeMode: MergeMode;
  onMergeModeChange: (mode: MergeMode) => void;
  onMergeKeyChange: (key: string) => void;
};

function buildCsvGraph(
  datasets: CsvDataset[],
  mergeKey: string,
  mergeMode: MergeMode,
): { nodes: Node[]; edges: Edge[] } {
  if (!datasets.length) {
    return { nodes: [], edges: [] };
  }

  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const fileSpacing = 100;

  datasets.forEach((ds, i) => {
    nodes.push({
      id: ds.id,
      type: "wiresheet",
      position: { x: 40, y: 40 + i * fileSpacing },
      data: {
        label: ds.name,
        nodeType: "csv_source",
        accent: "#3b6de0",
        config: {
          rows: ds.rowCount,
          columns: ds.columns.length,
          description: `${ds.rowCount.toLocaleString()} rows · ${ds.columns.length} columns`,
        },
      },
    });
  });

  const mergeId = "csv-merge-op";
  const mergeLabel = mergeMode === "append" ? "Append rows" : `Join on "${mergeKey}"`;
  nodes.push({
    id: mergeId,
    type: "wiresheet",
    position: { x: 280, y: 40 + ((datasets.length - 1) * fileSpacing) / 2 },
    data: {
      label: mergeLabel,
      nodeType: mergeMode === "append" ? "transform_join" : "transform_join",
      accent: "#7c5cbf",
      config: { merge_key: mergeKey, merge_mode: mergeMode },
    },
  });

  datasets.forEach((ds) => {
    edges.push({
      id: `e-${ds.id}-merge`,
      source: ds.id,
      target: mergeId,
      label: mergeMode === "append" ? "append" : "join",
      animated: true,
      style: { stroke: "var(--primary)", strokeWidth: 2 },
    });
  });

  nodes.push({
    id: "csv-output",
    type: "wiresheet",
    position: { x: 520, y: 40 + ((datasets.length - 1) * fileSpacing) / 2 },
    data: {
      label: datasets.length === 1 ? "Preview dataset" : "Merged dataset",
      nodeType: "datafusion_sql",
      accent: "#c9870a",
      config: { description: "Commit to historian when quality checks pass" },
    },
  });

  edges.push({
    id: "e-merge-out",
    source: mergeId,
    target: "csv-output",
    label: "feeds",
    animated: true,
    style: { stroke: "var(--primary)", strokeWidth: 2 },
  });

  return { nodes, edges };
}

/** CSV-only mini wiresheet — one source node per file, join/append merge, output dataset. */
export default function CsvFusionWiresheet({
  datasets,
  mergeKey,
  mergeMode,
  onMergeModeChange,
  onMergeKeyChange,
}: Props) {
  const graph = useMemo(
    () => buildCsvGraph(datasets, mergeKey, mergeMode),
    [datasets, mergeKey, mergeMode],
  );
  const [nodes, setNodes, onNodesChange] = useNodesState(graph.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(graph.edges);

  useEffect(() => {
    setNodes(graph.nodes);
    setEdges(graph.edges);
  }, [graph, setNodes, setEdges]);

  if (!datasets.length) {
    return (
      <div className="csv-fusion-wiresheet csv-fusion-wiresheet--empty">
        <p className="muted">Upload CSV files to build the fusion wiresheet. Each file becomes a source node.</p>
      </div>
    );
  }

  return (
    <div className="csv-fusion-wiresheet">
      <div className="csv-fusion-wiresheet__controls">
        <label className="field">
          <span className="field-label">Merge key</span>
          <input value={mergeKey} onChange={(e) => onMergeKeyChange(e.target.value)} />
        </label>
        <label className="field">
          <span className="field-label">Operation</span>
          <select value={mergeMode} onChange={(e) => onMergeModeChange(e.target.value as MergeMode)}>
            <option value="inner">Join on key</option>
            <option value="append">Append rows</option>
          </select>
        </label>
      </div>
      <div className="csv-fusion-wiresheet__canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={16} color="var(--border)" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </div>
  );
}
