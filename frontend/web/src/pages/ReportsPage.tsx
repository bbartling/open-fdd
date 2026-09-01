import { useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "../components/AppShell";
import { LockedSiteCaption } from "../components/LockedSiteCaption";
import { ruleLabelStandard, mergeRuleDescriptionsFromApi } from "../lib/ruleLabels";
import { RULES_UPDATED_EVENT } from "../components/RuleTuningPanel";
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
import { getPackageMapping } from "../api/mappingApi";
import {
  getFddResults,
  getFddSeries,
  listFddRules,
  type FddResultRow,
  type FddRuleSummary,
} from "../api/fddApi";
import { listFddEquipment, postInspect, postSensorHealth } from "../api/analyticsApi";
import {
  missingSegmentCount,
  type PlotlyFigure,
} from "../api/plotDataset";
import {
  ruleResultChart,
  sensorFaultChart,
  sensorHealthHeatmap,
} from "../api/vibeCharts";
import {
  fddStatusBucket,
  preferredPlotRuleId,
  type FddStatusFilter,
} from "../lib/fddPlotStatus";

export const SQL_ANALYTICS_RULE_IDS = new Set([
  "FAN-RUNTIME-HOURS",
  "AVG-ZONE-TEMP",
  "ZONE-COMFORT-PCT",
  "FAULT-ELAPSED-HOURS",
]);

const STATUS_FILTERS: FddStatusFilter[] = [
  "All",
  "FAULT",
  "PASS",
  "SKIPPED",
  "Not run",
];

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function lastYAxisTitle(fig: PlotlyFigure | null): string {
  if (!fig?.layout) return "";
  const yKeys = Object.keys(fig.layout).filter((k) => /^yaxis\d*$/.test(k));
  yKeys.sort((a, b) => {
    const na = a === "yaxis" ? 1 : Number(a.replace("yaxis", ""));
    const nb = b === "yaxis" ? 1 : Number(b.replace("yaxis", ""));
    return na - nb;
  });
  const last = fig.layout[yKeys[yKeys.length - 1] as "yaxis"] as
    | { title?: string | { text?: string }; domain?: number[] }
    | undefined;
  const title = last?.title;
  return typeof title === "string" ? title : String(title?.text ?? "");
}

function lastYAxisDomain0(fig: PlotlyFigure | null): number {
  if (!fig?.layout) return 1;
  const yKeys = Object.keys(fig.layout).filter((k) => /^yaxis\d*$/.test(k));
  yKeys.sort((a, b) => {
    const na = a === "yaxis" ? 1 : Number(a.replace("yaxis", ""));
    const nb = b === "yaxis" ? 1 : Number(b.replace("yaxis", ""));
    return na - nb;
  });
  const last = fig.layout[yKeys[yKeys.length - 1] as "yaxis"] as
    | { domain?: number[] }
    | undefined;
  return last?.domain?.[0] ?? 1;
}

export function ReportsPage() {
  const { query, setQuery } = useSessionQuery();
  const buildingId = query.siteId ?? "";
  const equipmentId = query.equipment ?? "";

  const [ruleId, setRuleId] = useState("");
  const [rules, setRules] = useState<FddRuleSummary[]>([]);
  const [mappedRoles, setMappedRoles] = useState<Set<string>>(new Set());
  const [inventory, setInventory] = useState<
    Array<{ equipment_id: string; equipment_type: string }>
  >([]);
  const [deviceType, setDeviceType] = useState("All");
  const [statusFilter, setStatusFilter] = useState<FddStatusFilter>("All");
  const [results, setResults] = useState<FddResultRow[]>([]);

  const [figure, setFigure] = useState<PlotlyFigure | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [noFaultBanner, setNoFaultBanner] = useState<string | null>(null);
  const [noFaultIsError, setNoFaultIsError] = useState(false);
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
    void listFddRules()
      .then((list) => {
        mergeRuleDescriptionsFromApi(list);
        setRules(list);
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!buildingId) {
      setInventory([]);
      setResults([]);
      return;
    }
    void Promise.all([
      getPackageMapping(buildingId).catch(() => null),
      listFddEquipment(buildingId).catch(() => []),
      getFddResults(buildingId).catch(() => [] as FddResultRow[]),
    ]).then(([inv, listed, rows]) => {
      const fromMap = (inv?.equipment ?? []).map((e) => ({
        equipment_id: String(e.equipment_id ?? ""),
        equipment_type: String(e.equipment_type ?? "unknown"),
      }));
      const fromList = listed.map((e) => ({
        equipment_id: String(e.equipment_id ?? ""),
        equipment_type: String(e.equipment_type ?? "unknown"),
      }));
      const byId = new Map<string, { equipment_id: string; equipment_type: string }>();
      for (const e of [...fromList, ...fromMap]) {
        if (!e.equipment_id) continue;
        const prev = byId.get(e.equipment_id);
        if (!prev || prev.equipment_type === "unknown") byId.set(e.equipment_id, e);
      }
      const merged = [...byId.values()].sort((a, b) =>
        a.equipment_id.localeCompare(b.equipment_id),
      );
      setInventory(merged);
      setResults(rows);
      if (!equipmentId && merged[0]) {
        setQuery({ equipment: merged[0].equipment_id }, true);
      }
    });
  }, [buildingId, equipmentId, setQuery]);

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

  const deviceTypes = useMemo(() => {
    const types = [
      ...new Set(inventory.map((e) => e.equipment_type).filter(Boolean)),
    ].sort((a, b) => a.localeCompare(b));
    return ["All", ...types];
  }, [inventory]);

  const filteredInventory = useMemo(() => {
    if (deviceType === "All") return inventory;
    return inventory.filter((e) => e.equipment_type === deviceType);
  }, [inventory, deviceType]);

  const statusByRule = useMemo(() => {
    const m = new Map<string, string>();
    for (const r of results) {
      if (String(r.equipment_id) !== equipmentId) continue;
      m.set(String(r.rule_id), String(r.status ?? ""));
    }
    return m;
  }, [results, equipmentId]);

  const applicableRules = useMemo(() => {
    return rules.filter((r) => {
      if (SQL_ANALYTICS_RULE_IDS.has(r.rule_id)) return false;
      const required = (r.required_roles ?? []).filter(Boolean);
      if (mappedRoles.size > 0 && required.some((role) => !mappedRoles.has(role))) {
        return false;
      }
      if (statusFilter === "All") return true;
      return fddStatusBucket(statusByRule.get(r.rule_id)) === statusFilter;
    });
  }, [rules, mappedRoles, statusFilter, statusByRule]);

  const ruleOptions = useMemo(
    () => [
      { value: "", label: "— rule —" },
      ...applicableRules.map((r) => ({
        value: r.rule_id,
        label: ruleLabelStandard(r.rule_id, r.description),
      })),
    ],
    [applicableRules],
  );

  useEffect(() => {
    const ids = applicableRules.map((r) => r.rule_id);
    if (ruleId && ids.includes(ruleId)) return;
    setRuleId(preferredPlotRuleId(ids, statusByRule));
  }, [applicableRules, ruleId, statusByRule]);

  const equipmentOptions = useMemo(
    () => [
      { value: "", label: "— equipment —" },
      ...filteredInventory.map((e) => ({
        value: e.equipment_id,
        label: e.equipment_id,
      })),
    ],
    [filteredInventory],
  );

  const loadSeries = useCallback(async () => {
    if (!equipmentId || !ruleId) {
      setError(buildingId ? "Select equipment and rule" : "Lock a site on Overview first");
      return;
    }
    if (SQL_ANALYTICS_RULE_IDS.has(ruleId)) {
      setFigure(null);
      setNoFaultBanner(null);
      setNoFaultIsError(false);
      setError(
        "Analytics rollups have no per-sample fault series — pick a diagnostic rule (FC*, VAV*, ECON*, …) and run FDD first.",
      );
      return;
    }
    setLoading(true);
    setError(null);
    setNoFaultBanner(null);
    setNoFaultIsError(false);
    try {
      const series = await getFddSeries(equipmentId, ruleId, buildingId || undefined);
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
      const resultExists = results.some(
        (r) =>
          String(r.equipment_id) === equipmentId && String(r.rule_id) === ruleId,
      );
      if (!fig) {
        setError("No plottable series for this equipment/rule.");
      } else if (!hasFaultOverlay && resultExists) {
        setNoFaultIsError(true);
        setNoFaultBanner(
          "Fault overlay missing after a successful rule run — timestamp join failed. This is a bug, not “no fault lane yet.”",
        );
      } else if (!hasFaultOverlay) {
        setNoFaultIsError(false);
        setNoFaultBanner(
          "No fault lane yet — run FDD from Overview or Update this rule in the sidebar, then refresh.",
        );
      }
    } catch (err) {
      setFigure(null);
      setError(formatErr(err));
    } finally {
      setLoading(false);
    }
  }, [buildingId, equipmentId, ruleId, results]);

  useEffect(() => {
    if (!buildingId || !equipmentId || !ruleId) return;
    void loadSeries();
  }, [buildingId, equipmentId, ruleId, loadSeries]);

  // After Lab "Update this rule" / Overview run-all, refresh results + fault overlay.
  useEffect(() => {
    const onRules = () => {
      if (!buildingId) return;
      void getFddResults(buildingId)
        .then((rows) => setResults(rows))
        .catch(() => undefined);
      if (equipmentId && ruleId) {
        void loadSeries();
      }
    };
    window.addEventListener(RULES_UPDATED_EVENT, onRules);
    return () => window.removeEventListener(RULES_UPDATED_EVENT, onRules);
  }, [buildingId, equipmentId, ruleId, loadSeries]);

  const loadSensorHealth = useCallback(async () => {
    if (!buildingId) {
      setSensorError("Lock a site on Overview first");
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

  const previewColumns = useMemo(() => {
    if (!previewRows[0]) {
      return [{ key: "timestamp", header: "timestamp" }];
    }
    return Object.keys(previewRows[0]).map((k) => ({ key: k, header: k }));
  }, [previewRows]);

  const lastTrace = figure?.data[figure.data.length - 1]?.name ?? "";
  const lastAxis = lastYAxisTitle(figure);
  const lastDomain0 = lastYAxisDomain0(figure);

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
            variant={noFaultIsError ? "danger" : "info"}
            testId="plots-no-fault"
          >
            {noFaultBanner}
          </InlineAlert>
        ) : null}

        <div data-testid="plots-page">
          <h2>FDD plot datasets</h2>
          <LockedSiteCaption buildingId={buildingId} />
          <p>
            Device type → device → applicable cookbook rules. Series auto-loads.
            <strong> confirmed_fault</strong> is the bottom-most lane when FDD
            has been run.
          </p>

          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}>
            <Select
              id="plots-device-type"
              label="Device type"
              value={deviceType}
              options={deviceTypes.map((t) => ({ value: t, label: t }))}
              onChange={(v) => {
                setDeviceType(v);
                const next = inventory.find(
                  (e) => v === "All" || e.equipment_type === v,
                );
                if (next && next.equipment_id !== equipmentId) {
                  setQuery({ equipment: next.equipment_id }, true);
                }
              }}
              testId="plots-device-type"
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

          <RadioGroup
            id="plots-status"
            label="Status"
            value={statusFilter}
            options={STATUS_FILTERS.map((s) => ({ value: s, label: s }))}
            onChange={(v) => setStatusFilter(v as FddStatusFilter)}
            testId="plots-status-filter"
          />

          <PlotlyHost
            id="fdd-series"
            label={figure?.layout?.title ?? "FDD series"}
            figure={figure}
            loading={loading}
            downloadFilename={
              equipmentId && ruleId
                ? `${equipmentId}_${ruleId}_series`
                : "fdd_series"
            }
            testId="plots-chart"
          />

          {figure ? (
            <p data-testid="plots-fault-lane">
              last_axis={lastAxis} last_trace={lastTrace} domain0={lastDomain0}
            </p>
          ) : null}

          <div style={{ margin: "0.75rem 0" }}>
            <Button
              id="plots-load"
              label={loading ? "Loading…" : "Refresh series"}
              onClick={() => void loadSeries()}
              disabled={loading || !equipmentId || !ruleId}
              testId="plots-load"
            />
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
              Sensor coverage and flatline checks for the locked site
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
              downloadFilename="sensor_health_coverage"
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
              downloadFilename="sensor_fault_chart"
              testId="sensor-fault-chart"
            />
          </Expander>
        </div>
      </div>
    </AppShell>
  );
}
