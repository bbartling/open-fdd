import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiFetch } from "../api/client";
import {
  readConnectorTarget,
  type ConnectorReadResult,
} from "../api/connectorReadApi";
import {
  fetchPriorityHistoryPage,
  type PriorityHistoryRecord,
  type PriorityHistoryResponse,
} from "../api/priorityHistoryApi";
import { getStoredActiveTenant } from "../api/tenantApi";
import {
  type ConnectorInventoryResponse,
  type InventoryPointReference,
  type InventoryProtocol,
  type InventoryRecord,
  type InventoryScope,
} from "../api/inventoryApi";
import { useConnectorInventory } from "../hooks/useConnectorInventory";
import {
  buildInventoryTree,
  flattenVisibleInventoryTree,
  nodeIsExpandable,
  type InventoryTreeModel,
  type InventoryTreeNode,
} from "../lib/inventoryTree";
import { useSessionQuery } from "../session";
import { Button, InlineAlert } from "./widgets";

interface TenantListResponse {
  ok?: boolean;
  active_tenant_id?: string | null;
  buildings_visible?: string[];
  tenants?: Array<{ id: string; name: string; building_ids?: string[] }>;
}

interface EdgeListResponse {
  ok?: boolean;
  edges?: Array<{ edge_id: string; site_id?: string | null; has_telemetry?: boolean }>;
}

interface ScopeSnapshot {
  loading: boolean;
  error: string | null;
  tenantId: string | null;
  buildings: string[];
  edges: Array<{ edge_id: string; site_id: string; has_telemetry?: boolean }>;
  buildingId: string | null;
  edgeId: string | null;
  scope: InventoryScope | null;
}

function normalizeId(value: string | null | undefined): string {
  return (value ?? "").trim();
}

