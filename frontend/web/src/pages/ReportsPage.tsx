import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppShell } from "../components/AppShell";
import {
  Button,
  DataTable,
  Expander,
  InlineAlert,
  PlotlyHost,
  RadioGroup,
  Select,
} from "../components/widgets";
import { useSessionQuery } from "../session";
import { listPackageBuildings, getPackageMapping } from "../api/mappingApi";
import {
  getFddResults,
  getFddSeries,
  listFddRules,
  type FddResultRow,
  type FddRuleSummary,
} from "../api/fddApi";
import {
  listFddEquipment,
  postInspect,
  postSensorHealth,
} from "../api/analyticsApi";
import { naturalCompare, naturalSorted } from "../naturalSort";
import {
  missingSegmentCount,
  type PlotlyFigure,
} from "../api/plotDataset";
import {
  ruleResultChart,
  sensorFaultChart,
  sensorHealthHeatmap,
} from "../api/vibeCharts";

export const SQL_ANALYTICS_RULE_IDS = new Set([
  "FAN-RUNTIME-HOURS",
  "AVG-ZONE-TEMP",
  "ZONE-COMFORT-PCT",
  "FAULT-ELAPSED-HOURS",
]);

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

const STATUS_FILTERS = ["All", "FAULT", "PASS", "SKIPPED"] as const;
export type FddStatusFilter = (typeof STATUS_FILTERS)[number];

/** vibe19 `_preferred_plot_rule_id`: FAULT/WARNING first, else first result, else first rule. */
export function preferredPlotRuleId(
  rules: FddRuleSummary[],
  results: FddResultRow[],
  equipmentId: string,
): string {
  const applicable = rules.filter((r) => !SQL_ANALYTICS_RULE_IDS.has(r.rule_id));
  if (!applicable.length) return "";
  const lookup = new Map(
    results
      .filter((r) => r.equipment_id === equipmentId)
      .map((r) => [r.rule_id, r] as const),
  );
  const ranked = applicable.map((rule) => {
    const res = lookup.get(rule.rule_id);
    const status = String(res?.status ?? "");
    let rank = 3;
    if (status === "FAULT" || status === "WARNING") rank = 0;
    else if (
      status === "PASS" ||
      status.startsWith("SKIPPED") ||
      status === "ERROR"
    ) {
      rank = 1;
    } else if (res) rank = 2;
    return { rank, id: rule.rule_id };
  });
  ranked.sort((a, b) => a.rank - b.rank || naturalCompare(a.id, b.id));
  return ranked[0]?.id ?? "";
}

export function matchesStatusFilter(
  status: string,
  filter: FddStatusFilter,
): boolean {
  if (filter === "All") return true;
  if (filter === "SKIPPED") return status.toUpperCase().startsWith("SKIPPED");
  return status.toUpperCase() === filter;
}

