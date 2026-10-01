import type {
  CapabilitiesAggregate,
  CapabilitiesResponse,
  CapabilityState,
  ConnectorCapability,
  ConnectorProtocol,
} from "../api/contract";

export const PROTOCOL_WORKSPACE_TABS = [
  { id: "mqtt", label: "MQTT troubleshooting" },
  { id: "bacnet", label: "BACnet" },
  { id: "modbus", label: "Modbus" },
  { id: "haystack", label: "Haystack" },
] as const satisfies ReadonlyArray<{ id: ConnectorProtocol; label: string }>;

export type ProtocolWorkspaceId = (typeof PROTOCOL_WORKSPACE_TABS)[number]["id"];

const STATE_LABELS: Record<CapabilityState, string> = {
  disabled: "Disabled",
  not_configured: "Not configured",
  checking: "Checking",
  ready: "Ready",
  degraded: "Degraded",
  unreachable: "Unreachable",
  auth_failure: "Authentication failed",
  incompatible: "Incompatible",
  stale: "Stale",
  unknown: "Unknown",
};

const STATE_PRIORITY: CapabilityState[] = [
  "ready",
  "degraded",
  "checking",
  "unreachable",
  "auth_failure",
  "incompatible",
  "stale",
  "disabled",
  "not_configured",
  "unknown",
];

export interface ProtocolCapabilityStatus {
  protocol: ProtocolWorkspaceId;
  label: string;
  state: CapabilityState;
  stateLabel: string;
  reason: string;
  evidenceCount: number;
  configuredCount: number;
  observedCount: number;
  readyCount: number;
  sourceHealth: CapabilityState[];
  connectionStates: CapabilityState[];
  durableStates: CapabilityState[];
}

function normalizeState(value: unknown): CapabilityState {
  if (typeof value === "string" && value in STATE_LABELS) {
    return value as CapabilityState;
  }
  return "unknown";
}

function protocolMatches(
  connector: ConnectorCapability,
  protocol: ProtocolWorkspaceId,
): boolean {
  return connector.protocol === protocol;
}

interface ConnectorEvidence {
  connector: ConnectorCapability;
  upstreamState?: CapabilityState;
}

function connectorEvidence(
  aggregate: CapabilitiesAggregate,
  protocol: ProtocolWorkspaceId,
): ConnectorEvidence[] {
  const evidence: ConnectorEvidence[] = [];
  if (aggregate.central) {
    evidence.push(
      ...(aggregate.central.connectors ?? [])
        .filter((connector) => protocolMatches(connector, protocol))
        .map((connector) => ({ connector })),
    );
  }
  for (const upstream of aggregate.upstreams ?? []) {
    if (!upstream.hello) continue;
    const upstreamState = normalizeState(upstream.state);
    evidence.push(
      ...(upstream.hello.connectors ?? [])
        .filter((connector) => protocolMatches(connector, protocol))
        .map((connector) => ({ connector, upstreamState })),
    );
  }
  return evidence;
}

function effectiveState(evidence: ConnectorEvidence): CapabilityState {
  const { connector, upstreamState } = evidence;
  if (!connector.compiled) return "incompatible";
  if (!connector.enabled) return "disabled";
  if (!connector.configured) return "not_configured";
  if (upstreamState && !["ready", "unknown"].includes(upstreamState)) {
    return upstreamState;
  }
  return normalizeState(connector.readiness);
}

function chooseState(states: CapabilityState[]): CapabilityState {
  if (states.length === 0) return "not_configured";
  const unique = new Set(states);
  if (unique.has("ready") && unique.size > 1) return "degraded";
  return STATE_PRIORITY.find((state) => unique.has(state)) ?? "unknown";
}

function reasonFor(
  state: CapabilityState,
  evidenceCount: number,
  configuredCount: number,
  readyCount: number,
): string {
  if (evidenceCount === 0) {
    return "No connector capability is configured for this protocol.";
  }
  if (state === "degraded" && readyCount > 0) {
    return "Connector capability reports mixed readiness; some configured sources need attention.";
  }
  if (state === "ready") {
    return "A configured connector reports runtime readiness. Protocol reads remain out of scope here.";
  }
  if (state === "not_configured") {
    return "The authenticated capability response reports no configured connector for this protocol.";
  }
  if (configuredCount === 0) {
    return "The connector is present in the capability response but is not configured.";
  }
  return `The configured connector reports ${STATE_LABELS[state].toLowerCase()}.`;
}

export function summarizeProtocolCapabilities(
  aggregate: CapabilitiesAggregate | null | undefined,
): ProtocolCapabilityStatus[] {
  return PROTOCOL_WORKSPACE_TABS.map(({ id, label }) => {
    const evidence = aggregate ? connectorEvidence(aggregate, id) : [];
    const states = evidence.map(effectiveState);
    const state = chooseState(states);
    const configuredCount = evidence.filter(({ connector }) => connector.configured).length;
    const readyCount = states.filter((item) => item === "ready").length;
    const sourceHealth = evidence.map(({ connector }) => normalizeState(connector.source_health));
    const connectionStates = evidence.map(({ connector }) => normalizeState(connector.mqtt_connection));
    const durableStates = evidence.map(({ connector }) => normalizeState(connector.durable_delivery));
    return {
      protocol: id,
      label,
      state,
      stateLabel: STATE_LABELS[state],
      reason: reasonFor(state, evidence.length, configuredCount, readyCount),
      evidenceCount: evidence.length,
      configuredCount,
      observedCount: readyCount,
      readyCount,
      sourceHealth,
      connectionStates,
      durableStates,
    };
  });
}

export function capabilityResponseAggregate(
  response: CapabilitiesResponse,
): CapabilitiesAggregate {
  if (!response || response.ok !== true) {
    throw new Error("Central capability status is unavailable");
  }
  if (!response.connector_capabilities) {
    throw new Error("Central did not return protocol capability status");
  }
  return response.connector_capabilities;
}
