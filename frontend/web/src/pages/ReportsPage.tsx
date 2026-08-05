import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
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
import { listPackageBuildings } from "../api/mappingApi";
import { getFddResults, getFddSeries, listFddRules } from "../api/fddApi";
import { postSensorHealth } from "../api/analyticsApi";
import {
  missingSegmentCount,
  type PlotlyFigure,
} from "../api/plotDataset";
import { ruleResultChart, sensorHealthHeatmap } from "../api/vibeCharts";
import {
  createReportDraft,
  getEngineeringFindingsReport,
  listReports,
  type ReportRecord,
} from "../api/reportsApi";

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

type ReportRow = {
  report_id: string;
  report_type: string;
  title: string;
};

export function ReportsPage() {
  const { query, setQuery } = useSessionQuery();
  const buildingId = query.siteId ?? "";
  const equipmentId = query.equipment ?? "";
  const mode =
    query.section === "artifacts" || query.section === "metering"
      ? "artifacts"
      : "plots";

  const [buildings, setBuildings] = useState<string[]>([]);
  const [ruleId, setRuleId] = useState("");
  const [ruleOptions, setRuleOptions] = useState<
    Array<{ value: string; label: string }>
  >([{ value: "", label: "— rule —" }]);
  const [equipmentOptions, setEquipmentOptions] = useState<
    Array<{ value: string; label: string }>
  >([{ value: "", label: "— equipment —" }]);

  const [figure, setFigure] = useState<PlotlyFigure | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sensorRows, setSensorRows] = useState<
    Array<Record<string, string | number | boolean>>
  >([]);
  const [sensorFigure, setSensorFigure] = useState<PlotlyFigure | null>(null);
  const [sensorLoading, setSensorLoading] = useState(false);
  const [sensorError, setSensorError] = useState<string | null>(null);
  const [sensorOpen, setSensorOpen] = useState(false);

  const [reports, setReports] = useState<ReportRecord[]>([]);
  const [artifactsNotice, setArtifactsNotice] = useState<string | null>(null);
  const [engFindings, setEngFindings] = useState("");

  useEffect(() => {
    void listPackageBuildings()
      .then(setBuildings)
      .catch(() => setBuildings([]));
    void listFddRules()
      .then((rules) => {
        setRuleOptions([
          { value: "", label: "— rule —" },
          ...rules.map((r) => ({
            value: r.rule_id,
            label: `${r.rule_id} — ${r.description ?? ""}`,
          })),
        ]);
        if (!ruleId && rules[0]) setRuleId(rules[0].rule_id);
      })
      .catch(() => undefined);
  }, [ruleId]);

  useEffect(() => {
    if (!buildingId) {
      setEquipmentOptions([{ value: "", label: "— equipment —" }]);
      return;
    }
    void getFddResults(buildingId)
      .then((rows) => {
        const ids = Array.from(new Set(rows.map((r) => r.equipment_id))).sort();
        setEquipmentOptions([
          { value: "", label: "— equipment —" },
          ...ids.map((id) => ({ value: id, label: id })),
        ]);
        if (!equipmentId && ids[0]) {
          setQuery({ equipment: ids[0] }, true);
        }
      })
      .catch(() => {
        setEquipmentOptions([{ value: "", label: "— equipment —" }]);
      });
  }, [buildingId, equipmentId, setQuery]);

  const refreshReports = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setReports(await listReports());
    } catch (err) {
      setError(formatErr(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (mode === "artifacts") void refreshReports();
  }, [mode, refreshReports]);

  const loadSeries = useCallback(async () => {
    if (!equipmentId || !ruleId) {
      setError("Select equipment and rule");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const series = await getFddSeries(equipmentId, ruleId);
      const roles = series.roles ?? [];
      const rows = (series.rows ?? []) as Array<Record<string, unknown>>;
      const fault = rows.map((r) => {
        const v = r.confirmed_fault ?? r.fault;
        if (v === true || v === 1 || v === "1" || v === "true") return 1;
        if (v === false || v === 0 || v === "0" || v === "false") return 0;
        return null;
      });
      const hasFault = fault.some((v) => v != null);
      setFigure(
        ruleResultChart(rows, {
          equipmentId: series.equipment_id ?? equipmentId,
          ruleId: series.rule_id ?? ruleId,
          roles,
          confirmedFault: hasFault ? fault : undefined,
        }),
      );
    } catch (err) {
      setFigure(null);
      setError(formatErr(err));
    } finally {
      setLoading(false);
    }
  }, [equipmentId, ruleId]);

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

  const onCreateDraft = async () => {
    setArtifactsNotice(null);
    setError(null);
    try {
      const out = await createReportDraft({
        template_id: "summary",
        title: "React draft (P1-M5-E)",
        note: "DOCX/PDF render may remain ORACLE until Rust owns them",
      });
      setArtifactsNotice(
        `Draft created: ${String(out.report_id ?? JSON.stringify(out))}`,
      );
      await refreshReports();
    } catch (err) {
      setError(formatErr(err));
    }
  };

  const onLoadEngFindings = async () => {
    setError(null);
    try {
      const body = await getEngineeringFindingsReport();
      setEngFindings(JSON.stringify(body, null, 2));
    } catch (err) {
      setEngFindings("");
      setError(formatErr(err));
    }
  };

  const gapSummary = useMemo(() => {
    if (!figure) return "";
    return figure.data
      .map((t) => `${t.name}:${missingSegmentCount(t)}`)
      .join(" · ");
  }, [figure]);

  const previewRows = useMemo(() => {
    if (!figure?.data[0]) return [];
    const n = Math.min(8, figure.data[0].x.length);
    return Array.from({ length: n }, (_, i) => {
      const row: Record<string, string> = {
        timestamp: String(figure.data[0].x[i] ?? ""),
      };
      for (const t of figure.data) {
        row[t.name] = t.y[i] == null ? "" : String(t.y[i]);
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

  const reportRows: ReportRow[] = reports.map((r) => ({
    report_id: String(r.report_id ?? ""),
    report_type: String(r.report_type ?? r.template_id ?? r.kind ?? ""),
    title: String(r.title ?? ""),
  }));

  return (
    <AppShell
      title="Reports"
      caption="FDD plots + /api/reports artifacts (P1-M5-E). PDF/DOCX may be ORACLE."
      activeSectionId={mode === "artifacts" ? "metering" : "fdd-plots"}
    >
      <div className="page-stack" data-testid="reports-page">
        <RadioGroup
          id="reports-mode"
          label="Reports view"
          value={mode}
          options={[
            { value: "plots", label: "FDD plots" },
            { value: "artifacts", label: "Artifacts (/api/reports)" },
          ]}
          onChange={(v) =>
            setQuery(
              { section: v === "artifacts" ? "artifacts" : "fdd-plots" },
              true,
            )
          }
          testId="reports-mode"
        />

        {error ? (
          <InlineAlert id="reports-error" variant="danger" testId="plots-error">
            {error}
          </InlineAlert>
        ) : null}

        {mode === "plots" ? (
          <div data-testid="plots-page">
            <h2>FDD plot datasets</h2>
            <p>
              Loads <code>GET /api/fdd/series</code>. Run FDD via{" "}
              <Link to="/rules">Rules</Link> first.
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
              id="fdd-series"
              label={figure?.layout?.title ?? "FDD series"}
              figure={figure}
              loading={loading}
              testId="plots-chart"
            />

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
                Loads <code>POST /api/analytics/sensor-health</code> for the
                selected building (optionally scoped to equipment).
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
            </Expander>
          </div>
        ) : (
          <div data-testid="reports-artifacts">
            <h2>Report artifacts</h2>
            <InlineAlert id="reports-oracle" variant="info">
              List/draft/engineering-findings via Rust. PDF/DOCX render may stay
              ORACLE-ONLY until deletion gates (see PYTHON_EXIT_MATRIX).
            </InlineAlert>
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              <Button
                id="reports-refresh"
                label="Refresh list"
                onClick={() => void refreshReports()}
                testId="reports-refresh"
              />
              <Button
                id="reports-draft"
                label="Create draft"
                variant="secondary"
                onClick={() => void onCreateDraft()}
                testId="reports-draft"
              />
              <Button
                id="reports-eng"
                label="Load engineering-findings"
                variant="secondary"
                onClick={() => void onLoadEngFindings()}
                testId="reports-eng"
              />
            </div>
            {artifactsNotice ? (
              <InlineAlert
                id="reports-notice"
                variant="success"
                testId="reports-notice"
              >
                {artifactsNotice}
              </InlineAlert>
            ) : null}
            <DataTable
              id="reports-table"
              label="Reports"
              columns={[
                { key: "report_id", header: "report_id" },
                { key: "report_type", header: "type" },
                { key: "title", header: "title" },
              ]}
              rows={reportRows}
              loading={loading}
              testId="reports-table"
            />
            {engFindings ? (
              <pre data-testid="reports-eng-json">{engFindings}</pre>
            ) : null}
          </div>
        )}
      </div>
    </AppShell>
  );
}
