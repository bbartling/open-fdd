import { describe, expect, it } from "vitest";
import {
  capabilityResponseAggregate,
  summarizeProtocolCapabilities,
} from "./protocolCapabilities";

function connector(
  protocol: string,
  readiness: string,
  configured = true,
) {
  return {
    protocol,
    compiled: true,
    configured,
    enabled: configured,
    readiness,
    source_health: readiness,
    mqtt_connection: "not_configured",
    durable_delivery: "unknown",
  };
}

describe("protocol capability summaries", () => {
  it("uses exact protocol evidence and reports unconfigured protocols honestly", () => {
    const [mqtt, bacnet, modbus, haystack] = summarizeProtocolCapabilities({
      central: { schema: "hello", connectors: [connector("mqtt", "ready")] },
      upstreams: [
        {
          state: "ready",
          hello: { schema: "hello", connectors: [connector("bacnet", "checking")] },
        },
      ],
    });

    expect(mqtt.state).toBe("ready");
    expect(mqtt.evidenceCount).toBe(1);
    expect(bacnet.state).toBe("checking");
    expect(modbus.state).toBe("not_configured");
    expect(modbus.reason).toMatch(/No connector capability/);
    expect(haystack.state).toBe("not_configured");
  });

  it("marks mixed connector readiness as degraded instead of claiming ready", () => {
    const [mqtt] = summarizeProtocolCapabilities({
      central: {
        connectors: [connector("mqtt", "ready"), connector("mqtt", "unreachable")],
      },
    });

    expect(mqtt.state).toBe("degraded");
    expect(mqtt.stateLabel).toBe("Degraded");
    expect(mqtt.readyCount).toBe(1);
  });

  it("does not claim a cached upstream is ready when its edge state is stale", () => {
    const bacnet = summarizeProtocolCapabilities({
      upstreams: [
        {
          state: "stale",
          hello: { connectors: [connector("bacnet", "ready")] },
        },
      ],
    }).find((status) => status.protocol === "bacnet");

    expect(bacnet?.state).toBe("stale");
    expect(bacnet?.stateLabel).toBe("Stale");
  });

  it("requires the authenticated aggregate before rendering protocol status", () => {
    expect(() =>
      capabilityResponseAggregate({
        ok: true,
        contract: {} as never,
        capabilities: {},
      }),
    ).toThrow(/protocol capability status/);
  });
});
