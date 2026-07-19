import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import PackageImportPanel from "../components/PackageImportPanel";
import { apiFetch } from "../lib/api";
import {
  uploadPackageZip,
  type PackageImportResponse,
} from "../lib/csvPackageImport";
import { formatApiError } from "../lib/formatApiError";
import {
  buildSessionConfig,
  downloadSessionConfig,
  fetchSessionConfig,
  parseSessionConfigFile,
  saveSessionConfig,
  sessionConfigToParamOverrides,
  type SessionConfig,
} from "../lib/sessionConfig";
import {
  barChart,
  plotlyConfig,
  ruleResultChart,
} from "../vibe19/charts";
import {
  type RegistryRule,
  type RuleParamDef,
  type Vibe19Section,
  RCX_PRESETS,
  VIBE19_SECTIONS,
} from "../vibe19/contract";
import { groupRulesByFamily } from "../vibe19/families";
import { PlotHost } from "../vibe19/PlotHost";
import "./vibe19.css";

type ParamOverrides = Record<string, Record<string, number>>;

type RulesResponse = { ok: boolean; count: number; rules: RegistryRule[]; error?: string };
type ParamsResponse = {
  ok: boolean;
  rule_id: string;
  params: Record<string, RuleParamDef>;
  error?: string;
};
type CacheStatus = {
  ok: boolean;
  parquet_exists: boolean;
  parquet_file_count: number;
  sql_rules_present: boolean;
  rule_file_count?: number;
  result_file_count?: number;
};
type Equipment = { equipment_id: string; equipment_type: string };
type EquipmentResponse = { ok: boolean; count: number; equipment: Equipment[]; error?: string };
type ResultRow = {
  rule_id: string;
  title?: string;
  equipment_id: string;
  equipment_type: string;
  status: string;
  fault_hours: number;
  fault_pct?: number | null;
  missing_roles?: string[];
  notes?: unknown;
};
type ResultsResponse = { ok: boolean; count: number; results: ResultRow[]; error?: string };
type SeriesResponse = {
  ok: boolean;
  equipment_id: string;
  equipment_type?: string;
  rule_id: string;
  roles?: string[];
  rows?: Record<string, unknown>[];
  error?: string;
};

