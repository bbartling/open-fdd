import { describe, expect, it } from "vitest";
import {
  credentialRefLabel,
  illustratedNfHistoryRead,
  interpretBindings,
  interpretWindowLedger,
  mergeProviderRows,
  providerStatusView,
  safeRequestPreview,
  sanitizeProviderOrigin,
  siteSourceLabels,
  windowStateLabel,
} from "./providerDisplay";

describe("provider display", () => {
  it("keeps only the origin and drops userinfo and query", () => {
    expect(
      sanitizeProviderOrigin("https://user:secret@portal.example/api?token=abc#frag"),
    ).toBe("https://portal.example");
    expect(sanitizeProviderOrigin("not a url")).toBe("unreadable endpoint");
    expect(sanitizeProviderOrigin("")).toBe("—");
  });

  it("does not treat an outer ok flag as poll health", () => {
    const missing = providerStatusView({ status: "ok", consecutiveErrors: 0, lastPollAt: null });
    expect(missing.tone).toBe("neutral");
    expect(missing.label).not.toBe("Poll ok");
    const clean = providerStatusView({
      status: "ok",
      consecutiveErrors: 0,
      lastPollAt: "2026-10-19T00:00:00Z",
    });
    expect(clean.tone).toBe("good");
    expect(clean.detail).toMatch(/not a committed-window/);
    expect(providerStatusView({ status: "not_implemented" }).label).toBe("Not implemented");
    expect(providerStatusView({ status: "auth_failed" }).tone).toBe("bad");
  });

  it("merges health and site config without requiring a csv id", () => {
    const rows = mergeProviderRows(
      [
        {
          building_id: "NF_EDGE",
          provider: "nf",
          last_poll_at: null,
          consecutive_errors: 0,
          health: { status: "not_configured" },
        },
      ],
      [
        {
          building_id: "NF_EDGE",
          provider: "nf",
          endpoint: "https://portal.example/v1",
          mapped_points: 5,
          client_id_configured: false,
          poll_secs: 3600,
        },
      ],
    );
    expect(rows).toHaveLength(1);
    expect(rows[0]?.mappedPoints).toBe(5);
    expect(rows[0]?.status).toBe("not_configured");
    expect(credentialRefLabel(rows[0]?.clientIdConfigured)).toBe("not configured");
  });

  it("labels sources as read-only facts", () => {
    expect(
      siteSourceLabels({ hasPackage: true, provider: "nf" }),
    ).toEqual(["CSV package", "NF"]);
  });

  it("treats a missing or shapeless ledger as unavailable", () => {
    expect(interpretWindowLedger(null, true).available).toBe(false);
    expect(interpretWindowLedger({}, false).available).toBe(false);
    const present = interpretWindowLedger(
      {
        windows: [
          {
            job_id: "job-1",
            device_id: "AHU_1",
            window_start: "2026-10-19T09:00:00Z",
            window_end: "2026-10-19T10:00:00Z",
            state: "partial",
            recoverable: false,
            reason: "retention expired",
          },
        ],
      },
      false,
    );
    expect(present.available).toBe(true);
    if (present.available) {
      expect(windowStateLabel(present.windows[0]!)).toBe("Unrecoverable");
    }
  });

  it("refuses secret and write previews", () => {
    expect(
      safeRequestPreview({
        method: "POST",
        path: "/api/v1/point/data",
        credentials_included: false,
      }).refusal,
    ).toMatch(/write/);
    expect(
      safeRequestPreview({
        method: "GET",
        path: "/api/v1/point/data?uuids=1&token=sekret",
      }).preview?.path,
    ).toBe("/api/v1/point/data?uuids=1");
    expect(
      safeRequestPreview({ method: "GET", path: "/api/v1/point/data", credentials_included: true })
        .preview,
    ).toBeNull();
  });

  it("keeps bindings honest when the route is missing", () => {
    const missing = interpretBindings(null, true);
    expect(missing.available).toBe(false);
    const ready = interpretBindings(
      {
        provider: "nf",
        model_revision: "rev-1",
        bindings: [
          {
            provider_point_id: "uuid-1",
            equipment_id: "AHU_1",
            role: "oa_t",
            selection_status: "approved",
          },
        ],
        request_preview: {
          method: "GET",
          path: "/api/v1/point/data?uuids=uuid-1",
          note: "server plan",
          point_count: 1,
        },
      },
      false,
    );
    expect(ready.available).toBe(true);
    if (ready.available) {
      expect(ready.preview?.method).toBe("GET");
      expect(ready.bindings[0]?.role).toBe("oa_t");
    }
    expect(illustratedNfHistoryRead(2)).toContain("GET /api/v1/point/data");
    expect(illustratedNfHistoryRead(2)).not.toMatch(/POST/);
  });
});
