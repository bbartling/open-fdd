import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import { useActiveSiteId } from "../lib/useActiveSiteId";
import { graphToFlow, newNodeId } from "../wiresheet/graphAdapter";
import WiresheetCanvas, { connectEdge, createFlowNode } from "../wiresheet/WiresheetCanvas";
import { useEdgesState, useNodesState, type Connection, type Node } from "@xyflow/react";
import type { WiresheetGraph } from "../wiresheet/types";

const GRAPH_ID = "graph:live-fdd-validation";

type Props = {
  compact?: boolean;
};

/** FDD-focused wiresheet — rule mapping to devices (used on Wiresheet Studio + Model page). */
export default function FddRuleWiresheet({ compact }: Props) {
  const siteId = useActiveSiteId();
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [graphMeta, setGraphMeta] = useState<Partial<WiresheetGraph>>({});

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  const loadGraph = useCallback(async () => {
    if (!siteId) return;
    setBusy(true);
    try {
      const qs = siteId ? `?site_id=${encodeURIComponent(siteId)}` : "";
      const graph = await fetchWiresheetGraph(GRAPH_ID, siteId);
      const flow = graphToFlow(graph);
      setNodes(flow.nodes);
      setEdges(flow.edges);
      setGraphMeta(graph);
      setStatus(`${flow.nodes.length} nodes loaded.`);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }, [siteId, setNodes, setEdges]);

  useEffect(() => {
    void loadGraph();
  }, [loadGraph]);

  const onConnect = useCallback(
    (connection: Connection) => {
      setEdges((eds) => connectEdge(eds, connection, newNodeId("e")));
    },
    [setEdges],
  );

  async function proposeFromAi() {
    setBusy(true);
    setError("");
    try {
      const out = await apiFetch<{ proposed?: unknown[]; review_status?: string }>(
        "/api/fdd-wires/propose-assignments",
        {
          method: "POST",
          body: JSON.stringify({ site_id: siteId || undefined, equipment_type: "ahu" }),
        },
      );
      setStatus(`AI proposed ${out.proposed?.length ?? 0} bindings — reload to view.`);
      await loadGraph();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={compact ? "fdd-rule-wiresheet fdd-rule-wiresheet--compact" : "fdd-rule-wiresheet"}>
      <div className="action-bar">
        <button type="button" className="secondary-btn" disabled={busy} onClick={() => void proposeFromAi()}>
          AI propose
        </button>
        <button type="button" className="secondary-btn" disabled={busy} onClick={() => void loadGraph()}>
          Reload
        </button>
        {!compact ? (
          <Link className="secondary-btn" to="/model">
            Model & assignments
          </Link>
        ) : null}
      </div>
      {error ? <p className="error-banner">{error}</p> : null}
      {status ? <p className="status-banner">{status}</p> : null}
      <div className="fdd-rule-wiresheet__canvas">
        <WiresheetCanvas
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onSelectionChange={() => undefined}
        />
      </div>
    </div>
  );
}

export function createFddNode(
  entry: { type: string; label: string; accent: string; description: string },
): Node {
  return createFlowNode(entry, newNodeId());
}
