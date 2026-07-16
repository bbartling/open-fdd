import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { apiFetch } from "../lib/api";
import { barChart, plotlyConfig, ruleResultChart, vavComfortDonut } from "../vibe19/charts";
import {
  type RegistryRule,
  type RuleParamDef,
  type Vibe19Section,
  VIBE19_SECTIONS,
} from "../vibe19/contract";
import { PlotHost } from "../vibe19/PlotHost";
import "./vibe19.css";

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

function RunRulesSection({ rules }: { rules?: RegistryRule[] }) {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<string[]>([]);
  const [activeRule, setActiveRule] = useState<string>("");
  const [paramOverrides, setParamOverrides] = useState<Record<string, Record<string, number>>>({});

  const paramsQ = useQuery({
    queryKey: ["fdd-params", activeRule],
    queryFn: () => fetchParams(activeRule),
    enabled: Boolean(activeRule),
  });

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
    const m = new Map<string, RegistryRule[]>();
    for (const r of rules ?? []) {
      const fam = r.rule_id.split("-")[0] || "OTHER";
      const arr = m.get(fam) ?? [];
      arr.push(r);
      m.set(fam, arr);
    }
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [rules]);

  return (
    <div className="vibe19-run">
      <aside className="vibe19-sidebar">
        <h3>Rule families</h3>
        {families.map(([fam, list]) => (
          <details key={fam} open={fam === "FC" || fam === "VAV" || fam === "SV"}>
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
                        setActiveRule(r.rule_id);
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
          {runMut.isPending ? "Running…" : "Run selected (registry)"}
        </button>
        {runMut.isError ? (
          <p className="error">{(runMut.error as Error).message}</p>
        ) : null}
        {runMut.data ? (
          <pre className="vibe19-pre">{JSON.stringify(runMut.data, null, 2)}</pre>
        ) : null}
      </aside>
      <div className="vibe19-card grow">
        <h3>Sliders — {activeRule || "select a rule"}</h3>
        {!activeRule ? (
          <p className="muted">Select a rule to tune confirm_min and thresholds (no raw SQL).</p>
        ) : paramsQ.isLoading ? (
          <p className="muted">Loading params…</p>
        ) : (
          <div className="vibe19-sliders">
            {Object.values(paramsQ.data?.params ?? {}).map((p) => {
              const val =
                paramOverrides[activeRule]?.[p.key] ??
                paramOverrides[activeRule]?.[p.sql_placeholder] ??
                p.default;
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
                    onChange={(e) => {
                      const n = Number(e.target.value);
                      setParamOverrides((prev) => ({
                        ...prev,
                        [activeRule]: { ...(prev[activeRule] ?? {}), [p.key]: n },
                      }));
                    }}
                  />
                </label>
              );
            })}
          </div>
        )}
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

function FddPlotsSection() {
  const demo = ruleResultChart({
    title: "Example rule card chart (SAT + confirmed fault)",
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
    <div className="vibe19-card">
      <h3>FDD Plots</h3>
      <p className="muted">
        Rule cards use <code>rule_result_chart</code> — multi-y traces with a confirmed-fault swim
        lane. Live series wire to registry run outputs next.
      </p>
      <PlotHost data={demo.data} layout={demo.layout} config={plotlyConfig()} height={360} />
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
  const rulesQ = useQuery({ queryKey: ["fdd-rules"], queryFn: fetchRules });
  const cacheQ = useQuery({ queryKey: ["fdd-cache"], queryFn: fetchCache });

  return (
    <div className="vibe19-shell">
      <header className="vibe19-hero">
        <div>
          <h1>Open-FDD Lab</h1>
          <p className="muted">
            vibe19 look &amp; feel — data-model driven, registry sliders, Plotly charts (no Streamlit
            reruns).
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
        {section === "Run Rules" ? <RunRulesSection rules={rulesQ.data?.rules} /> : null}
        {section === "Results by Category" ? (
          <ResultsSection rules={rulesQ.data?.rules} />
        ) : null}
        {section === "FDD Plots" ? <FddPlotsSection /> : null}
        {section === "RCx Plots" ? (
          <Placeholder
            title="RCx Plots"
            blurb="Frozen RCx presets (zone comfort, AHU resets, OA scatters) — chart builders landed; preset picker next."
          />
        ) : null}
        {section === "Metering" ? (
          <Placeholder title="Metering" blurb="Electric/gas monthly + degree-day charts." />
        ) : null}
        {section === "Export" ? (
          <Placeholder title="Export" blurb="CSV / session / health / data-model exports." />
        ) : null}
      </main>
    </div>
  );
}
