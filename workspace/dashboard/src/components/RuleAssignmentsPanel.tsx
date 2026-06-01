import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import { buildAssignmentRows, type AssignmentRow, type SavedRule } from "../lib/ruleBindings";
import { formatRuleLabel } from "../lib/ruleDisplay";

type ModelTree = {
  equipment: { id: string; name?: string }[];
  points: { id: string; equipment_id?: string; brick_type?: string; description?: string }[];
};

type Props = {
  refreshKey?: number;
};

function labelForPoint(tree: ModelTree | null, pointId: string): string {
  const p = tree?.points?.find((x) => x.id === pointId);
  if (!p) return pointId;
  return String(p.description || p.brick_type || p.id);
}

function labelForEquipment(tree: ModelTree | null, eqId: string): string {
  const eq = tree?.equipment?.find((x) => x.id === eqId);
  return String(eq?.name || eqId);
}

export default function RuleAssignmentsPanel({ refreshKey = 0 }: Props) {
  const [rows, setRows] = useState<AssignmentRow[]>([]);
  const [tree, setTree] = useState<ModelTree | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [saved, modelTree] = await Promise.all([
        apiFetch<{ rules: SavedRule[] }>("/api/rules/saved"),
        apiFetch<ModelTree>("/api/model/tree"),
      ]);
      setTree(modelTree);
      setRows(buildAssignmentRows(saved.rules ?? []));
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  return (
    <section className="panel rule-assignments-panel">
      <h3 className="panel-title">FDD assignments (read-only)</h3>
      <p className="muted">
        Map rules on the <a href="/data-model">Data Model</a> tab (right-click points, equipment, or sensor
        classes). Rule Lab edits rule code and config only.
      </p>
      {loading ? <p className="muted">Loading assignments…</p> : null}
      {error ? <p className="error">{error}</p> : null}
      {!loading && !rows.length ? (
        <p className="muted">No rules mapped yet — right-click a point in Data Model → Apply FDD rule.</p>
      ) : null}
      {rows.length ? (
        <ul className="rule-assignments-list">
          {rows.map((row) => (
            <li key={row.ruleId} className="rule-assignment-row">
              <div className="rule-assignment-head">
                <strong>{formatRuleLabel(row.ruleName)}</strong>
                <span className="badge">{row.severity}</span>
                <span className="muted">
                  {row.pointCount} pts · {row.equipmentCount} equip · {row.brickCount} classes
                </span>
              </div>
              {row.pointIds.length ? (
                <div className="rule-assignment-block">
                  <span className="rule-assignment-label">Points</span>
                  <ul>
                    {row.pointIds.map((pid) => (
                      <li key={pid}>
                        <code>{pid}</code>
                        <span className="muted"> · {labelForPoint(tree, pid)}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {row.equipmentIds.length ? (
                <div className="rule-assignment-block">
                  <span className="rule-assignment-label">Equipment</span>
                  <ul>
                    {row.equipmentIds.map((eid) => (
                      <li key={eid}>{labelForEquipment(tree, eid)}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {row.brickTypes.length ? (
                <div className="rule-assignment-block">
                  <span className="rule-assignment-label">BRICK classes</span>
                  <ul>
                    {row.brickTypes.map((bt) => (
                      <li key={bt}>
                        <code>{bt}</code>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
