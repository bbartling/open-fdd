import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchConnectorInventoryPage,
  inventoryRecordKey,
  type ConnectorInventoryResponse,
  type InventoryPageRequest,
  type InventoryProtocol,
  type InventoryRecord,
  type InventoryScope,
} from "../api/inventoryApi";

export type InventoryLoadStatus = "idle" | "loading" | "ready" | "partial" | "error";

export interface ConnectorInventoryState {
  records: InventoryRecord[];
  revision: string | null;
  provenance: ConnectorInventoryResponse["provenance"] | null;
  capturedAt: string | null;
  nextCursor: string | null;
  status: InventoryLoadStatus;
  loading: boolean;
  partial: boolean;
  error: Error | null;
}

export interface UseConnectorInventoryOptions {
  scope: InventoryScope | null;
  protocols: readonly InventoryProtocol[];
  pageSize?: number;
  enabled?: boolean;
}

export interface UseConnectorInventoryResult extends ConnectorInventoryState {
  refresh: () => void;
  loadMore: () => void;
}

const EMPTY_STATE: ConnectorInventoryState = {
  records: [],
  revision: null,
  provenance: null,
  capturedAt: null,
  nextCursor: null,
  status: "idle",
  loading: false,
  partial: false,
  error: null,
};

function scopeKey(scope: InventoryScope | null): string {
  if (!scope) return "";
  return `${scope.tenant_id}\u0000${scope.building_id}\u0000${scope.edge_id}`;
}

function mergeRecords(
  current: InventoryRecord[],
  additions: InventoryRecord[],
): InventoryRecord[] {
  const seen = new Set(current.map(inventoryRecordKey));
  const merged = [...current];
  for (const record of additions) {
    const key = inventoryRecordKey(record);
    if (seen.has(key)) {
      throw new Error("connector inventory repeated a record across pages");
    }
    seen.add(key);
    merged.push(record);
  }
  return merged;
}

interface LoadArgs {
  scope: InventoryScope;
  protocols: readonly InventoryProtocol[];
  pageSize: number;
  cursor: string | null;
  baseRecords: InventoryRecord[];
  baseRevision: string | null;
  baseProvenance: ConnectorInventoryResponse["provenance"] | null;
  baseCapturedAt: string | null;
  replace: boolean;
  requestedCursors: Set<string>;
}

/**
 * Fetch exactly one bounded inventory page. Cursors are opaque: the browser
 * only repeats the token supplied by central and never parses or manufactures
 * one. Additional pages require an explicit operator action.
 */
async function loadPages(
  args: LoadArgs,
  signal: AbortSignal,
  onProgress: (state: Partial<ConnectorInventoryState>) => void,
): Promise<void> {
  const cursor = args.cursor;
  let records = args.replace ? [] : [...args.baseRecords];

  try {
    const pageRequest: InventoryPageRequest = {
      scope: args.scope,
      protocols: args.protocols,
      pageSize: args.pageSize,
      ...(cursor ? { cursor } : {}),
      signal,
    };
    const page = await fetchConnectorInventoryPage(pageRequest);
    if (signal.aborted) return;
    if (args.baseRevision && page.revision !== args.baseRevision) {
      throw new Error("connector inventory revision changed during pagination");
    }
    if (args.baseProvenance && page.provenance !== args.baseProvenance) {
      throw new Error("connector inventory provenance changed during pagination");
    }
    records = mergeRecords(records, page.records);
    const nextCursor = page.next_cursor ?? null;
    if (nextCursor && args.requestedCursors.has(nextCursor)) {
      throw new Error("connector inventory repeated a continuation cursor");
    }
    if (nextCursor) args.requestedCursors.add(nextCursor);
    onProgress({
      records: [...records],
      revision: args.baseRevision ?? page.revision,
      provenance: args.baseProvenance ?? page.provenance,
      capturedAt: page.captured_at,
      nextCursor,
      status: nextCursor ? "partial" : "ready",
      loading: false,
      partial: Boolean(nextCursor),
      error: null,
    });
  } catch (error) {
    if (signal.aborted) return;
    const normalized = error instanceof Error ? error : new Error(String(error));
    onProgress({
      records: [...records],
      revision: args.baseRevision,
      provenance: args.baseProvenance,
      capturedAt: args.baseCapturedAt,
      nextCursor: cursor,
      status: records.length > 0 ? "partial" : "error",
      loading: false,
      partial: records.length > 0,
      error: normalized,
    });
  }
}

