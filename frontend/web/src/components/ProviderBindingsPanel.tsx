import { useEffect, useMemo, useState } from "react";
import {
  fetchOptionalJson,
  ingestGapsPath,
  ingestJobsPath,
} from "../api/providersApi";
import {
  jobIdentityBindings,
  ledgerFromFetches,
  type WindowLedgerView,
} from "../lib/providerDisplay";

/**
 * Queue identity for the active site: provider instance, device, and model revision
 * on durable ingest jobs. Typed point lists are not invented here.
 */
export function ProviderBindingsPanel({ buildingId }: { buildingId: string }) {
  const [view, setView] = useState<WindowLedgerView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const site = buildingId.trim();

  useEffect(() => {
    if (!site) {
      setView(null);
      setError(null);
      return;
    }
    const controller = new AbortController();
    setView(null);
    setError(null);
    void (async () => {
      const [jobs, gaps] = await Promise.all([
        fetchOptionalJson(ingestJobsPath(site), controller.signal),
        fetchOptionalJson(ingestGapsPath(site), controller.signal),
      ]);
      if (controller.signal.aborted) return;
      const message =
        jobs.http === "error" && jobs.message !== "aborted"
          ? jobs.message
          : gaps.http === "error" && gaps.message !== "aborted"
            ? gaps.message
            : null;
      if (message) setError(message);
      setView(ledgerFromFetches(jobs, gaps));
    })();
    return () => {
      controller.abort();
    };
  }, [site]);

  const bindings = useMemo(
    () => (view?.status === "ready" ? jobIdentityBindings(view.jobs) : []),
    [view],
  );

  if (!site) return null;

  return (
    <section data-testid="provider-bindings-panel" aria-labelledby="provider-bindings-heading">
      <h3 id="provider-bindings-heading">Provider bindings</h3>
      <p className="muted">
        Queue identity for {site}. A row is the provider instance, device, and model revision on a
        durable ingest job. Credentials and executable routes are not edited here.
      </p>
      {error ? (
        <p className="error" data-testid="provider-bindings-error">
          {error}
        </p>
      ) : null}
      {!view ? <p data-testid="provider-bindings-loading">Loading provider bindings…</p> : null}
      {view && view.status === "unavailable" ? (
        <p data-testid="provider-bindings-empty">{view.reason}</p>
      ) : null}
      {view && view.status === "ready" ? (
        <div data-testid="provider-bindings-ready">
          <p data-testid="provider-bindings-coverage">{view.coverageLabel}</p>
          <p data-testid="provider-bindings-gaps">{view.gapsNote}</p>
          <p data-testid="provider-bindings-jobs">{view.jobsNote}</p>
          {bindings.length === 0 ? (
            <p>No durable job bindings were returned. Empty is not an approved point map.</p>
          ) : (
            <div className="widget-table-wrap">
              <table data-testid="provider-bindings-table">
                <thead>
                  <tr>
                    <th>Provider instance</th>
                    <th>Device</th>
                    <th>Model revision</th>
                    <th>Windows</th>
                  </tr>
                </thead>
                <tbody>
                  {bindings.map((binding) => (
                    <tr key={binding.key}>
                      <td>{binding.providerInstanceId || "—"}</td>
                      <td>{binding.deviceId || "—"}</td>
                      <td>
                        <code>{binding.modelRevision || "—"}</code>
                      </td>
                      <td>{binding.windowCount}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p data-testid="provider-bindings-scope">
            Typed point bindings are not part of this contract. This screen does not build a history
            request.
          </p>
        </div>
      ) : null}
    </section>
  );
}
