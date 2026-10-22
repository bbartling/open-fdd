import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getFddRuleParams,
  listFddRules,
  runFdd,
  type FddRuleParamDef,
  type FddRuleSummary,
} from "../api/fddApi";
import { getSessionConfig, putSessionConfig } from "../api/mappingApi";
import { ruleLabelStandard, mergeRuleDescriptionsFromApi } from "../lib/ruleLabels";
import {
  effectiveRunParams,
  loadLocalRuleParams,
  OPERATIONAL_GATE_KEY,
  ruleNeedsRun,
  saveLocalRuleParams,
  SESSION_SCHEMA,
  stampOperationalGate,
  type RuleParamMap,
} from "../lib/ruleParams";
import { useSessionQuery } from "../session";
import {
  displayScalar,
  displayStep,
  displayUnitLabel,
  formatTunerCaption,
  resolveQuantityKind,
  storeScalar,
} from "../api/roleUnits";
import { naturalCompare } from "../lib/naturalSort";

export const RULES_UPDATED_EVENT = "openfdd:rules-updated";
const UNITS_KEY = "openfdd.ui.unit_system";

function familyOf(ruleId: string): string {
  if (/^FC\d+/i.test(ruleId)) return "FC";
  const i = ruleId.indexOf("-");
  return i > 0 ? ruleId.slice(0, i) : ruleId;
}

/** Lab UX: natural A–Z by rule_id after category filter (registry order stays for the engine). */
export function visibleRulesForLab(
  rules: FddRuleSummary[],
  family: string,
): FddRuleSummary[] {
  const filtered =
    family === "(all)"
      ? [...rules]
      : rules.filter((r) => familyOf(r.rule_id) === family);
  return filtered.sort((a, b) => naturalCompare(a.rule_id, b.rule_id));
}

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

const VALUE_EPS = 1e-9;

