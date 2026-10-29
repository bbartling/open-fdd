import { useEffect, useState } from "react";
import { fetchOptionalJson, ingestCatchupPath } from "../api/providersApi";
import {
  catchupModeLabel,
  ingestCatchupFromFetch,
  type IngestCatchupView,
} from "../lib/ingestCatchup";

/** ASAP catch-up progress for the selected site (mirrors `GET /api/ingest/catchup`). */
export function IngestCatchupProgress({ siteId }: { siteId: string }) {
  const [view, setView] = useState<IngestCatchupView>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    setView({ status: "loading" });
    void (async () => {
      const fetched = await fetchOptionalJson(ingestCatchupPath(siteId), controller.signal);
      if (controller.signal.aborted) return;
      setView(ingestCatchupFromFetch(fetched));
    })();
    return () => controller.abort();
  }, [siteId]);

  return (
    <div data-testid="ingest-catchup-progress">
      <h3>Catch-up progress</h3>
      {view.status === "loading" ? (
        <p data-testid="ingest-catchup-loading">Loading catch-up progress…</p>
      ) : null}
      {view.status === "unavailable" ? (
        <p data-testid="ingest-catchup-unavailable">{view.reason}</p>
      ) : null}
      {view.status === "error" ? (
        <p className="error" data-testid="ingest-catchup-error">
          {view.message}
        </p>
      ) : null}
      {view.status === "ready" && view.rows.length === 0 ? (
        <p data-testid="ingest-catchup-empty">No ingest devices on the committed plan.</p>
      ) : null}
      {view.status === "ready" && view.rows.length > 0 ? (
        <div className="widget-table-wrap">
          <table data-testid="ingest-catchup-table">
            <thead>
              <tr>
                <th>Provider</th>
                <th>Device</th>
                <th>Mode</th>
                <th>Last stored</th>
                <th>Missing windows</th>
                <th>Rows / min</th>
                <th>ETA</th>
                <th>Throttle</th>
              </tr>
            </thead>
            <tbody>
              {view.rows.map((row) => (
                <tr key={row.key} data-testid={`ingest-catchup-row-${row.deviceId}`}>
                  <td>{row.providerInstanceId}</td>
                  <td>{row.deviceId}</td>
                  <td data-testid="ingest-catchup-mode">{catchupModeLabel(row.mode)}</td>
                  <td>{row.lastStored}</td>
                  <td>{row.missingWindows}</td>
                  <td>{row.rowsPerMinute}</td>
                  <td>{row.eta}</td>
                  <td>{row.throttle}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