export function ReportsPage() {
  const { query, setQuery } = useSessionQuery();
  const buildingId = query.siteId ?? "";
  const equipmentId = query.equipment ?? "";

  const [buildings, setBuildings] = useState<string[]>([]);
  const [ruleId, setRuleId] = useState("");
  const [rules, setRules] = useState<FddRuleSummary[]>([]);
  const [mappedRoles, setMappedRoles] = useState<Set<string>>(new Set());
  const [ruleOptions, setRuleOptions] = useState<
    Array<{ value: string; label: string; disabled?: boolean }>
  >([{ value: "", label: "— rule —" }]);
  const [equipmentOptions, setEquipmentOptions] = useState<
    Array<{ value: string; label: string }>
  >([]);
  const [results, setResults] = useState<FddResultRow[]>([]);
  const [statusFilter, setStatusFilter] = useState<FddStatusFilter>("All");
  const lastPrefEq = useRef("");
  const appliedResultPref = useRef(false);
  const seriesSeq = useRef(0);

  const [figure, setFigure] = useState<PlotlyFigure | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [noFaultBanner, setNoFaultBanner] = useState<string | null>(null);
  const [sensorRows, setSensorRows] = useState<
    Array<Record<string, string | number | boolean>>
  >([]);
  const [sensorFigure, setSensorFigure] = useState<PlotlyFigure | null>(null);
  const [sensorFaultFigure, setSensorFaultFigure] =
    useState<PlotlyFigure | null>(null);
  const [sensorKey, setSensorKey] = useState("");
  const [sensorLoading, setSensorLoading] = useState(false);
  const [sensorFaultLoading, setSensorFaultLoading] = useState(false);
  const [sensorError, setSensorError] = useState<string | null>(null);
  const [sensorOpen, setSensorOpen] = useState(false);

  useEffect(() => {
    void listPackageBuildings()
      .then(setBuildings)
      .catch(() => setBuildings([]));
    void listFddRules()
      .then((list) => {
        setRules(list);
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!buildingId || !equipmentId) {
      setMappedRoles(new Set());
      return;
    }
    void getPackageMapping(buildingId, equipmentId)
      .then((inv) => {
        const roles = new Set<string>();
        const eq =
          inv.equipment?.find((e) => e.equipment_id === equipmentId) ??
          inv.equipment?.[0];
        for (const role of Object.values(eq?.roles ?? {})) {
          if (role) roles.add(String(role));
        }
        for (const col of eq?.columns ?? []) {
          if (col.role) roles.add(String(col.role));
        }
        setMappedRoles(roles);
      })
      .catch(() => setMappedRoles(new Set()));
  }, [buildingId, equipmentId]);

  useEffect(() => {
    setRuleOptions([
      { value: "", label: "— rule —" },
      ...rules.map((r) => {
        if (SQL_ANALYTICS_RULE_IDS.has(r.rule_id)) {
          return {
            value: r.rule_id,
            label: `${r.rule_id} — analytics rollup (no fault series)`,
            disabled: true,
          };
        }
        const required = (r.required_roles ?? []).filter(Boolean);
        const missing =
          mappedRoles.size > 0
            ? required.filter((role) => !mappedRoles.has(role))
            : [];
        const blocked = missing.length > 0;
        return {
          value: r.rule_id,
          label: blocked
            ? `${r.rule_id} — unavailable (missing ${missing.join(", ")})`
            : `${r.rule_id} — ${r.description ?? ""}`,
          disabled: blocked,
        };
      }),
    ]);
  }, [rules, mappedRoles]);

  useEffect(() => {
    if (ruleId && SQL_ANALYTICS_RULE_IDS.has(ruleId)) {
      const next = rules.find((r) => !SQL_ANALYTICS_RULE_IDS.has(r.rule_id));
      setRuleId(next?.rule_id ?? "");
    }
  }, [rules, ruleId]);

  useEffect(() => {
    if (!buildingId) {
      setEquipmentOptions([]);
      setResults([]);
      return;
    }
    void listFddEquipment(buildingId)
      .then((items) => {
        const sorted = naturalSorted(items, (e) => String(e.equipment_id));
        const opts = sorted.map((e) => ({
          value: String(e.equipment_id),
          label: String(e.equipment_id),
        }));
        setEquipmentOptions(opts);
        const ids = new Set(opts.map((o) => o.value));
        if ((!equipmentId || !ids.has(equipmentId)) && opts[0]) {
          setQuery({ equipment: opts[0].value }, true);
        }
      })
      .catch(() => {
        setEquipmentOptions([]);
      });
    void getFddResults(buildingId)
      .then(setResults)
      .catch(() => setResults([]));
  }, [buildingId, equipmentId, setQuery]);

  useEffect(() => {
    if (!equipmentId || !rules.length) return;
    const eqChanged = lastPrefEq.current !== equipmentId;
    if (eqChanged) {
      lastPrefEq.current = equipmentId;
      appliedResultPref.current = false;
    }
    if (!eqChanged && appliedResultPref.current && ruleId) return;
    appliedResultPref.current = true;
    const pref = preferredPlotRuleId(rules, results, equipmentId);
    if (pref) setRuleId(pref);
  }, [equipmentId, rules, results, ruleId]);

  const loadSeries = useCallback(async () => {
    if (!equipmentId || !ruleId) {
      setError("Select equipment and rule");
      return;
    }
    if (SQL_ANALYTICS_RULE_IDS.has(ruleId)) {
      setFigure(null);
      setNoFaultBanner(null);
      setError(
        "Analytics rollups have no per-sample fault series — pick a diagnostic rule (FC*, VAV*, ECON*, …) and run FDD first.",
      );
      return;
    }
    const seq = ++seriesSeq.current;
    setLoading(true);
    setError(null);
    setNoFaultBanner(null);
    try {
      const series = await getFddSeries(equipmentId, ruleId, buildingId || undefined);
      if (seq !== seriesSeq.current) return;
      const roles = series.roles ?? [];
      const rows = (series.rows ?? []) as Array<Record<string, unknown>>;
      const fault = rows.map((r) => {
        const v = r.confirmed_fault ?? r.fault;
        if (v === true || v === 1 || v === "1" || v === "true") return 1;
        if (v === false || v === 0 || v === "0" || v === "false") return 0;
        return null;
      });
      const hasFaultOverlay = fault.some((v) => v != null);
      const fig = ruleResultChart(rows, {
        equipmentId: series.equipment_id ?? equipmentId,
        ruleId: series.rule_id ?? ruleId,
        roles,
        confirmedFault: hasFaultOverlay ? fault : undefined,
      });
      setFigure(fig);
      if (!fig) {
        setError("No plottable series for this equipment/rule.");
      } else if (!hasFaultOverlay) {
        setNoFaultBanner(
          "No fault lane yet — run FDD from Overview or Update this rule in the sidebar, then Load series again.",
        );
      }
    } catch (err) {
      if (seq !== seriesSeq.current) return;
      setFigure(null);
      setError(formatErr(err));
    } finally {
      if (seq === seriesSeq.current) setLoading(false);
    }
  }, [buildingId, equipmentId, ruleId]);

  useEffect(() => {
    if (!equipmentId || !ruleId) return;
    void loadSeries();
  }, [equipmentId, ruleId, loadSeries]);

  const loadSensorHealth = useCallback(async () => {
    if (!buildingId) {
      setSensorError("Select a building");
      return;
    }
    setSensorLoading(true);
    setSensorError(null);
    try {
      const env = await postSensorHealth({
        building_id: buildingId,
        equipment_ids: equipmentId ? [equipmentId] : undefined,
      });
      const rows = (env.rows?.length ? env.rows : env.equipment) ?? [];
      const normalized = rows.map((r) => ({
        equipment_id: String(r.equipment_id ?? ""),
        role: String(r.role ?? ""),
        n: Number(r.n ?? 0),
        n_finite: Number(r.n_finite ?? 0),
        coverage_pct: Number(r.coverage_pct ?? 0),
        missingness: Number(r.missingness ?? 0),
        flatline_flag: Boolean(r.flatline_flag),
        min: r.min != null ? Number(r.min) : "",
        max: r.max != null ? Number(r.max) : "",
        mean: r.mean != null ? Number(r.mean) : "",
        std: r.std != null ? Number(r.std) : "",
      }));
      setSensorRows(normalized);
      setSensorFigure(
        sensorHealthHeatmap(normalized as Array<Record<string, unknown>>, {
          title: `Sensor health — ${buildingId}`,
        }),
      );
      setSensorKey((prev) => {
        if (prev || !normalized[0]) return prev;
        return `${normalized[0].equipment_id}::${normalized[0].role}`;
      });
      if (!normalized.length && env.warnings?.[0]) {
        setSensorError(env.warnings[0]);
      }
    } catch (err) {
      setSensorRows([]);
      setSensorFigure(null);
      setSensorError(formatErr(err));
    } finally {
      setSensorLoading(false);
    }
  }, [buildingId, equipmentId]);

  const loadSensorFaultChart = useCallback(async () => {
    if (!buildingId || !sensorKey.includes("::")) {
      setSensorError("Load sensor health and pick a sensor first");
      return;
    }
    const [eq, role] = sensorKey.split("::");
    if (!eq || !role) return;
    setSensorFaultLoading(true);
    setSensorError(null);
    try {
      const env = await postInspect({
        building_id: buildingId,
        equipment_ids: [eq],
        max_points: 4000,
        series: { columns: [role] },
      });
      const points = (env.points ?? []).map((p) => ({
        timestamp_utc: p.timestamp_utc,
        value_f: p[role] ?? p.value_f,
      }));
      const fig = sensorFaultChart(points, {
        sensorName: `${eq} · ${role}`,
        valueKey: "value_f",
        yTitle: role,
      });
      setSensorFaultFigure(fig);
      if (!fig) {
        setSensorError(
          env.warnings?.[0] ?? `No inspect points for ${eq}/${role}`,
        );
      }
    } catch (err) {
      setSensorFaultFigure(null);
      setSensorError(formatErr(err));
    } finally {
      setSensorFaultLoading(false);
    }
  }, [buildingId, sensorKey]);

  const sensorKeyOptions = useMemo(() => {
    const opts = sensorRows.map((r) => ({
      value: `${r.equipment_id}::${r.role}`,
      label: `${r.equipment_id} · ${r.role}${
        r.flatline_flag ? " (flatline)" : ""
      }`,
    }));
    return [{ value: "", label: "— sensor —" }, ...opts];
  }, [sensorRows]);

  const gapSummary = useMemo(() => {
    if (!figure) return "";
    return figure.data
      .map((t) => `${t.name}:${missingSegmentCount(t)}`)
      .join(" · ");
  }, [figure]);

  const previewRows = useMemo(() => {
    if (!figure?.data[0]) return [];
    const x0 = figure.data[0].x ?? [];
    const n = Math.min(8, x0.length);
    return Array.from({ length: n }, (_, i) => {
      const row: Record<string, string> = {
        timestamp: String(x0[i] ?? ""),
      };
      for (const t of figure.data) {
        const name = t.name ?? "series";
        const y = t.y ?? [];
        row[name] = y[i] == null ? "" : String(y[i]);
      }
      return row;
    });
  }, [figure]);

  const buildingOptions = [
    { value: "", label: "— building —" },
    ...buildings.map((b) => ({ value: b, label: b })),
  ];

  const previewColumns = useMemo(() => {
    if (!previewRows[0]) {
      return [{ key: "timestamp", header: "timestamp" }];
    }
    return Object.keys(previewRows[0]).map((k) => ({ key: k, header: k }));
  }, [previewRows]);

  return (
    <AppShell
      title="FDD Plots"
      caption="FDD series plots and sensor health."
      activeSectionId="fdd-plots"
    >
      <div className="page-stack" data-testid="reports-page">
        {error ? (
          <InlineAlert id="reports-error" variant="danger" testId="plots-error">
            {error}
          </InlineAlert>
        ) : null}
        {noFaultBanner ? (
          <InlineAlert
            id="reports-no-fault"
            variant="info"
            testId="plots-no-fault"
          >
            {noFaultBanner}
          </InlineAlert>
        ) : null}

        <div data-testid="plots-page">
          <h2>FDD Plots — rule validation</h2>
          <p>
            Pick a device → series auto-loads → <strong>one chart</strong> at a time.
            Cards below filter by status. Analytics rollups are disabled here. Run FDD
            from Overview or <strong>Update this rule</strong> in the left rail first.
          </p>

          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}>
            <Select
              id="plots-building"
              label="Building"
              value={buildingId}
              options={buildingOptions}
              onChange={(value) => setQuery({ siteId: value }, true)}
              testId="plots-building-select"
            />
            <Select
              id="plots-equipment"
              label="Equipment"
              value={equipmentId}
              options={equipmentOptions}
              onChange={(value) => setQuery({ equipment: value }, true)}
              testId="plots-equipment-select"
            />
            <Select
              id="plots-rule"
              label="Rule"
              value={ruleId}
              options={ruleOptions}
              onChange={setRuleId}
              testId="plots-rule-select"
            />
          </div>

          <div style={{ margin: "0.75rem 0" }}>
            <Button
              id="plots-load"
              label={loading ? "Loading…" : "Load series"}
              onClick={() => void loadSeries()}
              disabled={loading || !equipmentId || !ruleId}
              testId="plots-load"
            />
          </div>

          <PlotlyHost
            key={`fdd-${equipmentId || "none"}_${ruleId || "none"}`}
            id="fdd-series"
            figureId={`fdd-${equipmentId || "none"}_${ruleId || "none"}`}
            label={figure?.layout?.title ?? "FDD series"}
            figure={figure}
            loading={loading}
            testId="plots-chart"
          />

          <RadioGroup
            id="plots-status-filter"
            label="Filter cards"
            orientation="horizontal"
            value={statusFilter}
            options={STATUS_FILTERS.map((s) => ({ value: s, label: s }))}
            onChange={(v) => setStatusFilter(v as FddStatusFilter)}
            testId="plots-status-filter"
          />
          <div className="fdd-result-cards" data-testid="plots-result-cards">
            {results
              .filter(
                (r) =>
                  (!equipmentId || r.equipment_id === equipmentId) &&
                  matchesStatusFilter(String(r.status ?? ""), statusFilter),
              )
              .map((r) => {
                const active =
                  r.equipment_id === equipmentId && r.rule_id === ruleId;
                return (
                  <button
                    key={`${r.equipment_id}-${r.rule_id}`}
                    type="button"
                    className={`fdd-result-card${active ? " fdd-result-card--active" : ""}`}
                    data-testid={`plots-card-${r.rule_id}`}
                    onClick={() => {
                      if (r.equipment_id !== equipmentId) {
                        setQuery({ equipment: r.equipment_id }, true);
                      }
                      setRuleId(r.rule_id);
                    }}
                  >
                    <strong>{r.rule_id}</strong>
                    <span className="fdd-result-card__status">{r.status}</span>
                    {r.title ? <span>{r.title}</span> : null}
                  </button>
                );
              })}
          </div>

          {figure ? (
            <p data-testid="plots-gap-summary">
              Missing segments by role: {gapSummary || "none"}
            </p>
          ) : null}

          {previewRows.length ? (
            <DataTable
              id="plots-preview"
              label="Series preview (first rows)"
              columns={
                previewColumns as Array<{ key: string; header: string }>
              }
              rows={previewRows}
              testId="plots-preview-table"
            />
          ) : null}

          <Expander
            id="sensor-health"
            label="Sensor health — coverage / flatline (DataFusion)"
            expanded={sensorOpen}
            onChange={setSensorOpen}
            testId="sensor-health-expander"
          >
            <p>
              Sensor coverage and flatline checks for the selected building
              (optionally scoped to equipment).
            </p>
            <Button
              id="sensor-health-load"
              label={sensorLoading ? "Loading…" : "Load sensor health"}
              onClick={() => void loadSensorHealth()}
              disabled={sensorLoading || !buildingId}
              testId="sensor-health-load"
            />
            {sensorError ? (
              <InlineAlert id="sensor-health-error" variant="danger">
                {sensorError}
              </InlineAlert>
            ) : null}
            <PlotlyHost
              id="sensor-health-chart"
              label="Coverage heatmap"
              figure={sensorFigure}
              loading={sensorLoading}
              testId="sensor-health-chart"
            />
            {sensorRows.length ? (
              <DataTable
                id="sensor-health-table"
                label="Sensor health matrix"
                columns={[
                  { key: "equipment_id", header: "equipment" },
                  { key: "role", header: "role" },
                  { key: "coverage_pct", header: "coverage %" },
                  { key: "missingness", header: "missingness" },
                  { key: "flatline_flag", header: "flatline" },
                  { key: "n_finite", header: "n_finite" },
                  { key: "mean", header: "mean" },
                  { key: "std", header: "std" },
                ]}
                rows={sensorRows}
                testId="sensor-health-table"
              />
            ) : null}

            <Select
              id="sensor-fault-pick"
              label="Sensor for fault chart"
              value={sensorKey}
              options={sensorKeyOptions}
              onChange={setSensorKey}
              testId="sensor-fault-pick"
            />
            <Button
              id="sensor-fault-load"
              label={
                sensorFaultLoading ? "Loading…" : "Load sensor fault chart"
              }
              onClick={() => void loadSensorFaultChart()}
              disabled={
                sensorFaultLoading || !buildingId || !sensorKey.includes("::")
              }
              testId="sensor-fault-load"
            />
            <PlotlyHost
              id="sensor-fault-chart"
              label="Sensor fault chart"
              figure={sensorFaultFigure}
              loading={sensorFaultLoading}
              testId="sensor-fault-chart"
            />
          </Expander>
        </div>
      </div>
    </AppShell>
  );
}
