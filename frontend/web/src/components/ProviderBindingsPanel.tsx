import { useEffect, useState } from "react";
import {
  fetchOptionalJson,
  providerBindingsPath,
} from "../api/providersApi";
import {
  illustratedNfHistoryRead,
  interpretBindings,
  providerLabel,
  type BindingsView,
} from "../lib/providerDisplay";

/**
 * Typed source bindings and a redacted request preview.
 * Missing N3 routes stay an honest empty state — the browser does not invent ids.
 */
export function ProviderBindingsPanel({ buildingId }: { buildingId: string }) {
  const [view, setView] = useState<BindingsView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const site = buildingId.trim();
    if (!site) {
      setView(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setView(null);
    setError(null);
    void (async () => {
      const result = await fetchOptionalJson(providerBindingsPath(site));
      if (cancelled) return;
      if (result.http === "error") {
        setError(result.message);
        setView({
          available: false,
          reason: "Bindings could not be loaded. No request was composed in the browser.",
        });
        return;
      }
      setView(interpretBindings(result.http === "ok" ? result.body : null, result.http === "missing"));
    })();
    return () => {
      cancelled = true;
    };
  }, [buildingId]);

  if (!buildingId.trim()) return null;

  return (
    <section data-testid="provider-bindings-panel" aria-labelledby="provider-bindings-heading">
      <h3 id="provider-bindings-heading">Provider bindings</h3>
      <p className="muted">
        Source identity for {buildingId}. A point keeps a connection reference and an opaque series
        id. Credentials and executable routes are not edited here.
      </p>
      {error ? <p className="error">{error}</p> : null}
      {!view ? <p data-testid="provider-bindings-loading">Loading provider bindings…</p> : null}
      {view && !view.available ? (
        <p data-testid="provider-bindings-empty">{view.reason}</p>
      ) : null}
      {view && view.available ? (
        <div data-testid="provider-bindings-ready">
          <p>
            Provider {providerLabel(view.provider)} · model revision{" "}
            <code>{view.modelRevision ?? "not reported"}</code> · {view.bindings.length} binding
            {view.bindings.length === 1 ? "" : "s"}
          </p>
          {view.bindings.length === 0 ? (
            <p>The binding list is empty. Empty is not an approved model.</p>
          ) : (
            <div className="widget-table-wrap">
              <table data-testid="provider-bindings-table">
                <thead>
                  <tr>
                    <th>Equipment</th>
                    <th>Type</th>
                    <th>Role</th>
                    <th>Series id</th>
                    <th>Units</th>
                    <th>Selection</th>
                    <th>Kind / cadence</th>
                  </tr>
                </thead>
                <tbody>
                  {view.bindings.map((binding) => (
                    <tr
                      key={`${binding.equipment_id ?? ""}-${binding.role ?? ""}-${binding.provider_point_id ?? ""}-${binding.selection_status ?? ""}`}
                    >
                      <td>{binding.equipment_id || "—"}</td>
                      <td>{binding.equip_type || "—"}</td>
                      <td>{binding.role || "—"}</td>
                      <td>
                        <code>{binding.provider_point_id || "—"}</code>
                      </td>
                      <td>
                        {binding.source_unit || "—"} → {binding.canonical_unit || "—"}
                      </td>
                      <td>{binding.selection_status || "—"}</td>
                      <td>
                        {[binding.kind, binding.cadence].filter(Boolean).join(" · ") || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <h4>Request preview</h4>
          {view.preview ? (
            <div data-testid="provider-request-preview">
              <p>
                <code>
                  {view.preview.method} {view.preview.path}
                </code>
              </p>
              <p>{view.preview.note}</p>
              {view.preview.pointCount != null ? (
                <p>{view.preview.pointCount} points in the server preview.</p>
              ) : null}
            </div>
          ) : (
            <div data-testid="provider-request-preview-absent">
              <p>
                {view.previewRefusal ??
                  "This API did not issue a request preview. The browser will not build a live URL."}
              </p>
              {view.provider && providerLabel(view.provider) === "NF" ? (
                <p data-testid="provider-request-illustration">
                  Documented NF history shape, not a live request:{" "}
                  <code>{illustratedNfHistoryRead(view.bindings.length)}</code>
                </p>
              ) : null}
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}
