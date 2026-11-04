import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import {
  fetchOptionalJson,
  fetchProviderSites,
  fetchProvidersHealth,
  ingestGapsPath,
  ingestJobsPath,
  type CoverageLedgerView,
  type ProviderSiteConfig,
  type ProviderSiteHealth,
} from "../api/providersApi";
import {
  connectionLabel,
  credentialRefLabel,
  isArchivedFieldDriver,
  jobCoverageWord,
  lastErrorText,
  lastIngestedPointsText,
  ledgerFromFetches,
  mergeProviderRows,
  POLL_LEDGER_COVERAGE_LABEL,
  providerLabel,
  providerStatusView,
  sanitizeProviderOrigin,
  windowStateLabel,
  windowTone,
  type ProviderRow,
  type ProviderWindowRow,
  type WindowLedgerView,
} from "../lib/providerDisplay";
import { IngestCoverageStatus } from "./IngestCoverageStatus";
import { IngestCatchupProgress } from "./IngestCatchupProgress";
import { Button } from "./widgets";

const PAGE_SIZE = 20;

function formatPoll(seconds: number | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  if (seconds % 3600 === 0) return `${seconds / 3600} h`;
  if (seconds % 60 === 0) return `${seconds / 60} min`;
  return `${seconds} s`;
}

function filterWindows(rows: ProviderWindowRow[], query: string): ProviderWindowRow[] {
  const q = query.trim().toLowerCase();
  if (!q) return rows;
  return rows.filter((row) =>
    [row.deviceId, row.state, row.jobId, row.reason, row.providerInstanceId, windowStateLabel(row)]
      .join(" ")
      .toLowerCase()
      .includes(q),
  );
}

function inspectHref(buildingId: string, row: ProviderWindowRow): string {
  const q = new URLSearchParams();
  q.set("site", buildingId);
  if (row.deviceId) q.set("eq", row.deviceId);
  return `/inspect?${q.toString()}`;
}

function modelHref(buildingId: string, row: ProviderWindowRow): string {
  const q = new URLSearchParams();
  q.set("site", buildingId);
  if (row.deviceId) q.set("eq", row.deviceId);
  return `/mapping?${q.toString()}`;
}

