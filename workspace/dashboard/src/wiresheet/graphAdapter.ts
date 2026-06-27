import type { Edge, Node } from "@xyflow/react";
import type { WiresheetEdge, WiresheetGraph, WiresheetNode } from "./types";
import { accentForNodeType } from "./nodeCatalog";

export function graphToFlow(graph: WiresheetGraph): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = (graph.nodes ?? []).map((n) => wireNodeToFlow(n));
  const edges: Edge[] = (graph.edges ?? []).map((e) => wireEdgeToFlow(e));
  return { nodes, edges };
}

export function flowToGraph(
  graphId: string,
  siteId: string,
  nodes: Node[],
  edges: Edge[],
  base?: Partial<WiresheetGraph>,
): WiresheetGraph {
  return {
    schema_version: base?.schema_version ?? "1.0.0",
    graph_id: graphId,
    site_id: siteId,
    review_status: base?.review_status ?? "draft",
    nodes: nodes.map(flowNodeToWire),
    edges: edges.map(flowEdgeToWire),
    validation_errors: base?.validation_errors ?? [],
    validation_warnings: base?.validation_warnings ?? [],
    execution_status: base?.execution_status ?? "idle",
    updated_at: base?.updated_at,
  };
}

function wireNodeToFlow(n: WiresheetNode): Node {
  const accent = accentForNodeType(n.type);
  return {
    id: n.id,
    type: "wiresheet",
    position: n.position ?? { x: 0, y: 0 },
    data: {
      label: n.label,
      nodeType: n.type,
      config: n.config ?? {},
      validation: n.validation,
      accent,
    },
  };
}

function flowNodeToWire(n: Node): WiresheetNode {
  const data = n.data as {
    label?: string;
    nodeType?: string;
    config?: Record<string, unknown>;
    validation?: { status?: string; message?: string };
  };
  return {
    id: n.id,
    type: data.nodeType ?? "comment",
    label: data.label ?? n.id,
    position: n.position,
    config: data.config,
    validation: data.validation,
    source: "human_created",
  };
}

function wireEdgeToFlow(e: WiresheetEdge): Edge {
  return {
    id: e.id,
    source: e.from,
    target: e.to,
    label: e.type,
    animated: e.type === "feeds" || e.type === "rule_input",
    style: { stroke: "var(--primary)", strokeWidth: 2 },
  };
}

function flowEdgeToWire(e: Edge): WiresheetEdge {
  return {
    id: e.id,
    type: (typeof e.label === "string" ? e.label : "feeds") as WiresheetEdge["type"],
    from: e.source,
    to: e.target,
  };
}

export function newNodeId(prefix = "n"): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
}
