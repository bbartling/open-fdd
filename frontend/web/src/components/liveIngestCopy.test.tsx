import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { PlantHealthSections } from "./PlantHealthSections";
import { ProvidersPanel } from "./ProvidersPanel";
import { WeatherHealthSection } from "./WeatherHealthSection";

vi.mock("../api/client", () => ({
  apiFetch: vi.fn(),
}));

import { apiFetch } from "../api/client";

const emptyEnvelope = {
  schema_version: "analytics-envelope-v1",
  query_version: "test",
  generated_at: "2026-10-22T00:00:00Z",
  engine: "timescale-sql",
  warnings: [],
  rows: [],
  equipment: [],
  points: [],
  skipped: [],
};

describe("live ingest copy", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset();
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/api/providers/health") {
        return {
          ok: true,
          poll_enabled: false,
          registry: [
            { kind: "nf", capabilities: [{ name: "history", support: "read" }] },
            { kind: "mqtt", capabilities: [{ name: "subscribe", support: "read" }] },
            { kind: "bacnet", capabilities: [{ name: "whois", support: "read" }] },
          ],
          sites: [
            {
              building_id: "NF_EDGE",
              provider: "nf",
              endpoint: "https://portal.example",
              poll_secs: 3600,
              health: { status: "not_configured", message: null },
            },
            {
              building_id: "OLD_BUS",
              provider: "mqtt",
              endpoint: "mqtts://broker.example",
              poll_secs: 300,
              health: { status: "ok", message: "mqtt broker up" },
            },
          ],
        };
      }
      if (path === "/api/providers/sites") {
        return {
          sites: [
            { building_id: "NF_EDGE", provider: "nf", poll_secs: 3600 },
            { building_id: "OLD_BUS", provider: "bacnet", poll_secs: 300 },
          ],
        };
      }
      return emptyEnvelope;
    });
  });

  it("does not render archived field-driver copy on Overview or provider chrome", async () => {
    render(
      <MemoryRouter>
        <WeatherHealthSection buildingId="SITE" refreshToken={0} equipment={[]} />
        <PlantHealthSections buildingId="SITE" refreshToken={0} />
        <ProvidersPanel />
      </MemoryRouter>,
    );
    expect(
      await screen.findByText(
        /CSV packages and the NF portal include weather when it is mapped/,
      ),
    ).toBeTruthy();
    expect(
      await screen.findByText(/CSV packages and the NF portal stamp zone_other/),
    ).toBeTruthy();
    expect(await screen.findByTestId("providers-ingest")).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByTestId("provider-registry-nf")).toBeTruthy();
    });
    expect(screen.queryByTestId("provider-registry-mqtt")).toBeNull();
    expect(screen.queryByTestId("provider-registry-bacnet")).toBeNull();
    expect(screen.queryByText("OLD_BUS")).toBeNull();
    expect(screen.getByText("NF_EDGE")).toBeTruthy();
    expect(document.body.textContent ?? "").not.toMatch(/mqtt/i);
    expect(document.body.textContent ?? "").not.toMatch(/bacnet/i);
    expect(document.body.textContent ?? "").not.toMatch(/modbus/i);
    expect(document.body.textContent ?? "").not.toMatch(/haystack/i);
    expect(document.body.textContent ?? "").not.toMatch(/fieldbus/i);
  });
});