export function ProvidersPanel() {
  const requestGen = useRef(0);
  const [pollEnabled, setPollEnabled] = useState<boolean | null>(null);
  const [coverageSites, setCoverageSites] = useState<
    Array<{ key: string; buildingId: string; provider: string; ledger: CoverageLedgerView | null }>
  >([]);
  const [rows, setRows] = useState<ProviderRow[]>([]);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [ledger, setLedger] = useState<WindowLedgerView | null>(null);
  const [ledgerError, setLedgerError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);

  const refresh = useCallback(async () => {
    const ticket = ++requestGen.current;
    setLoading(true);
    try {
      const [health, sites] = await Promise.all([
        fetchProvidersHealth(),
        fetchProviderSites().catch(() => null),
      ]);
      if (ticket !== requestGen.current) return;
      const healthSites: ProviderSiteHealth[] = (health.sites ?? sites?.health ?? []).filter(
        (site) => !isArchivedFieldDriver(site.provider ?? site.health?.kind),
      );
      const configs: ProviderSiteConfig[] = (sites?.sites ?? []).filter(
        (site) => !isArchivedFieldDriver(site.provider),
      );
      setPollEnabled(
        typeof health.poll_enabled === "boolean"
          ? health.poll_enabled
          : typeof sites?.poll_enabled === "boolean"
            ? sites.poll_enabled
            : null,
      );
      setRows(mergeProviderRows(healthSites, configs));
      setCoverageSites(
        healthSites.map((site) => ({
          key: `${site.building_id ?? "site"}-${site.provider ?? "provider"}`,
          buildingId: site.building_id ?? "site",
          provider: site.provider ?? "provider",
          ledger: site.coverage_ledger ?? null,
        })),
      );
      setError(null);
    } catch (err) {
      if (ticket !== requestGen.current) return;
      setRows([]);
      setCoverageSites([]);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (ticket === requestGen.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), 15_000);
    return () => window.clearInterval(id);
  }, [refresh]);

  const selected = rows.find((row) => row.key === selectedKey) ?? null;
  const selectedBuildingId = selected?.buildingId ?? "";

  useEffect(() => {
    if (!selectedBuildingId) {
      setLedger(null);
      setLedgerError(null);
      return;
    }
    const buildingId = selectedBuildingId;
    const controller = new AbortController();
    setLedger(null);
    setLedgerError(null);
    setPage(0);
    void (async () => {
      const [jobs, gaps] = await Promise.all([
        fetchOptionalJson(ingestJobsPath(buildingId), controller.signal),
        fetchOptionalJson(ingestGapsPath(buildingId), controller.signal),
      ]);
      if (controller.signal.aborted) return;
      const message =
        jobs.http === "error" && jobs.message !== "aborted"
          ? jobs.message
          : gaps.http === "error" && gaps.message !== "aborted"
            ? gaps.message
            : null;
      if (message) setLedgerError(message);
      setLedger(ledgerFromFetches(jobs, gaps));
    })();
    return () => {
      controller.abort();
    };
  }, [selectedBuildingId]);

  const readyLedger = ledger?.status === "ready" ? ledger : null;
  const filteredJobs = useMemo(() => {
    if (!readyLedger) return [];
    return filterWindows(readyLedger.jobs, query);
  }, [readyLedger, query]);
  const filteredGaps = useMemo(() => {
    if (!readyLedger) return [];
    return filterWindows(readyLedger.gaps, query);
  }, [readyLedger, query]);

  const pageCount = Math.max(1, Math.ceil(filteredJobs.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const pageRows = filteredJobs.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE);
  const stateCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const row of filteredGaps) {
      const label = windowStateLabel(row);
      counts.set(label, (counts.get(label) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [filteredGaps]);

  return (
    <section aria-labelledby="providers-heading" data-testid="providers-health-panel">
      <div className="panel-header">
        <h2 id="providers-heading">Provider ingest</h2>
        <Button
          id="providers-refresh"
          label={loading ? "Refreshing…" : "Refresh"}
          variant="secondary"
          onClick={() => void refresh()}
        />
      </div>
      <p className="muted">Poll status is separate from history coverage.</p>
      <p data-testid="providers-poll-enabled">
        Polling: {pollEnabled == null ? "not reported" : pollEnabled ? "enabled" : "disabled"}
      </p>
      {coverageSites.map((site) => {
        const ledger = site.ledger;
        if (!ledger) {
          return (
            <p key={site.key} className="muted" data-testid={`coverage-ledger-absent-${site.key}`}>
              Coverage ledger for {site.buildingId} has not run. A latest sample is not coverage.
            </p>
          );
        }
        return (
          <div key={site.key} data-testid="coverage-ledger">
            <p data-testid="coverage-guarantee">{ledger.guarantee?.statement}</p>
            <p data-testid="coverage-gapless">{POLL_LEDGER_COVERAGE_LABEL}</p>
            <table>
              <thead>
                <tr>
                  <th>Axis</th>
                  <th>State</th>
                  <th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {(ledger.axes ?? []).map((axis) => (
                  <tr key={axis.id} data-testid={`coverage-axis-${axis.id}`}>
                    <td>{axis.id}</td>
                    <td>{axis.state}</td>
                    <td>{axis.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
      {error ? (
        <p className="error" data-testid="providers-error">
          {error}
        </p>
      ) : null}
      {loading && rows.length === 0 && !error ? (
        <p data-testid="providers-loading">Loading provider health…</p>
      ) : null}
      {!loading && rows.length === 0 && !error ? (
        <p className="muted" data-testid="providers-empty">
          No provider sites are configured.
        </p>
      ) : null}
      {rows.length > 0 ? (
        <div className="widget-table-wrap">
          <table data-testid="providers-health-table">
            <thead>
              <tr>
                <th>Site</th>
                <th>Provider</th>
                <th>Connection</th>
                <th>Status</th>
                <th>Origin</th>
                <th>Poll</th>
                <th>Mapped points</th>
                <th>Approved points</th>
                <th>Withheld points</th>
                <th>Credential ref</th>
                <th>Last poll</th>
                <th>Last success</th>
                <th>Last ingested points</th>
                <th>Last error</th>
                <th>Errors</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const status = providerStatusView({
                  status: row.status,
                  consecutiveErrors: row.consecutiveErrors,
                  lastPollAt: row.lastPollAt,
                  message: row.message,
                });
                const selectedRow = row.key === selectedKey;
                return (
                  <tr
                    key={row.key}
                    data-testid={`provider-row-${row.buildingId}`}
                    className={selectedRow ? "is-selected" : undefined}
                    onClick={() => setSelectedKey(row.key)}
                  >
                    <td>
                      <button
                        type="button"
                        className="linkish"
                        data-testid={`provider-open-${row.buildingId}`}
                        onClick={() => setSelectedKey(row.key)}
                      >
                        {row.buildingId}
                      </button>
                    </td>
                    <td>{providerLabel(row.provider)}</td>
                    <td data-testid={`provider-connection-${row.buildingId}`}>
                      {connectionLabel(row.provider, row.transport)}
                    </td>
                    <td>
                      <span
                        className={`provider-status provider-status--${status.tone}`}
                        data-testid={`provider-status-${row.buildingId}`}
                      >
                        {status.label}
                      </span>
                    </td>
                    <td data-testid={`provider-origin-${row.buildingId}`}>
                      {sanitizeProviderOrigin(row.endpoint)}
                    </td>
                    <td>{formatPoll(row.pollSecs)}</td>
                    <td>{row.mappedPoints ?? "—"}</td>
                    <td data-testid={`provider-approved-${row.buildingId}`}>
                      {row.approvedPoints ?? "—"}
                    </td>
                    <td data-testid={`provider-withheld-${row.buildingId}`}>
                      {row.withheldPoints ?? "—"}
                    </td>
                    <td>{credentialRefLabel(row.clientIdConfigured)}</td>
                    <td>{row.lastPollAt ?? "—"}</td>
                    <td data-testid={`provider-last-success-${row.buildingId}`}>
                      {row.lastSuccessAt ?? "—"}
                    </td>
                    <td data-testid={`provider-last-ingested-${row.buildingId}`}>
                      {lastIngestedPointsText(row.lastIngested)}
                    </td>
                    <td data-testid={`provider-last-error-${row.buildingId}`}>
                      {lastErrorText(row)}
                    </td>
                    <td>{row.consecutiveErrors ?? "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}

      {selected ? (
        <div data-testid="provider-detail" className="provider-detail">
          <h3>
            {selected.buildingId} · {providerLabel(selected.provider)}
          </h3>
          <p data-testid="provider-status-detail">
            {providerStatusView({
              status: selected.status,
              consecutiveErrors: selected.consecutiveErrors,
              lastPollAt: selected.lastPollAt,
              message: selected.message,
            }).detail}
          </p>
          {selected.withheldReasons && selected.withheldReasons.length > 0 ? (
            <div data-testid="provider-withheld-reasons">
              <h4>Withheld plan points</h4>
              <ul>
                {selected.withheldReasons.map((entry) => (
                  <li key={`${entry.equipmentId}:${entry.pointId}:${entry.reason}`}>
                    {entry.equipmentId} · {entry.pointId}: {entry.reason}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <IngestCoverageStatus siteId={selected.buildingId} />
          <IngestCatchupProgress siteId={selected.buildingId} />
          <h3 id="provider-ledger-heading">Window ledger</h3>
          {ledgerError ? (
            <p className="error" data-testid="provider-ledger-error">
              {ledgerError}
            </p>
          ) : null}
          {!ledger ? <p data-testid="provider-ledger-loading">Loading window ledger…</p> : null}
          {ledger && ledger.status === "unavailable" ? (
            <p data-testid="provider-ledger-empty">{ledger.reason}</p>
          ) : null}
          {ledger && ledger.status === "ready" ? (
            <div data-testid="provider-ledger">
              <p data-testid="provider-ledger-coverage">{ledger.coverageLabel}</p>
              <p data-testid="provider-ledger-jobs-note">{ledger.jobsNote}</p>
              <p data-testid="provider-ledger-gaps-note">{ledger.gapsNote}</p>
              <label>
                Search windows
                <input
                  value={query}
                  onChange={(event) => {
                    setQuery(event.target.value);
                    setPage(0);
                  }}
                  data-testid="provider-ledger-search"
                />
              </label>
              {stateCounts.length > 0 ? (
                <p data-testid="provider-ledger-groups">
                  {stateCounts.map(([label, count]) => `${label}: ${count}`).join(" · ")}
                </p>
              ) : (
                <p>No gap windows match this search.</p>
              )}
              <h4>Durable job windows</h4>
              {pageRows.length > 0 ? (
                <div className="widget-table-wrap">
                  <table data-testid="provider-ledger-jobs">
                    <thead>
                      <tr>
                        <th>Device</th>
                        <th>Window</th>
                        <th>State</th>
                        <th>Coverage</th>
                        <th>Points</th>
                        <th>Attempt</th>
                        <th>Job</th>
                        <th>Links</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pageRows.map((row) => (
                        <tr key={row.id}>
                          <td>{row.deviceId || "—"}</td>
                          <td>
                            {row.windowStart || "—"} → {row.windowEnd || "—"}
                          </td>
                          <td>
                            <span className={`provider-status provider-status--${windowTone(row)}`}>
                              {windowStateLabel(row)}
                            </span>
                            {row.reason ? ` — ${row.reason}` : ""}
                          </td>
                          <td data-testid="provider-job-coverage">{jobCoverageWord(row.coverage)}</td>
                          <td>
                            fetched {row.fetched ?? "—"} · accepted {row.accepted ?? "—"} · rejected{" "}
                            {row.rejected ?? "—"} · inserted {row.inserted ?? "—"}
                          </td>
                          <td>{row.attempt ?? "—"}</td>
                          <td>
                            <code>{row.jobId}</code>
                          </td>
                          <td>
                            <Link to={inspectHref(selected.buildingId, row)}>Inspect</Link>
                            {" · "}
                            <Link to={modelHref(selected.buildingId, row)}>Model</Link>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
              <h4>Gaps in returned windows</h4>
              {filteredGaps.length > 0 ? (
                <div className="widget-table-wrap">
                  <table data-testid="provider-ledger-gaps">
                    <thead>
                      <tr>
                        <th>Device</th>
                        <th>Window</th>
                        <th>State</th>
                        <th>Reason</th>
                        <th>Job</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredGaps.map((row) => (
                        <tr key={row.id}>
                          <td>{row.deviceId || "—"}</td>
                          <td>
                            {row.windowStart || "—"} → {row.windowEnd || "—"}
                          </td>
                          <td>
                            <span className={`provider-status provider-status--${windowTone(row)}`}>
                              {windowStateLabel(row)}
                            </span>
                          </td>
                          <td>{row.reason || "—"}</td>
                          <td>
                            <code>{row.jobId}</code>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
              {filteredJobs.length > PAGE_SIZE ? (
                <div className="button-row">
                  <Button
                    id="provider-ledger-prev"
                    label="Previous"
                    variant="secondary"
                    disabled={safePage === 0}
                    onClick={() => setPage((current) => Math.max(0, current - 1))}
                  />
                  <span>
                    Page {safePage + 1} of {pageCount}
                  </span>
                  <Button
                    id="provider-ledger-next"
                    label="Next"
                    variant="secondary"
                    disabled={safePage >= pageCount - 1}
                    onClick={() => setPage((current) => current + 1)}
                  />
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : rows.length > 0 ? (
        <p className="muted">Select a site to open its window ledger.</p>
      ) : null}
    </section>
  );
}
