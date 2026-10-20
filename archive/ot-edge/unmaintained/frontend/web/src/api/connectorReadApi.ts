import { apiFetch } from "./client";
import { newRequestId } from "./requestId";
import type { InventoryScope } from "./inventoryApi";

export const CONNECTOR_READ_CONTRACT_V1 = "openfdd.connector.read.v1";
export const CAPABILITIES_CONTRACT_V1 = "openfdd.connector.capabilities.v1";

export interface BacnetPointTarget {
  kind: "bacnet_point";
  device_instance: number;
  object_type: string;
  object_instance: number;
  property_id: string;
}

export interface BacnetPriorityArrayTarget {
  kind: "bacnet_priority_array";
  device_instance: number;
  object_type: string;
  object_instance: number;
}

export type ConnectorReadTarget = BacnetPointTarget | BacnetPriorityArrayTarget;
export type ReadValueState = "null" | "value" | "error" | "unknown";
export type PublicReadValue = null | boolean | number | string | PublicReadValue[];

export interface ReadPointResult extends Omit<BacnetPointTarget, "kind"> {
  kind: "point";
  type: string;
  value: PublicReadValue;
  quality: "good" | "bad";
  observed_at: string;
}

export interface ReadPrioritySlot {
  priority_level: number;
  state: ReadValueState;
  type: string;
  value?: PublicReadValue;
  error?: string;
}

export interface ReadPriorityArrayResult extends Omit<BacnetPriorityArrayTarget, "kind"> {
  kind: "priority_array";
  slots: ReadPrioritySlot[];
  state: "supported" | "unsupported" | "unknown";
  observed_at: string;
}

export type ConnectorReadResult = ReadPointResult | ReadPriorityArrayResult;

const MAX_BACNET_INSTANCE = 4_194_303;

export class ConnectorReadContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConnectorReadContractError";
  }
}

export class ConnectorReadError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "ConnectorReadError";
    this.code = code;
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function hasControlCharacter(value: string): boolean {
  return [...value].some((character) => {
    const code = character.codePointAt(0) ?? 0;
    return code <= 0x1f || (code >= 0x7f && code <= 0x9f);
  });
}

function text(value: unknown, field: string): string {
  if (typeof value !== "string" || !value.trim() || value.length > 512 || hasControlCharacter(value)) {
    throw new ConnectorReadContractError(`${field} is invalid`);
  }
  return value;
}

function publicMessage(value: unknown, field: string, max: number): string {
  if (typeof value !== "string" || value.length > max || hasControlCharacter(value)) {
    throw new ConnectorReadContractError(`${field} is invalid`);
  }
  return value;
}

function token(value: unknown, field: string, max = 512): string {
  const result = text(value, field);
  if (result.length > max) {
    throw new ConnectorReadContractError(`${field} is invalid`);
  }
  if (!/^[A-Za-z0-9_.-]+$/u.test(result)) {
    throw new ConnectorReadContractError(`${field} is invalid`);
  }
  return result;
}

function timestamp(value: unknown, field: string): string {
  const result = text(value, field);
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/u.test(result) || Number.isNaN(Date.parse(result))) {
    throw new ConnectorReadContractError(`${field} is invalid`);
  }
  return result;
}

function uint(value: unknown, field: string, max = MAX_BACNET_INSTANCE): number {
  if (!Number.isInteger(value) || (value as number) < 0 || (value as number) > max) {
    throw new ConnectorReadContractError(`${field} is invalid`);
  }
  return value as number;
}

function validateScope(scope: InventoryScope): void {
  if (!isObject(scope)) throw new ConnectorReadContractError("scope is invalid");
  for (const field of ["tenant_id", "building_id", "edge_id"] as const) {
    const value = text(scope[field], `scope.${field}`);
    if (value.includes("/") || value.includes("\\") || value.includes("..")) {
      throw new ConnectorReadContractError(`scope.${field} is invalid`);
    }
  }
}

function validateTarget(target: ConnectorReadTarget): void {
  if (!isObject(target)) throw new ConnectorReadContractError("target is invalid");
  switch (target.kind) {
    case "bacnet_point":
      uint(target.device_instance, "device_instance");
      token(target.object_type, "object_type", 64);
      uint(target.object_instance, "object_instance");
      token(target.property_id, "property_id", 64);
      return;
    case "bacnet_priority_array":
      uint(target.device_instance, "device_instance");
      token(target.object_type, "object_type", 64);
      uint(target.object_instance, "object_instance");
      return;
    default:
      throw new ConnectorReadContractError("target kind is unsupported");
  }
}

function sameScope(left: unknown, right: InventoryScope): boolean {
  return isObject(left) && left.tenant_id === right.tenant_id && left.building_id === right.building_id && left.edge_id === right.edge_id;
}