function useInventoryScope(capabilityEdgeIds: readonly string[]): ScopeSnapshot & {
  setBuilding: (buildingId: string) => void;
  setEdge: (edgeId: string) => void;
} {
  const { query, setQuery } = useSessionQuery();
  const [tenantResponse, setTenantResponse] = useState<TenantListResponse | null>(null);
  const [edgeResponse, setEdgeResponse] = useState<EdgeListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchParams, setSearchParams] = useSearchParamsCompat();
  const previousBuilding = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void Promise.all([
      apiFetch<TenantListResponse>("/api/tenants"),
      apiFetch<EdgeListResponse>("/api/edges"),
    ])
      .then(([tenants, edges]) => {
        if (cancelled) return;
        setTenantResponse(tenants);
        setEdgeResponse(edges);
      })
      .catch((reason) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const tenantId = useMemo(() => {
    const listed = tenantResponse?.tenants ?? [];
    const active = normalizeId(tenantResponse?.active_tenant_id);
    const stored = normalizeId(getStoredActiveTenant());
    const candidate = active || stored;
    return candidate && listed.some((tenant) => normalizeId(tenant.id) === candidate)
      ? candidate
      : null;
  }, [tenantResponse]);

  const buildings = useMemo(() => {
    if (!tenantId || !tenantResponse) return [];
    const tenant = (tenantResponse.tenants ?? []).find((item) => normalizeId(item.id) === tenantId);
    const declared = (tenant?.building_ids ?? []).map(normalizeId).filter(Boolean);
    const visible = (tenantResponse.buildings_visible ?? []).map(normalizeId).filter(Boolean);
    return [...new Set([...declared, ...visible])].sort((left, right) => left.localeCompare(right));
  }, [tenantId, tenantResponse]);

  const requestedBuilding = normalizeId(query.siteId);
  const buildingId = buildings.includes(requestedBuilding) ? requestedBuilding : null;
  const edges = useMemo(() => {
    const registered = (edgeResponse?.edges ?? [])
      .map((edge) => ({
      edge_id: normalizeId(edge.edge_id),
      site_id: normalizeId(edge.site_id),
      has_telemetry: edge.has_telemetry,
      }))
      .filter((edge) => edge.edge_id && edge.site_id && edge.site_id === buildingId);
    const known = new Set(registered.map((edge) => edge.edge_id));
    for (const rawEdgeId of capabilityEdgeIds) {
      const edgeId = normalizeId(rawEdgeId);
      if (edgeId && !known.has(edgeId)) {
        // Capability upstreams are authenticated connector candidates. Their
        // building binding is intentionally enforced by central when the
        // operator submits the explicit scope.
        registered.push({ edge_id: edgeId, site_id: "", has_telemetry: false });
        known.add(edgeId);
      }
    }
    return registered.sort((left, right) => left.edge_id.localeCompare(right.edge_id));
  }, [buildingId, capabilityEdgeIds, edgeResponse]);
  const requestedEdge = normalizeId(searchParams.get("edge"));
  const edgeId = edges.some((edge) => edge.edge_id === requestedEdge) ? requestedEdge : null;

  useEffect(() => {
    const previous = previousBuilding.current;
    previousBuilding.current = buildingId;
    if (previous === null || previous === buildingId || !searchParams.has("edge")) return;
    const next = new URLSearchParams(searchParams);
    next.delete("edge");
    setSearchParams(next, { replace: true });
  }, [buildingId, searchParams, setSearchParams]);

  useEffect(() => {
    if (!requestedEdge || edgeId || !edgeResponse || !buildingId) return;
    const next = new URLSearchParams(searchParams);
    next.delete("edge");
    setSearchParams(next, { replace: true });
  }, [buildingId, edgeId, edgeResponse, requestedEdge, searchParams, setSearchParams]);

  const setBuilding = useCallback((nextBuilding: string) => {
    const next = normalizeId(nextBuilding);
    setQuery({ siteId: next, equipment: "" }, true);
    const params = new URLSearchParams(searchParams);
    params.delete("edge");
    setSearchParams(params, { replace: true });
  }, [searchParams, setQuery, setSearchParams]);

  const setEdge = useCallback((nextEdge: string) => {
    const next = normalizeId(nextEdge);
    const allowed = edges.some((edge) => edge.edge_id === next);
    const params = new URLSearchParams(searchParams);
    if (allowed) params.set("edge", next);
    else params.delete("edge");
    setSearchParams(params, { replace: true });
  }, [edges, searchParams, setSearchParams]);

  const scope = tenantId && buildingId && edgeId
    ? { tenant_id: tenantId, building_id: buildingId, edge_id: edgeId }
    : null;
  return { loading, error, tenantId, buildings, edges, buildingId, edgeId, scope, setBuilding, setEdge };
}

/** Small adapter keeps this component testable without coupling scope state to OperationsPage. */
function useSearchParamsCompat(): [URLSearchParams, (next: URLSearchParams, options?: { replace?: boolean }) => void] {
  // Imported lazily through the router hook in a wrapper below. This function
  // is replaced at module load by the hook implementation to keep the scope
  // picker independent from the page's protocol query parameters.
  return useRouterSearchParams();
}

import { useSearchParams as useRouterSearchParams } from "react-router";

