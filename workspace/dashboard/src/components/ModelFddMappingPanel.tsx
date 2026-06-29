import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../lib/api";
import { assignmentSummary, parseCommissioningPayload } from "../lib/commissioningImport";

type Props = {
  onStatus?: (message: string) => void;
};

type PointRow = {
  id?: string;
  name?: string;
  haystack_id?: string;
  fdd_rule_ids?: string[];
  driver_ref?: string;
};

/** FDD point → rule mapping from commissioning JSON (replaces wiresheet studio). */
export default function ModelFddMappingPanel({ onStatus }: Props) {
  const [points, setPoints] = useState<PointRow[]>([]);
  const [rules, setRules] = useState<Array<{ id?: string; name?: string }>>([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const bundle = await apiFetch<Record<string, unknown>>("/api/model/commissioning-export");
      const parsed = parseCommissioningPayload(JSON.stringify(bundle));
      setPoints((parsed.points ?? []) as PointRow[]);
      const ruleList = (bundle.fdd_rules as Array<{ id?: string; name?: string; rule_id?: string }>) ?? [];
      setRules(
        ruleList.map((r) => ({
          id: (r.id ?? r.rule_id) as string | undefined,
          name: r.name,
        })),
      );
      const summary = assignmentSummary(parsed);
      onStatus?.(
        `${summary.boundPointCount} points bound to FDD · ${summary.ruleCount} rules in commissioning JSON`,
      );
    } catch (e) {
      onStatus?.(String(e));
    } finally {
      setBusy(false);
    }
  }, [onStatus]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const onChange = () => void load();
    window.addEventListener("ofdd-assignments-changed", onChange);
    return () => window.removeEventListener("ofdd-assignments-changed", onChange);
  }, [load]);

  const mapped = points.filter((p) => (p.fdd_rule_ids?.length ?? 0) > 0);
  const unmapped = points.filter((p) => !p.fdd_rule_ids?.length);

  return (
    <section className="panel">
      <div className="toolbar">
        <h3 className="panel-title">FDD mapping</h3>
        <button type="button" className="secondary-btn" disabled={busy} onClick={() => void load()}>
          {busy ? "Loading…" : "Reload"}
        </button>
        <Link className="secondary-btn" to="/sql-fdd">
          SQL FDD rules
        </Link>
      </div>
      <p className="muted">
        Map Haystack points (by ID, name, or driver ref) to SQL FDD rules via{" "}
        <code>points[].fdd_rule_ids</code> in commissioning JSON. AI agents use{" "}
        <code>openfdd_model_assignments_save</code> on the Integrations tab.
      </p>
      <dl className="detail-grid compact">
        <div>
          <dt>Mapped points</dt>
          <dd>{mapped.length}</dd>
        </div>
        <div>
          <dt>Unmapped points</dt>
          <dd>{unmapped.length}</dd>
        </div>
        <div>
          <dt>Rules in model</dt>
          <dd>{rules.length}</dd>
        </div>
      </dl>
      {mapped.length ? (
        <div className="table-wrap">
          <table className="data-table compact">
            <thead>
              <tr>
                <th>Point</th>
                <th>FDD rules</th>
              </tr>
            </thead>
            <tbody>
              {mapped.slice(0, 40).map((p) => (
                <tr key={p.id ?? p.haystack_id ?? p.name}>
                  <td>{p.name || p.id || p.haystack_id}</td>
                  <td>
                    <code>{(p.fdd_rule_ids ?? []).join(", ")}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {mapped.length > 40 ? <p className="muted">Showing 40 of {mapped.length} mapped points.</p> : null}
        </div>
      ) : (
        <p className="muted">
          No FDD rule bindings yet — edit commissioning JSON on Import / export or ask your AI agent to assign{" "}
          <code>fdd_rule_ids</code> per point.
        </p>
      )}
    </section>
  );
}