function publicValue(value: unknown): value is PublicReadValue {
  return value === null || typeof value === "boolean" || (typeof value === "number" && Number.isFinite(value)) ||
    (typeof value === "string" && value.length <= 512 && !hasControlCharacter(value) && !value.includes("://") && !value.includes("@") && !/password|authorization|credential|token=/i.test(value)) ||
    (Array.isArray(value) && value.every(publicValue));
}

function validatePoint(value: Record<string, unknown>, target: BacnetPointTarget): ReadPointResult {
  if (value.kind !== "point" || uint(value.device_instance, "device_instance") !== target.device_instance ||
      uint(value.object_instance, "object_instance") !== target.object_instance ||
      token(value.object_type, "object_type").toLowerCase() !== target.object_type.toLowerCase() ||
      token(value.property_id, "property_id").toLowerCase() !== target.property_id.toLowerCase() ||
      (value.quality !== "good" && value.quality !== "bad") || !publicValue(value.value)) {
    throw new ConnectorReadContractError("point result does not match its request");
  }
  token(value.type, "point type", 64);
  timestamp(value.observed_at, "point observed_at");
  return value as unknown as ReadPointResult;
}

function validatePriority(value: Record<string, unknown>, target: BacnetPriorityArrayTarget): ReadPriorityArrayResult {
  if (value.kind !== "priority_array" || uint(value.device_instance, "device_instance") !== target.device_instance ||
      uint(value.object_instance, "object_instance") !== target.object_instance ||
      token(value.object_type, "object_type").toLowerCase() !== target.object_type.toLowerCase() ||
      !["supported", "unsupported", "unknown"].includes(String(value.state)) || !Array.isArray(value.slots) || value.slots.length !== 16) {
    throw new ConnectorReadContractError("priority-array result does not match its request");
  }
  timestamp(value.observed_at, "priority observed_at");
  const levels = new Set<number>();
  for (const raw of value.slots) {
    if (!isObject(raw)) throw new ConnectorReadContractError("priority slot is invalid");
    const level = uint(raw.priority_level, "priority_level", 16);
    if (level < 1 || levels.has(level) || !["null", "value", "error", "unknown"].includes(String(raw.state))) {
      throw new ConnectorReadContractError("priority slots must be unique P1-P16");
    }
    levels.add(level);
    token(raw.type, "priority type", 64);
    if (raw.value !== undefined && !publicValue(raw.value)) throw new ConnectorReadContractError("priority value is invalid");
    if (raw.error !== undefined) {
      const error = text(raw.error, "priority error");
      if (error.length > 128) throw new ConnectorReadContractError("priority error is invalid");
    }
    if (raw.state === "value" && (raw.value === undefined || raw.error !== undefined)) throw new ConnectorReadContractError("value priority slot is malformed");
    if (raw.state === "null" && (raw.value !== undefined || raw.error !== undefined)) throw new ConnectorReadContractError("NULL priority slot is malformed");
    if (raw.state === "error" && (raw.value !== undefined || raw.error === undefined)) throw new ConnectorReadContractError("error priority slot is malformed");
    if (raw.state === "unknown" && raw.value !== undefined) throw new ConnectorReadContractError("unknown priority slot is malformed");
  }
  return value as unknown as ReadPriorityArrayResult;
}

export async function readConnectorTarget(scope: InventoryScope, target: ConnectorReadTarget, signal?: AbortSignal): Promise<ConnectorReadResult> {
  validateScope(scope);
  validateTarget(target);
  const request = { schema: CONNECTOR_READ_CONTRACT_V1, request_id: newRequestId(), scope, target };
  const response = await apiFetch<unknown>(`/api/connectors/${encodeURIComponent(scope.edge_id)}/read`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal,
  });
  if (!isObject(response) || response.schema !== CONNECTOR_READ_CONTRACT_V1 || response.request_id !== request.request_id ||
      !sameScope(response.scope, scope)) {
    throw new ConnectorReadContractError("connector read response correlation failed");
  }
  if (response.ok === false) {
    if (response.capability_contract != null || response.result != null || !isObject(response.error)) {
      throw new ConnectorReadContractError("connector read failure envelope is malformed");
    }
    const code = token(response.error.code, "read error code", 64);
    const message = publicMessage(response.error.message, "read error message", 128);
    throw new ConnectorReadError(code, message);
  }
  if (response.ok !== true || response.capability_contract !== CAPABILITIES_CONTRACT_V1 ||
      response.error != null || !isObject(response.result)) {
    throw new ConnectorReadContractError("connector read response is malformed");
  }
  return target.kind === "bacnet_point"
    ? validatePoint(response.result, target)
    : validatePriority(response.result, target);
}