function ScopePicker({ snapshot }: { snapshot: ScopeSnapshot & { setBuilding: (id: string) => void; setEdge: (id: string) => void } }) {
  return (
    <section className="inventory-scope" aria-labelledby="inventory-scope-heading" data-testid="inventory-scope">
      <h3 id="inventory-scope-heading">Inventory scope</h3>
      <div className="inventory-scope__controls">
        <label htmlFor="inventory-tenant">Authenticated tenant</label>
        <select id="inventory-tenant" value={snapshot.tenantId ?? ""} disabled aria-describedby="inventory-scope-help">
          <option value="">Select a tenant</option>
          {snapshot.tenantId ? <option value={snapshot.tenantId}>{snapshot.tenantId}</option> : null}
        </select>
        <label htmlFor="inventory-building">Active building</label>
        <select
          id="inventory-building"
          data-testid="inventory-building"
          value={snapshot.buildingId ?? ""}
          disabled={snapshot.loading || snapshot.buildings.length === 0}
          onChange={(event) => snapshot.setBuilding(event.target.value)}
        >
          <option value="">Select a building</option>
          {snapshot.buildings.map((building) => <option key={building} value={building}>{building}</option>)}
        </select>
        <label htmlFor="inventory-edge">Authorized edge</label>
        <select
          id="inventory-edge"
          data-testid="inventory-edge"
          value={snapshot.edgeId ?? ""}
          disabled={!snapshot.buildingId || snapshot.edges.length === 0}
          onChange={(event) => snapshot.setEdge(event.target.value)}
        >
          <option value="">Select an edge</option>
          {snapshot.edges.map((edge) => <option key={edge.edge_id} value={edge.edge_id}>{edge.edge_id}</option>)}
        </select>
      </div>
      <p id="inventory-scope-help" className="muted">
        Choose the authenticated tenant, active building, and an authorized edge before loading inventory.
      </p>
      {snapshot.error ? <InlineAlert id="inventory-scope-error" variant="danger" testId="inventory-scope-error">{snapshot.error}</InlineAlert> : null}
      {!snapshot.loading && !snapshot.error && !snapshot.tenantId ? (
        <InlineAlert id="inventory-scope-auth" variant="info" testId="inventory-scope-auth">No authenticated tenant scope is available.</InlineAlert>
      ) : null}
      {!snapshot.loading && snapshot.tenantId && snapshot.buildings.length === 0 ? (
        <InlineAlert id="inventory-scope-building" variant="info" testId="inventory-scope-building">No authorized buildings are available for this tenant.</InlineAlert>
      ) : null}
      {!snapshot.loading && snapshot.buildingId && snapshot.edges.length === 0 ? (
        <InlineAlert id="inventory-scope-edge" variant="info" testId="inventory-scope-edge">No authorized edge is registered for this building.</InlineAlert>
      ) : null}
    </section>
  );
}

function availabilityLabel(value: InventoryRecord["availability"]): string {
  return value.replaceAll("_", " ");
}

function commandabilityLabel(value: InventoryRecord["commandability"]): string {
  return value.replaceAll("_", " ");
}

function referenceFields(reference: InventoryPointReference): Array<[string, string]> {
  switch (reference.kind) {
    case "bacnet":
      return [
        ["Reference kind", "BACnet"],
        ["Device instance", String(reference.device_instance)],
        ["Object type", reference.object_type],
        ["Object instance", String(reference.object_instance)],
        ["Property", reference.property_id],
      ];
    case "modbus":
      return [
        ["Reference kind", "Modbus"],
        ["Unit", String(reference.unit_id)],
        ["Register", String(reference.register)],
        ["Function", reference.function],
      ];
    case "haystack":
      return [["Reference kind", "Haystack"], ["Source ref", reference.id]];
    case "rest":
      return [["Reference kind", "REST"], ["Device", reference.device], ["Point", reference.point]];
  }
}

