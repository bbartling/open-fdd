import { useCallback, useEffect, useState } from "react";
import { fetchAssignments } from "../lib/ruleBindings";
import { formatApiError } from "../lib/formatApiError";
import { formatRuleLabel } from "../lib/ruleDisplay";

type Props = {
  refreshKey?: number;
};

export default function PointRulePinsPanel({ refreshKey = 0 }: Props) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [rows, setRows] = useState<
    Array<{
      point_id: string;
      name: string;
      external_id?: string;
      brick_type?: string;
      bound_rules: { rule_id: string; rule_name: string }[];
    }>
  >([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await fetchAssignments();
      const pinned = (data.points ?? []).filter((p) => (p.bound_rules?.length ?? 0) > 0);
      pinned.sort((a, b) => String(a.name).localeCompare(String(b.name)));
      setRows(pinned);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  useEffect(() => {
    const onChange = () => void load();
    window.addEventListener("ofdd-assignments-changed", onChange);
    return () => window.removeEventListener("ofdd-assignments-changed", onChange);
  }, [load]);

  return (
    <section className="panel point-rule-pins-panel">
      <h3 className="panel-title">Point → FDD rule pins</h3>
      <p className="muted">
        Same mapping as Rule Lab and commissioning JSON — each point shows the <strong>rule name</strong> you see in
        Rule Lab, not just opaque ids. Edit pins via JSON <code>fdd_rule_ids</code> or right-click on{" "}
        <a href="/plot">Trend plot</a>.
      </p>
      {loading ? <p className="muted">Loading point pins…</p> : null}
      {error ? <p className="error">{error}</p> : null}
      {!loading && !rows.length ? (
        <p className="muted">No points have FDD rules pinned yet.</p>
      ) : null}
      {rows.length ? (
        <table className="data-table point-rule-pins-table">
          <thead>
            <tr>
              <th>Point</th>
              <th>Column / BRICK</th>
              <th>FDD rules (Rule Lab names)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.point_id}>
                <td>
                  <code>{row.point_id}</code>
                  <div className="muted">{row.name}</div>
                </td>
                <td>
                  {row.external_id ? <code>{row.external_id}</code> : "—"}
                  {row.brick_type ? (
                    <div className="muted">
                      <code>{row.brick_type}</code>
                    </div>
                  ) : null}
                </td>
                <td>
                  <ul className="point-rule-pins-list">
                    {row.bound_rules.map((r) => (
                      <li key={r.rule_id}>
                        <strong>{formatRuleLabel(r.rule_name)}</strong>
                        <span className="muted">
                          {" "}
                          · <code>{r.rule_id}</code>
                        </span>
                      </li>
                    ))}
                  </ul>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}
