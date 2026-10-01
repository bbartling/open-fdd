import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { OperationsPage } from "../pages/OperationsPage";
import { ProtocolWorkspace } from "./ProtocolWorkspace";

const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn() }));

vi.mock("../api/client", () => ({
  apiFetch,
  apiFetchBlob: vi.fn(),
}));

vi.mock("./AppShell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("./SitesPanel", () => ({
  SitesPanel: () => <div data-testid="sites-panel-preserved">Sites inventory</div>,
}));

vi.mock("../api/authApi", () => ({
  getStoredToken: vi.fn(() => null),
}));

vi.mock("../api/tenantApi", () => ({
  getStoredActiveTenant: vi.fn(() => null),
}));

function capabilityResponse() {
  return {
    ok: true,
    contract: {},
    capabilities: {},
    connector_capabilities: {
      central: {
        schema: "openfdd.connector.capabilities.v1",
        connectors: [
          {
            protocol: "mqtt",
            compiled: true,
            configured: true,
            enabled: true,
            readiness: "ready",
            source_health: "ready",
            mqtt_connection: "ready",
            durable_delivery: "ready",
          },
        ],
      },
      upstreams: [
        {
          state: "ready",
          hello: {
            schema: "openfdd.connector.capabilities.v1",
            connectors: [
              {
                protocol: "bacnet",
                compiled: true,
                configured: true,
                enabled: true,
                readiness: "checking",
                source_health: "checking",
                mqtt_connection: "not_configured",
                durable_delivery: "unknown",
              },
              {
                protocol: "haystack",
                compiled: true,
                configured: true,
                enabled: true,
                readiness: "auth_failure",
                source_health: "auth_failure",
                mqtt_connection: "not_configured",
                durable_delivery: "unknown",
              },
            ],
          },
        },
      ],
    },
  };
}

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location-search">{location.search}</output>;
}

function mockOperationsApi() {
  apiFetch.mockImplementation(async (path: string) => {
    if (path === "/api/capabilities") return capabilityResponse();
    if (path === "/api/mqtt/monitor") {
      return {
        connected: true,
        subscriptions: [],
        received_messages: 0,
        reconnects: 0,
        errors: 0,
        buffer_capacity: 10,
        recent_messages: [],
        recent_events: [],
        test_publish_enabled: false,
      };
    }
    if (path === "/api/ingest/stats") return { ingest_ok: 3, ingest_reject: 0 };
    if (path === "/api/edges") return { edges: [] };
    if (path === "/api/afdd/scheduler/status") {
      return {
        ok: true,
        config: {
          mode: "bulk",
          interval_minutes: 60,
          lookback_value: 1,
          lookback_unit: "days",
        },
        recent_cycles: [],
      };
    }
    if (path === "/api/data-management/summary" || path === "/api/fdd/results") return {};
    return {};
  });
}

describe("ProtocolWorkspace", () => {
  beforeEach(() => {
    apiFetch.mockReset();
  });

  it("shows loading then capability-driven protocol states", async () => {
    let resolveRequest: ((value: unknown) => void) | undefined;
    apiFetch.mockReturnValueOnce(new Promise((resolve) => { resolveRequest = resolve; }));
    render(
      <MemoryRouter>
        <ProtocolWorkspace protocol="bacnet" onProtocolChange={vi.fn()} />
      </MemoryRouter>,
    );

    expect(screen.getByTestId("protocol-status-loading")).toBeTruthy();
    resolveRequest?.(capabilityResponse());
    expect((await screen.findByTestId("protocol-state-bacnet")).textContent).toContain("Checking");
    expect(screen.getByTestId("protocol-state-mqtt").textContent).toContain("Ready");
    expect(screen.getByText("MQTT connection")).toBeTruthy();
    expect(screen.getAllByText("ready", { selector: "dd" })).toHaveLength(2);
    expect(screen.getByTestId("protocol-state-modbus").textContent).toContain("Not configured");
    expect(screen.getByTestId("protocol-state-haystack").textContent).toContain("Authentication failed");
    const bacnetRadio = screen.getByRole("radio", { name: "BACnet" });
    bacnetRadio.focus();
    expect(document.activeElement).toBe(bacnetRadio);
  });

  it("renders an actionable error and retries without inventing availability", async () => {
    apiFetch.mockRejectedValueOnce(new Error("capabilities timeout"));
    render(
      <MemoryRouter>
        <ProtocolWorkspace protocol="modbus" onProtocolChange={vi.fn()} />
      </MemoryRouter>,
    );
    expect((await screen.findByTestId("protocol-status-error")).textContent).toContain("capabilities timeout");
    expect(screen.queryByTestId("protocol-status-grid")).toBeNull();

    apiFetch.mockResolvedValueOnce(capabilityResponse());
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect((await screen.findByTestId("protocol-state-modbus")).textContent).toContain("Not configured");
  });

  it("shows configured upstream failure without assigning it to a protocol", async () => {
    const response = capabilityResponse();
    response.connector_capabilities.upstreams = [
      {
        address: "redacted-configured-upstream",
        state: "unreachable",
        hello: null,
        error: "edge connector is unreachable",
      },
    ];
    apiFetch.mockResolvedValueOnce(response);
    render(
      <MemoryRouter>
        <ProtocolWorkspace protocol="modbus" onProtocolChange={vi.fn()} />
      </MemoryRouter>,
    );

    const upstreamStatus = await screen.findByTestId("protocol-upstream-status");
    expect(upstreamStatus.textContent).toContain("unreachable");
    expect(upstreamStatus.textContent).not.toContain("redacted-configured-upstream");
    expect(upstreamStatus.textContent).not.toContain("edge connector is unreachable");
    expect(screen.getByTestId("protocol-state-modbus").textContent).toContain("Not configured");
    expect(screen.getByTestId("protocol-status-modbus").textContent).toContain("configured upstream");
  });
});

describe("Operations protocol navigation", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    mockOperationsApi();
  });

  it("honors a protocol deep link and preserves the Operations query scope", async () => {
    render(
      <MemoryRouter initialEntries={["/operations?view=mqtt&protocol=modbus&site=site-a&eq=equipment-a"]}>
        <OperationsPage />
        <LocationProbe />
      </MemoryRouter>,
    );

    expect((await screen.findByTestId("protocol-state-modbus")).textContent).toContain("Not configured");
    expect(screen.getByRole("heading", { name: "Modbus", level: 2 })).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "BACnet" }));
    await waitFor(() => expect(screen.getByTestId("location-search").textContent).toBe(
      "?view=mqtt&protocol=bacnet&site=site-a&eq=equipment-a",
    ));
  });

  it("keeps the existing MQTT panels and AFDD view available", async () => {
    const mqtt = render(
      <MemoryRouter initialEntries={["/operations"]}>
        <OperationsPage />
      </MemoryRouter>,
    );
    expect(await screen.findByTestId("mqtt-config-panel")).toBeTruthy();
    expect(screen.getByTestId("edge-kit-panel")).toBeTruthy();
    expect(screen.getByTestId("telemetry-suspend-panel")).toBeTruthy();
    mqtt.unmount();

    render(
      <MemoryRouter initialEntries={["/operations?view=afdd"]}>
        <OperationsPage />
      </MemoryRouter>,
    );
    expect(await screen.findByTestId("afdd-config-panel")).toBeTruthy();
    expect(screen.queryByTestId("protocol-workspace")).toBeNull();
  });
});