function InventoryDetails({
  node,
  provenance,
  capturedAt,
}: {
  node: InventoryTreeNode | null;
  provenance: ConnectorInventoryResponse["provenance"] | null;
  capturedAt: string | null;
}) {
  if (!node) {
    return <section className="inventory-details" data-testid="inventory-details-empty"><h3>Details</h3><p className="muted">Select a device, group, or point.</p></section>;
  }
  const record = node.record;
  const fields: Array<[string, string]> = [
    ["ID", record.kind === "device" ? record.device_id : record.kind === "group" ? record.group_id : record.point_id],
    ["Protocol", record.protocol],
    ["Name", record.display_name],
    ["Availability", availabilityLabel(record.availability)],
    ["Provenance", provenance?.replaceAll("_", " ") ?? "unknown"],
    ["Captured", capturedAt ?? "unknown"],
    ["Commandability", commandabilityLabel(record.commandability)],
  ];
  if (record.kind !== "device") fields.push(["Device", record.device_id]);
  if (record.kind === "point") {
    if (record.group_id) fields.push(["Group", record.group_id]);
    if (record.units) fields.push(["Units", record.units]);
    for (const field of referenceFields(record.reference)) fields.push(field);
  }
  return (
    <section className="inventory-details" aria-labelledby="inventory-details-heading" data-testid="inventory-details">
      <h3 id="inventory-details-heading">Details</h3>
      <dl>
        {fields.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
      </dl>
      <p className="muted">Actions: {record.actions.length ? record.actions.join(", ") : "none reported"}</p>
    </section>
  );
}

function InventoryReadPanel({
  node,
  scope,
}: {
  node: InventoryTreeNode | null;
  scope: InventoryScope;
}) {
  const [loading, setLoading] = useState<"point" | "priority" | null>(null);
  const [result, setResult] = useState<ConnectorReadResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const readController = useRef<AbortController | null>(null);
  const readGeneration = useRef(0);
  const loadingRef = useRef<"point" | "priority" | null>(null);
  const point = node?.record.kind === "point" && node.record.reference.kind === "bacnet"
    ? node.record
    : null;
  const canReadPoint = Boolean(point?.actions.includes("point_read"));
  const canReadPriority = Boolean(point?.actions.includes("priority_array_read"));
  const pointTargetKey = point?.reference.kind === "bacnet"
    ? `${point.reference.device_instance}:${point.reference.object_type}:${point.reference.object_instance}:${point.reference.property_id}:${point.actions.join(",")}`
    : "";

  useEffect(() => {
    readController.current?.abort();
    readController.current = null;
    loadingRef.current = null;
    readGeneration.current += 1;
    setLoading(null);
    setResult(null);
    setError(null);
    return () => {
      readController.current?.abort();
      readController.current = null;
      loadingRef.current = null;
      readGeneration.current += 1;
    };
  }, [pointTargetKey, node?.key, scope.building_id, scope.edge_id, scope.tenant_id]);

  if (!point || (!canReadPoint && !canReadPriority)) return null;
  const run = async (kind: "point" | "priority") => {
    if (loadingRef.current) return;
    const controller = new AbortController();
    const requestGeneration = readGeneration.current + 1;
    readGeneration.current = requestGeneration;
    readController.current = controller;
    loadingRef.current = kind;
    setLoading(kind);
    setError(null);
    setResult(null);
    const reference = point.reference;
    if (reference.kind !== "bacnet") {
      loadingRef.current = null;
      readController.current = null;
      setLoading(null);
      return;
    }
    try {
      const target = kind === "point"
        ? {
            kind: "bacnet_point" as const,
            device_instance: reference.device_instance,
            object_type: reference.object_type,
            object_instance: reference.object_instance,
            property_id: reference.property_id,
          }
        : {
            kind: "bacnet_priority_array" as const,
            device_instance: reference.device_instance,
            object_type: reference.object_type,
            object_instance: reference.object_instance,
          };
      const next = await readConnectorTarget(scope, target, controller.signal);
      if (readGeneration.current === requestGeneration && !controller.signal.aborted) {
        setResult(next);
      }
    } catch (reason) {
      if (controller.signal.aborted || (reason instanceof Error && reason.name === "AbortError")) return;
      if (readGeneration.current !== requestGeneration) return;
      const status = typeof reason === "object" && reason !== null && "status" in reason
        ? Number((reason as { status?: unknown }).status)
        : null;
      setError(status === 401 || status === 403
        ? "Connector read is not authorized for the selected scope."
        : reason instanceof Error ? reason.message : "Connector read failed");
    } finally {
      if (readGeneration.current === requestGeneration) {
        readController.current = null;
        loadingRef.current = null;
        setLoading(null);
      }
    }
  };
  return (
    <section className="inventory-read-panel" aria-labelledby="inventory-read-heading" aria-busy={loading !== null} data-testid="inventory-read-panel">
      <h3 id="inventory-read-heading">Live read</h3>
      <p className="muted">Runs once when requested. The inventory action and server authorization must both allow it.</p>
      <div className="inventory-read-panel__actions">
        {canReadPoint ? <Button id="inventory-read-point" label={loading === "point" ? "Reading…" : "Read point"} loading={loading === "point"} disabled={loading !== null} onClick={() => void run("point")} testId="inventory-read-point" /> : null}
        {canReadPriority ? <Button id="inventory-read-priority" label={loading === "priority" ? "Reading…" : "Read priority array"} loading={loading === "priority"} disabled={loading !== null} onClick={() => void run("priority")} testId="inventory-read-priority" /> : null}
      </div>
      {error ? <InlineAlert id="inventory-read-error" variant="danger" testId="inventory-read-error">{error}</InlineAlert> : null}
      {result?.kind === "point" ? (
        <dl className="inventory-read-result" role="status" data-testid="inventory-read-point-result">
          <div><dt>Value</dt><dd>{JSON.stringify(result.value)}</dd></div>
          <div><dt>Type</dt><dd>{result.type}</dd></div>
          <div><dt>Quality</dt><dd>{result.quality}</dd></div>
          <div><dt>Observed</dt><dd>{result.observed_at}</dd></div>
        </dl>
      ) : null}
      {result?.kind === "priority_array" ? (
        <div role="status" data-testid="inventory-read-priority-result">
          <p>State: {result.state} · Observed: {result.observed_at}</p>
          <table><caption>BACnet priority array</caption><thead><tr><th scope="col">Priority</th><th scope="col">State</th><th scope="col">Value</th></tr></thead><tbody>
            {result.slots.map((slot) => <tr key={slot.priority_level}><td>P{slot.priority_level}</td><td>{slot.state}</td><td>{slot.state === "value" ? JSON.stringify(slot.value) : slot.error ?? "—"}</td></tr>)}
          </tbody></table>
        </div>
      ) : null}
    </section>
  );
}

function PriorityHistoryPanel({
  point,
  scope,
}: {
  point: Extract<InventoryTreeNode["record"], { kind: "point" }> | null;
  scope: InventoryScope;
}) {
  const target = point?.reference.kind === "bacnet"
    ? {
        device_instance: point.reference.device_instance,
        object_type: point.reference.object_type,
        object_instance: point.reference.object_instance,
      }
    : null;
  const targetKey = target ? `${target.device_instance}:${target.object_type}:${target.object_instance}` : "";
  const [records, setRecords] = useState<PriorityHistoryRecord[]>([]);
  const [response, setResponse] = useState<PriorityHistoryResponse | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  const generation = useRef(0);

  useEffect(() => {
    controller.current?.abort();
    controller.current = null;
    generation.current += 1;
    setRecords([]);
    setResponse(null);
    setCursor(null);
    setLoading(false);
    setError(null);
    return () => controller.current?.abort();
  }, [scope.building_id, scope.edge_id, scope.tenant_id, targetKey]);

  if (!point || !target || !point.actions.includes("priority_array_read")) return null;

  const load = async (nextCursor: string | null = null) => {
    if (loading) return;
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    const requestGeneration = ++generation.current;
    setLoading(true);
    setError(null);
    try {
      const page = await fetchPriorityHistoryPage({ scope, target, cursor: nextCursor ?? undefined, signal: abort.signal });
      if (abort.signal.aborted || generation.current !== requestGeneration) return;
      setResponse(page);
      setRecords((previous) => nextCursor ? [...previous, ...page.records] : page.records);
      setCursor(page.next_cursor ?? null);
    } catch (reason) {
      if (abort.signal.aborted || (reason instanceof Error && reason.name === "AbortError")) return;
      if (generation.current !== requestGeneration) return;
      setError(reason instanceof Error ? reason.message : "Priority history request failed");
    } finally {
      if (generation.current === requestGeneration) {
        setLoading(false);
        controller.current = null;
      }
    }
  };

  return (
    <section className="inventory-history-panel" aria-labelledby="inventory-history-heading" data-testid="inventory-priority-history">
      <h3 id="inventory-history-heading">Priority history</h3>
      <p className="muted">Durable edge snapshots for this point. History reads do not trigger a BACnet request.</p>
      <Button id="inventory-priority-history-load" label={loading ? "Loading…" : records.length ? "Refresh history" : "Load history"} loading={loading} onClick={() => void load()} testId="inventory-priority-history-load" />
      {error ? <InlineAlert id="inventory-priority-history-error" variant="danger" testId="inventory-priority-history-error">{error}</InlineAlert> : null}
      {response ? <p className="muted" data-testid="inventory-priority-history-status">Scanner: {response.scanner.enabled ? "enabled" : "disabled"} · interval {response.scanner.interval_secs}s · retained {response.scanner.records_retained}</p> : null}
      {records.length > 0 ? (
        <div className="inventory-history-table-wrap">
          <table data-testid="inventory-priority-history-table"><caption>Recorded P1–P16 snapshots</caption><thead><tr><th scope="col">Label</th><th scope="col">Sequence</th><th scope="col">Observed</th><th scope="col">State</th><th scope="col">Active priorities</th></tr></thead><tbody>
            {records.map((record) => {
              const active = record.snapshot.slots.filter((slot) => slot.state === "value").map((slot) => `P${slot.priority_level}`).join(", ") || "none";
              return <tr key={record.sequence}><td>{record.label ?? "(unlabeled)"}</td><td>{record.sequence}</td><td>{record.snapshot.observed_at}</td><td>{record.snapshot.state}</td><td>{active}</td></tr>;
            })}
          </tbody></table>
        </div>
      ) : response && !loading ? <p className="muted" data-testid="inventory-priority-history-empty">No retained snapshots for this point.</p> : null}
      {cursor ? <Button id="inventory-priority-history-more" label="Load more" variant="secondary" onClick={() => void load(cursor)} testId="inventory-priority-history-more" /> : null}
    </section>
  );
}

interface InventoryContextMenuProps {
  node: InventoryTreeNode;
  expanded: boolean;
  onAction: (action: "details" | "copy-id" | "copy-reference" | "expand") => void;
  onEscape: () => void;
}

function InventoryContextMenu({ node, expanded, onAction, onEscape }: InventoryContextMenuProps) {
  return (
    <div
      className="inventory-context-menu"
      role="menu"
      tabIndex={-1}
      aria-label={`Actions for ${node.record.display_name}`}
      data-testid="inventory-context-menu"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          onEscape();
        }
      }}
    >
      <button type="button" role="menuitem" onClick={() => onAction("details")}>View details</button>
      <button type="button" role="menuitem" onClick={() => onAction("copy-id")}>Copy ID</button>
      {node.kind === "point" ? <button type="button" role="menuitem" onClick={() => onAction("copy-reference")}>Copy reference</button> : null}
      {nodeIsExpandable(node) ? <button type="button" role="menuitem" onClick={() => onAction("expand")}>{expanded ? "Collapse" : "Expand"}</button> : null}
    </div>
  );
}

