import { apiFetch } from "./client";
import { newRequestId } from "./requestId";

/** The wire contract implemented by the Phase 3A connector inventory seam. */
export const CONNECTOR_INVENTORY_CONTRACT_V1 = "openfdd.connector.inventory.v1";
export const INVENTORY_MAX_PAGE_SIZE = 100;
export const DEFAULT_INVENTORY_PAGE_SIZE = 50;

export const INVENTORY_PROTOCOLS = [
  "bacnet",
  "modbus",
  "haystack",
  "rest",
  "mqtt",
] as const;

export type InventoryProtocol = (typeof INVENTORY_PROTOCOLS)[number];

export type InventoryAvailability =
  | "configured"
  | "disabled"
  | "unavailable"
  | "unknown";

export type InventoryCommandability = "supported" | "unsupported" | "unknown";

export type InventoryProvenance = "trusted_configuration" | "local_registration";

export interface InventoryScope {
  tenant_id: string;
  building_id: string;
  edge_id: string;
}

export interface ConnectorInventoryRequest {
  schema: typeof CONNECTOR_INVENTORY_CONTRACT_V1;
  request_id: string;
  scope: InventoryScope;
  protocols: InventoryProtocol[];
  page_size: number;
  cursor?: string;
}

export interface BacnetPointReference {
  kind: "bacnet";
  device_instance: number;
  object_type: string;
  object_instance: number;
  property_id: string;
}

export interface ModbusPointReference {
  kind: "modbus";
  unit_id: number;
  register: number;
  function: string;
}

export interface HaystackPointReference {
  kind: "haystack";
  id: string;
}

export interface RestPointReference {
  kind: "rest";
  device: string;
  point: string;
}

export type InventoryPointReference =
  | BacnetPointReference
  | ModbusPointReference
  | HaystackPointReference
  | RestPointReference;

export type InventoryAction =
  | "metadata_read"
  | "point_read"
  | "priority_array_read";

export interface InventoryDeviceRecord {
  kind: "device";
  device_id: string;
  protocol: InventoryProtocol;
  display_name: string;
  availability: InventoryAvailability;
  commandability: InventoryCommandability;
  actions: InventoryAction[];
}

export interface InventoryGroupRecord {
  kind: "group";
  group_id: string;
  device_id: string;
  protocol: InventoryProtocol;
  display_name: string;
  availability: InventoryAvailability;
  commandability: InventoryCommandability;
  actions: InventoryAction[];
}

export interface InventoryPointRecord {
  kind: "point";
  point_id: string;
  device_id: string;
  group_id?: string | null;
  protocol: InventoryProtocol;
  display_name: string;
  units?: string | null;
  availability: InventoryAvailability;
  commandability: InventoryCommandability;
  actions: InventoryAction[];
  reference: InventoryPointReference;
}

export type InventoryRecord =
  | InventoryDeviceRecord
  | InventoryGroupRecord
  | InventoryPointRecord;

export interface ConnectorInventoryResponse {
  schema: typeof CONNECTOR_INVENTORY_CONTRACT_V1;
  request_id: string;
  scope: InventoryScope;
  protocols: InventoryProtocol[];
  revision: string;
  captured_at: string;
  provenance: InventoryProvenance;
  records: InventoryRecord[];
  next_cursor?: string | null;
}

export interface InventoryPageRequest {
  scope: InventoryScope;
  protocols?: readonly InventoryProtocol[];
  pageSize?: number;
  cursor?: string;
  signal?: AbortSignal;
}

/** Errors from an inventory response are kept distinct from transport errors. */
export class InventoryContractError extends Error {
  readonly code = "inventory.contract";

