import { describe, expect, it } from "vitest";
import {
  connectionLabel,
  credentialRefLabel,
  illustratedNfHistoryRead,
  interpretIngestLedger,
  jobCoverageWord,
  jobIdentityBindings,
  lastErrorText,
  lastIngestedPointsText,
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

  it("labels the configured NF transport without guessing or fallback", () => {
    expect(connectionLabel("nf", "grpc")).toBe("LAN (gRPC)");
    expect(connectionLabel("nf", "rest")).toBe("Portal (HTTPS)");
    expect(connectionLabel("normal_framework", " GRPC ")).toBe("LAN (gRPC)");
    expect(connectionLabel("nf", undefined)).toBe("not reported");
    expect(connectionLabel("nf", "mqtt")).toBe("unsupported transport");
    expect(connectionLabel("nf", "mqtt")).not.toMatch(/HTTPS|gRPC/);
    expect(connectionLabel("ace_iot", "grpc")).toBe("—");
  });

  it("carries the config transport onto the merged row", () => {
    const rows = mergeProviderRows(
      [{ building_id: "NF_LAN", provider: "nf", health: { status: "ok" } }],
      [{ building_id: "NF_LAN", provider: "nf", transport: "grpc" }],
    );
    expect(rows[0]?.transport).toBe("grpc");
    expect(connectionLabel(rows[0]?.provider, rows[0]?.transport)).toBe("LAN (gRPC)");
  });

  it("labels sources as read-only facts", () => {
    expect(
      siteSourceLabels({ hasPackage: true, provider: "nf" }),
    ).toEqual(["CSV package", "NF"]);
  });

  it("reads the ingest jobs and gaps contract and refuses a gap-free claim", () => {
    const refused = interpretIngestLedger(
      { jobs: [], coverage: "not_assessed", gapless: true },
      {
        gaps: [],
        coverage: "not_assessed",
        guarantee: "bounded_windows_only",
        update_log: "not_claimed",
      },
    );
    expect(refused.status).toBe("unavailable");
    const legacy = interpretIngestLedger({ windows: [] }, { gaps: [] });
    expect(legacy.status).toBe("unavailable");
    const present = interpretIngestLedger(
      {
        coverage: "not_assessed",
        jobs: [
          {
            job_id: "job-1",
            device_id: "device-a",
            provider_instance_id: "portal-a",
            model_revision: "rev-1",
            logical_window_start: "2026-10-19T09:00:00Z",
            logical_window_end: "2026-10-19T10:00:00Z",
            state: "committed",
            attempt: 1,
            coverage: "not_assessed",
            counts: { fetched: 1, accepted: 1, rejected: 0, inserted: 1 },
          },
        ],
      },
      {
        coverage: "not_assessed",
        guarantee: "bounded_windows_only",
        update_log: "not_claimed",
        gaps: [
          {
            recoverable: false,
            job: {
              job_id: "job-2",
              device_id: "device-a",
              provider_instance_id: "portal-a",
              model_revision: "rev-1",
              logical_window_start: "2026-10-19T08:00:00Z",
              logical_window_end: "2026-10-19T09:00:00Z",
              state: "permanent_failure",
              safe_error_code: "retention_exceeded",
              coverage: "not_assessed",
              counts: { fetched: 0, accepted: 0, rejected: 0, inserted: 0 },
            },
          },
        ],
      },
    );
    expect(present.status).toBe("ready");
    if (present.status === "ready") {
      expect(present.coverageLabel).toMatch(/Bounded-window coverage/);
      expect(present.coverageLabel).toMatch(/not a gap-free ingest claim/);
      expect(windowStateLabel(present.gaps[0]!)).toBe("Unrecoverable");
      expect(jobIdentityBindings(present.jobs)).toEqual([
        {
          key: "portal-a\u0000device-a\u0000rev-1",
          providerInstanceId: "portal-a",
          deviceId: "device-a",
          modelRevision: "rev-1",
          windowCount: 1,
        },
      ]);
    }
    const clear = interpretIngestLedger(
      { coverage: "not_assessed", jobs: [] },
      {
        coverage: "not_assessed",
        guarantee: "bounded_windows_only",
        update_log: "not_claimed",
        gaps: [],
      },
    );
    expect(clear.status).toBe("ready");
    if (clear.status === "ready") {
      expect(clear.gapsNote).toMatch(/not gap-free ingest/);
      expect(clear.jobsCoverage).toBe("not_assessed");
      expect(clear.gapsCoverage).toBe("not_assessed");
    }
  });

  it("parses complete and incomplete jobs without treating a receipt as gap-free", () => {
    const gapsWords = interpretIngestLedger(
      { coverage: "bounded_windows_only", jobs: [] },
      {
        coverage: "not_assessed",
        guarantee: "bounded_windows_only",
        update_log: "not_claimed",
        gaps: [],
      },
    );
    expect(gapsWords.status).toBe("unavailable");

    const mixed = interpretIngestLedger(
      {
        coverage: "complete",
        jobs: [
          {
            job_id: "job-complete",
            device_id: "device-a",
            provider_instance_id: "portal-a",
            model_revision: "rev-1",
            logical_window_start: "2026-10-19T09:00:00Z",
            logical_window_end: "2026-10-19T10:00:00Z",
            state: "committed",
            coverage: "complete",
            counts: { fetched: 4, accepted: 4, rejected: 0, inserted: 4 },
          },
        ],
      },
      {
        coverage: "complete",
        guarantee: "missing",
        gaps: [],
      },
    );
    expect(mixed.status).toBe("unavailable");

    const accounted = interpretIngestLedger(
      {
        coverage: "incomplete",
        jobs: [
          {
            job_id: "job-complete",
            device_id: "device-a",
            provider_instance_id: "portal-a",
            model_revision: "rev-1",
            logical_window_start: "2026-10-19T09:00:00Z",
            logical_window_end: "2026-10-19T10:00:00Z",
            state: "committed",
            coverage: "complete",
            counts: { fetched: 4, accepted: 4, rejected: 0, inserted: 4 },
          },
          {
            job_id: "job-partial",
            device_id: "device-a",
            provider_instance_id: "portal-a",
            model_revision: "rev-1",
            logical_window_start: "2026-10-19T10:00:00Z",
            logical_window_end: "2026-10-19T11:00:00Z",
            state: "partial",
            coverage: "incomplete",
            safe_error_code: "upstream_timeout",
            counts: { fetched: 3, accepted: 1, rejected: 2, inserted: 0 },
          },
        ],
      },
      {
        coverage: "incomplete",
        guarantee: "bounded_windows_only",
        update_log: "not_claimed",
        gaps: [
          {
            recoverable: true,
            job: {
              job_id: "job-partial",
              device_id: "device-a",
              provider_instance_id: "portal-a",
              model_revision: "rev-1",
              logical_window_start: "2026-10-19T10:00:00Z",
              logical_window_end: "2026-10-19T11:00:00Z",
              state: "partial",
              coverage: "incomplete",
              safe_error_code: "upstream_timeout",
            },
          },
        ],
      },
    );
    expect(accounted.status).toBe("ready");
    if (accounted.status !== "ready") return;
    expect(accounted.jobsCoverage).toBe("incomplete");
    expect(accounted.gapsCoverage).toBe("incomplete");
    expect(accounted.coverageLabel).toMatch(/Job coverage is incomplete/);
    expect(accounted.coverageLabel).toMatch(/not the gaps list/);
    expect(accounted.coverageLabel).toMatch(/not a gap-free ingest claim/);
    expect(accounted.coverageLabel).not.toMatch(/No gaps in the returned windows/);
    expect(accounted.gapsNote).toMatch(/Gaps coverage is incomplete/);
    expect(accounted.gapsNote).not.toMatch(/Job coverage is incomplete/);
    expect(jobCoverageWord(accounted.jobs[0]!.coverage)).toBe("Complete");
    expect(jobCoverageWord(accounted.jobs[1]!.coverage)).toBe("Incomplete");
    expect(windowStateLabel(accounted.gaps[0]!)).toBe("Partial");

    const receipt = interpretIngestLedger(
      {
        coverage: "complete",
        jobs: [
          {
            job_id: "job-complete",
            device_id: "device-a",
            provider_instance_id: "portal-a",
            model_revision: "rev-1",
            state: "committed",
            coverage: "complete",
          },
        ],
      },
      {
        coverage: "not_assessed",
        guarantee: "bounded_windows_only",
        update_log: "not_claimed",
        gaps: [],
      },
    );
    expect(receipt.status).toBe("ready");
    if (receipt.status !== "ready") return;
    expect(receipt.jobsCoverage).toBe("complete");
    expect(receipt.gapsCoverage).toBe("not_assessed");
    expect(receipt.coverageLabel).toMatch(/complete receipt is not proof that history has no gaps/);
    expect(receipt.coverageLabel).toMatch(/not a gap-free ingest claim/);
    expect(receipt.gapsNote).toMatch(/empty gap list is not gap-free ingest/);
    expect(receipt.gapsNote).not.toMatch(/Job coverage is complete/);
    expect(receipt.jobsNote).not.toMatch(/no gaps/);
  });

  it("keeps a healthy status message out of Last error and renders ingested points as a count", () => {
    expect(
      lastErrorText({
        status: "ok",
        message: "committed; update log not claimed",
        lastErrorAt: null,
      }),
    ).toBe("—");
    expect(
      lastErrorText({
        status: "ok",
        message: "committed; update log not claimed",
        lastErrorAt: "2026-10-01T00:00:00Z",
      }),
    ).toBe("2026-10-01T00:00:00Z");
    expect(
      lastErrorText({
        status: "error",
        message: "history_failed",
        lastErrorAt: "2026-10-01T00:00:00Z",
      }),
    ).toBe("history_failed");
    expect(lastIngestedPointsText(60)).toBe("60");
    expect(lastIngestedPointsText(1500)).toBe("1,500");
    expect(lastIngestedPointsText(1_700_000_000)).toBe("1,700,000,000");
    expect(lastIngestedPointsText(1_700_000_000)).not.toMatch(/T\d{2}:/);
    expect(lastIngestedPointsText(60)).not.toMatch(/1970/);
    expect(lastIngestedPointsText(undefined)).toBe("—");
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

  it("keeps the documented history read as a GET", () => {
    expect(illustratedNfHistoryRead(2)).toContain("GET /api/v1/point/data");
    expect(illustratedNfHistoryRead(2)).not.toMatch(/POST/);
  });
});