function pointReferenceText(reference: InventoryPointReference): string {
  return reference.kind === "bacnet"
    ? `bacnet:${reference.device_instance}:${reference.object_type}:${reference.object_instance}:${reference.property_id}`
    : reference.kind === "modbus"
      ? `modbus:${reference.unit_id}:${reference.register}:${reference.function}`
      : reference.kind === "haystack"
        ? reference.id
        : `${reference.device}:${reference.point}`;
}

function copyText(value: string): void {
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    void navigator.clipboard.writeText(value);
  }
}

function InventoryTreeView({
  model,
  selectedKey,
  onSelect,
  onModelAction,
}: {
  model: InventoryTreeModel;
  selectedKey: string | null;
  onSelect: (key: string) => void;
  onModelAction: (action: "expand" | "collapse", key: string) => void;
}) {
  const initialExpanded = useMemo(() => {
    const keys = new Set<string>();
    const visit = (node: InventoryTreeNode) => {
      if (!nodeIsExpandable(node)) return;
      keys.add(node.key);
      node.children.forEach(visit);
    };
    model.roots.forEach(visit);
    return keys;
  }, [model]);
  const [expanded, setExpanded] = useState<Set<string>>(() => initialExpanded);
  const [contextKey, setContextKey] = useState<string | null>(null);
  const [contextOpen, setContextOpen] = useState(false);
  const treeRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef(new Map<string, HTMLDivElement>());
  const visible = useMemo(() => flattenVisibleInventoryTree(model, expanded), [expanded, model]);
  const contextNode = contextKey ? model.nodes.get(contextKey) ?? null : null;

  useEffect(() => {
    setExpanded((previous) => {
      const valid = new Set<string>(model.nodes.keys());
      const next = new Set([...previous].filter((key) => valid.has(key)));
      if (!previous.size) initialExpanded.forEach((key) => next.add(key));
      return next;
    });
    if (selectedKey && !model.nodes.has(selectedKey)) onSelect("");
    if (contextKey && !model.nodes.has(contextKey)) {
      setContextKey(null);
      setContextOpen(false);
    }
  }, [contextKey, initialExpanded, model, onSelect, selectedKey]);

  const focusKey = useCallback((key: string) => {
    itemRefs.current.get(key)?.focus();
  }, []);

  const selectNode = useCallback((key: string) => {
    onSelect(key);
    setContextKey(null);
    setContextOpen(false);
  }, [onSelect]);

  const closeContext = useCallback((restore = true) => {
    const key = contextKey;
    setContextOpen(false);
    setContextKey(null);
    if (restore && key) focusKey(key);
  }, [contextKey, focusKey]);

  const openContext = useCallback((node: InventoryTreeNode) => {
    selectNode(node.key);
    setContextKey(node.key);
    setContextOpen(true);
    window.requestAnimationFrame(() => {
      const menu = treeRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]');
      menu?.focus();
    });
  }, [selectNode]);

  const toggle = useCallback((key: string) => {
    setExpanded((previous) => {
      const next = new Set(previous);
      if (next.has(key)) {
        next.delete(key);
        onModelAction("collapse", key);
      } else {
        next.add(key);
        onModelAction("expand", key);
      }
      return next;
    });
  }, [onModelAction]);

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>, node: InventoryTreeNode) => {
    const index = visible.findIndex((item) => item.key === node.key);
    if (event.key === "ArrowDown" || event.key === "ArrowUp" || event.key === "Home" || event.key === "End") {
      event.preventDefault();
      const nextIndex = event.key === "ArrowDown" ? Math.min(visible.length - 1, index + 1)
        : event.key === "ArrowUp" ? Math.max(0, index - 1)
          : event.key === "Home" ? 0 : visible.length - 1;
      const next = visible[nextIndex];
      if (next) {
        selectNode(next.key);
        focusKey(next.key);
      }
      return;
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      if (nodeIsExpandable(node) && !expanded.has(node.key)) toggle(node.key);
      else if (nodeIsExpandable(node) && node.children[0]) {
        selectNode(node.children[0].key);
        focusKey(node.children[0].key);
      }
      return;
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      if (nodeIsExpandable(node) && expanded.has(node.key)) toggle(node.key);
      else if (node.parentKey) {
        selectNode(node.parentKey);
        focusKey(node.parentKey);
      }
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      selectNode(node.key);
      return;
    }
    if (event.key === "ContextMenu" || (event.key === "F10" && event.shiftKey)) {
      event.preventDefault();
      openContext(node);
      return;
    }
    if (event.key === "Escape" && contextOpen) {
      event.preventDefault();
      closeContext(true);
    }
  };

  const contextAction = (action: "details" | "copy-id" | "copy-reference" | "expand") => {
    if (!contextNode) return;
    if (action === "details") selectNode(contextNode.key);
    if (action === "copy-id") {
      const record = contextNode.record;
      copyText(record.kind === "device" ? record.device_id : record.kind === "group" ? record.group_id : record.point_id);
    }
    if (action === "copy-reference" && contextNode.record.kind === "point") copyText(pointReferenceText(contextNode.record.reference));
    if (action === "expand") toggle(contextNode.key);
    closeContext(true);
  };

  return (
    <div className="inventory-tree-wrap" ref={treeRef}>
      <div
        className="inventory-tree"
        role="tree"
        tabIndex={-1}
        aria-label="Connector inventory"
        data-testid="inventory-tree"
        onContextMenu={(event) => event.preventDefault()}
      >
        {visible.length === 0 ? <p className="muted" data-testid="inventory-tree-empty">No inventory records returned for this protocol.</p> : null}
        {visible.map((node) => {
          let depth = 1;
          let parentKey = node.parentKey;
          while (parentKey) {
            depth += 1;
            parentKey = model.parents.get(parentKey) ?? null;
          }
          const isExpanded = expanded.has(node.key);
          const isSelected = selectedKey === node.key;
          return (
            <div
              key={node.key}
              ref={(element) => { if (element) itemRefs.current.set(node.key, element); else itemRefs.current.delete(node.key); }}
              className={`inventory-treeitem${isSelected ? " is-selected" : ""}`}
              role="treeitem"
              tabIndex={isSelected || (!selectedKey && visible[0]?.key === node.key) ? 0 : -1}
              aria-level={depth}
              aria-selected={isSelected}
              aria-expanded={nodeIsExpandable(node) ? isExpanded : undefined}
              data-testid={`inventory-treeitem-${node.key}`}
              onClick={() => selectNode(node.key)}
              onKeyDown={(event) => onKeyDown(event, node)}
              onContextMenu={(event) => { event.preventDefault(); openContext(node); }}
            >
              <span className="inventory-treeitem__marker" aria-hidden>{nodeIsExpandable(node) ? (isExpanded ? "▾" : "▸") : "·"}</span>
              <span>{node.record.display_name}</span>
              <span className={`inventory-treeitem__availability inventory-treeitem__availability--${node.record.availability}`}>{availabilityLabel(node.record.availability)}</span>
            </div>
          );
        })}
      </div>
      {contextOpen && contextNode ? <InventoryContextMenu node={contextNode} expanded={expanded.has(contextNode.key)} onAction={contextAction} onEscape={() => closeContext(true)} /> : null}
    </div>
  );
}

