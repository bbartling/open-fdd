import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getFddRuleParams,
  listFddRules,
  type FddRuleParamDef,
  type FddRuleSummary,
} from "../api/fddApi";

const PARAMS_KEY = "openfdd.ui.rule_params";

function loadStoredParams(): Record<string, Record<string, number>> {
  try {
    const raw = localStorage.getItem(PARAMS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, Record<string, number>>;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function saveStoredParams(map: Record<string, Record<string, number>>): void {
  try {
    localStorage.setItem(PARAMS_KEY, JSON.stringify(map));
  } catch {
    /* ignore */
  }
}

function familyOf(ruleId: string): string {
  const i = ruleId.indexOf("-");
  return i > 0 ? ruleId.slice(0, i) : ruleId;
}

function RuleExpander({
  rule,
  values,
  onChange,
}: {
  rule: FddRuleSummary;
  values: Record<string, number>;
  onChange: (ruleId: string, key: string, value: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const [defs, setDefs] = useState<Record<string, FddRuleParamDef> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || defs) return;
    let cancelled = false;
    setLoading(true);
    getFddRuleParams(rule.rule_id)
      .then((body) => {
        if (!cancelled) setDefs(body.params ?? {});
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setErr(e instanceof Error ? e.message : String(e));
          setDefs({});
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, defs, rule.rule_id]);

  const entries = useMemo(() => {
    if (!defs) return [];
    return Object.entries(defs).sort(([a], [b]) => a.localeCompare(b));
  }, [defs]);

  const modified = entries.some(([key, def]) => {
    const v = values[key];
    return v != null && Math.abs(v - def.default) > 1e-9;
  });

  return (
    <details
      className="oracle-sidebar__expander"
      open={open}
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
      data-testid={`rule-tune-${rule.rule_id}`}
    >
      <summary>
        {rule.rule_id} — {(rule.description || rule.rule_id).slice(0, 36)}
        {modified ? " · modified" : ""}
      </summary>
      <div className="oracle-sidebar__expander-body">
        {loading ? <p className="oracle-sidebar__caption">Loading params…</p> : null}
        {err ? <p className="oracle-sidebar__err">{err}</p> : null}
        {!loading && entries.length === 0 ? (
          <p className="oracle-sidebar__caption">No tunable params.</p>
        ) : null}
        {entries.map(([key, def]) => {
          const val = values[key] ?? def.default;
          return (
            <label key={key} className="oracle-sidebar__field">
              <span className="oracle-sidebar__label">
                {def.label || key}
                {def.unit ? ` (${def.unit})` : ""}
              </span>
              <input
                type="range"
                className="oracle-sidebar__slider"
                min={def.min}
                max={def.max}
                step={def.step || 0.1}
                value={val}
                onChange={(e) =>
                  onChange(rule.rule_id, key, Number(e.target.value))
                }
                title={def.label}
              />
              <span className="oracle-sidebar__caption">{val}</span>
            </label>
          );
        })}
      </div>
    </details>
  );
}

/** Streamlit-oracle left-rail Rule tuning (expanders + sliders). */
export function RuleTuningPanel() {
  const [rules, setRules] = useState<FddRuleSummary[]>([]);
  const [family, setFamily] = useState<string>("(all)");
  const [opsGate, setOpsGate] = useState(true);
  const [params, setParams] = useState(loadStoredParams);
  const [loadErr, setLoadErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listFddRules()
      .then((list) => {
        if (!cancelled) setRules(list);
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setLoadErr(e instanceof Error ? e.message : String(e));
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const families = useMemo(() => {
    const s = new Set(rules.map((r) => familyOf(r.rule_id)));
    return ["(all)", ...[...s].sort()];
  }, [rules]);

  const visible = useMemo(() => {
    if (family === "(all)") return rules;
    return rules.filter((r) => familyOf(r.rule_id) === family);
  }, [rules, family]);

  const onParam = useCallback(
    (ruleId: string, key: string, value: number) => {
      setParams((prev) => {
        const next = {
          ...prev,
          [ruleId]: { ...(prev[ruleId] ?? {}), [key]: value },
        };
        saveStoredParams(next);
        return next;
      });
    },
    [],
  );

  return (
    <section className="oracle-sidebar__block" data-testid="sidebar-rule-tuning">
      <h3 className="oracle-sidebar__h3">Rule tuning</h3>
      <p className="oracle-sidebar__caption">
        Sliders only change thresholds. Rules update when you click{" "}
        <strong>Run</strong> (Run Rules tab) or <strong>Rerun cat.</strong>
      </p>
      <label className="oracle-sidebar__check">
        <input
          type="checkbox"
          checked={opsGate}
          onChange={(e) => setOpsGate(e.target.checked)}
        />
        Require operational proof (fan/pump status)
      </label>
      <p className="oracle-sidebar__caption">
        FDD math: central DataFusion SQL. Pandas frames still load for
        plots/analytics only.
      </p>
      <label className="oracle-sidebar__field">
        <span className="oracle-sidebar__label">Category</span>
        <select
          className="oracle-sidebar__control"
          value={family}
          onChange={(e) => setFamily(e.target.value)}
          data-testid="sidebar-tune-category"
        >
          {families.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
      </label>
      {loadErr ? (
        <p className="oracle-sidebar__err" data-testid="sidebar-tune-error">
          {loadErr}
        </p>
      ) : null}
      <div className="oracle-sidebar__rules" data-testid="sidebar-tune-rules">
        {visible.slice(0, 80).map((rule) => (
          <RuleExpander
            key={rule.rule_id}
            rule={rule}
            values={params[rule.rule_id] ?? {}}
            onChange={onParam}
          />
        ))}
      </div>
    </section>
  );
}
