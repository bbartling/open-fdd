import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { AppShell } from "../components/AppShell";
import {
  Button,
  Checkbox,
  DataTable,
  InlineAlert,
  Progress,
  Select,
  Slider,
} from "../components/widgets";
import { useSessionQuery } from "../session";
import {
  getSessionConfig,
  listPackageBuildings,
  putSessionConfig,
  type SessionConfig,
} from "../api/mappingApi";
import {
  buildRuleParamPayload,
  getFddRuleParams,
  getFddStatus,
  listFddRules,
  runFdd,
  type FddResultRow,
  type FddRuleParamDef,
  type FddRuleSummary,
  type FddRunResponse,
  type FddStatus,
} from "../api/fddApi";

type RuleRow = {
  rule_id: string;
  description: string;
  parity: string;
  params: string;
  selected: string;
};

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function RulesPage() {
  const { query, setQuery } = useSessionQuery();
  const buildingId = query.siteId ?? "";
  const equipmentId = query.equipment ?? "";

  const [buildings, setBuildings] = useState<string[]>([]);
  const [status, setStatus] = useState<FddStatus | null>(null);
  const [rules, setRules] = useState<FddRuleSummary[]>([]);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [runAll, setRunAll] = useState(true);

  const [tuneRuleId, setTuneRuleId] = useState("");
  const [paramDefs, setParamDefs] = useState<Record<string, FddRuleParamDef>>(
    {},
  );
  const [paramValues, setParamValues] = useState<Record<string, number>>({});
  const [sessionParams, setSessionParams] = useState<
    Record<string, Record<string, number>>
  >({});
  const [sessionConfig, setSessionConfig] = useState<SessionConfig | null>(null);
  const [paramsDirty, setParamsDirty] = useState(false);

  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [savingParams, setSavingParams] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [runResult, setRunResult] = useState<FddRunResponse | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [st, ruleList, blds, sess] = await Promise.all([
        getFddStatus(),
        listFddRules(),
        listPackageBuildings().catch(() => [] as string[]),
        getSessionConfig().catch(() => ({ ok: true, config: null })),
      ]);
      setStatus(st);
      setRules(ruleList);
      setBuildings(blds);
      setSessionConfig(sess.config ?? null);
      setSessionParams(sess.config?.params ?? {});
      setSelected((prev) => {
        const next = { ...prev };
        for (const r of ruleList) {
          if (next[r.rule_id] === undefined) next[r.rule_id] = false;
        }
        return next;
      });
      if (!tuneRuleId && ruleList[0]) {
        setTuneRuleId(ruleList[0].rule_id);
      }
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setLoading(false);
    }
  }, [tuneRuleId]);

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- initial load only
  }, []);

  useEffect(() => {
    if (!tuneRuleId) {
      setParamDefs({});
      setParamValues({});
      return;
    }
    let cancelled = false;
    getFddRuleParams(tuneRuleId)
      .then((body) => {
        if (cancelled) return;
        const defs = body.params ?? {};
        setParamDefs(defs);
        const defaults: Record<string, number> = {};
        for (const [k, def] of Object.entries(defs)) {
          defaults[k] = def.default;
        }
        const fromSession = sessionParams[tuneRuleId] ?? {};
        setParamValues({ ...defaults, ...fromSession });
        setParamsDirty(false);
      })
      .catch((err) => {
        if (!cancelled) setError(formatErr(err));
      });
    return () => {
      cancelled = true;
    };
  }, [tuneRuleId, sessionParams]);

  const selectedIds = useMemo(
    () => Object.entries(selected).filter(([, v]) => v).map(([id]) => id),
    [selected],
  );

  const onParamChange = (key: string, value: number) => {
    setParamValues((prev) => ({ ...prev, [key]: value }));
    setParamsDirty(true);
    setNotice(null);
  };

  const onSaveParams = async () => {
    if (!tuneRuleId) return;
    setSavingParams(true);
    setError(null);
    setNotice(null);
    try {
      const payload = buildRuleParamPayload(paramValues, paramDefs);
      const nextParams = { ...sessionParams, [tuneRuleId]: payload };
      const config: SessionConfig = {
        schema_version: "openfdd_session_v1",
        unit_system: sessionConfig?.unit_system ?? "imperial",
        prefer_web_oat: sessionConfig?.prefer_web_oat ?? true,
        role_map: sessionConfig?.role_map ?? {},
        params: nextParams,
      };
      const saved = await putSessionConfig(config, buildingId || undefined);
      setSessionConfig(saved.config ?? config);
      setSessionParams(nextParams);
      setParamsDirty(false);
      setNotice(`Saved params for ${tuneRuleId} to session-config`);
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setSavingParams(false);
    }
  };

  const onRun = async () => {
    if (!buildingId) {
      setError("Select a building (?site=) — FDD runs are building-scoped");
      return;
    }
    if (!runAll && selectedIds.length === 0) {
      setError("Select at least one rule, or enable Run all");
      return;
    }
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setRunning(true);
    setError(null);
    setRunResult(null);
    try {
      const liveParams = { ...sessionParams };
      if (tuneRuleId && Object.keys(paramDefs).length) {
        liveParams[tuneRuleId] = buildRuleParamPayload(paramValues, paramDefs);
      }
      const result = await runFdd(
        {
          mode: "registry",
          building_id: buildingId,
          equipment_id: equipmentId || undefined,
          rule_ids: runAll ? undefined : selectedIds,
          params: liveParams,
        },
        { signal: ac.signal },
      );
      setRunResult(result);
    } catch (err) {
      if (ac.signal.aborted) {
        setError("Run cancelled");
      } else {
        setError(formatErr(err));
      }
    } finally {
      setRunning(false);
    }
  };

  const onCancel = () => {
    abortRef.current?.abort();
  };

  const ruleRows: RuleRow[] = rules.map((r) => ({
    rule_id: r.rule_id,
    description: String(r.description ?? ""),
    parity: String(r.parity_status ?? ""),
    params: String(r.parameter_count ?? 0),
    selected: selected[r.rule_id] ? "yes" : "no",
  }));

  const outcomeRows = (runResult?.timings ?? []).map((t) => ({
    rule_id: String(t.rule_id ?? ""),
    status: String(t.status ?? ""),
    ms: String(t.ms ?? ""),
    error: String(t.error ?? ""),
  }));

  const resultPreview: FddResultRow[] = runResult?.results ?? [];

  const buildingOptions = [
    { value: "", label: "— select building —" },
    ...buildings.map((b) => ({ value: b, label: b })),
  ];
  const tuneOptions = [
    { value: "", label: "— select rule to tune —" },
    ...rules.map((r) => ({
      value: r.rule_id,
      label: `${r.rule_id} (${r.parameter_count ?? 0} params)`,
    })),
  ];

  const tuneRule = rules.find((r) => r.rule_id === tuneRuleId);

  return (
    <AppShell
      title="Run Rules"
      caption="SQL FDD catalog + tuning via Rust registry (no Python)."
      activeSectionId="run-rules"
    >
      <div className="page-placeholder" data-testid="rules-page">
        <h2>FDD catalog & run</h2>
        <p>
          Metadata from <code>GET /api/fdd/rules</code> /{" "}
          <code>…/params</code>. Params save to{" "}
          <code>PUT /api/fdd/session-config</code> and bind into{" "}
          <code>POST /api/fdd/run</code>. Results on{" "}
          <Link
            to={
              buildingId
                ? `/findings?site=${encodeURIComponent(buildingId)}`
                : "/findings"
            }
          >
            Findings
          </Link>
          .
        </p>

        {status ? (
          <p data-testid="fdd-status">
            Registry: {status.rule_count} rules ·{" "}
            <code>{status.rules_dir}</code>
            {status.hint ? ` — ${status.hint}` : ""}
          </p>
        ) : null}

        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}>
          <Select
            id="fdd-building"
            label="Building"
            value={buildingId}
            options={buildingOptions}
            onChange={(value) => setQuery({ siteId: value }, true)}
            testId="fdd-building-select"
          />
          <Checkbox
            id="fdd-run-all"
            label="Run all rules"
            checked={runAll}
            onChange={setRunAll}
            testId="fdd-run-all"
          />
        </div>

        {loading ? <p data-testid="rules-loading">Loading rules…</p> : null}
        {error ? (
          <InlineAlert id="rules-error" variant="danger" testId="rules-error">
            {error}
          </InlineAlert>
        ) : null}
        {notice ? (
          <InlineAlert id="rules-notice" variant="success" testId="rules-notice">
            {notice}
          </InlineAlert>
        ) : null}

        <section data-testid="fdd-tuning-panel" style={{ margin: "1rem 0" }}>
          <h3>Parameter tuning</h3>
          <Select
            id="fdd-tune-rule"
            label="Rule"
            value={tuneRuleId}
            options={tuneOptions}
            onChange={setTuneRuleId}
            testId="fdd-tune-rule"
          />
          {tuneRule ? (
            <p data-testid="fdd-tune-meta">
              <code>{tuneRule.rule_id}</code> · parity{" "}
              <code>{tuneRule.parity_status || "—"}</code> · roles{" "}
              {(tuneRule.required_roles ?? []).join(", ") || "—"}
              {tuneRule.aliases?.length
                ? ` · aliases ${tuneRule.aliases.join(", ")}`
                : ""}
            </p>
          ) : null}
          <div
            style={{ display: "grid", gap: "0.75rem", maxWidth: "28rem" }}
            data-testid="fdd-param-sliders"
          >
            {Object.entries(paramDefs).map(([key, def]) => (
              <div key={key}>
                <Slider
                  id={`param-${key}`}
                  label={`${def.label} (${def.unit || "—"})`}
                  description={`${key} → ${def.sql_placeholder} · ${def.min}…${def.max}`}
                  value={paramValues[key] ?? def.default}
                  min={def.min}
                  max={def.max}
                  step={def.step || 1}
                  onChange={(v) => onParamChange(key, v)}
                  testId={`fdd-param-${key}`}
                />
                <label htmlFor={`param-num-${key}`}>
                  Advanced
                  <input
                    id={`param-num-${key}`}
                    type="number"
                    data-testid={`fdd-param-num-${key}`}
                    min={def.min}
                    max={def.max}
                    step={def.step || 1}
                    value={paramValues[key] ?? def.default}
                    onChange={(e) =>
                      onParamChange(key, Number(e.target.value))
                    }
                  />
                </label>
              </div>
            ))}
            {!Object.keys(paramDefs).length && tuneRuleId ? (
              <p>No tunable parameters for this rule.</p>
            ) : null}
          </div>
          <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem" }}>
            <Button
              id="fdd-save-params"
              label={savingParams ? "Saving…" : "Save params"}
              onClick={() => void onSaveParams()}
              disabled={savingParams || !paramsDirty || !tuneRuleId}
              testId="fdd-save-params"
            />
          </div>
        </section>

        {running ? (
          <div data-testid="fdd-run-progress">
            <Progress
              id="fdd-run"
              label="Running FDD (blocking until DataFusion returns)…"
              value={0}
            />
            <Button
              id="fdd-cancel"
              label="Cancel"
              variant="danger"
              onClick={onCancel}
              testId="fdd-cancel"
            />
          </div>
        ) : null}

        <div style={{ display: "flex", gap: "0.5rem", margin: "0.75rem 0" }}>
          <Button
            id="fdd-run"
            label={running ? "Running…" : "Run FDD"}
            onClick={() => void onRun()}
            disabled={running || !buildingId}
            testId="fdd-run"
          />
          <Button
            id="fdd-reload"
            label="Reload catalog"
            variant="secondary"
            onClick={() => void refresh()}
            disabled={running}
            testId="fdd-reload"
          />
        </div>

        {!runAll ? (
          <div data-testid="fdd-rule-pickers" style={{ marginBottom: "1rem" }}>
            <h3>Select rules</h3>
            {rules.map((r) => (
              <Checkbox
                key={r.rule_id}
                id={`rule-${r.rule_id}`}
                label={`${r.rule_id} — ${r.description ?? ""}`}
                checked={Boolean(selected[r.rule_id])}
                onChange={(v) =>
                  setSelected((prev) => ({ ...prev, [r.rule_id]: v }))
                }
                testId={`fdd-rule-${r.rule_id}`}
              />
            ))}
          </div>
        ) : null}

        <DataTable
          id="fdd-rules"
          label="Rule catalog"
          columns={[
            { key: "rule_id", header: "Rule" },
            { key: "description", header: "Description" },
            { key: "parity", header: "Parity" },
            { key: "params", header: "Params" },
            { key: "selected", header: "Selected" },
          ]}
          rows={ruleRows}
          testId="fdd-rules-table"
        />

        {runResult ? (
          <div data-testid="fdd-run-summary" style={{ marginTop: "1.25rem" }}>
            <h3>Last run</h3>
            <p>
              succeeded {runResult.rules_succeeded ?? 0} · failed{" "}
              {runResult.rules_failed ?? 0} · skipped{" "}
              {runResult.rules_skipped ?? 0} · {runResult.total_ms ?? 0} ms ·{" "}
              {runResult.engine}
            </p>
            {outcomeRows.length ? (
              <DataTable
                id="fdd-outcomes"
                label="Per-rule outcomes"
                columns={[
                  { key: "rule_id", header: "Rule" },
                  { key: "status", header: "Status" },
                  { key: "ms", header: "ms" },
                  { key: "error", header: "Error" },
                ]}
                rows={outcomeRows}
                testId="fdd-outcomes-table"
              />
            ) : null}
            {resultPreview.length ? (
              <p data-testid="fdd-result-count">
                {resultPreview.length} result row(s) — open{" "}
                <Link
                  to={`/findings?site=${encodeURIComponent(buildingId)}${
                    equipmentId ? `&eq=${encodeURIComponent(equipmentId)}` : ""
                  }`}
                >
                  Findings
                </Link>{" "}
                to filter / download.
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    </AppShell>
  );
}
