import { useEffect, useState } from "react";
import { fetchOptionalJson, ingestCoverageStatusPath } from "../api/providersApi";
import {
  coverageStateLabel,
  coverageStateTone,
  coverageStatusFromFetch,
  pointsText,
  type CoverageStatusView,
} from "../lib/ingestCoverageStatus";

/** Schedule and coverage status for one canonical site. */
export function IngestCoverageStatus({ siteId }: { siteId: string }) {
  const [view, setView] = useState<CoverageStatusView | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setView(null);
    void (async () => {
      const fetched = await fetchOptionalJson(ingestCoverageStatusPath(siteId), controller.signal);
      if (controller.signal.aborted) return;
      setView(coverageStatusFromFetch(fetched));
    })();
    return () => controller.abort();
  }, [siteId]);

  return (
    <div data-testid="ingest-coverage-status">
      <h3>Schedule and coverage</h3>
      {!view ? <p data-testid="ingest-coverage-loading">Loading coverage status…</p> : null}
      {view?.status === "unavailable" ? (
        <p data-testid="ingest-coverage-unavailable">{view.reason}</p>
      ) : null}
      {view?.status === "error" ? (
        <p className="error" data-testid="ingest-coverage-error">
          {view.message}
        </p>
      ) : null}
      {view?.status === "ready" ? (
        <div className="widget-table-wrap">
          <table data-testid="ingest-coverage-table">
            <thead>
              <tr>
                <th>Provider</th>
                <th>Schedule</th>
                <th>Next run</th>
                <th>Planned through</th>
                <th>Verified through</th>
                <th>Approved of discovered points</th>
                <th>State</th>
                <th>Oldest gap</th>
              </tr>
            </thead>
            <tbody>
              {view.rows.map((row) => (
                <tr key={row.key} data-testid={`ingest-coverage-row-${row.providerInstanceId}`}>
                  <td>{row.providerInstanceId}</td>
                  <td>
                    {row.mode}
                    {row.timezone ? ` · ${row.timezone}` : ""}
                  </td>
                  <td>{row.scheduleError ? `Schedule error: ${row.scheduleError}` : (row.nextRun ?? "—")}</td>
                  <td>{row.plannedThrough ?? "—"}</td>
                  <td data-testid="ingest-coverage-verified">{row.verifiedThrough ?? "Not verified"}</td>
                  <td>{pointsText(row)}</td>
                  <td>
                    <span className={`provider-status provider-status--${coverageStateTone(row.state)}`}>
                      {coverageStateLabel(row.state)}
                    </span>
                  </td>
                  <td data-testid="ingest-coverage-oldest-gap">
                    {row.oldestGap ??
                      (row.gapScanTruncated ? "Not in the first 200 gap rows" : "None recorded")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
