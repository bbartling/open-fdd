import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { apiFetch } from "../lib/api";
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
  basVsWebOatOverlay,
  meteringBarScatter,
  multiEquipmentBox,
  oatScatter,
  plotlyConfig,
  ruleResultChart,
  vavComfortDonut,
} from "../vibe19/charts";
import {
  type RegistryRule,
  type RcxPresetMeta,
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

async function fetchRules() {
  return apiFetch<RulesResponse>("/api/fdd/rules");
}
async function fetchParams(ruleId: string) {
  return apiFetch<ParamsResponse>(`/api/fdd/rules/${encodeURIComponent(ruleId)}/params`);
}
async function fetchCache() {
  return apiFetch<CacheStatus>("/api/fdd/cache/status");
}
async function runRegistry(body: Record<string, unknown>) {
  return apiFetch<Record<string, unknown>>("/api/fdd/run", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

function OverviewSection({ cache, rules }: { cache?: CacheStatus; rules?: RegistryRule[] }) {
  const donut = vavComfortDonut({ title: "Zone comfort (demo)", inComfort: 82, outComfort: 18 });
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
        <div className="label">Result files</div>
        <div className="value">{cache?.result_file_count ?? 0}</div>
      </div>
      <div className="vibe19-card wide">
        <PlotHost data={donut.data} layout={donut.layout} config={plotlyConfig()} height={280} />
      </div>
      <div className="vibe19-card wide">
        <PlotHost data={bars.data} layout={bars.layout} config={plotlyConfig()} height={280} />
      </div>
      <OverviewExtras />
    </div>
  );
}

function DataModelSection({ rules }: { rules?: RegistryRule[] }) {
  const roles = useMemo(() => {
    const s = new Set<string>();
    for (const r of rules ?? []) for (const role of r.required_roles ?? []) s.add(role);
    return [...s].sort();
  }, [rules]);
  return (
    <div className="vibe19-card">
      <h3>Role catalog (from registry required_roles)</h3>
      <p className="muted">
        Equipment → cookbook role → column mapping is data-model driven. Roles referenced by loaded
        rules:
      </p>
      <ul className="vibe19-role-list">
        {roles.map((r) => (
          <li key={r}>
            <code>{r}</code>
          </li>
        ))}
      </ul>
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
}: {
  rules: RegistryRule[];
  paramOverrides: ParamOverrides;
  setParamOverrides: React.Dispatch<React.SetStateAction<ParamOverrides>>;
}) {
  const [category, setCategory] = useState("(all)");
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
          Reset all tuning
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
}: {
  cache?: CacheStatus;
  rules: RegistryRule[];
  paramOverrides: ParamOverrides;
  setParamOverrides: React.Dispatch<React.SetStateAction<ParamOverrides>>;
  unitSystem: SessionConfig["unit_system"];
  setUnitSystem: (u: SessionConfig["unit_system"]) => void;
  baseConfig: SessionConfig | null;
  setBaseConfig: (c: SessionConfig) => void;
}) {
  return (
    <aside className="vibe19-lab-sidebar">
      <div className="vibe19-sidebar-block">
        <h3>Building data</h3>
        <p className="muted">
          {cache?.parquet_exists
            ? `Parquet cache ready (${cache.parquet_file_count} files).`
            : "No building data loaded yet."}
        </p>
        <div className="vibe19-sidebar-actions">
          <a href="/csv">
            <button type="button">Load CSV / package zip…</button>
          </a>
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
            <option value="si">si</option>
          </select>
        </label>
      </div>
      <hr />
      <RuleTuningSidebar
        rules={rules}
        paramOverrides={paramOverrides}
        setParamOverrides={setParamOverrides}
      />
    </aside>
  );
}

function RunRulesSection({
  rules,
  paramOverrides,
}: {
  rules?: RegistryRule[];
  paramOverrides: ParamOverrides;
}) {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<string[]>([]);

  const runMut = useMutation({
    mutationFn: () =>
      runRegistry({
        mode: "registry",
        rule_ids: selected.length ? selected : undefined,
        params: paramOverrides,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["fdd-cache"] });
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

function ResultsSection({ rules }: { rules?: RegistryRule[] }) {
  const byStatus = useMemo(() => {
    const m = new Map<string, RegistryRule[]>();
    for (const r of rules ?? []) {
      const k = r.parity_status || "unknown";
      const arr = m.get(k) ?? [];
      arr.push(r);
      m.set(k, arr);
    }
    return [...m.entries()];
  }, [rules]);
  return (
    <div className="vibe19-card">
      <h3>Results by category (registry metadata)</h3>
      <p className="muted">
        After a registry run, fault hours land in <code>.cache/rule_results</code>. Below is the
        catalog grouped by parity status until live results are loaded.
      </p>
      {byStatus.map(([status, list]) => (
        <div key={status}>
          <h4>{status}</h4>
          <table className="vibe19-table">
            <thead>
              <tr>
                <th>Rule</th>
                <th>Confirm (s)</th>
                <th>Roles</th>
              </tr>
            </thead>
            <tbody>
              {list.map((r) => (
                <tr key={r.rule_id}>
                  <td>{r.rule_id}</td>
                  <td>{r.confirm_seconds}</td>
                  <td>{(r.required_roles ?? []).join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

function FddPlotsSection({ rules }: { rules?: RegistryRule[] }) {
  const [focus, setFocus] = useState<string>("");
  const wired = useMemo(
    () => (rules ?? []).filter((r) => r.dashboard_wired).slice(0, 12),
    [rules],
  );
  const active = focus || wired[0]?.rule_id || "DEMO";
  const demo = ruleResultChart({
    title: `${active} — rule card (demo series)`,
    series: [
      {
        name: "sat",
        points: Array.from({ length: 48 }, (_, i) => ({
          t: i,
          y: 55 + Math.sin(i / 5) * 3,
        })),
      },
    ],
    confirmed: Array.from({ length: 48 }, (_, i) => ({ t: i, fault: i > 30 && i < 40 })),
  });
  return (
    <div className="vibe19-run">
      <aside className="vibe19-sidebar">
        <h3>Rule cards</h3>
        <p className="muted">Auto-list applicable (dashboard_wired) rules.</p>
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
          Cards use <code>rule_result_chart</code> (multi-y + confirmed-fault swim lane). Display
          downsample ≤5k points; rule math stays full-resolution.
        </p>
        <PlotHost data={demo.data} layout={demo.layout} config={plotlyConfig()} height={360} />
      </div>
    </div>
  );
}

function demoSeries(seed: number) {
  return Array.from({ length: 60 }, (_, i) => ({
    t: i,
    y: 50 + seed * 3 + Math.sin((i + seed) / 6) * 4,
  }));
}

function RcxPlotsSection() {
  const [presetId, setPresetId] = useState(RCX_PRESETS[0].id);
  const preset = RCX_PRESETS.find((p) => p.id === presetId) ?? RCX_PRESETS[0];
  const fig = useMemo(() => buildRcxDemo(preset), [preset]);
  const families = useMemo(() => {
    const m = new Map<string, RcxPresetMeta[]>();
    for (const p of RCX_PRESETS) {
      const arr = m.get(p.family) ?? [];
      arr.push(p);
      m.set(p.family, arr);
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
        <PlotHost data={fig.data} layout={fig.layout} config={plotlyConfig()} height={380} />
      </div>
    </div>
  );
}

function buildRcxDemo(preset: RcxPresetMeta) {
  if (preset.chart === "donut") {
    return vavComfortDonut({ title: preset.label, inComfort: 72, outComfort: 28 });
  }
  if (preset.chart === "box") {
    return multiEquipmentBox({
      title: preset.label,
      series: [
        { name: "AHU-1", values: [1.1, 1.2, 1.15, 1.3, 0.9] },
        { name: "AHU-2", values: [0.8, 0.85, 0.9, 1.0, 0.75] },
      ],
    });
  }
  if (preset.chart === "scatter") {
    const axis =
      preset.weatherAxis === "wet_bulb" ? "Web wet-bulb °F" : "Web dry-bulb °F";
    return oatScatter({
      title: preset.label,
      x: Array.from({ length: 80 }, (_, i) => 40 + (i % 40)),
      y: Array.from({ length: 80 }, (_, i) => 55 + Math.sin(i / 7) * 8),
      xTitle: axis,
      yTitle: "Leave / SAT °F",
    });
  }
  if (preset.chart === "metering") {
    return meteringBarScatter({
      title: preset.label,
      months: ["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
      usage: [120, 110, 95, 80, 70, 90],
      degreeDays: [900, 750, 500, 200, 50, 100],
      usageName: preset.id.includes("gas") ? "gas" : "kWh",
      ddName: preset.id.includes("gas") ? "HDD" : "CDD",
    });
  }
  const s1 = demoSeries(1);
  const s2 = demoSeries(2);
  return {
    data: [
      {
        type: "scatter",
        mode: "lines",
        name: "eq-1",
        x: s1.map((p) => p.t),
        y: s1.map((p) => p.y),
      },
      {
        type: "scatter",
        mode: "lines",
        name: "eq-2",
        x: s2.map((p) => p.t),
        y: s2.map((p) => p.y),
      },
    ],
    layout: { title: { text: preset.label }, margin: { t: 48, r: 24, b: 40, l: 48 } },
  };
}

function MeteringSection() {
  const elec = meteringBarScatter({
    title: "Electric kWh vs CDD",
    months: ["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
    usage: [140, 120, 100, 85, 95, 110],
    degreeDays: [50, 80, 200, 350, 450, 500],
    usageName: "kWh",
    ddName: "CDD",
  });
  const gas = meteringBarScatter({
    title: "Gas vs HDD",
    months: ["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
    usage: [300, 260, 180, 90, 40, 20],
    degreeDays: [900, 750, 500, 200, 50, 10],
    usageName: "therms",
    ddName: "HDD",
  });
  return (
    <div className="vibe19-grid">
      <div className="vibe19-card wide">
        <PlotHost data={elec.data} layout={elec.layout} config={plotlyConfig()} height={320} />
      </div>
      <div className="vibe19-card wide">
        <PlotHost data={gas.data} layout={gas.layout} config={plotlyConfig()} height={320} />
      </div>
    </div>
  );
}

function OverviewExtras() {
  const overlay = basVsWebOatOverlay({
    title: "BAS vs web OAT",
    bas: demoSeries(0).map((p) => ({ ...p, y: (p.y ?? 0) + 20 })),
    web: demoSeries(1).map((p) => ({ ...p, y: (p.y ?? 0) + 18 })),
  });
  return (
    <div className="vibe19-card wide">
      <PlotHost data={overlay.data} layout={overlay.layout} config={plotlyConfig()} height={280} />
    </div>
  );
}

function Placeholder({ title, blurb }: { title: string; blurb: string }) {
  return (
    <div className="vibe19-card">
      <h3>{title}</h3>
      <p className="muted">{blurb}</p>
    </div>
  );
}

export default function Vibe19LabPage() {
  const [section, setSection] = useState<Vibe19Section>("Overview");
  const [paramOverrides, setParamOverrides] = useState<ParamOverrides>({});
  const [unitSystem, setUnitSystem] = useState<SessionConfig["unit_system"]>("imperial");
  const [baseConfig, setBaseConfig] = useState<SessionConfig | null>(null);
  const rulesQ = useQuery({ queryKey: ["fdd-rules"], queryFn: fetchRules });
  const cacheQ = useQuery({ queryKey: ["fdd-cache"], queryFn: fetchCache });

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
      />

      <div className="vibe19-content">
        <header className="vibe19-hero">
          <div>
            <h1>Open FDD Vibe Coder</h1>
            <p className="muted">
              Streamlit-parity lab — tune rules in the left sidebar, run on demand, browse
              sections below. Units: {unitSystem}.
            </p>
          </div>
          <div className="vibe19-hero-meta">
            {rulesQ.data?.ok ? (
              <span>{rulesQ.data.count} rules</span>
            ) : (
              <span className="error">{rulesQ.data?.error ?? (rulesQ.isError ? "API error" : "…")}</span>
            )}
          </div>
        </header>

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
            <OverviewSection cache={cacheQ.data} rules={rulesQ.data?.rules} />
          ) : null}
          {section === "Data Model" ? <DataModelSection rules={rulesQ.data?.rules} /> : null}
          {section === "Run Rules" ? (
            <RunRulesSection rules={rulesQ.data?.rules} paramOverrides={paramOverrides} />
          ) : null}
          {section === "Results by Category" ? (
            <ResultsSection rules={rulesQ.data?.rules} />
          ) : null}
          {section === "FDD Plots" ? <FddPlotsSection rules={rulesQ.data?.rules} /> : null}
          {section === "RCx Plots" ? <RcxPlotsSection /> : null}
          {section === "Metering" ? <MeteringSection /> : null}
          {section === "Export" ? (
            <Placeholder title="Export" blurb="CSV / session / health / data-model exports." />
          ) : null}
        </main>
      </div>
    </div>
  );
}