export function ProtocolInventory({
  protocol,
  capabilityEdgeIds = [],
}: {
  protocol: InventoryProtocol;
  capabilityEdgeIds?: readonly string[];
}) {
  const snapshot = useInventoryScope(capabilityEdgeIds);
  const inventory = useConnectorInventory({ scope: snapshot.scope, protocols: [protocol], enabled: Boolean(snapshot.scope) });
  const model = useMemo(() => buildInventoryTree(inventory.records), [inventory.records]);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const selectedNode = selectedKey ? model.nodes.get(selectedKey) ?? null : null;
  const refresh = () => inventory.refresh();
  return (
    <section className="protocol-inventory" aria-labelledby="protocol-inventory-heading" data-testid="protocol-inventory">
      <h3 id="protocol-inventory-heading">{protocol} inventory</h3>
      <ScopePicker snapshot={snapshot} />
      {snapshot.scope ? (
        <>
          <div className="section-heading-row inventory-toolbar">
            <p className="muted">Inventory is a configuration projection. Select a point to see its advertised read actions.</p>
            <Button id="inventory-refresh" label={inventory.loading ? "Loading…" : "Refresh inventory"} variant="secondary" loading={inventory.loading} onClick={refresh} testId="inventory-refresh" />
          </div>
          {inventory.error ? <InlineAlert id="inventory-error" variant="danger" testId="inventory-error">{inventory.error.message}{inventory.partial ? " Some records remain visible." : ""}</InlineAlert> : null}
          {inventory.loading && inventory.records.length > 0 ? <p role="status" data-testid="inventory-partial-loading">Loading the next inventory page…</p> : null}
          {!inventory.loading && inventory.nextCursor ? (
            <div className="inventory-pagination">
              <p className="muted" role="status">Partial inventory snapshot. More records are available.</p>
              <Button id="inventory-load-more" label="Load more" variant="secondary" onClick={inventory.loadMore} testId="inventory-load-more" />
            </div>
          ) : null}
          <div className="inventory-layout">
            <InventoryTreeView model={model} selectedKey={selectedKey} onSelect={(key) => setSelectedKey(key || null)} onModelAction={() => undefined} />
            <div>
              <InventoryDetails node={selectedNode} provenance={inventory.provenance} capturedAt={inventory.capturedAt} />
              <InventoryReadPanel node={selectedNode} scope={snapshot.scope} />
              <PriorityHistoryPanel point={selectedNode?.record.kind === "point" ? selectedNode.record : null} scope={snapshot.scope} />
            </div>
          </div>
        </>
      ) : null}
    </section>
  );
}
