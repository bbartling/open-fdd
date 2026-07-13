import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "../../lib/api";
import { formatApiError } from "../../lib/formatApiError";
import {
  clearSessionRule,
  clampParam,
  getSessionOverrides,
  readSessionTuningStore,
  resolveDisplayValue,
  ruleParamsPath,
  setSessionParam,
  writeSessionTuningStore,
  type RuleParameterDef,
  type SessionTuningStore,
} from "../../lib/ruleTuningProfile";

type ParamsResponse = {
  ok?: boolean;
  tuning_ok?: boolean;
  tuning_error?: string;
  error?: string;
  rule?: {
    rule_id?: string;
    description?: string;
    parameters?: RuleParameterDef[];
  };
};

type Props = {
  /** Canonical registry rule_id only — never a slugified builder id. */
  ruleId: string | null;
};

function formatNum(n: number | undefined): string {
  if (typeof n !== "number" || !Number.isFinite(n)) return "—";
  return Number.isInteger(n) ? String(n) : String(Math.round(n * 1000) / 1000);
}

export default function RuleTuningPanel({ ruleId }: Props) {
  const [data, setData] = useState<ParamsResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionStore, setSessionStore] = useState<SessionTuningStore>(() => readSessionTuningStore());

  useEffect(() => {
    if (!ruleId) {
      setData(null);
      setError("");
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    setData(null);
    apiFetch<ParamsResponse>(ruleParamsPath(ruleId))
      .then((res) => {
        if (cancelled) return;
        setData(res);
        if (res.ok === false) setError(res.error ?? "Failed to load rule params");
      })
      .catch((e) => {
        if (!cancelled) setError(formatApiError(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [ruleId]);

  const persistSession = useCallback((next: SessionTuningStore) => {
    setSessionStore(next);
    writeSessionTuningStore(next);
  }, []);

  const overrides = useMemo(
    () => (ruleId ? getSessionOverrides(sessionStore, ruleId) : {}),
    [sessionStore, ruleId],
  );

  const params = data?.rule?.parameters ?? [];
  const tuningOk = data?.tuning_ok === true;
  const sessionDirty = Object.keys(overrides).length > 0;
  const canonicalId = data?.rule?.rule_id ?? ruleId;

  if (!ruleId) {
    return (
      <section className="panel rule-tuning-panel">
        <div className="panel-head">
          <h3>Rule tuning</h3>
        </div>
        <p className="muted small">Select a registry rule to inspect parameters and edit a session profile.</p>
      </section>
    );
  }

  return (
    <section className="panel rule-tuning-panel">
      <div className="panel-head">
        <h3>Rule tuning</h3>
        {sessionDirty ? <span className="gf-pill gf-pill--muted">session draft</span> : null}
      </div>

      <div className="rule-tuning-meta">
        <code className="rule-tuning-rule-id">{canonicalId}</code>
        {data?.rule?.description ? (
          <span className="muted small rule-tuning-desc">{data.rule.description}</span>
        ) : null}
      </div>

      <p className="muted small">
        Session profile only (localStorage). Does not write server <code>rule_tuning/</code> until you save
        explicitly in a later phase.
      </p>

      {error ? <p className="error-text">{error}</p> : null}
      {loading ? <p className="muted small">Loading parameters…</p> : null}

      {!loading && data?.ok !== false && !tuningOk ? (
        <div className="rule-tuning-error" role="alert">
          <strong>Tuning unavailable</strong>
          <span>{data?.tuning_error ?? "Server could not load tuning profiles."}</span>
          <span className="muted small">
            Registry defaults are shown for controls; effective values are not invented.
          </span>
        </div>
      ) : null}

      {!loading && params.length === 0 && !error ? (
        <p className="muted small">This rule has no tunable parameters.</p>
      ) : null}

      <ul className="rule-tuning-list">
        {params.map((param) => {
          const display = resolveDisplayValue(param, overrides[param.key], tuningOk);
          const controlValue = display.value;
          const isSlider = (param.control ?? "slider") === "slider";
          const min = typeof param.min === "number" ? param.min : 0;
          const max = typeof param.max === "number" ? param.max : 100;
          const step = typeof param.step === "number" && param.step > 0 ? param.step : 1;

          return (
            <li key={param.key} className="rule-tuning-row">
              <div className="rule-tuning-row__head">
                <span className="rule-tuning-label">{param.label ?? param.key}</span>
                {param.unit ? <span className="muted small">{param.unit}</span> : null}
              </div>
              <div className="rule-tuning-stats">
                <span title="Registry default">
                  def <code>{formatNum(param.default)}</code>
                </span>
                <span title="Server effective (tuning layers)">
                  eff{" "}
                  <code>
                    {tuningOk && typeof param.effective === "number" ? formatNum(param.effective) : "—"}
                  </code>
                </span>
                <span>
                  {formatNum(param.min)}…{formatNum(param.max)}
                  {param.step != null ? ` · step ${formatNum(param.step)}` : ""}
                </span>
              </div>
              {controlValue == null ? (
                <p className="muted small">No numeric baseline for this parameter.</p>
              ) : (
                <label className="rule-tuning-control">
                  {isSlider ? (
                    <input
                      type="range"
                      min={min}
                      max={max}
                      step={step}
                      value={controlValue}
                      aria-label={param.label ?? param.key}
                      onChange={(e) => {
                        if (!ruleId) return;
                        const nextVal = clampParam(Number(e.target.value), param.min, param.max);
                        persistSession(setSessionParam(sessionStore, ruleId, param.key, nextVal));
                      }}
                    />
                  ) : (
                    <input
                      type="number"
                      min={min}
                      max={max}
                      step={step}
                      value={controlValue}
                      aria-label={param.label ?? param.key}
                      onChange={(e) => {
                        if (!ruleId) return;
                        const raw = Number(e.target.value);
                        if (!Number.isFinite(raw)) return;
                        const nextVal = clampParam(raw, param.min, param.max);
                        persistSession(setSessionParam(sessionStore, ruleId, param.key, nextVal));
                      }}
                    />
                  )}
                  <span className="rule-tuning-value">
                    <strong>{formatNum(controlValue)}</strong>
                    <span className="muted small"> ({display.source})</span>
                  </span>
                </label>
              )}
            </li>
          );
        })}
      </ul>

      {sessionDirty && ruleId ? (
        <div className="rule-tuning-actions">
          <button
            type="button"
            className="secondary-btn"
            onClick={() => persistSession(clearSessionRule(sessionStore, ruleId))}
          >
            Reset session to server
          </button>
        </div>
      ) : null}
    </section>
  );
}
