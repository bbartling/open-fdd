import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../../lib/api";
import { formatApiError } from "../../lib/formatApiError";
import { ruleConfigLines } from "../../lib/faultInsight";
import { formatRuleLabel } from "../../lib/ruleDisplay";
import { normalizeBindings, type SavedRule } from "../../lib/ruleBindings";

type ModelTree = {
  equipment: { id: string; name?: string }[];
  points: { id: string; name?: string; description?: string; brick_type?: string; equipment_id?: string }[];
};

type RuleRow = SavedRule & { short_description?: string; config?: Record<string, unknown> };

function bindingSummary(rule: RuleRow, tree: ModelTree | null): string {
  const b = normalizeBindings(rule.bindings);
  const parts: string[] = [];
  if (b.equipment_ids.length) {
    const names = b.equipment_ids.map((id) => tree?.equipment?.find((e) => e.id === id)?.name || id);
    parts.push(`${b.equipment_ids.length} equipment (${names.slice(0, 2).join(", ")}${names.length > 2 ? "…" : ""})`);
  }
  if (b.brick_types.length) {
    parts.push(`${b.brick_types.length} BRICK type(s)`);
  }
  if (b.point_ids.length) {
    parts.push(`${b.point_ids.length} point(s)`);
  }
  return parts.length ? parts.join(" · ") : "No bindings yet";
}

function pointLabels(rule: RuleRow, tree: ModelTree | null): string[] {
  const ids = normalizeBindings(rule.bindings).point_ids;
  return ids.map((pid) => {
    const pt = tree?.points?.find((p) => p.id === pid);
    return String(pt?.description || pt?.name || pt?.brick_type || pid);
  });
}

export default function FddRulesInServicePanel() {
  const [rules, setRules] = useState<RuleRow[]>([]);
  const [tree, setTree] = useState<ModelTree | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [saved, modelTree] = await Promise.all([
        apiFetch<{ rules: RuleRow[] }>("/api/rules/saved"),
        apiFetch<ModelTree>("/api/model/tree"),
      ]);
      setRules((saved.rules ?? []).filter((r) => r.enabled !== false));
      setTree(modelTree);
      setError("");
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const onChange = () => void load();
    window.addEventListener("ofdd-assignments-changed", onChange);
    return () => window.removeEventListener("ofdd-assignments-changed", onChange);
  }, [load]);

  const enabledCount = rules.length;
  const boundCount = useMemo(
    () => rules.filter((r) => normalizeBindings(r.bindings).point_ids.length > 0).length,
    [rules],
  );

  return (
    <div className="bis-card">
      <div className="bis-card-head-row">
        <div>
          <h3>FDD rules in service</h3>
          <h2>
            Active detection rules{" "}
            <span className="bis-hint">expand for bindings</span>
          </h2>
        </div>
        <Link to="/rule-lab" className="bis-btn bis-btn-secondary">
          Rule Lab
        </Link>
      </div>

      {loading ? <p className="muted">Loading saved rules…</p> : null}
      {error ? <p className="error">{error}</p> : null}

      {!loading && !rules.length ? (
        <p className="muted">
          No enabled rules yet. Create rules in <Link to="/rule-lab">Rule Lab</Link> and bind them on the{" "}
          <Link to="/model">Model</Link> tab.
        </p>
      ) : null}

      {rules.length ? (
        <>
          <p className="bis-lead bis-muted-line">
            <strong>{enabledCount}</strong> rule{enabledCount === 1 ? "" : "s"} enabled ·{" "}
            <strong>{boundCount}</strong> with point bindings
          </p>
          <ul className="bis-fdd-rules-list">
            {rules.map((rule) => {
              const cfgLines = ruleConfigLines(rule.config);
              const pts = pointLabels(rule, tree);
              const eqIds = normalizeBindings(rule.bindings).equipment_ids;
              return (
                <li key={rule.id} className="bis-fdd-rule-item">
                  <details>
                    <summary className="bis-fdd-rule-summary">
                      <span className={`bis-severity-pill bis-sev-${rule.severity === "critical" ? "critical" : rule.severity === "warning" ? "medium" : "info"}`}>
                        {rule.severity || "warning"}
                      </span>
                      <strong>{formatRuleLabel(rule.name)}</strong>
                      <span className="bis-muted-inline">{bindingSummary(rule, tree)}</span>
                    </summary>
                    <div className="bis-fdd-rule-body">
                      {rule.short_description ? (
                        <p className="bis-fdd-rule-desc">{rule.short_description}</p>
                      ) : null}
                      {cfgLines.length ? (
                        <dl className="bis-meta-grid bis-meta-grid-compact">
                          {cfgLines.map((line) => (
                            <div key={line.label}>
                              <dt>{line.label}</dt>
                              <dd>{line.value}</dd>
                            </div>
                          ))}
                        </dl>
                      ) : null}
                      {eqIds.length ? (
                        <p className="bis-muted-line">
                          <strong>Equipment:</strong>{" "}
                          {eqIds
                            .map((id) => tree?.equipment?.find((e) => e.id === id)?.name || id)
                            .join(", ")}
                        </p>
                      ) : null}
                      {pts.length ? (
                        <p className="bis-muted-line">
                          <strong>Points:</strong> {pts.slice(0, 6).join(", ")}
                          {pts.length > 6 ? ` (+${pts.length - 6} more)` : ""}
                        </p>
                      ) : null}
                      <p className="bis-muted-line">
                        Rule id <code>{rule.id}</code>
                      </p>
                    </div>
                  </details>
                </li>
              );
            })}
          </ul>
        </>
      ) : null}
    </div>
  );
}
