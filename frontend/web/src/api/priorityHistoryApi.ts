import { apiFetch } from "./client";
import { newRequestId } from "./requestId";
import type { InventoryScope } from "./inventoryApi";
import type { PublicReadValue, ReadPrioritySlot, ReadValueState } from "./connectorReadApi";

export const PRIORITY_SCAN_CONTRACT_V1 = "openfdd.connector.priority_scan.v1";
export const PRIORITY_HISTORY_MAX_PAGE_SIZE = 100;

export interface PriorityHistoryTarget {
  device_instance: number;
  object_type: string;
  object_instance: number;
}

export interface PriorityHistoryRecord {
  sequence: number;
  target: PriorityHistoryTarget;
  label?: string | null;
  snapshot: {
    device_instance: number;
    object_type: string;
    object_instance: number;
    slots: ReadPrioritySlot[];
    state: "supported" | "unsupported" | "unknown";
    observed_at: string;
  };
  source: "scheduled_scan";
}

export interface PriorityScanStatus {
  schema: typeof PRIORITY_SCAN_CONTRACT_V1;
  scope: InventoryScope;
  enabled: boolean;
  interval_secs: number;
  max_points_per_device: number;
  catch_up: false;
  read_only: true;
  discovery_enabled: false;
  writes_enabled: false;
  last_started_at?: string | null;
  last_completed_at?: string | null;
  next_due_at?: string | null;
  last_device_identity?: string | null;
  last_error?: string | null;
  records_retained: number;
}

export interface PriorityHistoryResponse {
  schema: typeof PRIORITY_SCAN_CONTRACT_V1;
  request_id: string;
  scope: InventoryScope;
  revision: string;
  captured_at: string;
  records: PriorityHistoryRecord[];
  next_cursor?: string | null;
  scanner: PriorityScanStatus;
}

export interface PriorityHistoryPageRequest {
  scope: InventoryScope;
  target?: PriorityHistoryTarget;
  pageSize?: number;
  cursor?: string;
  signal?: AbortSignal;
}

export class PriorityHistoryContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PriorityHistoryContractError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function text(value: unknown, field: string, max = 512): string {
  if (typeof value !== "string" || !value.trim() || value.length > max || [...value].some((ch) => (ch.codePointAt(0) ?? 0) < 0x20)) {
    throw new PriorityHistoryContractError(`${field} is invalid`);
  }
  return value;
}

function timestamp(value: unknown, field: string): string {
  const result = text(value, field);
  if (Number.isNaN(Date.parse(result))) throw new PriorityHistoryContractError(`${field} is invalid`);
  return result;
}

function uint(value: unknown, field: string, max = 4_194_303): number {
  if (!Number.isInteger(value) || (value as number) < 0 || (value as number) > max) {
    throw new PriorityHistoryContractError(`${field} is invalid`);
  }
  return value as number;
}

function publicValue(value: unknown): value is PublicReadValue {
  return value === null || typeof value === "boolean" || (typeof value === "number" && Number.isFinite(value)) ||
    (typeof value === "string" && value.length <= 512 && !value.includes("://") && !value.includes("@") && !/password|authorization|credential|token=/i.test(value)) ||
    (Array.isArray(value) && value.every(publicValue));
}

function scope(value: unknown): InventoryScope {
  if (!isRecord(value)) throw new PriorityHistoryContractError("scope is invalid");
  return {
    tenant_id: text(value.tenant_id, "scope.tenant_id"),
    building_id: text(value.building_id, "scope.building_id"),
    edge_id: text(value.edge_id, "scope.edge_id"),
  };
}

function sameScope(left: InventoryScope, right: InventoryScope): boolean {
  return left.tenant_id === right.tenant_id && left.building_id === right.building_id && left.edge_id === right.edge_id;
}