export function useConnectorInventory({
  scope,
  protocols,
  pageSize = 50,
  enabled = true,
}: UseConnectorInventoryOptions): UseConnectorInventoryResult {
  const [state, setState] = useState<ConnectorInventoryState>(EMPTY_STATE);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const requestedCursors = useRef(new Set<string>());
  const stateRef = useRef(state);
  stateRef.current = state;

  const protocolKey = useMemo(() => protocols.join(","), [protocols]);
  const currentScopeKey = scopeKey(scope);
  const requestedProtocols = useMemo(
    () => protocolKey ? protocolKey.split(",") as InventoryProtocol[] : [],
    [protocolKey],
  );
  const tenantId = scope?.tenant_id ?? "";
  const buildingId = scope?.building_id ?? "";
  const edgeId = scope?.edge_id ?? "";
  const requestedScope = useMemo(
    () => (tenantId && buildingId && edgeId
      ? { tenant_id: tenantId, building_id: buildingId, edge_id: edgeId }
      : null),
    [buildingId, edgeId, tenantId],
  );
  const requestKey = `${currentScopeKey}\u0000${protocolKey}\u0000${pageSize}\u0000${enabled ? "on" : "off"}`;

  const begin = useCallback((replace: boolean, cursor: string | null = null) => {
    if (!enabled || !requestedScope || !requestedScope.tenant_id.trim() || !requestedScope.building_id.trim() || !requestedScope.edge_id.trim()) {
      controller.current?.abort();
      generation.current += 1;
      setState(EMPTY_STATE);
      return;
    }
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    const runGeneration = ++generation.current;
    const snapshot = stateRef.current;
    if (replace) requestedCursors.current = new Set<string>();
    if (cursor) requestedCursors.current.add(cursor);
    const baseRecords = replace ? [] : snapshot.records;
    const baseRevision = replace ? null : snapshot.revision;
    const baseProvenance = replace ? null : snapshot.provenance;
    const baseCapturedAt = replace ? null : snapshot.capturedAt;
    setState({
      records: baseRecords,
      revision: baseRevision,
      provenance: baseProvenance,
      capturedAt: baseCapturedAt,
      nextCursor: cursor,
      status: "loading",
      loading: true,
      partial: false,
      error: null,
    });
    void loadPages(
      {
        scope: requestedScope,
        protocols: requestedProtocols,
        pageSize,
        cursor,
        baseRecords,
        baseRevision,
        baseProvenance,
        baseCapturedAt,
        replace,
        requestedCursors: requestedCursors.current,
      },
      abort.signal,
      (patch) => {
        if (generation.current !== runGeneration || abort.signal.aborted) return;
        setState((previous) => ({ ...previous, ...patch }));
      },
    );
  }, [enabled, pageSize, requestedProtocols, requestedScope]);

  useEffect(() => {
    void requestKey;
    begin(true);
    return () => {
      controller.current?.abort();
      generation.current += 1;
    };
  }, [begin, requestKey]);

  const refresh = useCallback(() => begin(true), [begin]);
  const loadMore = useCallback(() => {
    const next = stateRef.current.nextCursor;
    if (!next || stateRef.current.loading || !requestedScope) return;
    begin(false, next);
  }, [begin, requestedScope]);

  return { ...state, refresh, loadMore };
}

/** Name used by consumers that want to emphasize the authorization boundary. */
export const useScopedConnectorInventory = useConnectorInventory;
