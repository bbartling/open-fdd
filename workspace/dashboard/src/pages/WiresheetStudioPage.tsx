import { useCallback, useEffect, useMemo, useState } from "react";
import {
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
} from "@xyflow/react";
import PageHeader from "../components/PageHeader";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import { useActiveSiteId } from "../lib/useActiveSiteId";
import GlobalSearchBar from "../wiresheet/GlobalSearchBar";
import WiresheetCanvas, { connectEdge, createFlowNode } from "../wiresheet/WiresheetCanvas";
import WiresheetPalette from "../wiresheet/WiresheetPalette";
import WiresheetPropertyPanel from "../wiresheet/WiresheetPropertyPanel";
import { flowToGraph, graphToFlow, newNodeId } from "../wiresheet/graphAdapter";
import type { NodeCatalogEntry, WiresheetGraph } from "../wiresheet/types";
import { fetchWiresheetGraph } from "../wiresheet/wiresheetApi";

const DEFAULT_GRAPH_ID = "graph:live-fdd-validation";

export default function WiresheetStudioPage() {
  const siteId = useActiveSiteId();
  const [graphMeta, setGraphMeta] = useState<Partial<WiresheetGraph>>({});
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<Node | null>(null);
  const [focusNodeId, setFocusNodeId] = useState<string | null>(null);

  const initial = useMemo(() => graphToFlow({ graph_id: DEFAULT_GRAPH_ID, site_id: siteId, nodes: [], edges: [] }), [siteId]);
  const [nodes, setNodes, onNodesChange] = useNodesState(initial.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initial.edges);

  const loadGraph = useCallback(async () => {
    if (!siteId) return;
    setBusy(true);
    setError("");
    try {
      const graph = await fetchWiresheetGraph(DEFAULT_GRAPH_ID, siteId);
      const flow = graphToFlow(graph);
      setNodes(flow.nodes);
      setEdges(flow.edges);
      setGraphMeta(graph);
      setStatus(`Loaded ${flow.nodes.length} node(s), ${flow.edges.length} edge(s).`);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }, [siteId, setNodes, setEdges]);

  useEffect(() => {
    void loadGraph();
  }, [loadGraph]);

  const saveGraph = useCallback(async () => {
    if (!siteId) return;
    setBusy(true);
    setError("");
    try {
      const payload = flowToGraph(DEFAULT_GRAPH_ID, siteId, nodes, edges, graphMeta);
      const qs = siteId ? `?site_id=${encodeURIComponent(siteId)}` : "";
      await apiFetch(`/api/fdd-wires/graphs/${encodeURIComponent(DEFAULT_GRAPH_ID)}${qs}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      setStatus("Graph saved.");
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }, [siteId, nodes, edges, graphMeta]);

  const validateGraph = useCallback(async () => {
    if (!siteId) return;
    setBusy(true);
    setError("");
    try {
      const qs = siteId ? `?site_id=${encodeURIComponent(siteId)}` : "";
      const out = await apiFetch<Record<string, unknown>>(
        `/api/fdd-wires/graphs/${encodeURIComponent(DEFAULT_GRAPH_ID)}/validate${qs}`,
        { method: "POST", body: "{}" },
      );
      setStatus(typeof out.message === "string" ? out.message : out.ok ? "Validation passed." : "Validation finished.");
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }, [siteId]);

  const onConnect = useCallback(
    (connection: Connection) => {
      setEdges((eds) => connectEdge(eds, connection, newNodeId("e")));
    },
    [setEdges],
  );

  const onAddPalette = useCallback(
    (entry: NodeCatalogEntry) => {
      const node = createFlowNode(entry, newNodeId());
      setNodes((prev) => [...prev, node]);
    },
    [setNodes],
  );

  const onPatchNode = useCallback(
    (nodeId: string, patch: { label?: string; config?: Record<string, unknown> }) => {
      setNodes((prev) =>
        prev.map((n) => {
          if (n.id !== nodeId) return n;
          const data = n.data as Record<string, unknown>;
          return {
            ...n,
            data: {
              ...data,
              ...(patch.label !== undefined ? { label: patch.label } : {}),
              ...(patch.config !== undefined
                ? { config: { ...(data.config as object), ...patch.config } }
                : {}),
            },
          };
        }),
      );
      if (selected?.id === nodeId) {
        setSelected((cur) => {
          if (!cur || cur.id !== nodeId) return cur;
          const data = cur.data as Record<string, unknown>;
          return {
            ...cur,
            data: {
              ...data,
              ...(patch.label !== undefined ? { label: patch.label } : {}),
              ...(patch.config !== undefined
                ? { config: { ...(data.config as object), ...patch.config } }
                : {}),
            },
          };
        });
      }
    },
    [selected, setNodes],
  );

  useEffect(() => {
    if (!focusNodeId) return;
    setSelected(nodes.find((n) => n.id === focusNodeId) ?? null);
  }, [focusNodeId, nodes]);

  return (
    <div className="page wiresheet-page">
      <PageHeader
        title="FDD Wiresheet Studio"
        subtitle="Rule mapping graph — Haystack points → FDD inputs → SQL rules → faults. AI proposes bindings; you review and save."
        meta={
          <div className="wiresheet-toolbar">
            <button type="button" className="primary-btn" disabled={busy} onClick={() => void saveGraph()}>
              Save graph
            </button>
            <button type="button" className="secondary-btn" disabled={busy} onClick={() => void validateGraph()}>
              Validate
            </button>
            <button type="button" className="secondary-btn" disabled={busy} onClick={() => void loadGraph()}>
              Reload
            </button>
            <a className="secondary-btn" href="/model">
              Model & FDD assignments
            </a>
            <a className="secondary-btn" href="/sql-fdd">
              SQL FDD editor
            </a>
          </div>
        }
      />

      {error ? <p className="error-banner">{error}</p> : null}
      {status ? <p className="status-banner">{status}</p> : null}

      <GlobalSearchBar nodes={nodes} onFocusNode={setFocusNodeId} />

      <div className="wiresheet-layout">
        <WiresheetPalette
          onAdd={onAddPalette}
          fddMode
          categories={["Data Sources", "Haystack", "Fault Detection", "Outputs"]}
        />
        <WiresheetCanvas
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onSelectionChange={({ nodes: sel }) => setSelected(sel[0] ?? null)}
        />
        <WiresheetPropertyPanel node={selected} onPatch={onPatchNode} />
      </div>
    </div>
  );
}