function target(value: unknown): PriorityHistoryTarget {
  if (!isRecord(value)) throw new PriorityHistoryContractError("target is invalid");
  return {
    device_instance: uint(value.device_instance, "target.device_instance"),
    object_type: text(value.object_type, "target.object_type", 64),
    object_instance: uint(value.object_instance, "target.object_instance"),
  };
}

function sameTarget(left: PriorityHistoryTarget, right: PriorityHistoryTarget): boolean {
  return left.device_instance === right.device_instance && left.object_instance === right.object_instance && left.object_type.toLowerCase() === right.object_type.toLowerCase();
}

function slot(value: unknown, index: number): ReadPrioritySlot {
  if (!isRecord(value)) throw new PriorityHistoryContractError(`priority slot ${index} is invalid`);
  const state = value.state;
  if (state !== "null" && state !== "value" && state !== "error" && state !== "unknown") throw new PriorityHistoryContractError(`priority slot ${index} state is invalid`);
  const level = uint(value.priority_level, `priority slot ${index}.priority_level`, 16);
  if (level < 1) throw new PriorityHistoryContractError(`priority slot ${index} level is invalid`);
  const result: ReadPrioritySlot = {
    priority_level: level,
    state: state as ReadValueState,
    type: text(value.type, `priority slot ${index}.type`, 64),
  };
  if (value.value !== undefined) {
    if (!publicValue(value.value)) throw new PriorityHistoryContractError(`priority slot ${index}.value is invalid`);
    result.value = value.value;
  }
  if (value.error !== undefined) result.error = text(value.error, `priority slot ${index}.error`, 128);
  if (state === "null" && (result.value !== undefined || result.error !== undefined)) throw new PriorityHistoryContractError(`priority slot ${index} NULL is malformed`);
  if (state === "value" && (result.value === undefined || result.error !== undefined)) throw new PriorityHistoryContractError(`priority slot ${index} value is malformed`);
  if (state === "error" && (result.value !== undefined || result.error === undefined)) throw new PriorityHistoryContractError(`priority slot ${index} error is malformed`);
  if (state === "unknown" && result.value !== undefined) throw new PriorityHistoryContractError(`priority slot ${index} unknown is malformed`);
  return result;
}

function snapshot(value: unknown, expected: PriorityHistoryTarget): PriorityHistoryRecord["snapshot"] {
  if (!isRecord(value) || uint(value.device_instance, "snapshot.device_instance") !== expected.device_instance || uint(value.object_instance, "snapshot.object_instance") !== expected.object_instance || text(value.object_type, "snapshot.object_type", 64).toLowerCase() !== expected.object_type.toLowerCase()) {
    throw new PriorityHistoryContractError("priority snapshot is not correlated to its target");
  }
  if (!Array.isArray(value.slots) || value.slots.length !== 16) {
    throw new PriorityHistoryContractError("priority snapshot must contain P1-P16 exactly once");
  }
  const state = value.state;
  if (state !== "supported" && state !== "unsupported" && state !== "unknown") throw new PriorityHistoryContractError("priority snapshot state is invalid");
  const slots = value.slots.map(slot);
  const levels = new Set(slots.map((item) => item.priority_level));
  if (levels.size !== 16 || levels.size !== slots.length) throw new PriorityHistoryContractError("priority snapshot must contain P1-P16 exactly once");
  return {
    device_instance: expected.device_instance,
    object_type: expected.object_type,
    object_instance: expected.object_instance,
    slots,
    state,
    observed_at: timestamp(value.observed_at, "snapshot.observed_at"),
  };
}