function RuleExpander({
  rule,
  values,
  onChange,
  applied,
  opsGate,
  onUpdateRule,
  updating,
  buildingId,
  unitSystem,
}: {
  rule: FddRuleSummary;
  values: Record<string, number>;
  applied: Record<string, number>;
  opsGate: boolean;
  onChange: (ruleId: string, key: string, value: number) => void;
  onUpdateRule: (ruleId: string, declaresGate: boolean) => void;
  updating: boolean;
  buildingId: string;
  unitSystem: "imperial" | "metric";
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
    if (key === OPERATIONAL_GATE_KEY) return false;
    const v = values[key];
    return v != null && Math.abs(v - def.default) > VALUE_EPS;
  });
  const needsRun = ruleNeedsRun(entries, values, applied, opsGate);
  const declaresGate = entries.some(([key]) => key === OPERATIONAL_GATE_KEY);

  return (
    <details
      className="oracle-sidebar__expander"
      open={open}
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
      data-testid={`rule-tune-${rule.rule_id}`}
    >
      <summary>
        {ruleLabelStandard(rule.rule_id, rule.description)}
        {modified ? " · modified" : ""}
      </summary>
      <div className="oracle-sidebar__expander-body">
        {loading ? <p className="oracle-sidebar__caption">Loading params…</p> : null}
        {err ? <p className="oracle-sidebar__err">{err}</p> : null}
        {!loading && defs && entries.length === 0 ? (
          <p className="oracle-sidebar__caption">No tunable params.</p>
        ) : null}
        {entries.filter(([key]) => key !== OPERATIONAL_GATE_KEY).map(([key, def]) => {
          const quantity = resolveQuantityKind(def.unit, key, def.quantity);
          const stored = values[key] ?? def.default;
          const val = displayScalar(stored, def.unit, unitSystem, quantity, key);
          const min = displayScalar(def.min, def.unit, unitSystem, quantity, key);
          const max = displayScalar(def.max, def.unit, unitSystem, quantity, key);
          const step = displayStep(def.step, def.unit, unitSystem, quantity, key);
          const unitLabel = displayUnitLabel(def.unit, unitSystem, quantity, key);
          return (
            <label key={key} className="oracle-sidebar__field">
              <span className="oracle-sidebar__label" data-testid={`tune-label-${key}`}>
                {def.label || key}
                {unitLabel ? ` (${unitLabel})` : ""}
              </span>
              <input
                type="range"
                className="oracle-sidebar__slider"
                min={min}
                max={max}
                step={step}
                value={val}
                onChange={(e) =>
                  onChange(
                    rule.rule_id,
                    key,
                    storeScalar(Number(e.target.value), def.unit, unitSystem, quantity, key),
                  )
                }
                title={def.label}
                data-testid={`tune-slider-${key}`}
              />
              <span className="oracle-sidebar__caption">{formatTunerCaption(val, quantity)}</span>
            </label>
          );
        })}
        {entries.length > 0 ? (
          <div className="oracle-sidebar__rule-actions">
            <button
              type="button"
              className="oracle-sidebar__btn oracle-sidebar__btn--primary"
              disabled={!buildingId || updating || !needsRun}
              title={
                !buildingId
                  ? "Select an active site first"
                  : !needsRun
                    ? "Draft matches the last successful update"
                    : `Re-run ${rule.rule_id} with tuned params`
              }
              onClick={() => onUpdateRule(rule.rule_id, declaresGate)}
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

/** Prefer a concrete family on first paint so Lab is not a 60+ rule wall. */
export function defaultLabFamily(rules: FddRuleSummary[]): string {
  const have = new Set(rules.map((r) => familyOf(r.rule_id)));
  for (const pref of ["FC", "VAV", "AHU", "ECON", "SV"]) {
    if (have.has(pref)) return pref;
  }
  const sorted = [...have].sort();
  return sorted[0] ?? "(all)";
}

/** Rule tuning left-rail (expanders + sliders). */
export function RuleTuningPanel() {
  const { query } = useSessionQuery();
  const buildingId = query.siteId ?? "";
  const [rules, setRules] = useState<FddRuleSummary[]>([]);
  const [family, setFamily] = useState<string>("(all)");
  const familyDefaulted = useRef(false);
  const [opsGate, setOpsGate] = useState(true);
  const [params, setParams] = useState<RuleParamMap>(() =>
    loadLocalRuleParams(buildingId),
  );
  const [lastApplied, setLastApplied] = useState<RuleParamMap>({});
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [runMsg, setRunMsg] = useState<string | null>(null);
  const [staleNote, setStaleNote] = useState<string | null>(null);
  const [runErr, setRunErr] = useState<string | null>(null);
  const [updatingRuleId, setUpdatingRuleId] = useState<string | null>(null);
  const [persistErr, setPersistErr] = useState<string | null>(null);
  const persistTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const persistGen = useRef(0);
  const opsTouched = useRef(false);
  const appliedSeeded = useRef(false);
  const [unitSystem, setUnitSystem] = useState<"imperial" | "metric">(() =>
    localStorage.getItem(UNITS_KEY) === "metric" ? "metric" : "imperial",
  );

  useEffect(() => {
    const onUnits = (e: Event) => {
      const d = (e as CustomEvent<"imperial" | "metric">).detail;
      if (d === "metric" || d === "imperial") setUnitSystem(d);
    };
    window.addEventListener("openfdd:unit-system-changed", onUnits);
    return () => window.removeEventListener("openfdd:unit-system-changed", onUnits);
  }, []);

  useEffect(() => {
    let cancelled = false;
    opsTouched.current = false;
    appliedSeeded.current = false;
    setStaleNote(null);
    listFddRules()
      .then((list) => {
        if (!cancelled) {
          mergeRuleDescriptionsFromApi(list);
          setRules(list);
          if (!familyDefaulted.current && list.length > 0) {
            familyDefaulted.current = true;
            setFamily(defaultLabFamily(list));
          }
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setLoadErr(e instanceof Error ? e.message : String(e));
        }
      });
    // Seed Lab sliders from persisted session_config (package / Vibe19 parity),
    // then apply any local browser overrides on top (scoped by building).
    setParams(loadLocalRuleParams(buildingId));
    void getSessionConfig(buildingId)
      .then((body) => {
        if (cancelled) return;
        const merged = effectiveRunParams(
          body.config?.params as Record<string, unknown>,
          loadLocalRuleParams(buildingId),
          buildingId,
        );
        setParams(merged);
        saveLocalRuleParams(merged, buildingId);
        if (!appliedSeeded.current) {
          setLastApplied(merged);
          appliedSeeded.current = true;
        }
        if (
          !opsTouched.current &&
          typeof body.config?.require_operational_proof === "boolean"
        ) {
          setOpsGate(body.config.require_operational_proof);
        }
      })
      .catch(() => {
        /* keep localStorage seed */
      });
    return () => {
      cancelled = true;
      if (persistTimer.current) clearTimeout(persistTimer.current);
    };
  }, [buildingId]);

  const families = useMemo(() => {
    const s = new Set(rules.map((r) => familyOf(r.rule_id)));
    return ["(all)", ...[...s].sort()];
  }, [rules]);

  const visible = useMemo(
    () => visibleRulesForLab(rules, family),
    [rules, family],
  );

  const persistSession = useCallback(
    async (nextParams: RuleParamMap, proof: boolean): Promise<boolean> => {
      const gen = ++persistGen.current;
      try {
        const prev = await getSessionConfig(buildingId);
        if (gen !== persistGen.current) return false;
        const saved = await putSessionConfig(
          {
            ...(prev.config ?? {}),
            schema_version: prev.config?.schema_version ?? SESSION_SCHEMA,
            require_operational_proof: proof,
            params: nextParams,
          },
          buildingId,
        );
        if (gen !== persistGen.current) return false;
        if (!saved.ok) {
          setPersistErr(
            `Session save failed (local sliders kept): ${saved.error || "rejected"}`,
          );
          return false;
        }
        setPersistErr(null);
        return true;
      } catch (err) {
        if (gen === persistGen.current) {
          setPersistErr(
            `Session save failed (local sliders kept): ${formatErr(err)}`,
          );
        }
        return false;
      }
    },
    [buildingId],
  );

  const schedulePersist = useCallback(
    (nextParams: RuleParamMap, proof: boolean) => {
      if (persistTimer.current) clearTimeout(persistTimer.current);
      persistTimer.current = setTimeout(() => {
        persistTimer.current = null;
        void persistSession(nextParams, proof);
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
        saveLocalRuleParams(next, buildingId);
        schedulePersist(next, opsGate);
        return next;
      });
    },
    [schedulePersist, buildingId, opsGate],
  );

  const onOpsGate = useCallback(
    (checked: boolean) => {
      opsTouched.current = true;
      setOpsGate(checked);
      schedulePersist(params, checked);
    },
    [params, schedulePersist],
  );

  const emitUpdated = (detail: Record<string, unknown>) => {
    try {
      window.dispatchEvent(new CustomEvent(RULES_UPDATED_EVENT, { detail }));
    } catch {
      /* ignore */
    }
  };

  const onUpdateRule = useCallback(
    async (ruleId: string, declaresGate: boolean) => {
      if (!buildingId) {
        setRunErr("Select an active site first");
        return;
      }
      if (persistTimer.current) {
        clearTimeout(persistTimer.current);
        persistTimer.current = null;
      }
      const nextParams = stampOperationalGate(params, ruleId, declaresGate, opsGate);
      setUpdatingRuleId(ruleId);
      setRunErr(null);
      setRunMsg(null);
      setStaleNote(null);
      const saved = await persistSession(nextParams, opsGate);
      if (!saved) {
        setUpdatingRuleId(null);
        return;
      }
      setParams(nextParams);
      saveLocalRuleParams(nextParams, buildingId);
      setRunMsg(`Updating ${ruleId}…`);
      try {
        const result = await runFdd({
          mode: "registry",
          building_id: buildingId,
          rule_ids: [ruleId],
          params: nextParams,
        });
        const n = result.results?.length ?? 0;
        setRunMsg(
          `Updated ${ruleId} · ${n} result row(s) · ${result.total_ms ?? "—"} ms`,
        );
        appliedSeeded.current = true;
        setLastApplied((prev) => ({
          ...prev,
          [ruleId]: nextParams[ruleId] ?? {},
        }));
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
    [buildingId, opsGate, params, persistSession],
  );

  const reset = () => {
    const cleared: RuleParamMap = {};
    setParams(cleared);
    opsTouched.current = true;
    setOpsGate(true);
    saveLocalRuleParams(cleared, buildingId);
    if (persistTimer.current) clearTimeout(persistTimer.current);
    persistTimer.current = null;
    setRunMsg(null);
    setRunErr(null);
    setStaleNote(null);
    void persistSession(cleared, true).then((ok) => {
      if (ok) {
        setStaleNote(
          "Thresholds reset to defaults. Last results are stale until you update.",
        );
      }
    });
  };

  return (
    <section className="oracle-sidebar__block" data-testid="sidebar-rule-tuning">
      <h3 className="oracle-sidebar__h3">Lab · rule thresholds</h3>
      <label className="oracle-sidebar__check">
        <input
          type="checkbox"
          checked={opsGate}
          onChange={(e) => onOpsGate(e.target.checked)}
          data-testid="sidebar-tune-ops-proof"
        />
        Require operational proof (fan/pump status)
      </label>
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
      <p className="oracle-sidebar__caption" data-testid="sidebar-tune-count">
        {visible.length} rule{visible.length === 1 ? "" : "s"}
      </p>
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
      {staleNote ? (
        <p className="oracle-sidebar__caption" data-testid="sidebar-tune-stale">
          {staleNote}
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
            applied={lastApplied[rule.rule_id] ?? {}}
            opsGate={opsGate}
            onChange={onParam}
            onUpdateRule={(id, declaresGate) => void onUpdateRule(id, declaresGate)}
            updating={updatingRuleId === rule.rule_id}
            buildingId={buildingId}
            unitSystem={unitSystem}
          />
        ))}
      </div>
    </section>
  );
}
