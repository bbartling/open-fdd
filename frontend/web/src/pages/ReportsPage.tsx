import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { AppShell } from "../components/AppShell";
import {
  Button,
  DataTable,
  InlineAlert,
  PlotlyHost,
  Select,
} from "../components/widgets";
import { useSessionQuery } from "../session";
import { listPackageBuildings } from "../api/mappingApi";
import { getFddResults, getFddSeries, listFddRules } from "../api/fddApi";
import {
  missingSegmentCount,
  seriesRowsToFigure,
  type PlotlyFigure,
} from "../api/plotDataset";

function formatErr(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function ReportsPage() {
  const { query, setQuery } = useSessionQuery();
  const buildingId = query.siteId ?? "";
  const equipmentId = query.equipment ?? "";

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
      setFigure(
        seriesRowsToFigure(rows, {
          equipmentId: series.equipment_id ?? equipmentId,
          ruleId: series.rule_id ?? ruleId,
          roles,
          downsampled: series.downsampled,
          maxPoints: series.max_points,
        }),
      );
    } catch (err) {
      setFigure(null);
      setError(formatErr(err));
    } finally {
      setLoading(false);
    }
  }, [equipmentId, ruleId]);

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

  return (
    <AppShell
      title="FDD Plots"
      caption="Series datasets from Rust/DataFusion — React assembles the figure."
      activeSectionId="fdd-plots"
    >
      <div className="page-placeholder" data-testid="plots-page">
        <h2>FDD plot datasets</h2>
        <p>
          Loads <code>GET /api/fdd/series?equipment_id=&rule_id=</code>. Chart
          is an SVG stand-in for Plotly (dataset contract is the SoT). Run FDD
          first via <Link to="/rules">Rules</Link> so results can seed equipment
          lists.
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

        {error ? (
          <InlineAlert id="plots-error" variant="danger" testId="plots-error">
            {error}
          </InlineAlert>
        ) : null}

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
            columns={previewColumns as Array<{ key: string; header: string }>}
            rows={previewRows}
            testId="plots-preview-table"
          />
        ) : null}
      </div>
    </AppShell>
  );
}