function validateStatus(value: unknown, requestedScope: InventoryScope): PriorityScanStatus {
  if (!isRecord(value) || value.schema !== PRIORITY_SCAN_CONTRACT_V1 || !sameScope(scope(value.scope), requestedScope) || value.catch_up !== false || value.read_only !== true || value.discovery_enabled !== false || value.writes_enabled !== false) {
    throw new PriorityHistoryContractError("priority scanner status is unsafe or out of scope");
  }
  const interval = uint(value.interval_secs, "scanner.interval_secs", 604_800);
  if (interval < 300 || uint(value.max_points_per_device, "scanner.max_points_per_device", 1_000) < 1) throw new PriorityHistoryContractError("priority scanner bounds are invalid");
  if (value.last_started_at != null) timestamp(value.last_started_at, "scanner.last_started_at");
  if (value.last_completed_at != null) timestamp(value.last_completed_at, "scanner.last_completed_at");
  if (value.next_due_at != null) timestamp(value.next_due_at, "scanner.next_due_at");
  if (value.last_device_identity != null) text(value.last_device_identity, "scanner.last_device_identity", 128);
  if (value.last_error != null) text(value.last_error, "scanner.last_error", 256);
  uint(value.records_retained, "scanner.records_retained", 100_000);
  return value as unknown as PriorityScanStatus;
}

function validateResponse(
  value: unknown,
  requestId: string,
  requestedScope: InventoryScope,
  pageSize: number,
  requestedTarget?: PriorityHistoryTarget,
): PriorityHistoryResponse {
  if (!isRecord(value) || value.schema !== PRIORITY_SCAN_CONTRACT_V1 || value.request_id !== requestId || !sameScope(scope(value.scope), requestedScope) || typeof value.revision !== "string" || !Array.isArray(value.records)) {
    throw new PriorityHistoryContractError("priority history response correlation failed");
  }
  const records = value.records.map((raw, index) => {
    if (!isRecord(raw) || !Number.isSafeInteger(raw.sequence) || (raw.sequence as number) < 1 || raw.source !== "scheduled_scan") throw new PriorityHistoryContractError(`priority history record ${index} is invalid`);
    const recordTarget = target(raw.target);
    if (requestedTarget && !sameTarget(recordTarget, requestedTarget)) throw new PriorityHistoryContractError("priority history record is outside target filter");
    const label = raw.label == null ? null : text(raw.label, `priority history record ${index}.label`, 128);
    return { sequence: raw.sequence as number, target: recordTarget, label, snapshot: snapshot(raw.snapshot, recordTarget), source: "scheduled_scan" as const };
  });
  if (records.length > pageSize) throw new PriorityHistoryContractError("priority history page exceeds its bound");
  const sequences = new Set(records.map((record) => record.sequence));
  if (sequences.size !== records.length) throw new PriorityHistoryContractError("priority history page contains duplicate sequences");
  if (value.next_cursor != null && records.length === 0) {
    throw new PriorityHistoryContractError("priority history continuation cursor is invalid");
  }
  const scanner = validateStatus(value.scanner, requestedScope);
  return {
    schema: PRIORITY_SCAN_CONTRACT_V1,
    request_id: requestId,
    scope: requestedScope,
    revision: text(value.revision, "revision", 128),
    captured_at: timestamp(value.captured_at, "captured_at"),
    records,
    next_cursor: value.next_cursor == null ? null : text(value.next_cursor, "next_cursor", 160),
    scanner,
  };
}

export async function fetchPriorityHistoryPage({ scope: requestedScope, target: requestedTarget, pageSize = 25, cursor, signal }: PriorityHistoryPageRequest): Promise<PriorityHistoryResponse> {
  if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > PRIORITY_HISTORY_MAX_PAGE_SIZE) throw new PriorityHistoryContractError("priority history page size is invalid");
  const requestId = newRequestId();
  const request = {
    schema: PRIORITY_SCAN_CONTRACT_V1,
    request_id: requestId,
    scope: requestedScope,
    page_size: pageSize,
    ...(cursor ? { cursor } : {}),
    ...(requestedTarget ? { target: requestedTarget } : {}),
  };
  const response = await apiFetch<unknown>(`/api/connectors/${encodeURIComponent(requestedScope.edge_id)}/priority-history`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal,
  });
  return validateResponse(response, requestId, requestedScope, pageSize, requestedTarget);
}