async function fetchRules() {
  return apiFetch<RulesResponse>("/api/fdd/rules");
}
async function fetchParams(ruleId: string) {
  return apiFetch<ParamsResponse>(`/api/fdd/rules/${encodeURIComponent(ruleId)}/params`);
}
async function fetchCache() {
  return apiFetch<CacheStatus>("/api/fdd/cache/status");
}
async function fetchEquipment() {
  return apiFetch<EquipmentResponse>("/api/fdd/equipment");
}
async function fetchResults() {
  return apiFetch<ResultsResponse>("/api/fdd/results");
}
async function fetchSeries(equipmentId: string, ruleId: string) {
  const query = new URLSearchParams({ equipment_id: equipmentId, rule_id: ruleId });
  return apiFetch<SeriesResponse>(`/api/fdd/series?${query}`);
}
async function runRegistry(body: Record<string, unknown>) {
  return apiFetch<Record<string, unknown>>("/api/fdd/run", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

function OverviewSection({
  cache,
  rules,
  equipment,
  results,
}: {
  cache?: CacheStatus;
  rules?: RegistryRule[];
  equipment?: Equipment[];
  results?: ResultRow[];
}) {
  const bars = barChart({
    title: "Rules by wiring status",
    labels: ["wired", "not wired"],
    values: [
      rules?.filter((r) => r.dashboard_wired).length ?? 0,
      rules?.filter((r) => !r.dashboard_wired).length ?? 0,
    ],
  });
  return (
    <div className="vibe19-grid">
      <div className="vibe19-metric">
        <div className="label">Registry rules</div>
        <div className="value">{rules?.length ?? "—"}</div>
      </div>
      <div className="vibe19-metric">
        <div className="label">SQL rules present</div>
        <div className="value">{cache?.sql_rules_present ? "yes" : "no"}</div>
      </div>
      <div className="vibe19-metric">
        <div className="label">Parquet cache</div>
        <div className="value">
          {cache?.parquet_exists ? `${cache.parquet_file_count} files` : "missing"}
        </div>
      </div>
      <p className="vibe19-lede" style={{ gridColumn: "1 / -1" }}>
        Start a job from CSV:{" "}
        <a href="/csv">CSV job upload</a>
        {" · "}
        then tune rules below without a full page reload.
      </p>
      <div className="vibe19-metric">
        <div className="label">Equipment</div>
        <div className="value">{equipment?.length ?? 0}</div>
      </div>
      <div className="vibe19-metric">
        <div className="label">Fault results</div>
        <div className="value">{results?.filter((r) => r.status === "FAULT").length ?? 0}</div>
      </div>
      <div className="vibe19-card wide">
        <PlotHost data={bars.data} layout={bars.layout} config={plotlyConfig()} height={280} />
      </div>
      <div className="vibe19-card wide">
        <h3>Building analytics</h3>
        <p className="muted">
          Motor runtime, mechanical-cooling OAT, comfort, and BAS-vs-web weather charts appear
          only when their mapped history is available. Demo series are intentionally not shown.
        </p>
      </div>
    </div>
  );
}

function DataModelSection({
  rules,
  packageResult,
}: {
  rules?: RegistryRule[];
  packageResult?: PackageImportResponse | null;
}) {
  const roles = useMemo(() => {
    const s = new Set<string>();
    for (const r of rules ?? []) for (const role of r.required_roles ?? []) s.add(role);
    return [...s].sort();
  }, [rules]);
  return (
    <div className="vibe19-grid">
      {packageResult ? <PackageImportPanel result={packageResult} /> : null}
      <div className="vibe19-card wide">
        <h3>Points by equipment</h3>
        <p className="muted">
          Import a package in the left rail to inspect and edit equipment role mappings here.
        </p>
        <details>
          <summary>Cookbook role catalog ({roles.length})</summary>
          <ul className="vibe19-role-list">
            {roles.map((r) => (
              <li key={r}>
                <code>{r}</code>
              </li>
            ))}
          </ul>
        </details>
      </div>
    </div>
  );
}

/** Save / load openfdd_session_v1 fault settings (#515) wired to the rule sliders. */
function SessionConfigPanel({
  paramOverrides,
  unitSystem,
  baseConfig,
  onBaseConfig,
  onUnitSystem,
  onLoaded,
}: {
  paramOverrides: ParamOverrides;
  unitSystem: SessionConfig["unit_system"];
  baseConfig: SessionConfig | null;
  onBaseConfig: (config: SessionConfig) => void;
  onUnitSystem: (unit: SessionConfig["unit_system"]) => void;
  onLoaded: (overrides: ParamOverrides, config: SessionConfig) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const seededRef = useRef(false);

  useEffect(() => {
    if (seededRef.current) return;
    seededRef.current = true;
    void fetchSessionConfig()
      .then((res) => {
        if (!res.ok || !res.config) return;
        onBaseConfig(res.config);
        onUnitSystem(res.config.unit_system ?? "imperial");
        if (res.persisted) {
          onLoaded(sessionConfigToParamOverrides(res.config), res.config);
          setNote("Loaded persisted session config (sliders seeded).");
        }
      })
      .catch(() => {
        /* offline / unauthenticated — keep defaults */
      });
  }, [onBaseConfig, onLoaded, onUnitSystem]);

  async function save() {
    setBusy(true);
    setError("");
    setNote("");
    try {
      const cfg = buildSessionConfig(paramOverrides, unitSystem, baseConfig);
      const out = await saveSessionConfig(cfg);
      if (!out.ok) throw new Error(out.error ?? "save failed");
      onBaseConfig(out.config ?? cfg);
      const warn = out.warnings?.length ? ` · ${out.warnings.length} warning(s)` : "";
      setNote(`Session saved to server${warn}.`);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function loadFile(file: File) {
    setBusy(true);
    setError("");
    setNote("");
    try {
      const cfg = parseSessionConfigFile(await file.text());
      const out = await saveSessionConfig(cfg);
      if (!out.ok) throw new Error(out.error ?? "load failed");
      const effective = out.config ?? cfg;
      onBaseConfig(effective);
      onUnitSystem(effective.unit_system ?? "imperial");
      onLoaded(sessionConfigToParamOverrides(effective), effective);
      const warn = out.warnings?.length ? ` · ${out.warnings.join("; ")}` : "";
      setNote(`Session loaded — sliders updated${warn}.`);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="vibe19-sidebar-block">
      <h3>Session restore</h3>
      {error ? <p className="error">{error}</p> : null}
      {note ? <p className="ok">{note}</p> : null}
      <div className="vibe19-sidebar-actions">
        <button type="button" disabled={busy} onClick={() => void save()}>
          {busy ? "Working…" : "Save session"}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => downloadSessionConfig(buildSessionConfig(paramOverrides, unitSystem, baseConfig))}
        >
          Download session config
        </button>
        <button type="button" disabled={busy} onClick={() => fileRef.current?.click()}>
          Load session JSON…
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".json,application/json"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void loadFile(f);
            e.target.value = "";
          }}
        />
      </div>
      <p className="muted">
        openfdd_session_v1 — slider overrides + units persist on the server and travel inside
        package zips as <code>session_config.json</code>.
      </p>
    </div>
  );
}

/** Per-rule tuning expander — params fetched lazily on first open (no full-app rerun). */
function RuleTuningExpander({
  rule,
  overrides,
  onChange,
}: {
  rule: RegistryRule;
  overrides: Record<string, number> | undefined;
  onChange: (key: string, value: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const paramsQ = useQuery({
    queryKey: ["fdd-params", rule.rule_id],
    queryFn: () => fetchParams(rule.rule_id),
    enabled: open,
  });
  const modified = Boolean(overrides && Object.keys(overrides).length);
  const title = rule.description
    ? `${rule.rule_id} — ${rule.description.slice(0, 36)}`
    : rule.rule_id;
  return (
    <details onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>
        {title}
        {modified ? <span className="modified"> · modified</span> : null}
      </summary>
      {!open ? null : paramsQ.isLoading ? (
        <p className="muted">Loading params…</p>
      ) : (
        <div className="vibe19-sliders">
          {Object.values(paramsQ.data?.params ?? {}).map((p) => {
            const val = overrides?.[p.key] ?? overrides?.[p.sql_placeholder] ?? p.default;
            return (
              <label key={p.key} className="vibe19-slider">
                <span>
                  {p.label} ({p.unit}) — <strong>{val}</strong>
                </span>
                <input
                  type="range"
                  min={p.min}
                  max={p.max}
                  step={p.step}
                  value={val}
                  onChange={(e) => onChange(p.key, Number(e.target.value))}
                />
              </label>
            );
          })}
          {Object.keys(paramsQ.data?.params ?? {}).length === 0 ? (
            <p className="muted">No tunable params.</p>
          ) : null}
        </div>
      )}
    </details>
  );
}

/** Sidebar rule tuning — vibe19 category selectbox + per-rule expanders. */
function RuleTuningSidebar({
  rules,
  paramOverrides,
  setParamOverrides,
  onRerunCategory,
  rerunning,
}: {
  rules: RegistryRule[];
  paramOverrides: ParamOverrides;
  setParamOverrides: React.Dispatch<React.SetStateAction<ParamOverrides>>;
  onRerunCategory: (ruleIds: string[]) => void;
  rerunning: boolean;
}) {
  const [category, setCategory] = useState("(all)");
  const [requireOperationalProof, setRequireOperationalProof] = useState(true);
  const grouped = useMemo(
    () => groupRulesByFamily(rules.map((r) => r.rule_id)),
    [rules],
  );
  const byId = useMemo(() => new Map(rules.map((r) => [r.rule_id, r])), [rules]);
  const shown = grouped.filter(([label]) => category === "(all)" || label === category);
  const modifiedCount = Object.keys(paramOverrides).filter(
    (id) => Object.keys(paramOverrides[id] ?? {}).length,
  ).length;
  return (
    <div className="vibe19-sidebar-block">
      <h3>Rule tuning</h3>
      <p className="muted">
        Sliders only change thresholds. Rules update when you click Run or Rerun cat.
      </p>
      <label className="vibe19-checkbox">
        <input
          type="checkbox"
          checked={requireOperationalProof}
          onChange={(e) => setRequireOperationalProof(e.target.checked)}
        />
        Require operational proof (fan/pump status)
      </label>
      <label>
        Category
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="(all)">(all)</option>
          {grouped.map(([label]) => (
            <option key={label} value={label}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <p className="muted">
        Sliders update local state only — run rules to apply.{" "}
        {modifiedCount ? `${modifiedCount} rule(s) modified.` : ""}
      </p>
      <div className="vibe19-sidebar-actions">
        <button type="button" onClick={() => setParamOverrides({})}>
          Reset
        </button>
        <button
          type="button"
          disabled={rerunning}
          onClick={() =>
            onRerunCategory(shown.flatMap(([, ids]) => ids))
          }
        >
          {rerunning ? "Running…" : "Rerun cat."}
        </button>
      </div>
      <div className="vibe19-tuning">
        {shown.map(([label, ids]) => (
          <div key={label}>
            <p className="vibe19-tuning-family">{label}</p>
            {ids.map((id) => {
              const rule = byId.get(id);
              if (!rule) return null;
              return (
                <RuleTuningExpander
                  key={id}
                  rule={rule}
                  overrides={paramOverrides[id]}
                  onChange={(key, value) =>
                    setParamOverrides((prev) => ({
                      ...prev,
                      [id]: { ...(prev[id] ?? {}), [key]: value },
                    }))
                  }
                />
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

/** Streamlit-parity page sidebar: data load → session restore → display & site → rule tuning. */
function LabSidebar({
  cache,
  rules,
  paramOverrides,
  setParamOverrides,
  unitSystem,
  setUnitSystem,
  baseConfig,
  setBaseConfig,
  onPackageImported,
  onRerunCategory,
  rerunning,
}: {
  cache?: CacheStatus;
  rules: RegistryRule[];
  paramOverrides: ParamOverrides;
  setParamOverrides: React.Dispatch<React.SetStateAction<ParamOverrides>>;
  unitSystem: SessionConfig["unit_system"];
  setUnitSystem: (u: SessionConfig["unit_system"]) => void;
  baseConfig: SessionConfig | null;
  setBaseConfig: (c: SessionConfig) => void;
  onPackageImported: (result: PackageImportResponse) => void;
  onRerunCategory: (ruleIds: string[]) => void;
  rerunning: boolean;
}) {
  const packageRef = useRef<HTMLInputElement>(null);
  const [packageBusy, setPackageBusy] = useState(false);
  const [packageNote, setPackageNote] = useState("");
  const [packageError, setPackageError] = useState("");

  async function importPackage(file: File) {
    setPackageBusy(true);
    setPackageNote("");
    setPackageError("");
    try {
      const result = await uploadPackageZip(file);
      if (!result.ok) throw new Error(result.error ?? "package import failed");
      onPackageImported(result);
      setPackageNote(
        `Loaded ${result.equipment_written ?? result.equipment?.length ?? 0} equipment · ${result.total_rows?.toLocaleString() ?? "?"} rows`,
      );
    } catch (error) {
      setPackageError(formatApiError(error));
    } finally {
      setPackageBusy(false);
    }
  }

  return (
    <aside className="vibe19-lab-sidebar">
      <div className="vibe19-sidebar-block">
        <h3>Building data</h3>
        <p className="muted">
          {cache?.parquet_exists
            ? `Parquet cache ready (${cache.parquet_file_count} files).`
            : "No building data loaded yet."}
        </p>
        {packageNote ? <p className="ok">{packageNote}</p> : null}
        {packageError ? <p className="error">{packageError}</p> : null}
        <div className="vibe19-sidebar-actions">
          <button
            type="button"
            disabled={packageBusy}
            onClick={() => packageRef.current?.click()}
          >
            {packageBusy ? "Loading…" : "Building package zip(s)…"}
          </button>
          <input
            ref={packageRef}
            type="file"
            accept=".zip,application/zip"
            hidden
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void importPackage(file);
              e.target.value = "";
            }}
          />
        </div>
      </div>
      <hr />
      <SessionConfigPanel
        paramOverrides={paramOverrides}
        unitSystem={unitSystem}
        baseConfig={baseConfig}
        onBaseConfig={setBaseConfig}
        onUnitSystem={setUnitSystem}
        onLoaded={(overrides) => setParamOverrides(overrides)}
      />
      <hr />
      <div className="vibe19-sidebar-block">
        <h3>Display &amp; site</h3>
        <label>
          Units
          <select
            value={unitSystem}
            onChange={(e) => setUnitSystem(e.target.value as SessionConfig["unit_system"])}
          >
            <option value="imperial">imperial</option>
            <option value="metric">metric</option>
          </select>
        </label>
        <label className="vibe19-checkbox">
          <input
            type="checkbox"
            checked={baseConfig?.prefer_web_oat ?? true}
            onChange={(e) =>
              setBaseConfig({
                ...(baseConfig ?? buildSessionConfig(paramOverrides, unitSystem)),
                prefer_web_oat: e.target.checked,
              })
            }
          />
          Prefer web OAT (Open-Meteo)
        </label>
        <label>
          CHW leave proof max {unitSystem === "metric" ? "°C" : "°F"}
          <input
            type="range"
            min={unitSystem === "metric" ? 1.7 : 35}
            max={unitSystem === "metric" ? 10 : 50}
            step={0.5}
            value={
              unitSystem === "metric"
                ? (((baseConfig?.chw_leave_max_f ?? 48) - 32) * 5) / 9
                : (baseConfig?.chw_leave_max_f ?? 48)
            }
            onChange={(e) => {
              const displayed = Number(e.target.value);
              setBaseConfig({
                ...(baseConfig ?? buildSessionConfig(paramOverrides, unitSystem)),
                chw_leave_max_f:
                  unitSystem === "metric" ? (displayed * 9) / 5 + 32 : displayed,
              });
            }}
          />
        </label>
      </div>
      <hr />
      <RuleTuningSidebar
        rules={rules}
        paramOverrides={paramOverrides}
        setParamOverrides={setParamOverrides}
        onRerunCategory={onRerunCategory}
        rerunning={rerunning}
      />
    </aside>
  );
}

function RunRulesSection({
  rules,
  paramOverrides,
  selectedEquipment,
}: {
  rules?: RegistryRule[];
  paramOverrides: ParamOverrides;
  selectedEquipment?: string;
}) {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<string[]>([]);
  const [equipmentScope, setEquipmentScope] = useState<"selected" | "all">("all");

  const runMut = useMutation({
    mutationFn: () =>
      runRegistry({
        mode: "registry",
        rule_ids: selected.length ? selected : undefined,
        params: paramOverrides,
        equipment_id: equipmentScope === "selected" ? selectedEquipment : undefined,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["fdd-cache"] });
      void qc.invalidateQueries({ queryKey: ["fdd-results"] });
    },
  });

  const families = useMemo(() => {
    const byId = new Map((rules ?? []).map((r) => [r.rule_id, r]));
    return groupRulesByFamily([...byId.keys()]).map(
      ([label, ids]) =>
        [label, ids.map((id) => byId.get(id)!).filter(Boolean)] as [string, RegistryRule[]],
    );
  }, [rules]);
  const modifiedIds = Object.keys(paramOverrides).filter(
    (id) => Object.keys(paramOverrides[id] ?? {}).length,
  );

  return (
    <div className="vibe19-run">
      <aside className="vibe19-sidebar">
        <h3>Scope</h3>
        <p className="muted">
          {selected.length ? `${selected.length} rule(s) selected` : "All rules (no selection)"}
        </p>
        {families.map(([fam, list]) => (
          <details key={fam}>
            <summary>
              {fam} ({list.length})
            </summary>
            <ul>
              {list.map((r) => (
                <li key={r.rule_id}>
                  <label>
                    <input
                      type="checkbox"
                      checked={selected.includes(r.rule_id)}
                      onChange={(e) => {
                        setSelected((prev) =>
                          e.target.checked
                            ? [...prev, r.rule_id]
                            : prev.filter((id) => id !== r.rule_id),
                        );
                      }}
                    />{" "}
                    {r.rule_id}
                  </label>
                </li>
              ))}
            </ul>
          </details>
        ))}
        <button
          type="button"
          className="primary-btn"
          disabled={runMut.isPending}
          onClick={() => runMut.mutate()}
        >
          {runMut.isPending ? "Running…" : selected.length ? "Run selected" : "Run all rules"}
        </button>
        {runMut.isError ? (
          <p className="error">{(runMut.error as Error).message}</p>
        ) : null}
      </aside>
      <div className="vibe19-card grow">
        <h3>Run rules</h3>
        <p className="muted">
          Thresholds come from <strong>Rule tuning</strong> in the left sidebar — slider changes
          stay local until you press Run (no Streamlit-style rerun).
        </p>
        <fieldset className="vibe19-inline-radio">
          <legend>Equipment scope</legend>
          <label>
            <input
              type="radio"
              checked={equipmentScope === "selected"}
              disabled={!selectedEquipment}
              onChange={() => setEquipmentScope("selected")}
            />
            selected equipment{selectedEquipment ? ` (${selectedEquipment})` : ""}
          </label>
          <label>
            <input
              type="radio"
              checked={equipmentScope === "all"}
              onChange={() => setEquipmentScope("all")}
            />
            all equipment
          </label>
        </fieldset>
        {modifiedIds.length ? (
          <p>
            Tuned rules applied on run:{" "}
            {modifiedIds.map((id) => (
              <code key={id} style={{ marginRight: "0.4rem" }}>
                {id}
              </code>
            ))}
          </p>
        ) : (
          <p className="muted">No slider overrides yet — registry defaults will be used.</p>
        )}
        {runMut.data ? (
          <pre className="vibe19-pre">{JSON.stringify(runMut.data, null, 2)}</pre>
        ) : null}
      </div>
    </div>
  );
}

function ResultsSection({ results }: { results?: ResultRow[] }) {
  const [hideNa, setHideNa] = useState(true);
  const byEquipmentType = useMemo(() => {
    const grouped = new Map<string, Map<string, ResultRow[]>>();
    for (const row of results ?? []) {
      if (hideNa && row.status === "NOT_APPLICABLE_EQUIPMENT_TYPE") continue;
      const byDevice = grouped.get(row.equipment_type) ?? new Map<string, ResultRow[]>();
      const deviceRows = byDevice.get(row.equipment_id) ?? [];
      deviceRows.push(row);
      byDevice.set(row.equipment_id, deviceRows);
      grouped.set(row.equipment_type, byDevice);
    }
    return [...grouped.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [hideNa, results]);
  const statuses = ["PASS", "FAULT", "SKIPPED_MISSING_ROLES", "SKIPPED_EQUIPMENT_OFF", "NOT_APPLICABLE_EQUIPMENT_TYPE", "ERROR"];
  return (
    <div>
      <h3>Results by equipment type</h3>
      <p className="muted">
        Organized by mechanical device type, then device. Run rules to refresh these live rows.
      </p>
      <div className="vibe19-status-metrics">
        {statuses.map((status) => (
          <div className="vibe19-metric" key={status}>
            <div className="label">{status.replaceAll("_", " ")}</div>
            <div className="value">{results?.filter((r) => r.status === status).length ?? 0}</div>
          </div>
        ))}
      </div>
      <label className="vibe19-checkbox">
        <input type="checkbox" checked={hideNa} onChange={(e) => setHideNa(e.target.checked)} />
        Hide N/A rows (NOT_APPLICABLE_EQUIPMENT_TYPE)
      </label>
      {byEquipmentType.length === 0 ? (
        <div className="vibe19-card"><p className="muted">No live rule results yet.</p></div>
      ) : null}
      {byEquipmentType.map(([equipmentType, devices]) => (
        <section key={equipmentType}>
          <h3>{equipmentType} · {devices.size} device(s)</h3>
          {[...devices.entries()].map(([equipmentId, rows]) => (
            <details className="vibe19-result-device" key={equipmentId}>
              <summary>
                {equipmentId} · FAULT {rows.filter((r) => r.status === "FAULT").length} · PASS{" "}
                {rows.filter((r) => r.status === "PASS").length}
              </summary>
              <table className="vibe19-table">
                <thead>
                  <tr><th>Rule</th><th>Status</th><th>Fault hours</th><th>Fault %</th></tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={`${equipmentId}-${row.rule_id}`}>
                      <td title={row.title}>{row.rule_id}</td>
                      <td>{row.status}</td>
                      <td>{row.fault_hours.toFixed(3)}</td>
                      <td>{row.fault_pct == null ? "—" : row.fault_pct.toFixed(1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          ))}
        </section>
      ))}
    </div>
  );
}

function FddPlotsSection({
  rules,
  equipment,
  selectedEquipment,
  onEquipment,
  results,
}: {
  rules?: RegistryRule[];
  equipment?: Equipment[];
  selectedEquipment: string;
  onEquipment: (equipmentId: string) => void;
  results?: ResultRow[];
}) {
  const [focus, setFocus] = useState<string>("");
  const wired = useMemo(
    () => (rules ?? []).filter((r) => r.dashboard_wired),
    [rules],
  );
  const active = focus || wired[0]?.rule_id || "";
  const seriesQ = useQuery({
    queryKey: ["fdd-series", selectedEquipment, active],
    queryFn: () => fetchSeries(selectedEquipment, active),
    enabled: Boolean(selectedEquipment && active),
  });
  const figure = useMemo(() => {
    const rows = seriesQ.data?.rows ?? [];
    const roles = seriesQ.data?.roles ?? [];
    if (!rows.length) return null;
    return ruleResultChart({
      title: `${active} — ${selectedEquipment}`,
      series: roles.map((role) => ({
        name: role,
        points: rows
          .map((row, index) => ({
            t: (row.timestamp_utc as string | number | undefined) ?? index,
            y: typeof row[role] === "number" ? (row[role] as number) : null,
          }))
          .filter((point) => point.y != null),
      })),
      confirmed: [],
    });
  }, [active, selectedEquipment, seriesQ.data]);
  const activeResults = (results ?? []).filter(
    (row) => row.equipment_id === selectedEquipment,
  );
  return (
    <div className="vibe19-run">
      <aside className="vibe19-sidebar">
        <h3>FDD plot picker</h3>
        <label>
          Device
          <select value={selectedEquipment} onChange={(e) => onEquipment(e.target.value)}>
            {(equipment ?? []).map((item) => (
              <option key={item.equipment_id} value={item.equipment_id}>
                {item.equipment_type} · {item.equipment_id}
              </option>
            ))}
          </select>
        </label>
        <ul>
          {wired.map((r) => (
            <li key={r.rule_id}>
              <button type="button" className={r.rule_id === active ? "active" : ""} onClick={() => setFocus(r.rule_id)}>
                {r.rule_id}
              </button>
            </li>
          ))}
        </ul>
      </aside>
      <div className="vibe19-card grow">
        <h3>FDD Plots — {active}</h3>
        <p className="muted">
          Live mapped history from the parquet cache. Display is capped at 5,000 points; rule math
          stays full-resolution.
        </p>
        {seriesQ.isLoading ? <p>Loading series…</p> : null}
        {seriesQ.data && !seriesQ.data.ok ? <p className="error">{seriesQ.data.error}</p> : null}
        {figure ? (
          <PlotHost data={figure.data} layout={figure.layout} config={plotlyConfig()} height={420} />
        ) : !seriesQ.isLoading ? (
          <p className="muted">No mapped live series are available for this device/rule.</p>
        ) : null}
        <h3>Rule cards</h3>
        {wired.map((rule) => {
          const result = activeResults.find((row) => row.rule_id === rule.rule_id);
          return (
            <details key={rule.rule_id} open={rule.rule_id === active}>
              <summary>
                {rule.rule_id} — {rule.description} · {result?.status ?? "Not run"}
              </summary>
              <p>{rule.description}</p>
              <p className="muted">
                Roles: {(rule.required_roles ?? []).join(", ") || "none"} · Confirm{" "}
                {rule.confirm_seconds}s
              </p>
            </details>
          );
        })}
      </div>
    </div>
  );
}

function RcxPlotsSection() {
  const [presetId, setPresetId] = useState(RCX_PRESETS[0].id);
  const preset = RCX_PRESETS.find((p) => p.id === presetId) ?? RCX_PRESETS[0];
  const families = useMemo(() => {
    const m = new Map<string, typeof RCX_PRESETS>();
    for (const p of RCX_PRESETS) {
      m.set(p.family, [...(m.get(p.family) ?? []), p]);
    }
    return [...m.entries()];
  }, []);
  return (
    <div className="vibe19-run">
      <aside className="vibe19-sidebar">
        <h3>RCx presets</h3>
        <p className="muted">
          Weather: dry-bulb for SAT/HW/CHW resets; wet-bulb for CW/tower.
        </p>
        {families.map(([fam, list]) => (
          <details key={fam} open>
            <summary>
              {fam} ({list.length})
            </summary>
            <ul>
              {list.map((p) => (
                <li key={p.id}>
                  <button
                    type="button"
                    className={p.id === presetId ? "active" : ""}
                    onClick={() => setPresetId(p.id)}
                  >
                    {p.label}
                  </button>
                </li>
              ))}
            </ul>
          </details>
        ))}
      </aside>
      <div className="vibe19-card grow">
        <h3>
          {preset.label}{" "}
          <span className="muted">
            ({preset.weatherAxis === "none" ? "no weather axis" : preset.weatherAxis})
          </span>
        </h3>
        <p className="muted">
          No mapped live series currently satisfies this preset. Synthetic fallback charts have
          been removed; import the required package roles and rerun rules.
        </p>
      </div>
    </div>
  );
}

function MeteringSection() {
  return (
    <div className="vibe19-card">
      <h3>Metering</h3>
      <p className="muted">
        Electric kWh/CDD and gas/HDD charts require mapped meter and weather series. No synthetic
        monthly values are displayed.
      </p>
    </div>
  );
}

function ExportSection({ results }: { results?: ResultRow[] }) {
  function downloadResults() {
    const headers = ["rule_id", "equipment_id", "equipment_type", "status", "fault_hours", "fault_pct"];
    const lines = [
      headers.join(","),
      ...(results ?? []).map((row) =>
        headers
          .map((key) => JSON.stringify(row[key as keyof ResultRow] ?? ""))
          .join(","),
      ),
    ];
    const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "fdd_results_by_equipment.csv";
    anchor.click();
    URL.revokeObjectURL(url);
  }
  return (
    <div className="vibe19-card">
      <h3>Export</h3>
      <p>Current live result rows and session configuration can leave the Lab without a route hop.</p>
      <button type="button" disabled={!results?.length} onClick={downloadResults}>
        Download full results CSV
      </button>
      <p className="muted">WattLab dump and Generic RCx DOCX remain tracked in #518.</p>
    </div>
  );
}

export default function Vibe19LabPage() {
  const [section, setSection] = useState<Vibe19Section>("Overview");
  const [paramOverrides, setParamOverrides] = useState<ParamOverrides>({});
  const [unitSystem, setUnitSystem] = useState<SessionConfig["unit_system"]>("imperial");
  const [baseConfig, setBaseConfig] = useState<SessionConfig | null>(null);
  const [packageResult, setPackageResult] = useState<PackageImportResponse | null>(null);
  const [selectedEquipment, setSelectedEquipment] = useState("");
  const rulesQ = useQuery({ queryKey: ["fdd-rules"], queryFn: fetchRules });
  const cacheQ = useQuery({ queryKey: ["fdd-cache"], queryFn: fetchCache });
  const equipmentQ = useQuery({ queryKey: ["fdd-equipment"], queryFn: fetchEquipment });
  const resultsQ = useQuery({ queryKey: ["fdd-results"], queryFn: fetchResults });
  const queryClient = useQueryClient();
  const rerunMutation = useMutation({
    mutationFn: (ruleIds: string[]) =>
      runRegistry({
        mode: "registry",
        rule_ids: ruleIds.length ? ruleIds : undefined,
        params: paramOverrides,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["fdd-results"] });
      void queryClient.invalidateQueries({ queryKey: ["fdd-cache"] });
    },
  });

  useEffect(() => {
    const first = equipmentQ.data?.equipment?.[0]?.equipment_id;
    if (!selectedEquipment && first) setSelectedEquipment(first);
  }, [equipmentQ.data, selectedEquipment]);

  return (
    <div className="vibe19-shell">
      <LabSidebar
        cache={cacheQ.data}
        rules={rulesQ.data?.rules ?? []}
        paramOverrides={paramOverrides}
        setParamOverrides={setParamOverrides}
        unitSystem={unitSystem}
        setUnitSystem={setUnitSystem}
        baseConfig={baseConfig}
        setBaseConfig={setBaseConfig}
        onPackageImported={(result) => {
          setPackageResult(result);
          void queryClient.invalidateQueries({ queryKey: ["fdd-cache"] });
          void queryClient.invalidateQueries({ queryKey: ["fdd-equipment"] });
          void fetchSessionConfig().then((response) => {
            if (!response.config) return;
            setBaseConfig(response.config);
            setUnitSystem(response.config.unit_system);
            setParamOverrides(sessionConfigToParamOverrides(response.config));
          });
        }}
        onRerunCategory={(ruleIds) => rerunMutation.mutate(ruleIds)}
        rerunning={rerunMutation.isPending}
      />

      <div className="vibe19-content">
        <header className="vibe19-hero">
          <div>
            <h1>Open FDD Vibe Coder</h1>
            <p className="muted">
              Educational React + DataFusion lab for the Open-FDD cookbook. Building data stays
              as-is — map columns to roles, tune thresholds, then run on demand.
            </p>
            <p><strong>How it works:</strong> Data package → Data model → Run Rules → FDD / RCx plots.</p>
          </div>
          <div className="vibe19-hero-meta">
            {rulesQ.data?.ok ? (
              <span>{rulesQ.data.count} rules</span>
            ) : (
              <span className="error">{rulesQ.data?.error ?? (rulesQ.isError ? "API error" : "…")}</span>
            )}
          </div>
        </header>

        <label className="vibe19-equipment-picker">
          Equipment
          <select
            value={selectedEquipment}
            onChange={(event) => setSelectedEquipment(event.target.value)}
          >
            {(equipmentQ.data?.equipment ?? []).map((item) => (
              <option key={item.equipment_id} value={item.equipment_id}>
                {item.equipment_id}
              </option>
            ))}
          </select>
        </label>

        <nav className="vibe19-nav" aria-label="Lab sections">
          {VIBE19_SECTIONS.map((s) => (
            <button
              key={s}
              type="button"
              className={s === section ? "active" : ""}
              onClick={() => setSection(s)}
            >
              {s}
            </button>
          ))}
        </nav>

        <main className="vibe19-main">
          {section === "Overview" ? (
            <OverviewSection
              cache={cacheQ.data}
              rules={rulesQ.data?.rules}
              equipment={equipmentQ.data?.equipment}
              results={resultsQ.data?.results}
            />
          ) : null}
          {section === "Data Model" ? (
            <DataModelSection rules={rulesQ.data?.rules} packageResult={packageResult} />
          ) : null}
          {section === "Run Rules" ? (
            <RunRulesSection
              rules={rulesQ.data?.rules}
              paramOverrides={paramOverrides}
              selectedEquipment={selectedEquipment}
            />
          ) : null}
          {section === "Results by Category" ? (
            <ResultsSection results={resultsQ.data?.results} />
          ) : null}
          {section === "FDD Plots" ? (
            <FddPlotsSection
              rules={rulesQ.data?.rules}
              equipment={equipmentQ.data?.equipment}
              selectedEquipment={selectedEquipment}
              onEquipment={setSelectedEquipment}
              results={resultsQ.data?.results}
            />
          ) : null}
          {section === "RCx Plots" ? <RcxPlotsSection /> : null}
          {section === "Metering" ? <MeteringSection /> : null}
          {section === "Export" ? <ExportSection results={resultsQ.data?.results} /> : null}
        </main>
      </div>
    </div>
  );
}