  constructor(message: string) {
    super(message);
    this.name = "InventoryContractError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object";
}

function isProtocol(value: unknown): value is InventoryProtocol {
  return typeof value === "string" &&
    (INVENTORY_PROTOCOLS as readonly string[]).includes(value);
}

function isAvailability(value: unknown): value is InventoryAvailability {
  return value === "configured" || value === "disabled" || value === "unavailable" || value === "unknown";
}

function isCommandability(value: unknown): value is InventoryCommandability {
  return value === "supported" || value === "unsupported" || value === "unknown";
}

function isAction(value: unknown): value is InventoryAction {
  return value === "metadata_read" || value === "point_read" || value === "priority_array_read";
}

function requireText(value: unknown, field: string): string {
  if (typeof value !== "string" || value.trim() === "") {
    throw new InventoryContractError(`inventory ${field} is missing`);
  }
  return value;
}

function validateScope(scope: unknown, field = "scope"): asserts scope is InventoryScope {
  if (!isRecord(scope)) throw new InventoryContractError(`inventory ${field} is missing`);
  requireText(scope.tenant_id, `${field}.tenant_id`);
  requireText(scope.building_id, `${field}.building_id`);
  requireText(scope.edge_id, `${field}.edge_id`);
}

function sameScope(left: InventoryScope, right: InventoryScope): boolean {
  return left.tenant_id === right.tenant_id &&
    left.building_id === right.building_id &&
    left.edge_id === right.edge_id;
}

function validateActions(value: unknown, field: string): InventoryAction[] {
  if (!Array.isArray(value) || value.length > 8 || value.some((action) => !isAction(action))) {
    throw new InventoryContractError(`${field} contains an unsupported action`);
  }
  const actions = value as InventoryAction[];
  if (new Set(actions).size !== actions.length) {
    throw new InventoryContractError(`${field} contains duplicate actions`);
  }
  return actions;
}

function validatePointReference(value: unknown, protocol: InventoryProtocol, field: string): InventoryPointReference {
  if (!isRecord(value) || typeof value.kind !== "string") {
    throw new InventoryContractError(`${field} is missing`);
  }
  if (value.kind !== protocol || protocol === "mqtt") {
    throw new InventoryContractError(`${field} does not match its protocol`);
  }
  switch (value.kind) {
    case "bacnet":
      if (typeof value.device_instance !== "number" || typeof value.object_instance !== "number" ||
        typeof value.object_type !== "string" || typeof value.property_id !== "string") {
        throw new InventoryContractError(`${field} is malformed`);
      }
      return value as unknown as BacnetPointReference;
    case "modbus":
      if (typeof value.unit_id !== "number" || typeof value.register !== "number" ||
        typeof value.function !== "string") {
        throw new InventoryContractError(`${field} is malformed`);
      }
      return value as unknown as ModbusPointReference;
    case "haystack":
      requireText(value.id, `${field}.id`);
      return value as unknown as HaystackPointReference;
    case "rest":
      requireText(value.device, `${field}.device`);
      requireText(value.point, `${field}.point`);
      return value as unknown as RestPointReference;
    default:
      throw new InventoryContractError(`${field} has an unsupported kind`);
  }
}

function validateRecord(value: unknown, index: number): InventoryRecord {
  const field = `inventory records[${index}]`;
  if (!isRecord(value) || typeof value.kind !== "string" || !isProtocol(value.protocol)) {
    throw new InventoryContractError(`${field} is malformed`);
  }
  const displayName = requireText(value.display_name, `${field}.display_name`);
  const availability = value.availability;
  const commandability = value.commandability;
  if (!isAvailability(availability) || !isCommandability(commandability)) {
    throw new InventoryContractError(`${field} has an invalid status`);
  }
  const actions = validateActions(value.actions, `${field}.actions`);
  if ((availability === "disabled" || availability === "unavailable") && actions.length > 0) {
    throw new InventoryContractError(`${field} advertises actions while unavailable`);
  }
  if (value.kind === "device") {
    if (commandability !== "unknown") {
      throw new InventoryContractError(`${field} device commandability is not unknown`);
    }
    requireText(value.device_id, `${field}.device_id`);
    return {
      kind: "device",
      device_id: value.device_id as string,
      protocol: value.protocol,
      display_name: displayName,
      availability,
      commandability,
      actions,
    };
  }
  if (value.kind === "group") {
    if (commandability !== "unknown") {
      throw new InventoryContractError(`${field} group commandability is not unknown`);
    }
    requireText(value.group_id, `${field}.group_id`);
    requireText(value.device_id, `${field}.device_id`);
    return {
      kind: "group",
      group_id: value.group_id as string,
      device_id: value.device_id as string,
      protocol: value.protocol,
      display_name: displayName,
      availability,
      commandability,
      actions,
    };
  }
  if (value.kind === "point") {
    requireText(value.point_id, `${field}.point_id`);
    requireText(value.device_id, `${field}.device_id`);
    if (value.group_id != null) requireText(value.group_id, `${field}.group_id`);
    if (value.units != null && typeof value.units !== "string") {
      throw new InventoryContractError(`${field}.units is malformed`);
    }
    if (availability === "unavailable" && commandability !== "unknown") {
      throw new InventoryContractError(`${field} unavailable commandability is not unknown`);
    }
    return {
      kind: "point",
      point_id: value.point_id as string,
      device_id: value.device_id as string,
      group_id: (value.group_id as string | null | undefined) ?? undefined,
      protocol: value.protocol,
      display_name: displayName,
      units: (value.units as string | null | undefined) ?? undefined,
      availability,
      commandability,
      actions,
      reference: validatePointReference(value.reference, value.protocol, `${field}.reference`),
    };
  }
  throw new InventoryContractError(`${field} has an unsupported kind`);
}

export function inventoryRecordKey(record: InventoryRecord): string {
  if (record.kind === "device") return `device:${record.device_id}`;
  if (record.kind === "group") return `group:${record.group_id}`;
  return `point:${record.point_id}`;
}

/** Validate and narrow one response before it enters the tree reducer. */
export function validateConnectorInventoryResponse(
  value: unknown,
  request: ConnectorInventoryRequest,
): ConnectorInventoryResponse {
  if (!isRecord(value) || value.schema !== CONNECTOR_INVENTORY_CONTRACT_V1) {
    throw new InventoryContractError("inventory schema is unsupported");
  }
  const responseRequestId = requireText(value.request_id, "request_id");
  if (responseRequestId !== request.request_id) {
    throw new InventoryContractError("inventory response request correlation failed");
  }
  validateScope(value.scope);
  if (!sameScope(value.scope, request.scope)) {
    throw new InventoryContractError("inventory response scope correlation failed");
  }
  const revision = requireText(value.revision, "revision");
  const capturedAt = requireText(value.captured_at, "captured_at");
  if (value.provenance !== "trusted_configuration" && value.provenance !== "local_registration") {
    throw new InventoryContractError("inventory provenance is unsupported");
  }
  if (!Array.isArray(value.protocols) || value.protocols.some((protocol) => !isProtocol(protocol))) {
    throw new InventoryContractError("inventory protocols are malformed");
  }
  if (new Set(value.protocols).size !== value.protocols.length) {
    throw new InventoryContractError("inventory protocols contain duplicates");
  }
  const requested = new Set(request.protocols);
  const pageProtocols = value.protocols as InventoryProtocol[];
  if (pageProtocols.some((protocol) => requested.size > 0 && !requested.has(protocol))) {
    throw new InventoryContractError("inventory page is outside the protocol filter");
  }
  if (!Array.isArray(value.records) || value.records.length > request.page_size || value.records.length > INVENTORY_MAX_PAGE_SIZE) {
    throw new InventoryContractError("inventory page exceeds its bound");
  }
  const records = value.records.map((record, index) => validateRecord(record, index));
  const keys = new Set<string>();
  const actualProtocols = new Set<InventoryProtocol>();
  for (const record of records) {
    const key = inventoryRecordKey(record);
    if (keys.has(key)) throw new InventoryContractError("inventory contains duplicate record ids");
    keys.add(key);
    actualProtocols.add(record.protocol);
    if (requested.size > 0 && !requested.has(record.protocol)) {
      throw new InventoryContractError("inventory record is outside the protocol filter");
    }
  }
  if (actualProtocols.size !== pageProtocols.length || [...actualProtocols].some((protocol) => !pageProtocols.includes(protocol))) {
    throw new InventoryContractError("inventory response protocols do not match its page");
  }
  if (value.next_cursor != null && (typeof value.next_cursor !== "string" || value.next_cursor.trim() === "")) {
    throw new InventoryContractError("inventory continuation cursor is malformed");
  }
  if (value.next_cursor != null && records.length === 0) {
    throw new InventoryContractError("inventory empty pages cannot continue");
  }
  return {
    schema: CONNECTOR_INVENTORY_CONTRACT_V1,
    request_id: responseRequestId,
    scope: value.scope,
    protocols: pageProtocols,
    revision,
    captured_at: capturedAt,
    provenance: value.provenance,
    records,
    next_cursor: value.next_cursor as string | null | undefined,
  };
}

function validatePageSize(value: number): number {
  if (!Number.isInteger(value) || value < 1 || value > INVENTORY_MAX_PAGE_SIZE) {
    throw new InventoryContractError(`inventory page_size must be between 1 and ${INVENTORY_MAX_PAGE_SIZE}`);
  }
  return value;
}

function normalizeProtocols(protocols: readonly InventoryProtocol[] | undefined): InventoryProtocol[] {
  const next = [...(protocols ?? [])];
  if (new Set(next).size !== next.length) {
    throw new InventoryContractError("inventory protocol filter contains duplicates");
  }
  if (next.some((protocol) => !isProtocol(protocol))) {
    throw new InventoryContractError("inventory protocol filter is unsupported");
  }
  return next;
}

export function buildConnectorInventoryRequest({
  scope,
  protocols,
  pageSize = DEFAULT_INVENTORY_PAGE_SIZE,
  cursor,
}: Omit<InventoryPageRequest, "signal">): ConnectorInventoryRequest {
  validateScope(scope);
  const request: ConnectorInventoryRequest = {
    schema: CONNECTOR_INVENTORY_CONTRACT_V1,
    request_id: newRequestId(),
    scope,
    protocols: normalizeProtocols(protocols),
    page_size: validatePageSize(pageSize),
  };
  if (cursor != null) request.cursor = cursor;
  return request;
}

/** Fetch exactly one opaque-cursor page through central's authenticated API. */
export async function fetchConnectorInventoryPage(
  options: InventoryPageRequest,
): Promise<ConnectorInventoryResponse> {
  const request = buildConnectorInventoryRequest(options);
  const edge = encodeURIComponent(options.scope.edge_id);
  const response = await apiFetch<unknown>(`/api/connectors/${edge}/inventory`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal: options.signal,
  });
  return validateConnectorInventoryResponse(response, request);
}
