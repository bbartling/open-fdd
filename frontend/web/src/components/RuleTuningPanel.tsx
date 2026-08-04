import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getFddRuleParams,
  listFddRules,
  runFdd,
  type FddRuleParamDef,
  type FddRuleSummary,
} from "../api/fddApi";
import { getSessionConfig, putSessionConfig } from "../api/mappingApi";
import { useSessionQuery } from "../session";

const PARAMS_KEY = "openfdd.ui.rule_params";
export const RULES_UPDATED_EVENT = "openfdd:rules-updated";

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

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function RuleExpander({
  rule,
  values,
  onChange,
  onUpdateRule,
  updating,
  buildingId,
}: {
  rule: FddRuleSummary;
  values: Record<string, number>;
  onChange: (ruleId: string, key: string, value: number) => void;
  onUpdateRule: (ruleId: string) => void;
  updating: boolean;
  buildingId: string;
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
          setDefs(null);
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
        {!loading && defs && entries.length === 0 ? (
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
        {entries.length > 0 ? (
          <div className="oracle-sidebar__rule-actions">
            <button
              type="button"
              className="oracle-sidebar__btn oracle-sidebar__btn--primary"
              disabled={!buildingId || updating || !modified}
              title={
                !buildingId
                  ? "Select an active site first"
                  : !modified
                    ? "Move a slider to enable Update this rule"
                    : `Re-run ${rule.rule_id} with tuned params`
              }
              onClick={() => onUpdateRule(rule.rule_id)}
              data-testid={`sidebar-update-rule-${rule.rule_id}`}
            >
              {updating ? "Updating…" : "Update this rule"}
            </button>
          </div>
        ) : null}
      </div>
    </details>
  );
}

/** Streamlit-oracle left-rail Rule tuning (expanders + sliders). */
export function RuleTuningPanel() {
  const { query } = useSessionQuery();
  const buildingId = query.siteId ?? "";
  const [rules, setRules] = useState<FddRuleSummary[]>([]);
  const [family, setFamily] = useState<string>("(all)");
  const [opsGate, setOpsGate] = useState(true);
  const [params, setParams] = useState(loadStoredParams);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [runMsg, setRunMsg] = useState<string | null>(null);
  const [runErr, setRunErr] = useState<string | null>(null);
  const [updatingRuleId, setUpdatingRuleId] = useState<string | null>(null);
  const [persistErr, setPersistErr] = useState<string | null>(null);
  const persistTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const persistGen = useRef(0);

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
      if (persistTimer.current) clearTimeout(persistTimer.current);
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

  const persistSession = useCallback(
    async (nextParams: Record<string, Record<string, number>>) => {
      const gen = ++persistGen.current;
      try {
        const prev = await getSessionConfig();
        if (gen !== persistGen.current) return;
        await putSessionConfig({
          ...(prev.config ?? {}),
          schema_version: prev.config?.schema_version ?? "openfdd.session.v1",
          params: {
            ...nextParams,
            _ui: {
              ...(nextParams._ui ?? {}),
              require_operational_proof: opsGate ? 1 : 0,
            },
          },
        });
        if (gen === persistGen.current) setPersistErr(null);
      } catch (err) {
        if (gen === persistGen.current) {
          setPersistErr(
            `Session save failed (local sliders kept): ${formatErr(err)}`,
          );
        }
      }
    },
    [opsGate],
  );

  const schedulePersist = useCallback(
    (nextParams: Record<string, Record<string, number>>) => {
      if (persistTimer.current) clearTimeout(persistTimer.current);
      persistTimer.current = setTimeout(() => {
        persistTimer.current = null;
        void persistSession(nextParams);
      }, 350);
    },
    [persistSession],
  );

  const onParam = useCallback(
    (ruleId: string, key: string, value: number) => {
      setParams((prev) => {
        const next = {
          ...prev,
          [ruleId]: { ...(prev[ruleId] ?? {}), [key]: value },
        };
        saveStoredParams(next);
        schedulePersist(next);
        return next;
      });
    },
    [schedulePersist],
  );

  const emitUpdated = (detail: Record<string, unknown>) => {
    try {
      window.dispatchEvent(new CustomEvent(RULES_UPDATED_EVENT, { detail }));
    } catch {
      /* ignore */
    }
  };

  const onUpdateRule = useCallback(
    async (ruleId: string) => {
      if (!buildingId) {
        setRunErr("Select an active site first");
        return;
      }
      setUpdatingRuleId(ruleId);
      setRunErr(null);
      setRunMsg(`Updating ${ruleId}…`);
      try {
        await persistSession(params);
        const result = await runFdd({
          mode: "registry",
          building_id: buildingId,
          rule_ids: [ruleId],
          params,
        });
        const n = result.results?.length ?? 0;
        setRunMsg(
          `Updated ${ruleId} · ${n} result row(s) · ${result.total_ms ?? "—"} ms`,
        );
        emitUpdated({
          mode: "single",
          rule_id: ruleId,
          building_id: buildingId,
          count: n,
        });
      } catch (err) {
        setRunErr(formatErr(err));
        setRunMsg(null);
      } finally {
        setUpdatingRuleId(null);
      }
    },
    [buildingId, params, persistSession],
  );

  const reset = () => {
    setParams({});
    saveStoredParams({});
    if (persistTimer.current) clearTimeout(persistTimer.current);
    void persistSession({});
  };

  return (
    <section className="oracle-sidebar__block" data-testid="sidebar-rule-tuning">
      <h3 className="oracle-sidebar__h3">Rule tuning</h3>
      <p className="oracle-sidebar__caption">
        Sliders write session config. After tuning, click{" "}
        <strong>Update this rule</strong> next to the slider (or{" "}
        <strong>Update all rules</strong> on Overview).
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
        FDD math: central DataFusion SQL. Active site:{" "}
        <code>{buildingId || "—"}</code>
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
      <div className="oracle-sidebar__btn-row">
        <button
          type="button"
          className="oracle-sidebar__btn"
          onClick={reset}
          data-testid="sidebar-tune-reset"
        >
          Reset
        </button>
      </div>
      {runMsg ? (
        <p className="oracle-sidebar__ok" data-testid="sidebar-tune-run-msg">
          {runMsg}
        </p>
      ) : null}
      {runErr || loadErr || persistErr ? (
        <p className="oracle-sidebar__err" data-testid="sidebar-tune-error">
          {runErr || loadErr || persistErr}
        </p>
      ) : null}
      <div className="oracle-sidebar__rules" data-testid="sidebar-tune-rules">
        {visible.map((rule) => (
          <RuleExpander
            key={rule.rule_id}
            rule={rule}
            values={params[rule.rule_id] ?? {}}
            onChange={onParam}
            onUpdateRule={(id) => void onUpdateRule(id)}
            updating={updatingRuleId === rule.rule_id}
            buildingId={buildingId}
          />
        ))}
      </div>
    </section>
  );
}
