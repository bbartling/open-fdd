import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../../lib/api";
import { formatApiError } from "../../lib/formatApiError";

type RegistryRule = {
  rule_id: string;
  description?: string;
  parity_status?: string;
  dashboard_wired?: boolean;
  required_roles?: string[];
  parameters?: Array<{ key: string; label?: string; effective?: number; unit?: string }>;
};

type RegistryResponse = {
  ok?: boolean;
  rule_count?: number;
  rules_dir?: string;
  rules?: RegistryRule[];
  error?: string;
};

type Props = {
  selectedRuleId?: string;
  onSelectRuleId?: (ruleId: string) => void;
};

export default function RuleRegistryPanel({ selectedRuleId, onSelectRuleId }: Props) {
  const [data, setData] = useState<RegistryResponse | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");

  useEffect(() => {
    apiFetch<RegistryResponse>("/api/fdd/rules")
      .then(setData)
      .catch((e) => setError(formatApiError(e)));
  }, []);

  const rules = useMemo(() => {
    const list = data?.rules ?? [];
    const q = filter.trim().toLowerCase();
    if (!q) return list;
    return list.filter(
      (r) =>
        r.rule_id.toLowerCase().includes(q) ||
        (r.description ?? "").toLowerCase().includes(q) ||
        (r.parity_status ?? "").toLowerCase().includes(q),
    );
  }, [data?.rules, filter]);

  if (error) {
    return (
      <section className="panel rule-registry-panel">
        <h3>SQL rule registry</h3>
        <p className="error-text">{error}</p>
      </section>
    );
  }

  if (!data?.ok) {
    return (
      <section className="panel rule-registry-panel">
        <h3>SQL rule registry</h3>
        <p className="muted">{data?.error ?? "Loading registry…"}</p>
      </section>
    );
  }

  return (
    <section className="panel rule-registry-panel">
      <div className="panel-head">
        <h3>SQL rule registry</h3>
        <span className="gf-pill gf-pill--muted">{data.rule_count ?? rules.length} rules</span>
      </div>
      <p className="muted small">
        Production cookbook rules from <code>{data.rules_dir ?? "sql_rules"}</code>. Tune parameters via{" "}
        <code>/api/fdd/rules/&#123;id&#125;/params</code>.
      </p>
      <input
        type="search"
        className="rule-registry-filter"
        placeholder="Filter rules…"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        aria-label="Filter registry rules"
      />
      <ul className="rule-registry-list">
        {rules.map((rule) => {
          const active = selectedRuleId === rule.rule_id;
          return (
            <li key={rule.rule_id}>
              <button
                type="button"
                className={`rule-registry-item${active ? " active" : ""}`}
                onClick={() => onSelectRuleId?.(rule.rule_id)}
              >
                <span className="rule-registry-id">{rule.rule_id}</span>
                {rule.parity_status ? (
                  <span className={`rule-registry-parity parity-${rule.parity_status}`}>{rule.parity_status}</span>
                ) : null}
                {rule.description ? <span className="rule-registry-desc">{rule.description}</span> : null}
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
